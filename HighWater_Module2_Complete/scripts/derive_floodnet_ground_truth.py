"""Derive per-image ground truth from FloodNet segmentation masks.

Label encoding (verified against real files): grayscale (mode 'L') PNG, raw
class-index pixel values, matching the documented FloodNet legend:
0=Background, 1=Building-Flooded, 2=Building-Non-Flooded, 3=Road-Flooded,
4=Road-Non-Flooded, 5=Water, 6=Tree, 7=Vehicle, 8=Pool, 9=Grass.

Across the 30 real label files inspected, classes 0 (Background) and 3
(Road-Flooded) never appear at all, and only one image has any class-1
(Building-Flooded) pixels — this is a real property of this small sample,
not an encoding mismatch.

An image counts as "flooded" if pixels of class 1 (Building-Flooded) or
class 3 (Road-Flooded) are present above MIN_FLOODED_PIXELS, a small fixed
threshold chosen to filter stray/mislabeled pixels while still catching any
real flooded region. Chosen as 500 px (~0.004% of a 4000x3000 image) —
small enough to catch a real building/road-sized region, large enough that
a handful of mislabeled pixels at class boundaries can't flip the label.

Run: python scripts/derive_floodnet_ground_truth.py
"""
import glob
import json
import os

import numpy as np
from PIL import Image

BASE = os.path.join(os.path.dirname(__file__), "..")
LABEL_DIR = os.path.join(BASE, "data", "raw_floodnet", "test-label-img")
OUT_PATH = os.path.join(BASE, "output_floodnet", "ground_truth.json")

MIN_FLOODED_PIXELS = 500
FLOODED_CLASSES = {1, 3}  # Building-Flooded, Road-Flooded


def main():
    results = {}
    files = sorted(glob.glob(os.path.join(LABEL_DIR, "*_lab.png")))
    for fp in files:
        image_id = os.path.basename(fp).replace("_lab.png", "")
        arr = np.array(Image.open(fp))
        total_pixels = arr.size
        flooded_pixels = int(np.isin(arr, list(FLOODED_CLASSES)).sum())
        flooded_percent = 100 * flooded_pixels / total_pixels
        flooded = flooded_pixels >= MIN_FLOODED_PIXELS
        results[image_id] = {
            "flooded": flooded,
            "flooded_pixels": flooded_pixels,
            "total_pixels": total_pixels,
            "flooded_percent": flooded_percent,
        }

    with open(OUT_PATH, "w") as fh:
        json.dump({
            "method": (
                f"flooded = (Building-Flooded class 1 OR Road-Flooded class 3) pixel count "
                f">= {MIN_FLOODED_PIXELS} px, from the raw grayscale class-index label PNG."
            ),
            "min_flooded_pixels_threshold": MIN_FLOODED_PIXELS,
            "images": results,
        }, fh, indent=2)

    n_flooded = sum(1 for v in results.values() if v["flooded"])
    print(f"Total images: {len(results)}")
    print(f"Flooded: {n_flooded}, Not flooded: {len(results) - n_flooded}")
    print(f"Written to {OUT_PATH}")


if __name__ == "__main__":
    main()
