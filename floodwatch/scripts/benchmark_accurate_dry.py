"""
Accurate Mode Dry & Flooded Benchmark (Phase 4.9 Task 3)

1. Run Accurate Mode across all 136 not-in-pool tiles.
   - Record before, after, net, latency.
   - Compare side-by-side with Fast Mode from tile_scan.json:
     - before / after / net distributions (min, median, p90, max)
     - count of before > 0.1% and after > 0.1%
     - max values
     - list any tiles with before > 0, after > 0, or net != 0

2. Run Accurate Mode across all 66 flooded (train) tiles.
   - Count tiles with net > 1.0% in Fast vs Accurate.

3. Save full raw outputs to data/accurate_dry_benchmark.json and data/accurate_flooded_66.json.
"""
import sys
import os
import json
import time
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.flood_inference import get_model, analyze_tile

def percentiles_dict(arr):
    if len(arr) == 0:
        return {"min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0}
    s = np.array(arr)
    return {
        "min": float(round(float(s.min()), 4)),
        "median": float(round(float(np.median(s)), 4)),
        "p90": float(round(float(np.percentile(s, 90)), 4)),
        "max": float(round(float(s.max()), 4)),
    }

def main():
    print("=======================================================")
    print("TASK 3: ACCURATE MODE ON DRY TILES (136 NOT-IN-POOL)")
    print("=======================================================")

    with open(os.path.join("data", "tile_scan.json"), "r", encoding="utf-8") as f:
        tile_scan = json.load(f)

    dry_tiles = [t for t in tile_scan if t.get("split") == "not_in_pool"]
    flooded_tiles = [t for t in tile_scan if t.get("split") == "train"]

    print(f"Total tiles in tile_scan.json: {len(tile_scan)}")
    print(f"Dry (not_in_pool) tiles:      {len(dry_tiles)}")
    print(f"Flooded (train) tiles:        {len(flooded_tiles)}")

    # Warm up model once
    get_model()

    # 1. Run Accurate Mode on 136 Dry Tiles
    print("\n--- Running Accurate Mode on 136 Dry Tiles ---")
    dry_results = []
    t0_dry = time.perf_counter()

    for idx, t in enumerate(dry_tiles, 1):
        tid = t["tile_id"]
        t_start = time.perf_counter()
        r = analyze_tile(tid, mode="accurate")
        dt = (time.perf_counter() - t_start) * 1000

        dry_results.append({
            "tile_id": tid,
            "fast_before": t["before"],
            "fast_after": t["after"],
            "fast_net": t["net"],
            "accurate_before": r.before_water_pct,
            "accurate_after": r.after_water_pct,
            "accurate_net": r.net_intrusion_pct,
            "latency_ms": r.latency_ms,
        })
        if idx % 20 == 0 or idx == len(dry_tiles):
            el = time.perf_counter() - t0_dry
            print(f"  [{idx:3d}/{len(dry_tiles)}] Dry tiles scanned ({el:.1f}s, avg {el/idx*1000:.1f}ms/tile)")

    # 2. Run Accurate Mode on 66 Flooded Tiles
    print("\n--- Running Accurate Mode on 66 Flooded (Train) Tiles ---")
    flooded_results = []
    t0_flood = time.perf_counter()

    for idx, t in enumerate(flooded_tiles, 1):
        tid = t["tile_id"]
        t_start = time.perf_counter()
        r = analyze_tile(tid, mode="accurate")
        dt = (time.perf_counter() - t_start) * 1000

        flooded_results.append({
            "tile_id": tid,
            "fast_before": t["before"],
            "fast_after": t["after"],
            "fast_net": t["net"],
            "accurate_before": r.before_water_pct,
            "accurate_after": r.after_water_pct,
            "accurate_net": r.net_intrusion_pct,
            "gt_flooded_count": t.get("gt_flooded_count", 0),
            "latency_ms": r.latency_ms,
        })
        if idx % 15 == 0 or idx == len(flooded_tiles):
            el = time.perf_counter() - t0_flood
            print(f"  [{idx:2d}/{len(flooded_tiles)}] Flooded tiles scanned ({el:.1f}s, avg {el/idx*1000:.1f}ms/tile)")

    # ========================================================= Analysis & Comparisons
    print("\n=======================================================")
    print("SIDE-BY-SIDE EVALUATION: DRY TILES (136 NOT-IN-POOL)")
    print("=======================================================")

    fast_befores = [d["fast_before"] for d in dry_results]
    fast_afters = [d["fast_after"] for d in dry_results]
    fast_nets = [d["fast_net"] for d in dry_results]

    acc_befores = [d["accurate_before"] for d in dry_results]
    acc_afters = [d["accurate_after"] for d in dry_results]
    acc_nets = [d["accurate_net"] for d in dry_results]

    dry_stats = {
        "fast_mode": {
            "before_dist": percentiles_dict(fast_befores),
            "after_dist": percentiles_dict(fast_afters),
            "net_dist": percentiles_dict(fast_nets),
            "count_before_gt_0_1": sum(1 for b in fast_befores if b > 0.1),
            "count_after_gt_0_1": sum(1 for a in fast_afters if a > 0.1),
            "count_net_eq_0": sum(1 for n in fast_nets if n == 0.0),
            "count_net_gt_0": sum(1 for n in fast_nets if n > 0.0),
            "count_net_lt_0": sum(1 for n in fast_nets if n < 0.0),
            "max_before": max(fast_befores),
            "max_after": max(fast_afters),
            "max_net": max(fast_nets),
            "min_net": min(fast_nets),
        },
        "accurate_mode": {
            "before_dist": percentiles_dict(acc_befores),
            "after_dist": percentiles_dict(acc_afters),
            "net_dist": percentiles_dict(acc_nets),
            "count_before_gt_0_1": sum(1 for b in acc_befores if b > 0.1),
            "count_after_gt_0_1": sum(1 for a in acc_afters if a > 0.1),
            "count_net_eq_0": sum(1 for n in acc_nets if n == 0.0),
            "count_net_gt_0": sum(1 for n in acc_nets if n > 0.0),
            "count_net_lt_0": sum(1 for n in acc_nets if n < 0.0),
            "max_before": max(acc_befores),
            "max_after": max(acc_afters),
            "max_net": max(acc_nets),
            "min_net": min(acc_nets),
        }
    }

    print("Fast Mode vs Accurate Mode on 136 Dry Tiles:")
    print(f"  Count Before > 0.1%: Fast = {dry_stats['fast_mode']['count_before_gt_0_1']} | Accurate = {dry_stats['accurate_mode']['count_before_gt_0_1']}")
    print(f"  Count After > 0.1%:  Fast = {dry_stats['fast_mode']['count_after_gt_0_1']} | Accurate = {dry_stats['accurate_mode']['count_after_gt_0_1']}")
    print(f"  Max Before:          Fast = {dry_stats['fast_mode']['max_before']:.2f}% | Accurate = {dry_stats['accurate_mode']['max_before']:.2f}%")
    print(f"  Max After:           Fast = {dry_stats['fast_mode']['max_after']:.2f}% | Accurate = {dry_stats['accurate_mode']['max_after']:.2f}%")
    print(f"  Max Net Intrusion:   Fast = {dry_stats['fast_mode']['max_net']:.2f}% | Accurate = {dry_stats['accurate_mode']['max_net']:.2f}%")
    print(f"  Min Net Intrusion:   Fast = {dry_stats['fast_mode']['min_net']:.2f}% | Accurate = {dry_stats['accurate_mode']['min_net']:.2f}%")
    print(f"  Count Net == 0.0%:   Fast = {dry_stats['fast_mode']['count_net_eq_0']} / 136 | Accurate = {dry_stats['accurate_mode']['count_net_eq_0']} / 136")

    print("\nAccurate Mode Dry Anomalies (before > 0 or after > 0 or net != 0):")
    acc_anomalies = [d for d in dry_results if d["accurate_before"] > 0 or d["accurate_after"] > 0 or d["accurate_net"] != 0]
    for a in acc_anomalies:
        print(f"  Tile {a['tile_id']}: before={a['accurate_before']:.2f}%, after={a['accurate_after']:.2f}%, net={a['accurate_net']:+.2f}%")

    print("\n=======================================================")
    print("FLOODED TILES COMPARISON: 66 TRAINING POOL TILES")
    print("=======================================================")
    fast_flooded_nets = [f["fast_net"] for f in flooded_results]
    acc_flooded_nets = [f["accurate_net"] for f in flooded_results]

    count_fast_gt_1 = sum(1 for n in fast_flooded_nets if n > 1.0)
    count_acc_gt_1 = sum(1 for n in acc_flooded_nets if n > 1.0)

    print(f"Flooded tiles with Net > 1.0%:")
    print(f"  Fast Mode:     {count_fast_gt_1} / 66 ({count_fast_gt_1 / 66 * 100:.1f}%)")
    print(f"  Accurate Mode: {count_acc_gt_1} / 66 ({count_acc_gt_1 / 66 * 100:.1f}%)")

    flooded_stats = {
        "fast_gt_1_count": count_fast_gt_1,
        "fast_gt_1_pct": count_fast_gt_1 / 66 * 100,
        "accurate_gt_1_count": count_acc_gt_1,
        "accurate_gt_1_pct": count_acc_gt_1 / 66 * 100,
        "fast_net_dist": percentiles_dict(fast_flooded_nets),
        "accurate_net_dist": percentiles_dict(acc_flooded_nets),
    }

    # Save to data directory
    out_dry = {
        "summary": dry_stats,
        "tiles": dry_results
    }
    with open(os.path.join("data", "accurate_dry_benchmark.json"), "w", encoding="utf-8") as f:
        json.dump(out_dry, f, indent=2)

    out_flood = {
        "summary": flooded_stats,
        "tiles": flooded_results
    }
    with open(os.path.join("data", "accurate_flooded_66.json"), "w", encoding="utf-8") as f:
        json.dump(out_flood, f, indent=2)

    print("\nOutputs saved to:")
    print("  - data/accurate_dry_benchmark.json")
    print("  - data/accurate_flooded_66.json")

if __name__ == "__main__":
    main()
