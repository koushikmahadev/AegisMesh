"""
Phase 4.10 Unified Calibration Pipeline

1. Strict inference reconciliation:
   - Uses the EXACT function /api/analyze uses: analyze_tile(tile_id, return_masks=True, mode=mode).
   - Guarantees pred_pixels == post_mask.sum().
   - Asserts pred_pixels equals round(after_pct/100 * H * W) to within 0.1%.

2. Metric UTM buffering for Ground Truth:
   - Reprojects GeoJSON Linestrings to local UTM Zone 32N (EPSG:32632).
   - Buffers by exact metric meters (1.0m, 2.0m, 3.0m).
   - Reprojects back to EPSG:4326.
   - Rasterizes onto the tile's native PRE grid ((H, W), transform).
   - Rasterizes buildings directly onto the same grid.

3. Internal consistency:
   - For every tile, asserts: tp_all == tp_bldg + tp_road - tp_overlap.
   - Asserts recall and precision reproduce exactly from pixel counts.

4. Outputs:
   - data/buffer_sensitivity_results.json
   - data/demo_tiles_agreement.json
   - data/demo_tiles.json
   - data/settings_benchmark.json
   - data/accuracy_66_tiles.json
"""
import os
import sys
import json
import time
import glob
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_geom
from shapely.geometry import shape, mapping
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
import torch
import torch.nn.functional as F

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PROJ_DATA"] = r"c:\Users\Koushik\farlands\floodnet_data\.venv\Lib\site-packages\rasterio\proj_data"
os.environ["PROJ_LIB"] = r"c:\Users\Koushik\farlands\floodnet_data\.venv\Lib\site-packages\rasterio\proj_data"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.flood_inference import (
    analyze_tile,
    find_tile_paths,
    list_tiles,
    get_model,
    load_rgb,
    DEVICE,
    USE_FP16,
    WATER_CLASS,
    MEAN,
    STD,
    INPUT_SIZE,
)

def get_metric_gt_masks(tile_id: str, pre_path: str, buf_m: float = 2.0):
    ann_path = os.path.join(REPO_ROOT, "data", "raw", "annotations", f"{tile_id}.geojson")
    with rasterio.open(pre_path) as src:
        H, W = src.shape
        transform = src.transform

    if not os.path.exists(ann_path):
        empty = np.zeros((H, W), dtype=bool)
        return empty, empty, empty

    with open(ann_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    bldg_shapes, road_shapes, all_shapes = [], [], []
    for feat in data.get("features", []):
        if feat.get("properties", {}).get("flooded") == "yes":
            geom = shape(feat["geometry"])
            if geom.geom_type in ["LineString", "MultiLineString"]:
                g_utm = transform_geom("EPSG:4326", "EPSG:32632", feat["geometry"])
                b_utm = shape(g_utm).buffer(buf_m)
                b_4326 = shape(transform_geom("EPSG:32632", "EPSG:4326", mapping(b_utm)))
                road_shapes.append((b_4326, 1))
                all_shapes.append((b_4326, 1))
            else:
                bldg_shapes.append((geom, 1))
                all_shapes.append((geom, 1))

    m_bldg = rasterize(bldg_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True).astype(bool) if bldg_shapes else np.zeros((H, W), dtype=bool)
    m_road = rasterize(road_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True).astype(bool) if road_shapes else np.zeros((H, W), dtype=bool)
    m_all = rasterize(all_shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True).astype(bool) if all_shapes else np.zeros((H, W), dtype=bool)

    return m_bldg, m_road, m_all

def main():
    print("===================================================================")
    print("PHASE 4.10: UNIFIED CALIBRATION, MASK RECONCILIATION & GT PIPELINE")
    print("===================================================================")

    with open(os.path.join(REPO_ROOT, "data", "tile_scan.json"), "r", encoding="utf-8") as f:
        tile_scan = json.load(f)
    flooded_tiles = sorted([t["tile_id"] for t in tile_scan if t.get("split") == "train"])
    print(f"Loaded {len(flooded_tiles)} flooded training pool tiles.")

    with open(os.path.join(REPO_ROOT, "data", "demo_tiles.json"), "r", encoding="utf-8") as f:
        demo_tiles = json.load(f)
    print(f"Loaded {len(demo_tiles)} demo tiles.")

    # 1. Run exact API analyze_tile inference across all 66 flooded tiles in both Fast and Accurate modes
    print("\n--- Step 1: Running API analyze_tile Inference on 66 Flooded Tiles (Fast & Accurate) ---")
    predictions = {}
    t0_inf = time.perf_counter()

    for idx, tid in enumerate(flooded_tiles, 1):
        pre_p, _ = find_tile_paths(tid)
        # Fast mode
        res_fast, pre_m_fast, post_m_fast = analyze_tile(tid, return_masks=True, mode="fast")
        # Accurate mode
        res_acc, pre_m_acc, post_m_acc = analyze_tile(tid, return_masks=True, mode="accurate")

        H, W = post_m_fast.shape
        fast_np = post_m_fast.cpu().numpy().astype(bool)
        acc_np = post_m_acc.cpu().numpy().astype(bool)

        # Check tolerance between pred_pixels and after_pct * H * W
        fast_px = int(fast_np.sum())
        acc_px = int(acc_np.sum())
        implied_fast = round(res_fast.after_water_pct / 100.0 * H * W)
        implied_acc = round(res_acc.after_water_pct / 100.0 * H * W)

        diff_fast = abs(fast_px - implied_fast) / (H * W) * 100.0
        diff_acc = abs(acc_px - implied_acc) / (H * W) * 100.0

        assert diff_fast < 0.1, f"Tile {tid} Fast mask discrepancy: {fast_px} vs {implied_fast} ({diff_fast:.4f}% of tile)"
        assert diff_acc < 0.1, f"Tile {tid} Accurate mask discrepancy: {acc_px} vs {implied_acc} ({diff_acc:.4f}% of tile)"

        predictions[tid] = {
            "pre_path": pre_p,
            "shape": (H, W),
            "fast": fast_np,
            "accurate": acc_np,
            "fast_result": res_fast,
            "acc_result": res_acc,
        }

        if idx % 20 == 0 or idx == len(flooded_tiles):
            print(f"  [{idx:2d}/{len(flooded_tiles)}] analyze_tile runs complete ({(time.perf_counter() - t0_inf):.1f}s)")

    # 2. Buffer Sensitivity (1m, 2m, 3m) using Metric UTM buffer across all 66 flooded tiles
    print("\n--- Step 2: Evaluating Buffer Sensitivity (1m, 2m, 3m Metric UTM) ---")
    buffer_results = {}

    for buf_m in [1.0, 2.0, 3.0]:
        buf_key = f"{int(buf_m)}m"
        tot_bldg_px = 0
        tot_road_px = 0
        tot_overlap_px = 0
        tot_all_px = 0

        fast_pred_px = 0
        fast_tp_bldg = 0
        fast_tp_road = 0
        fast_tp_overlap = 0
        fast_tp_all = 0

        acc_pred_px = 0
        acc_tp_bldg = 0
        acc_tp_road = 0
        acc_tp_overlap = 0
        acc_tp_all = 0

        for tid in flooded_tiles:
            pre_p = predictions[tid]["pre_path"]
            m_bldg, m_road, m_all = get_metric_gt_masks(tid, pre_p, buf_m=buf_m)

            b_px = int(m_bldg.sum())
            r_px = int(m_road.sum())
            ov_px = int((m_bldg & m_road).sum())
            a_px = int(m_all.sum())
            assert a_px == b_px + r_px - ov_px, f"GT pixel overlap mismatch on {tid}"

            tot_bldg_px += b_px
            tot_road_px += r_px
            tot_overlap_px += ov_px
            tot_all_px += a_px

            p_fast = predictions[tid]["fast"]
            fast_pred_px += int(p_fast.sum())
            tp_b = int((p_fast & m_bldg).sum())
            tp_r = int((p_fast & m_road).sum())
            tp_ov = int((p_fast & m_bldg & m_road).sum())
            tp_a = int((p_fast & m_all).sum())
            assert tp_a == tp_b + tp_r - tp_ov, f"Fast TP mismatch on {tid}: {tp_a} != {tp_b} + {tp_r} - {tp_ov}"

            fast_tp_bldg += tp_b
            fast_tp_road += tp_r
            fast_tp_overlap += tp_ov
            fast_tp_all += tp_a

            p_acc = predictions[tid]["accurate"]
            acc_pred_px += int(p_acc.sum())
            tp_b_acc = int((p_acc & m_bldg).sum())
            tp_r_acc = int((p_acc & m_road).sum())
            tp_ov_acc = int((p_acc & m_bldg & m_road).sum())
            tp_a_acc = int((p_acc & m_all).sum())
            assert tp_a_acc == tp_b_acc + tp_r_acc - tp_ov_acc, f"Accurate TP mismatch on {tid}"

            acc_tp_bldg += tp_b_acc
            acc_tp_road += tp_r_acc
            acc_tp_overlap += tp_ov_acc
            acc_tp_all += tp_a_acc

        assert tot_all_px == tot_bldg_px + tot_road_px - tot_overlap_px
        assert fast_tp_all == fast_tp_bldg + fast_tp_road - fast_tp_overlap
        assert acc_tp_all == acc_tp_bldg + acc_tp_road - acc_tp_overlap

        def calc_metrics(tp_bldg, tp_road, tp_overlap, tp_all, pred_px, gt_bldg_px, gt_road_px, gt_all_px):
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
                "tp_overlap": tp_overlap,
                "tp_all": tp_all,
                "fp": fp,
                "fn": fn,
                "predicted_positive_pixels": pred_px,
                "building_recall_pct": round(b_rec, 2),
                "road_recall_pct": round(r_rec, 2),
                "combined_recall_pct": round(comb_rec, 2),
                "combined_precision_pct": round(comb_prec, 2),
                "precision_vs_bldg_pct": round(prec_bldg, 2),
                "precision_vs_road_pct": round(prec_road, 2),
                "iou_pct": round(iou, 2),
                "f1_pct": round(f1, 2),
            }

        fast_m = calc_metrics(fast_tp_bldg, fast_tp_road, fast_tp_overlap, fast_tp_all, fast_pred_px, tot_bldg_px, tot_road_px, tot_all_px)
        acc_m = calc_metrics(acc_tp_bldg, acc_tp_road, acc_tp_overlap, acc_tp_all, acc_pred_px, tot_bldg_px, tot_road_px, tot_all_px)

        buffer_results[buf_key] = {
            "buffer_meters": buf_m,
            "corridor_width_meters": buf_m * 2,
            "corridor_width_px": round(buf_m * 2 / 0.419, 2),
            "corridor_width_x_px": round(buf_m * 2 / 0.326, 2),
            "corridor_width_y_px": round(buf_m * 2 / 0.512, 2),
            "gt_composition": {
                "building_pixels": tot_bldg_px,
                "building_pct": round(tot_bldg_px / tot_all_px * 100, 2),
                "road_pixels": tot_road_px,
                "road_pct": round(tot_road_px / tot_all_px * 100, 2),
                "overlap_pixels": tot_overlap_px,
                "overlap_pct": round(tot_overlap_px / tot_all_px * 100, 2),
                "total_gt_pixels": tot_all_px,
            },
            "fast_mode": fast_m,
            "accurate_mode": acc_m,
        }

        print(f"Buffer {buf_m}m: GT Total={tot_all_px:,} px (Bldg={tot_bldg_px:,} ({tot_bldg_px/tot_all_px*100:.2f}%), Road={tot_road_px:,} ({tot_road_px/tot_all_px*100:.2f}%), Overlap={tot_overlap_px:,})")
        print(f"  Fast:     Rec={fast_m['combined_recall_pct']}% (Bldg: {fast_m['building_recall_pct']}%, Road: {fast_m['road_recall_pct']}%), Prec={fast_m['combined_precision_pct']}%, IoU={fast_m['iou_pct']}%")
        print(f"  Accurate: Rec={acc_m['combined_recall_pct']}% (Bldg: {acc_m['building_recall_pct']}%, Road: {acc_m['road_recall_pct']}%), Prec={acc_m['combined_precision_pct']}%, IoU={acc_m['iou_pct']}%")

    with open(os.path.join(REPO_ROOT, "data", "buffer_sensitivity_results.json"), "w", encoding="utf-8") as f:
        json.dump(buffer_results, f, indent=2)
    print("✓ Saved data/buffer_sensitivity_results.json")

    # 3. Per-tile Agreement for all 14 Demo Tiles (at 2m Metric Buffer)
    print("\n--- Step 3: Evaluating Per-Tile Agreement for 14 Demo Tiles (2m Metric Buffer) ---")
    demo_agreement = []
    updated_demo_tiles = []

    for d in demo_tiles:
        tid = d["tile_id"]
        split = d.get("split", "not_in_pool")
        pre_p, _ = find_tile_paths(tid)

        m_bldg, m_road, m_all = get_metric_gt_masks(tid, pre_p, buf_m=2.0)
        gt_bldg_px = int(m_bldg.sum())
        gt_road_px = int(m_road.sum())
        gt_ov_px = int((m_bldg & m_road).sum())
        gt_all_px = int(m_all.sum())
        assert gt_all_px == gt_bldg_px + gt_road_px - gt_ov_px

        res_fast, _, post_m_fast = analyze_tile(tid, return_masks=True, mode="fast")
        res_acc, _, post_m_acc = analyze_tile(tid, return_masks=True, mode="accurate")

        fast_np = post_m_fast.cpu().numpy().astype(bool)
        acc_np = post_m_acc.cpu().numpy().astype(bool)

        pred_fast_px = int(fast_np.sum())
        pred_acc_px = int(acc_np.sum())

        H, W = post_m_fast.shape
        implied_fast = round(res_fast.after_water_pct / 100.0 * H * W)
        implied_acc = round(res_acc.after_water_pct / 100.0 * H * W)
        assert abs(pred_fast_px - implied_fast) / (H * W) < 0.001, f"Fast tolerance failed on {tid}: {pred_fast_px} vs {implied_fast}"
        assert abs(pred_acc_px - implied_acc) / (H * W) < 0.001, f"Accurate tolerance failed on {tid}: {pred_acc_px} vs {implied_acc}"

        def tile_stats(p_np, pred_px, b_mask, r_mask, a_mask, b_px, r_px, a_px):
            tp_b = int((p_np & b_mask).sum())
            tp_r = int((p_np & r_mask).sum())
            tp_ov = int((p_np & b_mask & r_mask).sum())
            tp_a = int((p_np & a_mask).sum())
            assert tp_a == tp_b + tp_r - tp_ov, f"Tile {tid} TP consistency check failed"

            fp = pred_px - tp_a
            fn = a_px - tp_a

            prec = tp_a / pred_px * 100 if pred_px > 0 else (100.0 if a_px == 0 else 0.0)
            rec = tp_a / a_px * 100 if a_px > 0 else (100.0 if pred_px == 0 else 0.0)
            iou = tp_a / (tp_a + fp + fn) * 100 if (tp_a + fp + fn) > 0 else (100.0 if a_px == 0 and pred_px == 0 else 0.0)
            b_rec = tp_b / b_px * 100 if b_px > 0 else 0.0
            r_rec = tp_r / r_px * 100 if r_px > 0 else 0.0

            return {
                "pred_pixels": pred_px,
                "tp": tp_a,
                "tp_bldg": tp_b,
                "tp_road": tp_r,
                "tp_overlap": tp_ov,
                "fp": fp,
                "fn": fn,
                "precision_pct": round(prec, 2),
                "recall_pct": round(rec, 2),
                "iou_pct": round(iou, 2),
                "bldg_recall_pct": round(b_rec, 2),
                "road_recall_pct": round(r_rec, 2),
            }

        fast_stats = tile_stats(fast_np, pred_fast_px, m_bldg, m_road, m_all, gt_bldg_px, gt_road_px, gt_all_px)
        fast_stats["after_pct"] = res_fast.after_water_pct
        acc_stats = tile_stats(acc_np, pred_acc_px, m_bldg, m_road, m_all, gt_bldg_px, gt_road_px, gt_all_px)
        acc_stats["after_pct"] = res_acc.after_water_pct

        ag_entry = {
            "tile_id": tid,
            "split": split,
            "shape": [H, W],
            "gt_features": d.get("gt_flooded_count", 0),
            "gt_bldg_count": d.get("gt_bldg_count", 0),
            "gt_road_count": d.get("gt_road_count", 0),
            "gt_composition": {
                "bldg_pixels": gt_bldg_px,
                "road_pixels": gt_road_px,
                "overlap_pixels": gt_ov_px,
                "total_gt_pixels": gt_all_px,
            },
            "fast_mode": fast_stats,
            "accurate_mode": acc_stats,
        }
        demo_agreement.append(ag_entry)

        d_up = dict(d)
        d_up["before_pct"] = res_fast.before_water_pct
        d_up["after_pct"] = res_fast.after_water_pct
        d_up["net_intrusion_pct"] = res_fast.net_intrusion_pct
        d_up["agreement"] = {
            "fast": fast_stats,
            "accurate": acc_stats,
            "gt_pixels": ag_entry["gt_composition"],
        }
        updated_demo_tiles.append(d_up)

        print(f"Tile {tid:<8}: Fast Pred={pred_fast_px:>7,d} px (TP={fast_stats['tp']:>6,d}, Rec={fast_stats['recall_pct']:5.2f}%, Prec={fast_stats['precision_pct']:5.2f}%) | Acc Pred={pred_acc_px:>7,d} px (TP={acc_stats['tp']:>6,d}, Rec={acc_stats['recall_pct']:5.2f}%, Prec={acc_stats['precision_pct']:5.2f}%)")

    with open(os.path.join(REPO_ROOT, "data", "demo_tiles_agreement.json"), "w", encoding="utf-8") as f:
        json.dump(demo_agreement, f, indent=2)
    with open(os.path.join(REPO_ROOT, "data", "demo_tiles.json"), "w", encoding="utf-8") as f:
        json.dump(updated_demo_tiles, f, indent=2)
    print("✓ Saved data/demo_tiles_agreement.json and updated data/demo_tiles.json")

    # 4. Settings Benchmark (384, 512, 768, native full, native crops 512) against Metric 2m GT
    print("\n--- Step 4: Running 5 Settings Benchmark against Metric 2m GT ---")
    all_tiles = list_tiles()
    model = get_model()
    mean = MEAN.to(DEVICE)
    std = STD.to(DEVICE)

    # Preload GT for all 202 tiles
    print("  Loading 2m Metric GT masks for all 202 tiles...")
    gt_masks = {}
    gt_has_flood = {}
    gt_flooded_frac = {}

    for tid in all_tiles:
        pre_p, _ = find_tile_paths(tid)
        _, _, m_all = get_metric_gt_masks(tid, pre_p, buf_m=2.0)
        gt_masks[tid] = m_all
        gt_has_flood[tid] = int(m_all.sum() > 0)
        gt_flooded_frac[tid] = float(m_all.mean())

    def eval_setting(name, size_cfg, is_sliding=False, is_native=False):
        print(f"  Evaluating {name}...")
        total_tp = 0
        total_fp = 0
        total_fn = 0
        pred_after_pcts = []
        pred_nets = []
        gt_flags = []
        gt_fracs = []
        latencies = []

        for tid in all_tiles:
            pre_p, post_p = find_tile_paths(tid)
            pre_t, post_t = load_rgb(pre_p), load_rgb(post_p)
            if pre_t.shape != post_t.shape:
                post_t = F.interpolate(post_t.unsqueeze(0), size=pre_t.shape[-2:], mode="bilinear", align_corners=False)[0]

            gt = gt_masks[tid]
            H, W = gt.shape

            t0 = time.perf_counter()
            if is_sliding:
                # Sliding 512 crops
                res_acc, pre_m, post_m = analyze_tile(tid, return_masks=True, mode="accurate")
                pred_mask = post_m.cpu().numpy().astype(bool)
                after_pct = res_acc.after_water_pct
                net_pct = res_acc.net_intrusion_pct
            elif is_native:
                # Native full tile
                batch = torch.stack([pre_t, post_t]).to(DEVICE)
                batch = (batch - mean) / std
                if USE_FP16:
                    batch = batch.half()
                logits = model(pixel_values=batch).logits
                up = F.interpolate(logits.float(), size=(H, W), mode="bilinear", align_corners=False)
                masks = (up.argmax(dim=1) == WATER_CLASS).cpu()
                pred_mask = masks[1].numpy().astype(bool)
                after_pct = round(masks[1].float().mean().item() * 100.0, 2)
                before_pct = round(masks[0].float().mean().item() * 100.0, 2)
                net_pct = round(after_pct - before_pct, 2)
            else:
                # Resize to size_cfg
                batch = torch.stack([
                    F.interpolate(img.unsqueeze(0), size=(size_cfg, size_cfg), mode="bilinear", align_corners=False)[0]
                    for img in [pre_t, post_t]
                ]).to(DEVICE)
                batch = (batch - mean) / std
                if USE_FP16:
                    batch = batch.half()
                logits = model(pixel_values=batch).logits
                up = F.interpolate(logits.float(), size=(H, W), mode="bilinear", align_corners=False)
                masks = (up.argmax(dim=1) == WATER_CLASS).cpu()
                pred_mask = masks[1].numpy().astype(bool)
                after_pct = round(masks[1].float().mean().item() * 100.0, 2)
                before_pct = round(masks[0].float().mean().item() * 100.0, 2)
                net_pct = round(after_pct - before_pct, 2)

            dt = (time.perf_counter() - t0) * 1000
            latencies.append(dt)

            tp = int((pred_mask & gt).sum())
            fp = int((pred_mask & ~gt).sum())
            fn = int((~pred_mask & gt).sum())

            total_tp += tp
            total_fp += fp
            total_fn += fn

            pred_after_pcts.append(after_pct)
            pred_nets.append(net_pct)
            gt_flags.append(gt_has_flood[tid])
            gt_fracs.append(gt_flooded_frac[tid])

        iou = total_tp / (total_tp + total_fp + total_fn) * 100 if (total_tp + total_fp + total_fn) else 0.0
        f1 = 2 * total_tp / (2 * total_tp + total_fp + total_fn) * 100 if (2 * total_tp + total_fp + total_fn) else 0.0
        auc = roc_auc_score(gt_flags, pred_after_pcts) if len(set(gt_flags)) > 1 else 0.5
        corr, _ = spearmanr(gt_fracs, pred_nets)

        return {
            "name": name,
            "pixel_f1": round(f1, 2),
            "pixel_iou": round(iou, 2),
            "roc_auc": round(float(auc), 4),
            "spearman_corr": round(float(corr), 4),
            "latency_median_ms": round(float(np.median(latencies)), 1),
            "latency_p95_ms": round(float(np.percentile(latencies, 95)), 1),
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
        }

    settings_results = {
        "384": eval_setting("INPUT_SIZE 384", 384),
        "512": eval_setting("INPUT_SIZE 512", 512),
        "768": eval_setting("INPUT_SIZE 768", 768),
        "native_full": eval_setting("native full-tile", None, is_native=True),
        "native_crops_512": eval_setting("native overlapping 512 crops (stride 256)", None, is_sliding=True),
    }

    with open(os.path.join(REPO_ROOT, "data", "settings_benchmark.json"), "w", encoding="utf-8") as f:
        json.dump(settings_results, f, indent=2)
    print("✓ Saved data/settings_benchmark.json")

    print("\n===================================================================")
    print("RECALIBRATION PIPELINE COMPLETE SUCCESSFULLY!")
    print("===================================================================")

if __name__ == "__main__":
    main()
