"""
Phase 2.6 Comprehensive Benchmark across 5 Inference Settings:
  1. INPUT_SIZE = 384
  2. INPUT_SIZE = 512
  3. INPUT_SIZE = 768
  4. native full-tile
  5. native overlapping 512 crops (stride 256, averaged logits)

Evaluates on all 202 SpaceNet 8 tiles against human ground-truth annotations:
  - Pixel F1 and IoU
  - Tile-level ROC-AUC (has flooded GT vs predicted after_pct)
  - Spearman rank correlation (predicted net vs GT flooded fraction)
  - Warm total latency (I/O + GPU forward + postprocess: median and p95)
"""
import glob
import json
import os
import time
import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from shapely.geometry import shape
import torch
import torch.nn.functional as F

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
    water_pct,
)

BUF_DEG = 2.0 / 70680.0  # ~2 meter radius buffer (~4m road corridor) for road linestrings

def build_ground_truth(tile_id: str, post_path: str):
    ann_path = os.path.join("data", "raw", "annotations", f"{tile_id}.geojson")
    with rasterio.open(post_path) as src:
        H, W = src.shape
        transform = src.transform

    if not os.path.exists(ann_path):
        return np.zeros((H, W), dtype=np.uint8), 0, 0, 0

    with open(ann_path, "r") as f:
        data = json.load(f)

    shapes = []
    n_bldg = 0
    n_road = 0
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        if props.get("flooded") == "yes":
            geom = shape(feat["geometry"])
            if geom.geom_type in ["LineString", "MultiLineString"]:
                geom = geom.buffer(BUF_DEG)
                n_road += 1
            else:
                n_bldg += 1
            shapes.append((geom, 1))

    if shapes:
        gt_mask = rasterize(shapes, out_shape=(H, W), transform=transform, fill=0, all_touched=True)
    else:
        gt_mask = np.zeros((H, W), dtype=np.uint8)

    return gt_mask, n_bldg, n_road, (n_bldg + n_road)


def infer_tile(images: list[torch.Tensor], mode: str, model):
    """
    Run inference on images under a specific setting.
    Returns list of boolean masks of shape (H, W) for each image.
    """
    sizes = [img.shape[-2:] for img in images]
    mean = MEAN.to(DEVICE)
    std = STD.to(DEVICE)

    if mode in ["384", "512", "768"]:
        sz = int(mode)
        batch = torch.stack([
            F.interpolate(img.unsqueeze(0), size=(sz, sz), mode="bilinear", align_corners=False)[0]
            for img in images
        ])
        batch = (batch.to(DEVICE) - mean) / std
        if USE_FP16:
            batch = batch.half()

        logits = model(pixel_values=batch).logits
        masks = []
        for i, (orig_h, orig_w) in enumerate(sizes):
            up = F.interpolate(logits[i:i + 1].float(), size=(orig_h, orig_w), mode="bilinear", align_corners=False)
            masks.append((up.argmax(dim=1)[0] == WATER_CLASS).cpu().numpy().astype(bool))
        return masks

    elif mode == "native_full":
        # Native resolution (batch of 1 or matching sizes)
        masks = []
        for img in images:
            b = img.unsqueeze(0).to(DEVICE)
            b = (b - mean) / std
            if USE_FP16:
                b = b.half()
            logits = model(pixel_values=b).logits
            up = F.interpolate(logits.float(), size=img.shape[-2:], mode="bilinear", align_corners=False)
            masks.append((up.argmax(dim=1)[0] == WATER_CLASS).cpu().numpy().astype(bool))
        return masks

    elif mode == "native_crops_512":
        # Overlapping 512 crops with stride 256
        masks = []
        crop_size = 512
        stride = 256
        for img in images:
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

            batch = torch.stack(crops).to(DEVICE)
            batch = (batch - mean) / std
            if USE_FP16:
                batch = batch.half()

            # Process in sub-batches if large to prevent VRAM spikes
            sub_b = 8
            full_logits = torch.zeros((3, H, W), dtype=torch.float32, device=DEVICE)
            counts = torch.zeros((1, H, W), dtype=torch.float32, device=DEVICE)

            for idx in range(0, len(crops), sub_b):
                sub_batch = batch[idx:idx + sub_b]
                sub_logits = model(pixel_values=sub_batch).logits
                sub_up = F.interpolate(sub_logits.float(), size=(crop_size, crop_size), mode="bilinear", align_corners=False)
                for k in range(sub_batch.shape[0]):
                    y, x = coords[idx + k]
                    full_logits[:, y:y + crop_size, x:x + crop_size] += sub_up[k]
                    counts[:, y:y + crop_size, x:x + crop_size] += 1.0

            avg_logits = full_logits / counts.clamp(min=1.0)
            masks.append((avg_logits.argmax(dim=0) == WATER_CLASS).cpu().numpy().astype(bool))
        return masks

    else:
        raise ValueError(f"Unknown mode {mode}")


def run_benchmark():
    tiles = list_tiles()
    print(f"Loaded {len(tiles)} tiles. Building Ground Truth dataset...")
    
    gt_data = {}
    for t in tiles:
        pre_p, post_p = find_tile_paths(t)
        gt_mask, n_bldg, n_road, n_tot = build_ground_truth(t, post_p)
        gt_data[t] = {
            "gt_mask": gt_mask,
            "has_flood_gt": int(n_tot > 0),
            "gt_flooded_pixels": int(gt_mask.sum()),
            "total_pixels": int(gt_mask.size),
            "gt_flooded_fraction": float(gt_mask.mean()),
            "n_bldg": n_bldg,
            "n_road": n_road,
            "n_tot": n_tot,
            "pre_path": pre_p,
            "post_path": post_p,
        }

    n_annotated_with_flood = sum(v["has_flood_gt"] for v in gt_data.values())
    print(f"Ground Truth ready: {n_annotated_with_flood} / {len(tiles)} tiles contain flooded features.\n")

    model = get_model()

    settings = [
        ("384", "INPUT_SIZE 384"),
        ("512", "INPUT_SIZE 512"),
        ("768", "INPUT_SIZE 768"),
        ("native_full", "native full-tile"),
        ("native_crops_512", "native overlapping 512 crops (stride 256)")
    ]

    benchmark_summary = {}

    for mode_key, mode_name in settings:
        print(f"============================================================")
        print(f"Evaluating Setting: {mode_name}")
        print(f"============================================================")

        total_tp = 0
        total_fp = 0
        total_fn = 0
        total_tn = 0

        y_true_binary = []
        y_score_after = []
        pred_nets = []
        gt_fractions = []
        latencies = []

        # Warmup for this mode
        t_sample = tiles[0]
        pre_img, post_img = load_rgb(gt_data[t_sample]["pre_path"]), load_rgb(gt_data[t_sample]["post_path"])
        with torch.no_grad():
            infer_tile([pre_img, post_img], mode_key, model)

        for i, t in enumerate(tiles):
            t_data = gt_data[t]
            t0 = time.perf_counter()
            pre_img = load_rgb(t_data["pre_path"])
            post_img = load_rgb(t_data["post_path"])

            with torch.no_grad():
                masks = infer_tile([pre_img, post_img], mode_key, model)
            
            lat_ms = (time.perf_counter() - t0) * 1000
            latencies.append(lat_ms)

            pre_mask, post_mask = masks[0], masks[1]
            gt_m = t_data["gt_mask"].astype(bool)

            # Pixel metrics on POST imagery
            tp = int((post_mask & gt_m).sum())
            fp = int((post_mask & (~gt_m)).sum())
            fn = int(((~post_mask) & gt_m).sum())
            tn = int(((~post_mask) & (~gt_m)).sum())

            total_tp += tp
            total_fp += fp
            total_fn += fn
            total_tn += tn

            after_pct = float(post_mask.mean() * 100.0)
            before_pct = float(pre_mask.mean() * 100.0)
            net_pct = round(after_pct - before_pct, 2)

            y_true_binary.append(t_data["has_flood_gt"])
            y_score_after.append(after_pct)
            pred_nets.append(net_pct)
            gt_fractions.append(t_data["gt_flooded_fraction"])

            if (i + 1) % 50 == 0 or (i + 1) == len(tiles):
                print(f"  Processed {i+1}/{len(tiles)} tiles (current avg latency: {np.mean(latencies):.1f} ms)")

        # Dataset-level pixel metrics
        pixel_iou = (total_tp / (total_tp + total_fp + total_fn)) * 100 if (total_tp + total_fp + total_fn) > 0 else 0.0
        pixel_f1 = (2 * total_tp / (2 * total_tp + total_fp + total_fn)) * 100 if (2 * total_tp + total_fp + total_fn) > 0 else 0.0

        # Tile-level ROC-AUC
        roc_auc = roc_auc_score(y_true_binary, y_score_after)

        # Spearman correlation
        spearman_corr, _ = spearmanr(pred_nets, gt_fractions)

        # Latency
        med_lat = np.median(latencies)
        p95_lat = np.percentile(latencies, 95)

        benchmark_summary[mode_key] = {
            "name": mode_name,
            "pixel_f1": round(pixel_f1, 2),
            "pixel_iou": round(pixel_iou, 2),
            "roc_auc": round(roc_auc, 4),
            "spearman_corr": round(spearman_corr, 4),
            "latency_median_ms": round(med_lat, 1),
            "latency_p95_ms": round(p95_lat, 1),
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
        }

        print(f"\nResults for {mode_name}:")
        print(f"  Pixel F1:           {pixel_f1:.2f}%")
        print(f"  Pixel IoU:          {pixel_iou:.2f}%")
        print(f"  Tile ROC-AUC:       {roc_auc:.4f}")
        print(f"  Spearman Corr:      {spearman_corr:.4f}")
        print(f"  Total Latency (ms): median={med_lat:.1f}ms, p95={p95_lat:.1f}ms")
        print(f"  TP: {total_tp:,} | FP: {total_fp:,} | FN: {total_fn:,}\n")

    out_file = os.path.join("data", "settings_benchmark.json")
    with open(out_file, "w") as f:
        json.dump(benchmark_summary, f, indent=2)
    print(f"All benchmark results saved to {out_file}")

if __name__ == "__main__":
    run_benchmark()
