"""
Scan all 202 SpaceNet 8 tiles with analyze_tile and save to data/tile_scan.json.
"""
import json
import os
import time
import numpy as np
from src.flood_inference import list_tiles, analyze_tile, get_model

def run_scan():
    tiles = list_tiles()
    print(f"Starting scan of all {len(tiles)} tiles...")
    # Warm up model once
    get_model()
    
    results = []
    t0_all = time.perf_counter()

    for i, t in enumerate(tiles):
        t_start = time.perf_counter()
        r = analyze_tile(t)
        dt = int((time.perf_counter() - t_start) * 1000)
        results.append({
            "tile_id": r.tile_id,
            "before": r.before_water_pct,
            "after": r.after_water_pct,
            "net": r.net_intrusion_pct,
            "latency_ms": r.latency_ms
        })
        if (i + 1) % 25 == 0 or (i + 1) == len(tiles):
            elapsed = time.perf_counter() - t0_all
            print(f"Progress: {i+1}/{len(tiles)} tiles scanned ({elapsed:.1f}s, avg {elapsed/(i+1)*1000:.1f}ms/tile)")

    out_path = os.path.join("data", "tile_scan.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Scan saved to {out_path}")

    nets = np.array([r["net"] for r in results])
    befores = np.array([r["before"] for r in results])
    afters = np.array([r["after"] for r in results])
    lats = np.array([r["latency_ms"] for r in results])

    print("\n=== DISTRIBUTION OF NET_INTRUSION_PCT ===")
    print(f"Min:    {nets.min():.2f}%")
    print(f"Median: {np.median(nets):.2f}%")
    print(f"p90:    {np.percentile(nets, 90):.2f}%")
    print(f"Max:    {nets.max():.2f}%")

    print(f"\nTiles with net > 1%:  {int((nets > 1.0).sum())}")
    print(f"Tiles with net > 5%:  {int((nets > 5.0).sum())}")
    print(f"Tiles with net > 10%: {int((nets > 10.0).sum())}")
    print(f"Tiles with net > 0%:  {int((nets > 0.0).sum())}")
    print(f"Tiles with net < 0%:  {int((nets < 0.0).sum())}")
    print(f"Tiles with net == 0%: {int((nets == 0.0).sum())}")

    print("\nTop 15 highest net tiles:")
    top15 = sorted(results, key=lambda x: x["net"], reverse=True)[:15]
    for x in top15:
        print(f"  Tile {x['tile_id']}: before={x['before']}%, after={x['after']}%, net={x['net']:+}%, lat={x['latency_ms']}ms")

    print("\nTop 5 lowest net tiles:")
    bot5 = sorted(results, key=lambda x: x["net"])[:5]
    for x in bot5:
        print(f"  Tile {x['tile_id']}: before={x['before']}%, after={x['after']}%, net={x['net']:+}%, lat={x['latency_ms']}ms")

    print(f"\nLatency benchmark (all {len(tiles)} tiles):")
    print(f"  Min: {lats.min()}ms, Median: {np.median(lats):.1f}ms, p95: {np.percentile(lats, 95):.1f}ms, Max: {lats.max()}ms")

if __name__ == "__main__":
    run_scan()
