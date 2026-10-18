"""
FloodWatch core: before/after water segmentation with a local SegFormer model.

    Net Flood Intrusion = After water % - Before water %

CLI:
    python -m src.flood_inference --tile 0_39_62
"""
from __future__ import annotations

import argparse
import glob
import os
import time
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Optional

import numpy as np
import rasterio
import torch
import torch.nn.functional as F
from transformers import SegformerForSemanticSegmentation

# ---------------------------------------------------------------- config
MODEL_DIR = os.getenv("FW_MODEL_DIR", "models/segformer")
DATA_DIR = os.getenv("FW_DATA_DIR", "data/raw")
WATER_CLASS = int(os.getenv("FW_WATER_CLASS", "1"))   # verify against model.config.id2label
INPUT_SIZE = int(os.getenv("FW_INPUT_SIZE", "768"))

# ImageNet stats (standard for SegFormer); change if you trained differently.
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
USE_FP16 = DEVICE.type == "cuda"


# ---------------------------------------------------------------- types
@dataclass
class TileResult:
    tile_id: str
    before_water_pct: float
    after_water_pct: float
    net_intrusion_pct: float
    latency_ms: int
    device: str
    timings: Optional[dict[str, float]] = None

    def to_dict(self) -> dict:
        return asdict(self)


class TileNotFound(FileNotFoundError):
    pass


# ---------------------------------------------------------------- model
@lru_cache(maxsize=1)
def get_model() -> SegformerForSemanticSegmentation:
    """Load the model once and keep it on the device."""
    model = SegformerForSemanticSegmentation.from_pretrained(MODEL_DIR)
    model.eval().to(DEVICE)
    if USE_FP16:
        model.half()
    return model


# ---------------------------------------------------------------- data
def find_tile_paths(tile_id: str) -> tuple[str, str]:
    """Resolve pre/post GeoTIFF paths for a tile ID like '0_39_62'."""
    pre = glob.glob(os.path.join(DATA_DIR, "PRE-event", f"*_{tile_id}.tif"))
    post = glob.glob(os.path.join(DATA_DIR, "POST-event", f"*_{tile_id}.tif"))
    if not pre:
        raise TileNotFound(f"No PRE-event image for tile {tile_id}")
    if not post:
        raise TileNotFound(f"No POST-event image for tile {tile_id}")
    return pre[0], post[0]


def list_tiles() -> list[str]:
    """Tile IDs that have BOTH a pre and a post image."""
    def ids(sub: str) -> set[str]:
        out = set()
        for p in glob.glob(os.path.join(DATA_DIR, sub, "*.tif")):
            stem = os.path.splitext(os.path.basename(p))[0]
            out.add("_".join(stem.split("_")[-3:]))
        return out
    return sorted(ids("PRE-event") & ids("POST-event"))


def load_rgb(path: str) -> torch.Tensor:
    """Read a GeoTIFF as a float tensor (3, H, W) scaled to [0, 1]."""
    with rasterio.open(path) as src:
        arr = src.read([1, 2, 3])
    if np.issubdtype(arr.dtype, np.integer):
        arr = arr.astype(np.float32) / float(np.iinfo(arr.dtype).max)
    else:
        arr = np.clip(arr.astype(np.float32), 0.0, 1.0)
    return torch.from_numpy(arr)


# ---------------------------------------------------------------- inference
@torch.no_grad()
def segment_water_with_timings(images: list[torch.Tensor], mode: str = "fast") -> tuple[list[torch.Tensor], dict[str, float]]:
    """
    Run SegFormer on a list of (3, H, W) images and record fine-grained stage timings.
    Returns (masks, timings) where timings contains preprocess, gpu, postprocess in ms.
    """
    model = get_model()
    sizes = [img.shape[-2:] for img in images]
    mean = MEAN.to(DEVICE)
    std = STD.to(DEVICE)

    if mode == "accurate":
        crop_size = 512
        stride = 256
        chunk_size = 8
        masks = []
        t_pre_total = 0.0
        t_gpu_total = 0.0
        t_post_total = 0.0

        for img in images:
            t0 = time.perf_counter()
            _, H, W = img.shape
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
                    crops.append(img[:, y:y + crop_size, x:x + crop_size])
                    coords.append((y, x))

            batch = torch.stack(crops)
            t_pre_total += (time.perf_counter() - t0) * 1000

            full_logits = torch.zeros((3, H, W), dtype=torch.float32, device=DEVICE)
            counts = torch.zeros((1, H, W), dtype=torch.float32, device=DEVICE)

            for idx in range(0, len(crops), chunk_size):
                t_pre_sub = time.perf_counter()
                sub_batch = batch[idx:idx + chunk_size].to(DEVICE)
                sub_batch = (sub_batch - mean) / std
                if USE_FP16:
                    sub_batch = sub_batch.half()
                t_pre_total += (time.perf_counter() - t_pre_sub) * 1000

                if DEVICE.type == "cuda":
                    torch.cuda.synchronize()
                t_gpu_sub = time.perf_counter()
                sub_logits = model(pixel_values=sub_batch).logits
                if DEVICE.type == "cuda":
                    torch.cuda.synchronize()
                t_gpu_total += (time.perf_counter() - t_gpu_sub) * 1000

                t_post_sub = time.perf_counter()
                sub_up = F.interpolate(sub_logits.float(), size=(crop_size, crop_size), mode="bilinear", align_corners=False)
                for k in range(sub_batch.shape[0]):
                    y, x = coords[idx + k]
                    full_logits[:, y:y + crop_size, x:x + crop_size] += sub_up[k]
                    counts[:, y:y + crop_size, x:x + crop_size] += 1.0
                t_post_total += (time.perf_counter() - t_post_sub) * 1000

            t_post_end = time.perf_counter()
            avg_logits = full_logits / counts.clamp(min=1.0)
            masks.append((avg_logits.argmax(dim=0) == WATER_CLASS).cpu())
            t_post_total += (time.perf_counter() - t_post_end) * 1000

        timings = {"preprocess": t_pre_total, "gpu": t_gpu_total, "postprocess": t_post_total}
        return masks, timings

    # Default 'fast' mode: whole-tile resize to INPUT_SIZE
    t_pre_0 = time.perf_counter()
    batch = torch.stack([
        F.interpolate(img.unsqueeze(0), size=(INPUT_SIZE, INPUT_SIZE),
                      mode="bilinear", align_corners=False)[0]
        for img in images
    ]).to(DEVICE)
    batch = (batch - mean) / std
    if USE_FP16:
        batch = batch.half()
    t_pre = (time.perf_counter() - t_pre_0) * 1000

    if DEVICE.type == "cuda":
        torch.cuda.synchronize()
    t_gpu_0 = time.perf_counter()
    logits = model(pixel_values=batch).logits            # (B, C, H/4, W/4)
    if DEVICE.type == "cuda":
        torch.cuda.synchronize()
    t_gpu = (time.perf_counter() - t_gpu_0) * 1000

    t_post_0 = time.perf_counter()
    masks = []
    for i, size in enumerate(sizes):
        up = F.interpolate(logits[i:i + 1].float(), size=size,
                           mode="bilinear", align_corners=False)
        masks.append((up.argmax(dim=1)[0] == WATER_CLASS).cpu())
    t_post = (time.perf_counter() - t_post_0) * 1000

    timings = {"preprocess": t_pre, "gpu": t_gpu, "postprocess": t_post}
    return masks, timings


@torch.no_grad()
def segment_water(images: list[torch.Tensor], mode: str = "fast") -> list[torch.Tensor]:
    """Run SegFormer on a list of images. Returns boolean water masks."""
    masks, _ = segment_water_with_timings(images, mode=mode)
    return masks


def water_pct(mask: torch.Tensor) -> float:
    return round(mask.float().mean().item() * 100.0, 2)


def analyze_tile(tile_id: str, return_masks: bool = False, return_tensors: bool = False, mode: str = "fast"):
    """Before/after analysis for one tile. Supports mode='fast'|'accurate'."""
    t0 = time.perf_counter()
    pre_path, post_path = find_tile_paths(tile_id)

    t_io_0 = time.perf_counter()
    pre, post = load_rgb(pre_path), load_rgb(post_path)
    if pre.shape != post.shape:   # misaligned sizes: match post to pre
        post = F.interpolate(post.unsqueeze(0), size=pre.shape[-2:],
                             mode="bilinear", align_corners=False)[0]
    t_io = (time.perf_counter() - t_io_0) * 1000

    try:
        masks, sub_timings = segment_water_with_timings([pre, post], mode=mode)
        pre_mask, post_mask = masks[0], masks[1]
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()                           # retry one by one
        m0, t0_s = segment_water_with_timings([pre], mode=mode)
        m1, t1_s = segment_water_with_timings([post], mode=mode)
        pre_mask, post_mask = m0[0], m1[0]
        sub_timings = {
            "preprocess": t0_s["preprocess"] + t1_s["preprocess"],
            "gpu": t0_s["gpu"] + t1_s["gpu"],
            "postprocess": t0_s["postprocess"] + t1_s["postprocess"],
        }

    before, after = water_pct(pre_mask), water_pct(post_mask)
    total_time = (time.perf_counter() - t0) * 1000
    timings = {
        "io": round(t_io, 1),
        "preprocess": round(sub_timings["preprocess"], 1),
        "gpu": round(sub_timings["gpu"], 1),
        "postprocess": round(sub_timings["postprocess"], 1),
        "total": round(total_time, 1),
    }

    result = TileResult(
        tile_id=tile_id,
        before_water_pct=before,
        after_water_pct=after,
        net_intrusion_pct=round(after - before, 2),
        latency_ms=int(total_time),
        device=DEVICE.type,
        timings=timings,
    )
    if return_tensors:
        return (result, pre_mask, post_mask, (pre, post))
    return (result, pre_mask, post_mask) if return_masks else result


# ---------------------------------------------------------------- CLI
def _main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="FloodWatch tile analysis")
    ap.add_argument("--tile", required=True, help="Tile ID, e.g. 0_39_62")
    args = ap.parse_args(argv)

    get_model()                      # warm up so reported latency is realistic
    analyze_tile(args.tile)          # first call includes CUDA warm-up
    r = analyze_tile(args.tile)
    print(f"Tile {r.tile_id}")
    print(f"  Before water : {r.before_water_pct} %")
    print(f"  After water  : {r.after_water_pct} %")
    print(f"  Net intrusion: {r.net_intrusion_pct:+} %")
    print(f"  Latency      : {r.latency_ms} ms (device: {r.device})")


if __name__ == "__main__":
    _main()
