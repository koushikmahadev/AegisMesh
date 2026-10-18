"""
Buffer Sensitivity (1m, 2m, 3m) & Demo Tiles Agreement Benchmark (Phase 4.9 Tasks 4 & 5)

1. Road-Buffer Sensitivity across all 66 flooded Germany tiles:
   - Buffers: 1m, 2m, 3m
   - Modes: Fast (768), Accurate (512 sliding window)
   - Metrics: GT pixels (building, road, total), Predicted pixels, Building recall/precision, Road recall/precision, Combined recall/precision/IoU/F1.

2. Per-Tile Agreement for the 14 Demo Tiles (2m buffer):
   - Fast and Accurate modes
   - GT building/road pixels, predicted pixels, TP, FP, FN, precision, recall, IoU.
   - For 0_23_62: specific building recall and road recall in both modes.

3. Outputs saved to data/buffer_sensitivity_results.json and data/demo_tiles_agreement.json.
"""
import os
import sys
import json
import time
import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import shape
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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

METERS_PER_DEG = 70758.0  # At latitude 50.53N (lon deg: cos(50.53)*111320 ~= 70758m)

def rasterize_gt(tile_id: str, post_path: str, buffer_m: float):
    buf_deg = buffer_m / METERS_PER_DEG
    ann_path = os.path.join("data", "raw", "annotations", f"{tile_id}.geojson")
    with rasterio.open(post_path) as src:
        H, W = src.shape
        transform = src.transform

    if not os.path.exists(ann_path):
        empty = np.zeros((H, W), dtype=bool)
        return empty, empty, empty

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
                buffered = geom.buffer(buf_deg)
                road_shapes.append((buffered, 1))
                all_shapes.append((buffered, 1))
            else:
                bldg_shapes.append((geom, 1))
                all_shapes.append((geom, 1))

    m_bldg = rasterize(bldg_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True).astype(bool) if bldg_shapes else np.zeros((H, W), dtype=bool)
    m_road = rasterize(road_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True).astype(bool) if road_shapes else np.zeros((H, W), dtype=bool)
    m_all = rasterize(all_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True).astype(bool) if all_shapes else np.zeros((H, W), dtype=bool)

    return m_bldg, m_road, m_all

def main():
    print("=======================================================")
    print("TASKS 4 & 5: BUFFER SENSITIVITY & DEMO TILES AGREEMENT")
    print("=======================================================")

    with open(os.path.join("data", "tile_scan.json"), "r", encoding="utf-8") as f:
        tile_scan = json.load(f)
    flooded_tiles = sorted([t["tile_id"] for t in tile_scan if t.get("split") == "train"])
    print(f"Loaded {len(flooded_tiles)} flooded training pool tiles.")

    with open(os.path.join("data", "demo_tiles.json"), "r", encoding="utf-8") as f:
        demo_tiles_list = json.load(f)
    print(f"Loaded {len(demo_tiles_list)} demo tiles.")

    model = get_model()

    # Pre-compute post-event predicted masks for both Fast and Accurate on all 66 flooded tiles
    print("\n--- Pre-computing Fast & Accurate Predictions on POST Imagery (66 Flooded Tiles) ---")
    predictions = {}
    t0_pred = time.perf_counter()

    for idx, tid in enumerate(flooded_tiles, 1):
        _, post_path = find_tile_paths(tid)
        post_t = load_rgb(post_path)

        # Fast prediction
        (fast_m,), _ = segment_water_with_timings([post_t], mode="fast")
        # Accurate prediction
        (acc_m,), _ = segment_water_with_timings([post_t], mode="accurate")

        predictions[tid] = {
            "fast": fast_m.cpu().numpy().astype(bool),
            "accurate": acc_m.cpu().numpy().astype(bool),
            "post_path": post_path,
        }
        if idx % 20 == 0 or idx == len(flooded_tiles):
            print(f"  [{idx:2d}/{len(flooded_tiles)}] Predictions computed ({(time.perf_counter() - t0_pred):.1f}s)")

    # ---------------------------------------------------- Task 5: Road-Buffer Sensitivity (1m, 2m, 3m)
    print("\n=======================================================")
    print("TASK 5: ROAD-BUFFER SENSITIVITY (1m, 2m, 3m)")
    print("=======================================================")

    buffer_results = {}

    for buf_m in [1.0, 2.0, 3.0]:
        print(f"\n--- Evaluating Road Buffer = {buf_m} m ---")
        buf_key = f"{int(buf_m)}m"

        tot_bldg_px = 0
        tot_road_px = 0
        tot_all_px = 0

        fast_pred_px = 0
        fast_tp_bldg = 0
        fast_tp_road = 0
        fast_tp_all = 0

        acc_pred_px = 0
        acc_tp_bldg = 0
        acc_tp_road = 0
        acc_tp_all = 0

        for tid in flooded_tiles:
            post_path = predictions[tid]["post_path"]
            m_bldg, m_road, m_all = rasterize_gt(tid, post_path, buffer_m=buf_m)

            tot_bldg_px += int(m_bldg.sum())
            tot_road_px += int(m_road.sum())
            tot_all_px += int(m_all.sum())

            p_fast = predictions[tid]["fast"]
            fast_pred_px += int(p_fast.sum())
            fast_tp_bldg += int((p_fast & m_bldg).sum())
            fast_tp_road += int((p_fast & m_road).sum())
            fast_tp_all += int((p_fast & m_all).sum())

            p_acc = predictions[tid]["accurate"]
            acc_pred_px += int(p_acc.sum())
            acc_tp_bldg += int((p_acc & m_bldg).sum())
            acc_tp_road += int((p_acc & m_road).sum())
            acc_tp_all += int((p_acc & m_all).sum())

        def calc_metrics(tp_bldg, tp_road, tp_all, pred_px, gt_bldg_px, gt_road_px, gt_all_px):
            b_rec = tp_bldg / gt_bldg_px * 100 if gt_bldg_px else 0.0
            r_rec = tp_road / gt_road_px * 100 if gt_road_px else 0.0
            comb_rec = tp_all / gt_all_px * 100 if gt_all_px else 0.0
            comb_prec = tp_all / pred_px * 100 if pred_px else 0.0
            prec_bldg = tp_bldg / pred_px * 100 if pred_px else 0.0
            prec_road = tp_road / pred_px * 100 if pred_px else 0.0
            fp = pred_px - tp_all
            fn = gt_all_px - tp_all
            iou = tp_all / (tp_all + fp + fn) * 100 if (tp_all + fp + fn) else 0.0
            f1 = 2 * tp_all / (2 * tp_all + fp + fn) * 100 if (2 * tp_all + fp + fn) else 0.0
            return {
                "tp_bldg": tp_bldg,
                "tp_road": tp_road,
                "tp_all": tp_all,
                "fp": fp,
                "fn": fn,
                "building_recall_pct": round(b_rec, 2),
                "road_recall_pct": round(r_rec, 2),
                "combined_recall_pct": round(comb_rec, 2),
                "combined_precision_pct": round(comb_prec, 2),
                "precision_vs_bldg_pct": round(prec_bldg, 2),
                "precision_vs_road_pct": round(prec_road, 2),
                "iou_pct": round(iou, 2),
                "f1_pct": round(f1, 2),
            }

        fast_m = calc_metrics(fast_tp_bldg, fast_tp_road, fast_tp_all, fast_pred_px, tot_bldg_px, tot_road_px, tot_all_px)
        acc_m = calc_metrics(acc_tp_bldg, acc_tp_road, acc_tp_all, acc_pred_px, tot_bldg_px, tot_road_px, tot_all_px)

        buffer_results[buf_key] = {
            "buffer_meters": buf_m,
            "corridor_width_meters": buf_m * 2,
            "corridor_width_px": round(buf_m * 2 / (0.419), 2),
            "gt_composition": {
                "building_pixels": tot_bldg_px,
                "building_pct": round(tot_bldg_px / tot_all_px * 100, 2),
                "road_pixels": tot_road_px,
                "road_pct": round(tot_road_px / tot_all_px * 100, 2),
                "total_gt_pixels": tot_all_px,
            },
            "fast_mode": fast_m,
            "accurate_mode": acc_m,
        }

        print(f"GT: Buildings = {tot_bldg_px:,} px ({tot_bldg_px/tot_all_px*100:.1f}%) | Roads = {tot_road_px:,} px ({tot_road_px/tot_all_px*100:.1f}%) | Total = {tot_all_px:,} px")
        print(f"Fast Mode:     Bldg Recall = {fast_m['building_recall_pct']:5.2f}% | Road Recall = {fast_m['road_recall_pct']:5.2f}% | Comb Recall = {fast_m['combined_recall_pct']:5.2f}% | Comb Prec = {fast_m['combined_precision_pct']:5.2f}% | IoU = {fast_m['iou_pct']:5.2f}%")
        print(f"Accurate Mode: Bldg Recall = {acc_m['building_recall_pct']:5.2f}% | Road Recall = {acc_m['road_recall_pct']:5.2f}% | Comb Recall = {acc_m['combined_recall_pct']:5.2f}% | Comb Prec = {acc_m['combined_precision_pct']:5.2f}% | IoU = {acc_m['iou_pct']:5.2f}%")

    with open(os.path.join("data", "buffer_sensitivity_results.json"), "w", encoding="utf-8") as f:
        json.dump(buffer_results, f, indent=2)
    print("\n✓ buffer_sensitivity_results.json saved.")

    # ---------------------------------------------------- Task 4: Per-Tile Agreement for the 14 Demo Tiles
    print("\n=======================================================")
    print("TASK 4: PER-TILE AGREEMENT FOR 14 DEMO TILES (2m Buffer)")
    print("=======================================================")

    demo_agreement = []

    for d in demo_tiles_list:
        tid = d["tile_id"]
        split = d.get("split", "not_in_pool")
        _, post_path = find_tile_paths(tid)

        m_bldg, m_road, m_all = rasterize_gt(tid, post_path, buffer_m=2.0)
        gt_bldg_px = int(m_bldg.sum())
        gt_road_px = int(m_road.sum())
        gt_all_px = int(m_all.sum())

        post_t = load_rgb(post_path)

        # Fast prediction
        (p_fast,), _ = segment_water_with_timings([post_t], mode="fast")
        p_fast_np = p_fast.cpu().numpy().astype(bool)
        pred_fast_px = int(p_fast_np.sum())
        tp_fast_bldg = int((p_fast_np & m_bldg).sum())
        tp_fast_road = int((p_fast_np & m_road).sum())
        tp_fast = int((p_fast_np & m_all).sum())
        fp_fast = pred_fast_px - tp_fast
        fn_fast = gt_all_px - tp_fast

        rec_fast = tp_fast / gt_all_px * 100 if gt_all_px > 0 else (100.0 if pred_fast_px == 0 else 0.0)
        prec_fast = tp_fast / pred_fast_px * 100 if pred_fast_px > 0 else (100.0 if gt_all_px == 0 else 0.0)
        iou_fast = tp_fast / (tp_fast + fp_fast + fn_fast) * 100 if (tp_fast + fp_fast + fn_fast) > 0 else (100.0 if gt_all_px == 0 and pred_fast_px == 0 else 0.0)
        bldg_rec_fast = tp_fast_bldg / gt_bldg_px * 100 if gt_bldg_px > 0 else 0.0
        road_rec_fast = tp_fast_road / gt_road_px * 100 if gt_road_px > 0 else 0.0

        # Accurate prediction
        (p_acc,), _ = segment_water_with_timings([post_t], mode="accurate")
        p_acc_np = p_acc.cpu().numpy().astype(bool)
        pred_acc_px = int(p_acc_np.sum())
        tp_acc_bldg = int((p_acc_np & m_bldg).sum())
        tp_acc_road = int((p_acc_np & m_road).sum())
        tp_acc = int((p_acc_np & m_all).sum())
        fp_acc = pred_acc_px - tp_acc
        fn_acc = gt_all_px - tp_acc

        rec_acc = tp_acc / gt_all_px * 100 if gt_all_px > 0 else (100.0 if pred_acc_px == 0 else 0.0)
        prec_acc = tp_acc / pred_acc_px * 100 if pred_acc_px > 0 else (100.0 if gt_all_px == 0 else 0.0)
        iou_acc = tp_acc / (tp_acc + fp_acc + fn_acc) * 100 if (tp_acc + fp_acc + fn_acc) > 0 else (100.0 if gt_all_px == 0 and pred_acc_px == 0 else 0.0)
        bldg_rec_acc = tp_acc_bldg / gt_bldg_px * 100 if gt_bldg_px > 0 else 0.0
        road_rec_acc = tp_acc_road / gt_road_px * 100 if gt_road_px > 0 else 0.0

        tile_data = {
            "tile_id": tid,
            "split": split,
            "gt_features": d.get("gt_flooded_count", 0),
            "gt_bldg_count": d.get("gt_bldg_count", 0),
            "gt_road_count": d.get("gt_road_count", 0),
            "gt_composition": {
                "bldg_pixels": gt_bldg_px,
                "road_pixels": gt_road_px,
                "total_gt_pixels": gt_all_px,
            },
            "fast_mode": {
                "pred_pixels": pred_fast_px,
                "tp": tp_fast,
                "fp": fp_fast,
                "fn": fn_fast,
                "precision_pct": round(prec_fast, 2),
                "recall_pct": round(rec_fast, 2),
                "iou_pct": round(iou_fast, 2),
                "bldg_recall_pct": round(bldg_rec_fast, 2),
                "road_recall_pct": round(road_rec_fast, 2),
            },
            "accurate_mode": {
                "pred_pixels": pred_acc_px,
                "tp": tp_acc,
                "fp": fp_acc,
                "fn": fn_acc,
                "precision_pct": round(prec_acc, 2),
                "recall_pct": round(rec_acc, 2),
                "iou_pct": round(iou_acc, 2),
                "bldg_recall_pct": round(bldg_rec_acc, 2),
                "road_recall_pct": round(road_rec_acc, 2),
            }
        }
        demo_agreement.append(tile_data)

        print(f"Tile {tid:<8} ({split:<11}) | GT: {gt_all_px:>7,d} px (Bldg: {gt_bldg_px:>6,d}, Road: {gt_road_px:>6,d})")
        print(f"  Fast:     Pred = {pred_fast_px:>7,d} px | Prec = {prec_fast:5.1f}% | Rec = {rec_fast:5.1f}% | IoU = {iou_fast:5.1f}% | Bldg Rec = {bldg_rec_fast:5.1f}% | Road Rec = {road_rec_fast:5.1f}%")
        print(f"  Accurate: Pred = {pred_acc_px:>7,d} px | Prec = {prec_acc:5.1f}% | Rec = {rec_acc:5.1f}% | IoU = {iou_acc:5.1f}% | Bldg Rec = {bldg_rec_acc:5.1f}% | Road Rec = {road_rec_acc:5.1f}%")

    with open(os.path.join("data", "demo_tiles_agreement.json"), "w", encoding="utf-8") as f:
        json.dump(demo_agreement, f, indent=2)
    print("\n✓ demo_tiles_agreement.json saved.")

if __name__ == "__main__":
    main()
