"""
Ground-Truth Composition & Settings Measurement Script (Phase 4 Corrections - Item 1)

1a. Ground-Truth Composition on 66 Flooded Tiles:
    - Rasterize GT buildings and GT roads separately (2m buffer on linestrings)
    - Read exact transform resolution dx, dy and calculate road corridor width in pixels
    - Total GT pixels per class (buildings vs roads)
    - Pixel recall and precision for Fast (768) and Accurate (512 sliding window) split by buildings vs roads

1b. Accurate mode vs Fast mode on 4 demo 'model miss' tiles:
    - 0_23_62, 0_29_66, 0_40_62, 0_39_62
    - Report before / after / net for Fast vs Accurate
"""
import os
import sys
import json
import time
import math
import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import shape
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8")

from src.flood_inference import (
    get_model,
    load_rgb,
    find_tile_paths,
    list_tiles,
    MEAN,
    STD,
    DEVICE,
    USE_FP16,
    WATER_CLASS,
    segment_water_with_timings,
    analyze_tile,
)

BUF_DEG = 2.0 / 70680.0  # 2m radius buffer (4m corridor)

def get_66_flooded_tiles():
    with open(os.path.join("data", "tile_scan.json"), "r") as f:
        scan = json.load(f)
    flooded = [item["tile_id"] for item in scan if item.get("gt_flooded_count", 0) > 0]
    return sorted(flooded)

def rasterize_split_gt(tile_id: str, post_path: str):
    ann_path = os.path.join("data", "raw", "annotations", f"{tile_id}.geojson")
    with rasterio.open(post_path) as src:
        H, W = src.shape
        transform = src.transform
        res_x = abs(transform.a)
        res_y = abs(transform.e)

    if not os.path.exists(ann_path):
        return None, None, None, res_x, res_y, H, W

    with open(ann_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    bldg_shapes = []
    road_shapes = []
    all_shapes = []

    for feat in data.get("features", []):
        props = feat.get("properties", {})
        if props.get("flooded") == "yes":
            geom = shape(feat["geometry"])
            if geom.geom_type in ["LineString", "MultiLineString"]:
                buffered = geom.buffer(BUF_DEG)
                road_shapes.append((buffered, 1))
                all_shapes.append((buffered, 1))
            else:
                bldg_shapes.append((geom, 1))
                all_shapes.append((geom, 1))

    mask_bldg = rasterize(bldg_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True) if bldg_shapes else np.zeros((H, W), dtype=np.uint8)
    mask_road = rasterize(road_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True) if road_shapes else np.zeros((H, W), dtype=np.uint8)
    mask_all = rasterize(all_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True) if all_shapes else np.zeros((H, W), dtype=np.uint8)

    return mask_bldg, mask_road, mask_all, res_x, res_y, H, W

def main():
    print("=======================================================")
    print("TASK 1A: GROUND-TRUTH COMPOSITION & RESOLUTION AUDIT")
    print("=======================================================")

    flooded_tiles = get_66_flooded_tiles()
    print(f"Total Flooded Germany Tiles: {len(flooded_tiles)}")

    # 1. Inspect resolution across all 66 flooded tiles
    resolutions_x = []
    resolutions_y = []
    corridor_widths_px = []
    buffer_radii_px = []

    total_bldg_px = 0
    total_road_px = 0
    total_overlap_px = 0
    total_combined_px = 0

    gt_masks = {}

    for tid in flooded_tiles:
        pre_p, post_p = find_tile_paths(tid)
        mbldg, mroad, mall, rx, ry, H, W = rasterize_split_gt(tid, post_p)
        resolutions_x.append(rx)
        resolutions_y.append(ry)

        # 4m corridor = 2 * BUF_DEG. Width in pixels = (2 * BUF_DEG) / rx
        corridor_w = (2.0 * BUF_DEG) / rx
        corridor_widths_px.append(corridor_w)
        buffer_radii_px.append(BUF_DEG / rx)

        bldg_cnt = int(mbldg.sum())
        road_cnt = int(mroad.sum())
        overlap_cnt = int(((mbldg == 1) & (mroad == 1)).sum())
        all_cnt = int(mall.sum())

        total_bldg_px += bldg_cnt
        total_road_px += road_cnt
        total_overlap_px += overlap_cnt
        total_combined_px += all_cnt

        gt_masks[tid] = {
            "bldg": mbldg,
            "road": mroad,
            "all": mall,
            "post_path": post_p,
        }

    avg_rx = np.mean(resolutions_x)
    avg_ry = np.mean(resolutions_y)
    avg_corridor_px = np.mean(corridor_widths_px)
    avg_radius_px = np.mean(buffer_radii_px)

    # Conversion to meters at latitude ~50.5 deg N
    lat_deg = 50.53
    m_per_deg_lat = 111240.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_deg)) # ~70758 m

    pixel_m_x = avg_rx * m_per_deg_lon
    pixel_m_y = avg_ry * m_per_deg_lat

    print("\n--- GeoTIFF Transform & Pixel Dimensions ---")
    print(f"Transform Resolution (dx): {avg_rx:.8e} deg/px")
    print(f"Transform Resolution (dy): {avg_ry:.8e} deg/px")
    print(f"Pixel Size (Longitude dx): {pixel_m_x:.3f} m/pixel")
    print(f"Pixel Size (Latitude dy):  {pixel_m_y:.3f} m/pixel")
    print(f"2-Meter Buffer Radius:     {avg_radius_px:.2f} pixels ({BUF_DEG:.6e} deg)")
    print(f"4-Meter Road Corridor:     {avg_corridor_px:.2f} pixels (full width)")

    print("\n--- Ground-Truth Pixel Breakdown (All 66 Flooded Tiles) ---")
    print(f"Total Flooded Building Pixels: {total_bldg_px:,} ({total_bldg_px / total_combined_px * 100:.2f}% of total GT)")
    print(f"Total Flooded Road Pixels:     {total_road_px:,} ({total_road_px / total_combined_px * 100:.2f}% of total GT)")
    print(f"Road & Building Overlap Pixels:{total_overlap_px:,} ({total_overlap_px / total_combined_px * 100:.2f}% overlap)")
    print(f"Total Ground-Truth Flooded Px: {total_combined_px:,}")

    # 2. Run inference on POST imagery for both Fast (768) and Accurate (512 crops)
    print("\n--- Evaluating Fast Mode (INPUT_SIZE = 768) on POST Imagery ---")
    model = get_model()

    fast_tp_bldg = 0
    fast_tp_road = 0
    fast_tp_all = 0
    fast_pred_pos = 0

    accurate_tp_bldg = 0
    accurate_tp_road = 0
    accurate_tp_all = 0
    accurate_pred_pos = 0

    for idx, tid in enumerate(flooded_tiles, 1):
        masks = gt_masks[tid]
        mbldg = masks["bldg"]
        mroad = masks["road"]
        mall = masks["all"]
        post_path = masks["post_path"]

        post_t = load_rgb(post_path)

        # Run Fast mode (768)
        (fast_mask,), _ = segment_water_with_timings([post_t], mode="fast")
        fast_pos = fast_mask.cpu().numpy().astype(bool)
        fast_pred_pos += int(fast_pos.sum())
        fast_tp_bldg += int((fast_pos & (mbldg == 1)).sum())
        fast_tp_road += int((fast_pos & (mroad == 1)).sum())
        fast_tp_all += int((fast_pos & (mall == 1)).sum())

        # Run Accurate mode (512 sliding window)
        (acc_mask,), _ = segment_water_with_timings([post_t], mode="accurate")
        acc_pos = acc_mask.cpu().numpy().astype(bool)
        accurate_pred_pos += int(acc_pos.sum())
        accurate_tp_bldg += int((acc_pos & (mbldg == 1)).sum())
        accurate_tp_road += int((acc_pos & (mroad == 1)).sum())
        accurate_tp_all += int((acc_pos & (mall == 1)).sum())

        if idx % 15 == 0 or idx == len(flooded_tiles):
            print(f"  Evaluated {idx}/{len(flooded_tiles)} tiles...")

    # Calculate metrics
    # Fast mode
    fast_recall_bldg = (fast_tp_bldg / total_bldg_px) * 100
    fast_recall_road = (fast_tp_road / total_road_px) * 100
    fast_recall_all = (fast_tp_all / total_combined_px) * 100
    fast_prec_all = (fast_tp_all / max(1, fast_pred_pos)) * 100
    fast_prec_bldg = (fast_tp_bldg / max(1, fast_pred_pos)) * 100
    fast_prec_road = (fast_tp_road / max(1, fast_pred_pos)) * 100

    # Accurate mode
    acc_recall_bldg = (accurate_tp_bldg / total_bldg_px) * 100
    acc_recall_road = (accurate_tp_road / total_road_px) * 100
    acc_recall_all = (accurate_tp_all / total_combined_px) * 100
    acc_prec_all = (accurate_tp_all / max(1, accurate_pred_pos)) * 100
    acc_prec_bldg = (accurate_tp_bldg / max(1, accurate_pred_pos)) * 100
    acc_prec_road = (accurate_tp_road / max(1, accurate_pred_pos)) * 100

    print("\n=======================================================")
    print("RESULTS: PIXEL RECALL & PRECISION BY FEATURE CLASS")
    print("=======================================================")
    print(f"{'Metric':<30} | {'Fast Mode (768)':<18} | {'Accurate Mode (512)'}")
    print("-" * 75)
    print(f"{'GT Building Pixels':<30} | {total_bldg_px:<18,d} | {total_bldg_px:,d}")
    print(f"{'GT Road Pixels':<30} | {total_road_px:<18,d} | {total_road_px:,d}")
    print(f"{'Total GT Flooded Pixels':<30} | {total_combined_px:<18,d} | {total_combined_px:,d}")
    print("-" * 75)
    print(f"{'Predicted Positive Pixels':<30} | {fast_pred_pos:<18,d} | {accurate_pred_pos:,d}")
    print(f"{'TP on Buildings':<30} | {fast_tp_bldg:<18,d} | {accurate_tp_bldg:,d}")
    print(f"{'TP on Roads':<30} | {fast_tp_road:<18,d} | {accurate_tp_road:,d}")
    print(f"{'Total True Positives':<30} | {fast_tp_all:<18,d} | {accurate_tp_all:,d}")
    print("-" * 75)
    print(f"{'Building Pixel Recall':<30} | {fast_recall_bldg:<17.2f}% | {acc_recall_bldg:.2f}%")
    print(f"{'Road Pixel Recall':<30} | {fast_recall_road:<17.2f}% | {acc_recall_road:.2f}%")
    print(f"{'Combined Pixel Recall':<30} | {fast_recall_all:<17.2f}% | {acc_recall_all:.2f}%")
    print("-" * 75)
    print(f"{'Precision (vs Buildings only)':<30} | {fast_prec_bldg:<17.2f}% | {acc_prec_bldg:.2f}%")
    print(f"{'Precision (vs Roads only)':<30} | {fast_prec_road:<17.2f}% | {acc_prec_road:.2f}%")
    print(f"{'Combined Precision':<30} | {fast_prec_all:<17.2f}% | {acc_prec_all:.2f}%")

    # ---------------------------------------------------- Task 1b: 4 Demo Miss Tiles
    print("\n=======================================================")
    print("TASK 1B: FAST VS ACCURATE ON 4 DEMO 'MODEL MISS' TILES")
    print("=======================================================")
    miss_tiles = ["0_23_62", "0_29_66", "0_40_62", "0_39_62"]
    miss_results = {}

    for tid in miss_tiles:
        res_fast = analyze_tile(tid, mode="fast")
        res_acc = analyze_tile(tid, mode="accurate")

        # Ground truth counts
        with open(os.path.join("data", "raw", "annotations", f"{tid}.geojson"), "r") as f:
            d = json.load(f)
        b_cnt = sum(1 for feat in d.get("features", []) if feat.get("properties", {}).get("flooded") == "yes" and feat.get("geometry", {}).get("type") not in ["LineString", "MultiLineString"])
        r_cnt = sum(1 for feat in d.get("features", []) if feat.get("properties", {}).get("flooded") == "yes" and feat.get("geometry", {}).get("type") in ["LineString", "MultiLineString"])

        miss_results[tid] = {
            "gt_flooded_buildings": b_cnt,
            "gt_flooded_roads": r_cnt,
            "gt_total": b_cnt + r_cnt,
            "fast": {
                "before_water_pct": res_fast.before_water_pct,
                "after_water_pct": res_fast.after_water_pct,
                "net_intrusion_pct": res_fast.net_intrusion_pct,
            },
            "accurate": {
                "before_water_pct": res_acc.before_water_pct,
                "after_water_pct": res_acc.after_water_pct,
                "net_intrusion_pct": res_acc.net_intrusion_pct,
            }
        }

        print(f"Tile {tid} (GT: {b_cnt} bldgs, {r_cnt} roads):")
        print(f"  Fast:     Before={res_fast.before_water_pct:5.2f}% | After={res_fast.after_water_pct:5.2f}% | Net={res_fast.net_intrusion_pct:+6.2f}%")
        print(f"  Accurate: Before={res_acc.before_water_pct:5.2f}% | After={res_acc.after_water_pct:5.2f}% | Net={res_acc.net_intrusion_pct:+6.2f}%")

    # Save all results to data/gt_composition_metrics.json
    out_data = {
        "geotiff_resolution": {
            "dx_deg": avg_rx,
            "dy_deg": avg_ry,
            "pixel_m_x": pixel_m_x,
            "pixel_m_y": pixel_m_y,
            "buffer_radius_m": 2.0,
            "buffer_radius_px": avg_radius_px,
            "road_corridor_width_m": 4.0,
            "road_corridor_width_px": avg_corridor_px,
        },
        "gt_composition": {
            "total_bldg_px": total_bldg_px,
            "total_road_px": total_road_px,
            "total_overlap_px": total_overlap_px,
            "total_combined_px": total_combined_px,
            "bldg_pct_of_gt": total_bldg_px / total_combined_px * 100,
            "road_pct_of_gt": total_road_px / total_combined_px * 100,
        },
        "fast_mode": {
            "pred_pos_px": fast_pred_pos,
            "tp_bldg_px": fast_tp_bldg,
            "tp_road_px": fast_tp_road,
            "tp_all_px": fast_tp_all,
            "recall_bldg_pct": fast_recall_bldg,
            "recall_road_pct": fast_recall_road,
            "recall_all_pct": fast_recall_all,
            "precision_all_pct": fast_prec_all,
            "precision_bldg_pct": fast_prec_bldg,
            "precision_road_pct": fast_prec_road,
        },
        "accurate_mode": {
            "pred_pos_px": accurate_pred_pos,
            "tp_bldg_px": accurate_tp_bldg,
            "tp_road_px": accurate_tp_road,
            "tp_all_px": accurate_tp_all,
            "recall_bldg_pct": acc_recall_bldg,
            "recall_road_pct": acc_recall_road,
            "recall_all_pct": acc_recall_all,
            "precision_all_pct": acc_prec_all,
            "precision_bldg_pct": acc_prec_bldg,
            "precision_road_pct": acc_prec_road,
        },
        "demo_miss_comparison": miss_results,
    }

    out_file = os.path.join("data", "gt_composition_metrics.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)
    print(f"\nAll measured metrics written to {out_file}")

if __name__ == "__main__":
    main()
