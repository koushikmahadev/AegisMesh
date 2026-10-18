"""
Threshold sweep over all Germany AOI tiles with PRE, POST imagery and ground truth.
Uses scripts/ai_flood_detect_local.py logic on CUDA.
Saves CSV to output/threshold_sweep.csv.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image
import torch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.ai_flood_detect_local import get_model, load_rgb, looks_cloudy, segment_flood
from src.flood_inference import find_tile_paths

RAW_DIR = os.path.join(REPO_ROOT, "data", "raw")
OUT_DIR = os.path.join(REPO_ROOT, "output")
OUT_CSV = os.path.join(OUT_DIR, "threshold_sweep.csv")

THRESHOLDS = [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]


def find_all_germany_tiles() -> List[str]:
    """Finds all tile IDs that have PRE-event, POST-event, and annotations."""
    pre_files = glob.glob(os.path.join(RAW_DIR, "PRE-event", "*.tif"))
    post_files = glob.glob(os.path.join(RAW_DIR, "POST-event", "*.tif"))
    ann_files = glob.glob(os.path.join(RAW_DIR, "annotations", "*.geojson"))

    def get_tid(p: str) -> str:
        base = os.path.splitext(os.path.basename(p))[0]
        parts = base.split("_")
        return f"{parts[-3]}_{parts[-2]}_{parts[-1]}"

    pre_tids = {get_tid(p) for p in pre_files}
    post_tids = {get_tid(p) for p in post_files}
    ann_tids = {os.path.splitext(os.path.basename(p))[0] for p in ann_files}

    common = sorted(list(pre_tids & post_tids & ann_tids))
    return common


def get_gt_flooded_info(tile_id: str) -> Tuple[bool, int]:
    """Returns (gt_flooded: bool, gt_flooded_feature_count: int) from SpaceNet 8 GeoJSON."""
    ann_path = os.path.join(RAW_DIR, "annotations", f"{tile_id}.geojson")
    if not os.path.exists(ann_path):
        return False, 0
    with open(ann_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    fl_count = 0
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        if props.get("flooded") == "yes":
            fl_count += 1
    return (fl_count > 0), fl_count


def run_sweep():
    os.makedirs(OUT_DIR, exist_ok=True)
    tile_ids = find_all_germany_tiles()
    print(f"Total Germany AOI tiles with PRE, POST, and GT: {len(tile_ids)}")

    # Load model on CUDA
    device_str = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device_str}")
    model, dev, model_dir, id2label = get_model(device_str=device_str)

    rows = []
    t0 = time.time()

    print("\nProcessing tiles on CUDA...")
    for i, tid in enumerate(tile_ids, 1):
        pre_p, post_p = find_tile_paths(tid)
        pre_rgb = load_rgb(pre_p)
        post_rgb = load_rgb(post_p)

        # Match sizes if differing
        if post_rgb.shape[:2] != pre_rgb.shape[:2]:
            post_im = Image.fromarray(post_rgb).resize((pre_rgb.shape[1], pre_rgb.shape[0]), Image.BILINEAR)
            post_rgb = np.asarray(post_im, dtype=np.uint8)

        # Cloud check on POST image
        is_cloudy = looks_cloudy(post_rgb)

        # GT info
        gt_flooded, gt_count = get_gt_flooded_info(tid)

        # Fast mode inference
        m_pf = segment_flood(pre_rgb, model, dev, flood_classes=[1], mode="fast", size=768)
        m_qf = segment_flood(post_rgb, model, dev, flood_classes=[1], mode="fast", size=768)
        pre_frac_fast = float(m_pf.mean())
        post_frac_fast = float(m_qf.mean())
        new_frac_fast = float((m_qf & ~m_pf).mean())

        # Accurate mode inference (sliding window 512 crops)
        m_pa = segment_flood(pre_rgb, model, dev, flood_classes=[1], mode="accurate", size=768)
        m_qa = segment_flood(post_rgb, model, dev, flood_classes=[1], mode="accurate", size=768)
        new_frac_acc = float((m_qa & ~m_pa).mean())

        row = {
            "tile_id": tid,
            "gt_flooded": gt_flooded,
            "gt_flooded_feature_count": gt_count,
            "pre_frac": round(pre_frac_fast, 6),
            "post_frac": round(post_frac_fast, 6),
            "new_frac (fast)": round(new_frac_fast, 6),
            "new_frac (accurate)": round(new_frac_acc, 6),
            "cloudy": is_cloudy,
        }
        rows.append(row)

        if i % 25 == 0 or i == len(tile_ids):
            elapsed = time.time() - t0
            print(f"  [{i}/{len(tile_ids)}] {elapsed:.1f}s ({elapsed/i*1000:.1f}ms/tile) - last: {tid} (gt={gt_flooded}, fast={new_frac_fast:.4f}, acc={new_frac_acc:.4f})")

    # 1. Save CSV
    fieldnames = [
        "tile_id",
        "gt_flooded",
        "gt_flooded_feature_count",
        "pre_frac",
        "post_frac",
        "new_frac (fast)",
        "new_frac (accurate)",
        "cloudy",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[OK] Saved threshold sweep CSV to: {OUT_CSV}")

    # Also save to c:\Users\Koushik\farlands\output\threshold_sweep.csv if running from floodwatch
    root_out_dir = os.path.join(os.path.dirname(REPO_ROOT), "output")
    if os.path.exists(root_out_dir):
        root_csv = os.path.join(root_out_dir, "threshold_sweep.csv")
        with open(root_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    # 2. Separate cloudy tiles
    cloudy_tiles = [r for r in rows if r["cloudy"]]
    clean_tiles = [r for r in rows if not r["cloudy"]]

    print("\n" + "=" * 80)
    print("THRESHOLD SWEEP & EVALUATION REPORT")
    print("=" * 80)

    # 4. Class Balance
    total_tiles = len(rows)
    flooded_all = sum(1 for r in rows if r["gt_flooded"])
    dry_all = sum(1 for r in rows if not r["gt_flooded"])
    print("\n--- 4. Class Balance (Full Germany AOI Dataset) ---")
    print(f"Total tiles evaluated: {total_tiles}")
    print(f"  Flooded tiles (GT > 0): {flooded_all} ({flooded_all/total_tiles*100:.2f}%)")
    print(f"  Dry tiles     (GT == 0): {dry_all} ({dry_all/total_tiles*100:.2f}%)")
    print(f"  Always-'Flooded' Baseline Accuracy: {flooded_all/total_tiles*100:.2f}% (Recall: 100.0%, False-Alarm Rate: 100.0%)")
    print(f"  Always-'Dry' Baseline Accuracy:     {dry_all/total_tiles*100:.2f}% (Recall: 0.0%, False-Alarm Rate: 0.0%)")

    # Cloud summary
    print("\n--- Cloud / Haze Summary ---")
    print(f"Cloudy tiles detected: {len(cloudy_tiles)} of {total_tiles}")
    for ct in cloudy_tiles:
        print(f"  Tile {ct['tile_id']}: gt_flooded={ct['gt_flooded']}, gt_count={ct['gt_flooded_feature_count']}, fast_new={ct['new_frac (fast)']:.4f}, acc_new={ct['new_frac (accurate)']:.4f}")
    print(f"Non-cloudy tiles retained for confusion matrices: {len(clean_tiles)} (Flooded: {sum(1 for r in clean_tiles if r['gt_flooded'])}, Dry: {sum(1 for r in clean_tiles if not r['gt_flooded'])})")

    # 2. Confusion Matrices per Mode & Threshold
    print("\n--- 2. Performance Across Decision Thresholds (Excluding Cloudy Tiles) ---")

    modes = [("fast", "new_frac (fast)"), ("accurate", "new_frac (accurate)")]

    sweep_results = []

    for mode_name, key in modes:
        print(f"\n=========================================")
        print(f"MODE: {mode_name.upper()}")
        print(f"=========================================")
        print(f"{'Threshold':<11} | {'TP':>4} {'TN':>4} {'FP':>4} {'FN':>4} | {'Accuracy':>8} | {'Recall':>8} | {'FA Rate':>8} {'(FP tiles)':>10}")
        print("-" * 75)

        for th in THRESHOLDS:
            tp = sum(1 for r in clean_tiles if r["gt_flooded"] and r[key] >= th)
            fn = sum(1 for r in clean_tiles if r["gt_flooded"] and r[key] < th)
            fp = sum(1 for r in clean_tiles if not r["gt_flooded"] and r[key] >= th)
            tn = sum(1 for r in clean_tiles if not r["gt_flooded"] and r[key] < th)

            n_pos = tp + fn
            n_neg = fp + tn
            acc = (tp + tn) / (n_pos + n_neg) if (n_pos + n_neg) > 0 else 0.0
            recall = (tp / n_pos * 100.0) if n_pos > 0 else 0.0
            fa_rate = (fp / n_neg * 100.0) if n_neg > 0 else 0.0

            print(f"{th:<11.4f} | {tp:4d} {tn:4d} {fp:4d} {fn:4d} | {acc*100:7.2f}% | {recall:7.2f}% | {fa_rate:7.2f}% ({fp:2d} tiles)")

            missed_tiles = [r["tile_id"] for r in clean_tiles if r["gt_flooded"] and r[key] < th]
            fp_tiles = [r["tile_id"] for r in clean_tiles if not r["gt_flooded"] and r[key] >= th]

            sweep_results.append({
                "mode": mode_name,
                "threshold": th,
                "tp": tp,
                "tn": tn,
                "fp": fp,
                "fn": fn,
                "accuracy": acc,
                "recall": recall,
                "fa_rate": fa_rate,
                "missed_tiles": missed_tiles,
                "fp_tiles": fp_tiles,
            })

    # 3. Best threshold with false alarms <= 1 tile
    candidates = [s for s in sweep_results if s["fp"] <= 1]
    candidates.sort(key=lambda s: (s["recall"], s["accuracy"], -s["fp"]), reverse=True)

    print("\n--- 3. Best Threshold with False Alarms <= 1 Tile ---")
    if candidates:
        best = candidates[0]
        print(f"BEST CONFIGURATION:")
        print(f"  Mode:                {best['mode'].upper()}")
        print(f"  Decision Threshold:  {best['threshold']}")
        print(f"  Recall on Flooded:   {best['recall']:.2f}% ({best['tp']}/{best['tp'] + best['fn']} tiles detected)")
        print(f"  False Alarms:        {best['fp']} tile ({best['fa_rate']:.2f}% false alarm rate on dry tiles)")
        if best["fp_tiles"]:
            print(f"  False-Alarm Tile(s): {', '.join(best['fp_tiles'])}")
        print(f"  Accuracy:            {best['accuracy']*100:.2f}%")
        print(f"\nTiles Still Missed ({len(best['missed_tiles'])} tiles):")
        # Print details for each missed tile
        for tid in best["missed_tiles"]:
            r = next(row for row in rows if row["tile_id"] == tid)
            print(f"    - {tid}: {r['gt_flooded_feature_count']} flooded features, fast_new={r['new_frac (fast)']:.6f}, acc_new={r['new_frac (accurate)']:.6f}")


if __name__ == "__main__":
    run_sweep()
