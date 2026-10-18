"""Offline AI flood detection using trained SegFormer-B0.

Runs fully local inference without any cloud API keys or internet connection.
Compatible with FloodNet test images, SpaceNet, and external aerial drone photos.

Outputs predictions in the same contract schema used by ai_flood_detect_floodnet.py,
allowing direct validation against ground truth via validate_floodnet_predictions.py.

Usage:
  python scripts/ai_flood_detect_offline.py
  python scripts/ai_flood_detect_offline.py --images data/raw_floodnet/test-org-img --out output_floodnet/ai_predictions_segformer.json
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
DEFAULT_MODEL_DIR = BASE_DIR / "models" / "segformer"
DEFAULT_IMG_DIR = BASE_DIR / "data" / "raw_floodnet" / "test-org-img"
DEFAULT_OUT_PATH = BASE_DIR / "output_floodnet" / "ai_predictions_segformer.json"

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
FLOOD_THRESHOLD_PERCENT = 0.5  # If >0.5% of pixels are flooded, flag damage

def to_tensor(img_uint8):
    x = (img_uint8.astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(x.transpose(2, 0, 1).copy()).unsqueeze(0)

def load_model(model_dir):
    if not (model_dir / "model.safetensors").exists():
        # Fallback to floodnet_data checkpoints if not yet copied
        fallback = BASE_DIR.parent.parent / "floodnet_data" / "checkpoints_full" / "best"
        if (fallback / "model.safetensors").exists():
            model_dir = fallback
        else:
            raise FileNotFoundError(f"SegFormer model weights not found in {model_dir}")
    print(f"Loading SegFormer weights from: {model_dir}")
    model = SegformerForSemanticSegmentation.from_pretrained(str(model_dir))
    model.eval()
    return model

@torch.no_grad()
def infer_image(model, img_path, device="cpu"):
    pil_img = Image.open(img_path).convert("RGB")
    orig_w, orig_h = pil_img.size
    
    # Resize to standard 640x480 for fast consistent inference
    resized = pil_img.resize((640, 480), Image.BILINEAR)
    tensor = to_tensor(np.array(resized)).to(device)
    
    logits = model(pixel_values=tensor).logits
    logits = F.interpolate(logits, size=(480, 640), mode="bilinear", align_corners=False)
    pred = logits.argmax(1).squeeze(0).cpu().numpy()
    
    # Class 0: Background, Class 1: Flooded, Class 2: Natural Water
    flooded_px = int((pred == 1).sum())
    water_px = int((pred == 2).sum())
    total_px = pred.size
    
    flood_pct = (flooded_px / total_px) * 100.0
    water_pct = (water_px / total_px) * 100.0
    
    is_flooded = flood_pct >= FLOOD_THRESHOLD_PERCENT
    
    # Assign confidence based on flood percentage and margin
    if flood_pct > 5.0 or (not is_flooded and flood_pct < 0.1):
        confidence = "high"
    elif flood_pct > 1.0 or (not is_flooded and flood_pct < 0.3):
        confidence = "medium"
    else:
        confidence = "low"
        
    if is_flooded:
        reasoning = f"SegFormer detected {flood_pct:.2f}% submerged area (flooded buildings/roads) and {water_pct:.2f}% natural water."
    else:
        reasoning = f"No significant inundation detected ({flood_pct:.2f}% flooded pixels, {water_pct:.2f}% natural water)."
        
    return {
        "flood_damage_detected": bool(is_flooded),
        "confidence": confidence,
        "reasoning": reasoning,
        "flooded_percent": round(flood_pct, 2),
        "natural_water_percent": round(water_pct, 2),
        "model": "segformer-b0-floodnet-local"
    }

def main():
    parser = argparse.ArgumentParser(description="Run local SegFormer flood inference")
    parser.add_argument("--images", default=str(DEFAULT_IMG_DIR), help="Path to input images directory")
    parser.add_argument("--model", default=str(DEFAULT_MODEL_DIR), help="Path to SegFormer model directory")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH), help="Path to output predictions JSON")
    args = parser.parse_args()

    img_dir = Path(args.images)
    model_dir = Path(args.model)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    model = load_model(model_dir)
    image_files = sorted(list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png")))
    if not image_files:
        print(f"No images found in {img_dir}")
        return

    print(f"Running offline inference on {len(image_files)} images from {img_dir}...")
    results = {}
    flooded_count = 0
    t0 = time.time()

    for idx, img_path in enumerate(image_files, 1):
        # Extract base image id (strip extension and common suffixes like _lab)
        image_id = img_path.stem
        res = infer_image(model, img_path)
        results[image_id] = res
        if res["flood_damage_detected"]:
            flooded_count += 1
        print(f"[{idx}/{len(image_files)}] {img_path.name} -> Flood: {res['flood_damage_detected']} ({res['flooded_percent']}%) | Conf: {res['confidence']}")

    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=2)

    elapsed = time.time() - t0
    print(f"\nDone! Processed {len(image_files)} images in {elapsed:.1f}s ({elapsed/len(image_files):.2f}s/img).")
    print(f"Detected flood damage in {flooded_count}/{len(image_files)} images.")
    print(f"Predictions saved to: {out_path}")

if __name__ == "__main__":
    main()
