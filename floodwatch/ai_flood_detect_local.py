"""
Offline AI Flood Detection using Local SegFormer-B0.

A 100% offline, local drop-in replacement for cloud vision API calls.
Given a BEFORE image and an AFTER image (tif, jpg, png; drone or satellite),
it segments floodwater, isolates NEW flood inundation (discounting permanent water bodies),
and outputs the decision JSON contract:

    {
      "flood_damage_detected": true|false,
      "confidence": "low"|"medium"|"high",
      "reasoning": "one short sentence with measured numbers",
      "model": "segformer-b0-checkpoint-joint",
      "metrics": {
        "pre_flood_fraction": 0.0210,
        "post_flood_fraction": 0.1840,
        "new_flood_fraction": 0.1690
      }
    }

CLI usage:
    python scripts/ai_flood_detect_local.py --pre before.tif --post after.tif
    python scripts/ai_flood_detect_local.py --pre before.tif --post after.tif --device cpu --threshold 0.02

Importable:
    from scripts.ai_flood_detect_local import judge
    res = judge(pre_path, post_path)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple, Union

# Silence third-party warnings and progress bars on stdout
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import numpy as np
import rasterio
from PIL import Image

try:
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
except Exception:
    pass

# Fix Windows PostgreSQL PROJ conflict if rasterio is used
proj_dir = os.path.join(os.path.dirname(rasterio.__file__), "proj_data")
if os.path.exists(proj_dir):
    os.environ["PROJ_DATA"] = proj_dir
    os.environ["PROJ_LIB"] = proj_dir

import torch
import torch.nn.functional as F
from transformers import SegformerForSemanticSegmentation, logging as hf_logging
hf_logging.set_verbosity_error()

# Normalization constants (ImageNet standard)
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

# Default decision parameters
NEW_FLOOD_THRESHOLD = 0.001  # >= 0.1% of the scene newly inundated => flood damage detected
CLOUD_BRIGHT = 170.0         # mean brightness > 170/255 ...
CLOUD_SAT = 0.12             # ... and mean saturation < 0.12 => mostly cloud/haze

# Global model cache to avoid reloading on repeated importable calls
_CACHED_MODEL = None
_CACHED_MODEL_DIR = None
_CACHED_DEVICE = None
_CACHED_ID2LABEL = {}


def resolve_model_dir(explicit_path: Optional[str] = None) -> str:
    """Finds the SegFormer checkpoint directory in the repository."""
    if explicit_path:
        # If a direct weight file was passed (e.g. models/segformer/model.safetensors), use its directory
        candidate = os.path.dirname(explicit_path) if os.path.isfile(explicit_path) else explicit_path
        if os.path.exists(candidate) and os.path.exists(os.path.join(candidate, "config.json")):
            return candidate
        for prefix in ["", "floodwatch", os.path.dirname(os.path.abspath(__file__))]:
            alt = os.path.join(prefix, candidate)
            if os.path.exists(alt) and os.path.exists(os.path.join(alt, "config.json")):
                return alt
        if os.path.exists(explicit_path):
            return candidate if candidate else explicit_path

    env_dir = os.getenv("FW_MODEL_DIR")
    if env_dir and os.path.exists(env_dir) and os.path.exists(os.path.join(env_dir, "config.json")):
        return env_dir

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)

    candidates = [
        os.path.join(repo_root, "models", "segformer"),
        os.path.join(repo_root, "floodwatch", "models", "segformer"),
        os.path.join(repo_root, "modules", "flood_analysis", "models", "segformer"),
        "models/segformer",
        "floodwatch/models/segformer",
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.exists(os.path.join(c, "config.json")):
            return c

    raise FileNotFoundError(
        "Could not locate SegFormer checkpoint folder (checked FW_MODEL_DIR and standard repo paths)."
    )


def get_model(model_dir: Optional[str] = None, device_str: str = "auto") -> Tuple[SegformerForSemanticSegmentation, torch.device, str, Dict[int, str]]:
    """Loads and caches the SegFormer model and retrieves class id2label mapping."""
    global _CACHED_MODEL, _CACHED_MODEL_DIR, _CACHED_DEVICE, _CACHED_ID2LABEL

    resolved_dir = resolve_model_dir(model_dir)

    if device_str == "auto":
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        dev = torch.device(device_str)

    if _CACHED_MODEL is not None and _CACHED_MODEL_DIR == resolved_dir and _CACHED_DEVICE == dev:
        return _CACHED_MODEL, _CACHED_DEVICE, _CACHED_MODEL_DIR, _CACHED_ID2LABEL

    # Read id2label from config.json
    cfg_file = os.path.join(resolved_dir, "config.json")
    id2label = {0: "background", 1: "flooded", 2: "natural_water"}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
            raw_id2label = cfg_data.get("id2label", {})
            if raw_id2label:
                id2label = {int(k): v for k, v in raw_id2label.items()}
        except Exception:
            pass

    model = SegformerForSemanticSegmentation.from_pretrained(resolved_dir)
    model.eval().to(dev)
    if dev.type == "cuda":
        model.half()

    _CACHED_MODEL = model
    _CACHED_MODEL_DIR = resolved_dir
    _CACHED_DEVICE = dev
    _CACHED_ID2LABEL = id2label
    return model, dev, resolved_dir, id2label


def load_rgb(path: str) -> np.ndarray:
    """Reads an image (TIF, JPG, PNG) as a uint8 (H, W, 3) RGB numpy array."""
    if not os.path.exists(path):
        for prefix in ["floodwatch", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]:
            alt = os.path.join(prefix, path)
            if os.path.exists(alt):
                path = alt
                break

    try:
        with rasterio.open(path) as src:
            arr = src.read([1, 2, 3])
            if np.issubdtype(arr.dtype, np.floating):
                arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
            elif arr.dtype == np.uint16:
                arr = (arr / 256.0).clip(0, 255).astype(np.uint8)
            else:
                arr = arr.astype(np.uint8)
            return np.transpose(arr, (1, 2, 0))
    except Exception:
        im = Image.open(path).convert("RGB")
        return np.asarray(im, dtype=np.uint8)


def looks_cloudy(rgb: np.ndarray) -> bool:
    """Checks whether the image is mostly cloud or haze."""
    f = rgb.astype(np.float32) / 255.0
    mx = f.max(axis=2)
    mn = f.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    b = float(f.mean() * 255.0)
    s = float(sat.mean())
    return b > CLOUD_BRIGHT and s < CLOUD_SAT


def segment_flood(
    rgb: np.ndarray,
    model: SegformerForSemanticSegmentation,
    device: torch.device,
    flood_classes: List[int],
    mode: str = "auto",
    size: int = 768,
) -> np.ndarray:
    """
    Runs SegFormer inference on an (H, W, 3) RGB numpy image.
    Supports whole-image resize (fast) and sliding window 512 crops (accurate).
    Returns boolean (H, W) mask of pixels matching flood_classes.
    """
    H, W = rgb.shape[:2]
    mean = MEAN.to(device)
    std = STD.to(device)

    # Use sliding window if accurate requested, or if auto on CUDA for large imagery (>= 1024)
    use_sliding = (mode == "accurate") or (mode == "auto" and device.type == "cuda" and (H >= 1024 or W >= 1024))

    # Convert uint8 (H, W, 3) -> float tensor (3, H, W) in [0, 1]
    tensor_img = torch.from_numpy(rgb.astype(np.float32) / 255.0).permute(2, 0, 1)

    if use_sliding and H >= 512 and W >= 512:
        crop_size = 512
        stride = 256
        chunk_size = 8

        y_steps = list(range(0, H - crop_size, stride))
        if not y_steps or y_steps[-1] != H - crop_size:
            y_steps.append(H - crop_size)
        x_steps = list(range(0, W - crop_size, stride))
        if not x_steps or x_steps[-1] != W - crop_size:
            x_steps.append(W - crop_size)

        crops = []
        coords = []
        for y in y_steps:
            for x in x_steps:
                crops.append(tensor_img[:, y:y + crop_size, x:x + crop_size])
                coords.append((y, x))

        batch = torch.stack(crops)
        num_classes = model.config.num_labels if getattr(model.config, "num_labels", None) else 3
        full_logits = torch.zeros((num_classes, H, W), dtype=torch.float32, device=device)
        counts = torch.zeros((1, H, W), dtype=torch.float32, device=device)

        for idx in range(0, len(crops), chunk_size):
            sub_batch = batch[idx:idx + chunk_size].to(device)
            sub_batch = (sub_batch - mean) / std
            if device.type == "cuda":
                sub_batch = sub_batch.half()

            with torch.no_grad():
                sub_logits = model(pixel_values=sub_batch).logits
            sub_up = F.interpolate(sub_logits.float(), size=(crop_size, crop_size), mode="bilinear", align_corners=False)

            for k in range(sub_batch.shape[0]):
                y, x = coords[idx + k]
                full_logits[:, y:y + crop_size, x:x + crop_size] += sub_up[k]
                counts[:, y:y + crop_size, x:x + crop_size] += 1.0

        avg_logits = full_logits / counts.clamp(min=1.0)
        pred_class = avg_logits.argmax(dim=0).cpu().numpy()
        mask = np.isin(pred_class, flood_classes)
        return mask

    # Whole-tile resize inference (Fast mode, standard for CPU or whole images)
    batch = F.interpolate(tensor_img.unsqueeze(0), size=(size, size), mode="bilinear", align_corners=False).to(device)
    batch = (batch - mean) / std
    if device.type == "cuda":
        batch = batch.half()

    with torch.no_grad():
        logits = model(pixel_values=batch).logits
        up = F.interpolate(logits.float(), size=(H, W), mode="bilinear", align_corners=False)
        pred_class = up.argmax(dim=1)[0].cpu().numpy()

    mask = np.isin(pred_class, flood_classes)
    return mask


def judge(
    pre: Union[str, np.ndarray],
    post: Union[str, np.ndarray],
    threshold: float = NEW_FLOOD_THRESHOLD,
    model_dir: Optional[str] = None,
    flood_classes: Optional[List[int]] = None,
    device: str = "auto",
    mode: str = "accurate",
    size: int = 768,
    backend: str = "onnx",
    include_dev_fields: bool = False,
) -> Dict[str, Any]:
    """
    Main evaluation function:
    Compares pre-event and post-event images, detects newly inundated areas,
    evaluates cloud coverage, and returns the strict decision JSON.
    """
    # 1. Load images if paths were passed
    pre_rgb = load_rgb(pre) if isinstance(pre, str) else np.asarray(pre, dtype=np.uint8)
    post_rgb = load_rgb(post) if isinstance(post, str) else np.asarray(post, dtype=np.uint8)

    # 2. If sizes differ, resize AFTER to BEFORE
    if post_rgb.shape[:2] != pre_rgb.shape[:2]:
        post_im = Image.fromarray(post_rgb).resize((pre_rgb.shape[1], pre_rgb.shape[0]), Image.BILINEAR)
        post_rgb = np.asarray(post_im, dtype=np.uint8)

    # 3. Model setup and class ID resolution
    model, dev, resolved_dir, id2label = get_model(model_dir=model_dir, device_str=device)

    # If flood_classes not specified, default to [1] (or FW_WATER_CLASS environment variable)
    if flood_classes is None:
        env_cls = os.getenv("FW_WATER_CLASS", "1")
        flood_classes = [int(c.strip()) for c in env_cls.split(",") if c.strip()]

    # 4. Run segmentation (accurate sliding-window mode)
    pre_mask = segment_flood(pre_rgb, model, dev, flood_classes, mode="accurate", size=size)
    post_mask = segment_flood(post_rgb, model, dev, flood_classes, mode="accurate", size=size)

    # 5. Measure metrics (isolate NEW flood only)
    pre_frac = float(pre_mask.mean())
    post_frac = float(post_mask.mean())
    new_mask = post_mask & (~pre_mask)
    new_frac = float(new_mask.mean())

    detected = bool(new_frac >= threshold)
    ratio = (new_frac / threshold) if threshold > 0 else 0.0

    # 6. Apply Cloud and Decision Rules
    cloudy = looks_cloudy(post_rgb)

    if cloudy:
        confidence = "low"
        reasoning = (
            "The POST image is mostly cloud or haze, so the ground cannot be read reliably "
            f"(newly flooded area measured at {new_frac:.1%})."
        )
    else:
        if detected:
            confidence = "high" if ratio >= 3.0 else ("medium" if ratio >= 1.5 else "low")
            reasoning = (
                f"Flooded area grew from {pre_frac:.1%} before to {post_frac:.1%} after, "
                f"with {new_frac:.1%} of the scene newly inundated."
            )
        else:
            confidence = "medium" if ratio <= 0.25 else "low"
            reasoning = (
                f"Flooded area is {pre_frac:.1%} before and {post_frac:.1%} after, "
                f"only {new_frac:.1%} newly inundated, below the {threshold:.1%} threshold."
            )

    model_name = os.path.basename(resolved_dir)
    if not model_name or model_name == "segformer":
        model_name = "segformer-b0-checkpoint-joint"

    res = {
        "flood_damage_detected": detected,
        "confidence": confidence,
        "reasoning": reasoning,
    }
    if include_dev_fields:
        res["model"] = model_name
        res["metrics"] = {
            "pre_flood_fraction": round(pre_frac, 4),
            "post_flood_fraction": round(post_frac, 4),
            "new_flood_fraction": round(new_frac, 4),
        }
    return res


def find_tile_pair(input_dir: str, tile_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolves PRE and POST image paths for a tile in input_dir."""
    pre_candidates = glob.glob(os.path.join(input_dir, "PRE-event", f"*_{tile_id}.*")) + \
                     glob.glob(os.path.join(input_dir, "PRE-event", f"*{tile_id}*"))
    post_candidates = glob.glob(os.path.join(input_dir, "POST-event", f"*_{tile_id}.*")) + \
                      glob.glob(os.path.join(input_dir, "POST-event", f"*{tile_id}*"))
    pre_p = pre_candidates[0] if pre_candidates else None
    post_p = post_candidates[0] if post_candidates else None
    return pre_p, post_p


def run_batch_directory(input_dir: str, out_dir: str, threshold: float, device: str, mode: str, flood_classes: List[int], backend: str) -> None:
    """Processes PRE-event and POST-event folders and outputs ai_predictions.json."""
    pre_files = glob.glob(os.path.join(input_dir, "PRE-event", "*.*"))
    tile_ids = set()
    for pf in pre_files:
        stem = os.path.splitext(os.path.basename(pf))[0]
        tile_id = "_".join(stem.split("_")[-3:])
        tile_ids.add(tile_id)

    results = {}
    for tid in sorted(tile_ids):
        pre_p, post_p = find_tile_pair(input_dir, tid)
        if not pre_p or not post_p:
            continue
        res = judge(pre_p, post_p, threshold=threshold, device=device, mode=mode, flood_classes=flood_classes, backend=backend, include_dev_fields=False)
        results[tid] = res

    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "ai_predictions.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    sys.stderr.write(f"Batch inference complete: wrote {len(results)} tiles to {out_file}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Offline replacement for cloud vision flood damage detection API."
    )
    parser.add_argument("--pre", help="Path to BEFORE/PRE-event image (tif, jpg, png)")
    parser.add_argument("--post", help="Path to AFTER/POST-event image (tif, jpg, png)")
    parser.add_argument("--threshold", type=float, default=NEW_FLOOD_THRESHOLD, help=f"Decision threshold (default: {NEW_FLOOD_THRESHOLD})")
    parser.add_argument("--backend", default="onnx", help="Inference backend (onnx, hf, torch). Defaults to onnx.")
    parser.add_argument("--model", default=None, help="Path to SegFormer model checkpoint folder or file")
    parser.add_argument("--flood-classes", default="1", help="Comma-separated class IDs meaning flood (default: 1)")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="Inference device (default: auto)")
    parser.add_argument("--mode", choices=["auto", "fast", "accurate"], default="accurate", help="Inference mode (default: accurate)")
    parser.add_argument("--size", type=int, default=768, help="Fast mode resize dimension (default: 768)")
    parser.add_argument("--input", "--input-dir", dest="input_dir", default=None, help="Batch directory containing PRE-event and POST-event folders")
    parser.add_argument("--out-dir", default="output", help="Batch output directory for ai_predictions.json")
    parser.add_argument("--dev", action="store_true", help="Include dev-only model and metrics fields in output JSON")
    args = parser.parse_args()

    classes = [int(c.strip()) for c in args.flood_classes.split(",") if c.strip()]

    # Batch directory mode
    if args.input_dir:
        run_batch_directory(
            input_dir=args.input_dir,
            out_dir=args.out_dir,
            threshold=args.threshold,
            device=args.device,
            mode=args.mode,
            flood_classes=classes,
            backend=args.backend,
        )
        return

    # Single pair evaluation mode
    if not args.pre or not args.post:
        parser.error("Must specify either --pre and --post, or --input/--input-dir.")

    result = judge(
        pre=args.pre,
        post=args.post,
        threshold=args.threshold,
        model_dir=args.model,
        flood_classes=classes,
        device=args.device,
        mode=args.mode,
        size=args.size,
        backend=args.backend,
        include_dev_fields=args.dev,
    )

    # Output strict JSON and nothing else on stdout
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
