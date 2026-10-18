"""Offline AI flood detection on SpaceNet 8 satellite imagery (Germany & Louisiana).

Runs 100% locally using our trained SegFormer-B0 model without any external API calls.
Analyzes POST-event imagery (and compares against PRE-event baselines where available)
to detect water intrusion, flood extent, and damaged zones.

Outputs predictions matching the project's data contract in:
  - Germany:   output/ai_predictions.json
  - Louisiana: output_louisiana/ai_predictions.json

Usage:
  python scripts/ai_flood_detect_spacenet_offline.py --dataset germany
  python scripts/ai_flood_detect_spacenet_offline.py --dataset louisiana
"""
import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import SegformerForSemanticSegmentation

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "models" / "segformer"

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

DATASET_CONFIGS = {
    "germany": {
        "raw_dir": BASE_DIR / "data" / "raw",
        "out_path": BASE_DIR / "output" / "ai_predictions_segformer.json",
        "tiles": [f"0_{r}_{c}" for r in range(36, 42) for c in range(59, 63)],
        "label": "Dernau, Germany (SpaceNet 8)"
    },
    "louisiana": {
        "raw_dir": BASE_DIR / "data" / "raw_louisiana",
        "out_path": BASE_DIR / "output_louisiana" / "ai_predictions.json",
        "tiles": ["2_20_43", "2_20_44", "2_20_45", "2_19_43", "2_21_43", "2_21_44", "2_18_44", "2_19_45", "2_19_44"],
        "label": "Louisiana, USA (SpaceNet 8)"
    }
}

def load_model(device="cpu"):
    if not (MODEL_DIR / "model.safetensors").exists():
        fallback = BASE_DIR.parent.parent / "floodnet_data" / "checkpoints_full" / "best"
        if (fallback / "model.safetensors").exists():
            model_path = fallback
        else:
            raise FileNotFoundError(f"Model weights not found at {MODEL_DIR}")
    else:
        model_path = MODEL_DIR
    print(f"Loading SegFormer weights from: {model_path}")
    model = SegformerForSemanticSegmentation.from_pretrained(str(model_path)).to(device)
    model.eval()
    return model

@torch.no_grad()
def analyze_tile(model, post_path, pre_path=None, device="cpu"):
    im_post = Image.open(post_path).convert("RGB")
    w, h = im_post.size

    # Extract 5 spatial crops across the satellite tile (corners + center)
    crop_size = min(512, w, h)
    crops = [
        im_post.crop((0, 0, crop_size, crop_size)),
        im_post.crop((w - crop_size, 0, w, crop_size)),
        im_post.crop((0, h - crop_size, crop_size, h)),
        im_post.crop((w - crop_size, h - crop_size, w, h)),
        im_post.crop((w // 2 - crop_size // 2, h // 2 - crop_size // 2, w // 2 + crop_size // 2, h // 2 + crop_size // 2))
    ]

    water_pixels = 0
    total_pixels = 0
    for crp in crops:
        x = (np.array(crp).astype(np.float32) / 255.0 - MEAN) / STD
        t = torch.from_numpy(x.transpose(2, 0, 1)).unsqueeze(0).to(device)
        logits = F.interpolate(model(pixel_values=t).logits, size=(crop_size, crop_size), mode="bilinear", align_corners=False)
        pred = logits.argmax(1).squeeze(0).cpu().numpy()
        # Class 1 = flooded, Class 2 = natural water
        water_pixels += int((pred > 0).sum())
        total_pixels += pred.size

    water_pct = (water_pixels / total_pixels) * 100.0

    # Decision threshold: In satellite imagery, water coverage > 0.5% indicates water presence/flooding
    is_flooded = water_pct > 0.5

    # Check PRE-event baseline if available
    pre_water_pct = 0.0
    if pre_path and os.path.exists(pre_path):
        try:
            im_pre = Image.open(pre_path).convert("RGB")
            pw, ph = im_pre.size
            p_crop = im_pre.crop((pw // 2 - crop_size // 2, ph // 2 - crop_size // 2, pw // 2 + crop_size // 2, ph // 2 + crop_size // 2))
            px = (np.array(p_crop).astype(np.float32) / 255.0 - MEAN) / STD
            pt = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).to(device)
            p_logits = F.interpolate(model(pixel_values=pt).logits, size=(crop_size, crop_size), mode="bilinear", align_corners=False)
            p_pred = p_logits.argmax(1).squeeze(0).cpu().numpy()
            pre_water_pct = float((p_pred > 0).sum()) / p_pred.size * 100.0
        except Exception:
            pre_water_pct = 0.0

    net_change = water_pct - pre_water_pct

    # Determine confidence and reasoning
    if water_pct > 15.0 or (not is_flooded and water_pct == 0.0):
        confidence = "high"
    elif water_pct > 2.0 or (not is_flooded and water_pct < 0.2):
        confidence = "medium"
    else:
        confidence = "low"

    if is_flooded:
        reasoning = f"SegFormer detected {water_pct:.1f}% water coverage in POST-event satellite tile (net surge: {net_change:+.1f}% vs PRE baseline)."
    else:
        reasoning = f"Dry landscape with no significant flood inundation ({water_pct:.1f}% water detected)."

    return {
        "flood_damage_detected": bool(is_flooded),
        "confidence": confidence,
        "reasoning": reasoning,
        "water_coverage_percent": round(water_pct, 2),
        "net_change_percent": round(net_change, 2),
        "model": "segformer-b0-local-offline"
    }

def run_dataset(dataset_key):
    cfg = DATASET_CONFIGS[dataset_key]
    raw_dir = cfg["raw_dir"]
    out_path = cfg["out_path"]
    tiles = cfg["tiles"]
    label = cfg["label"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(device=device)

    print(f"\n=======================================================")
    print(f"Running Offline AI Detection on {label}")
    print(f"Target tiles: {len(tiles)} | Output: {out_path}")
    print(f"=======================================================")

    results = {}
    flooded_count = 0
    t0 = time.time()

    for idx, tile_id in enumerate(tiles, 1):
        post_matches = glob.glob(str(raw_dir / "POST-event" / f"*{tile_id}.tif"))
        pre_matches = glob.glob(str(raw_dir / "PRE-event" / f"*{tile_id}.tif"))

        if not post_matches:
            print(f"[{idx}/{len(tiles)}] Tile {tile_id} -> POST imagery missing, skipping")
            continue

        post_file = post_matches[0]
        pre_file = pre_matches[0] if pre_matches else None

        res = analyze_tile(model, post_file, pre_file, device=device)
        results[tile_id] = res

        if res["flood_damage_detected"]:
            flooded_count += 1

        print(f"[{idx}/{len(tiles)}] Tile {tile_id} -> Flood: {res['flood_damage_detected']} ({res['water_coverage_percent']}%) | Conf: {res['confidence']}")

    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=2)

    elapsed = time.time() - t0
    print(f"\nDone! Processed {len(results)} tiles in {elapsed:.1f}s ({elapsed/max(1, len(results)):.2f}s/tile).")
    print(f"Detected flood damage in {flooded_count}/{len(results)} tiles.")
    print(f"Saved results to: {out_path}")
    return results

def main():
    parser = argparse.ArgumentParser(description="Run local SegFormer AI flood detection on SpaceNet satellite data")
    parser.add_argument("--dataset", choices=["germany", "louisiana", "all"], default="germany",
                        help="Which dataset to process (germany, louisiana, or all)")
    args = parser.parse_args()

    if args.dataset in ["germany", "all"]:
        run_dataset("germany")
    if args.dataset in ["louisiana", "all"]:
        run_dataset("louisiana")

if __name__ == "__main__":
    main()
