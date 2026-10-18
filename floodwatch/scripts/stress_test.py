"""
FloodWatch Stress Test Suite (Phase 4C).
Runs:
  Stage 1: 50 sequential uncached fast requests over random tiles
  Stage 2: 20 requests with 4 concurrent clients
  Stage 3: 10 accurate requests over distinct tiles

Measures min/median/p95 latency, peak GPU VRAM, and process RAM before/after.
Fails immediately on any error.
"""
import sys
import os
import json
import time
import random
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")

SERVER_URL = os.getenv("FW_SERVER_URL", "http://127.0.0.1:8000")

def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "FloodWatch-StressTest"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def compute_percentiles(latencies):
    if not latencies:
        return 0.0, 0.0, 0.0, 0.0
    s = sorted(latencies)
    min_v = s[0]
    med_v = s[len(s) // 2]
    p95_v = s[int(len(s) * 0.95)]
    max_v = s[-1]
    return min_v, med_v, p95_v, max_v

def main():
    print("=======================================================")
    print("Starting FloodWatch Stress Test")
    print(f"Target Server: {SERVER_URL}")
    print("=======================================================")

    # 1. Initial Health & Resource Check
    h_init = fetch_json(f"{SERVER_URL}/api/health")
    all_tiles = fetch_json(f"{SERVER_URL}/api/tiles")
    print(f"Server Device:     {h_init.get('device')}")
    print(f"Available Tiles:   {len(all_tiles)}")
    print(f"Initial Process RAM: {h_init.get('process_ram_mb')} MB")
    print(f"Initial Peak VRAM:   {h_init.get('peak_vram_mb')} MB")
    print("-------------------------------------------------------")

    random.seed(42)
    shuffled_tiles = list(all_tiles)
    random.shuffle(shuffled_tiles)

    errors = []

    # ---------------------------------------------------- Stage 1: 50 Sequential Fast Requests
    print("\n--- Clearing cache before Stage 1 ---")
    fetch_json(f"{SERVER_URL}/api/cache/clear")
    h_before_s1 = fetch_json(f"{SERVER_URL}/api/health")
    assert h_before_s1.get("cache_size") == 0, "Cache should be empty before Stage 1"

    print("\n--- Stage 1: 50 Sequential Fast Requests ---")
    s1_tiles = shuffled_tiles[:50]
    s1_latencies = []
    t_stage1_start = time.perf_counter()

    for idx, tid in enumerate(s1_tiles, 1):
        t0 = time.perf_counter()
        try:
            res = fetch_json(f"{SERVER_URL}/api/analyze/{tid}?mode=fast")
            dt = (time.perf_counter() - t0) * 1000
            s1_latencies.append(dt)
            assert "net_intrusion_pct" in res, "Missing net_intrusion_pct in response"
            assert "latency_ms" in res, "Missing latency_ms in response"
            assert res.get("cached") is False, f"Expected cached == False in Stage 1 for tile {tid}"
            if idx % 10 == 0 or idx == 50:
                print(f"  [Req {idx:2d}/50] Tile {tid:<8} | Latency: {dt:6.1f} ms | Cached: {str(res.get('cached')):<5} | Net: {res['net_intrusion_pct']:>6.2f}%")
        except Exception as e:
            errors.append(f"Stage 1 error on {tid}: {e}")
            print(f"  [Req {idx:2d}/50] Tile {tid:<8} | ERROR: {e}")

    s1_min, s1_med, s1_p95, s1_max = compute_percentiles(s1_latencies)
    h_s1 = fetch_json(f"{SERVER_URL}/api/health")
    print(f"Stage 1 Complete: {len(s1_latencies)} requests in {time.perf_counter() - t_stage1_start:.2f}s")
    print(f"  Latency (ms) -> Min: {s1_min:.1f} | Median: {s1_med:.1f} | P95: {s1_p95:.1f} | Max: {s1_max:.1f}")
    print(f"  RAM RSS: {h_s1.get('process_ram_mb')} MB | Peak VRAM: {h_s1.get('peak_vram_mb')} MB | Cache: {h_s1.get('cache_size')} tiles")

    # ---------------------------------------------------- Stage 2: 20 Requests with 4 Concurrent Clients
    print("\n--- Clearing cache before Stage 2 ---")
    fetch_json(f"{SERVER_URL}/api/cache/clear")
    h_before_s2 = fetch_json(f"{SERVER_URL}/api/health")
    assert h_before_s2.get("cache_size") == 0, "Cache should be empty before Stage 2"

    print("\n--- Stage 2: 20 Requests with 4 Concurrent Clients ---")
    s2_tiles = shuffled_tiles[50:70]
    s2_latencies = []
    t_stage2_start = time.perf_counter()

    def worker_fetch(t_id):
        t0 = time.perf_counter()
        try:
            res = fetch_json(f"{SERVER_URL}/api/analyze/{t_id}?mode=fast")
            dt = (time.perf_counter() - t0) * 1000
            return dt, res, None
        except Exception as e:
            return 0.0, None, str(e)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(worker_fetch, tid) for tid in s2_tiles]
        for idx, f in enumerate(futures, 1):
            dt, res, err = f.result()
            if err:
                errors.append(f"Stage 2 concurrent error: {err}")
            else:
                s2_latencies.append(dt)
            if idx % 5 == 0 or idx == 20:
                print(f"  [Concurrent {idx:2d}/20] Latency: {dt:6.1f} ms | Status: {'OK' if not err else 'ERR'}")

    s2_min, s2_med, s2_p95, s2_max = compute_percentiles(s2_latencies)
    h_s2 = fetch_json(f"{SERVER_URL}/api/health")
    print(f"Stage 2 Complete: {len(s2_latencies)} requests in {time.perf_counter() - t_stage2_start:.2f}s")
    print(f"  Latency (ms) -> Min: {s2_min:.1f} | Median: {s2_med:.1f} | P95: {s2_p95:.1f} | Max: {s2_max:.1f}")
    print(f"  RAM RSS: {h_s2.get('process_ram_mb')} MB | Peak VRAM: {h_s2.get('peak_vram_mb')} MB | Cache: {h_s2.get('cache_size')} tiles")

    # ---------------------------------------------------- Stage 3: 10 Accurate Mode Requests
    print("\n--- Clearing cache before Stage 3 ---")
    fetch_json(f"{SERVER_URL}/api/cache/clear")
    h_before_s3 = fetch_json(f"{SERVER_URL}/api/health")
    assert h_before_s3.get("cache_size") == 0, "Cache should be empty before Stage 3"

    print("\n--- Stage 3: 10 Accurate Mode Requests (Sliding Window 512) ---")
    s3_tiles = shuffled_tiles[70:80]
    s3_latencies = []
    t_stage3_start = time.perf_counter()

    for idx, tid in enumerate(s3_tiles, 1):
        t0 = time.perf_counter()
        try:
            res = fetch_json(f"{SERVER_URL}/api/analyze/{tid}?mode=accurate")
            dt = (time.perf_counter() - t0) * 1000
            s3_latencies.append(dt)
            print(f"  [Accurate {idx:2d}/10] Tile {tid:<8} | Latency: {dt:6.1f} ms | Net: {res['net_intrusion_pct']:>6.2f}%")
        except Exception as e:
            errors.append(f"Stage 3 error on {tid}: {e}")
            print(f"  [Accurate {idx:2d}/10] Tile {tid:<8} | ERROR: {e}")

    s3_min, s3_med, s3_p95, s3_max = compute_percentiles(s3_latencies)
    h_s3 = fetch_json(f"{SERVER_URL}/api/health")
    print(f"Stage 3 Complete: {len(s3_latencies)} requests in {time.perf_counter() - t_stage3_start:.2f}s")
    print(f"  Latency (ms) -> Min: {s3_min:.1f} | Median: {s3_med:.1f} | P95: {s3_p95:.1f} | Max: {s3_max:.1f}")
    print(f"  RAM RSS: {h_s3.get('process_ram_mb')} MB | Peak VRAM: {h_s3.get('peak_vram_mb')} MB | Cache: {h_s3.get('cache_size')} tiles")

    # ---------------------------------------------------- Final Summary & Evaluation
    print("\n=======================================================")
    print("STRESS TEST FINAL SUMMARY")
    print("=======================================================")
    print(f"Total Requests Executed: {len(s1_latencies) + len(s2_latencies) + len(s3_latencies)}")
    print(f"Total Errors Encountered: {len(errors)}")
    print(f"Initial Process RAM:      {h_init.get('process_ram_mb')} MB")
    print(f"Final Process RAM:        {h_s3.get('process_ram_mb')} MB (Growth: {h_s3.get('process_ram_mb') - h_init.get('process_ram_mb'):+.2f} MB)")
    print(f"Initial Peak GPU VRAM:    {h_init.get('peak_vram_mb')} MB")
    print(f"Final Peak GPU VRAM:      {h_s3.get('peak_vram_mb')} MB (Growth: {h_s3.get('peak_vram_mb') - h_init.get('peak_vram_mb'):+.2f} MB)")
    print(f"Final Cache Storage:      {h_s3.get('cache_size')} / {h_s3.get('cache_capacity')} ({h_s3.get('cache_memory_mb')} MB)")

    out_data = {
        "initial": {
            "ram_mb": h_init.get("process_ram_mb"),
            "peak_vram_mb": h_init.get("peak_vram_mb"),
        },
        "stage1_fast_50": {
            "count": len(s1_latencies),
            "min_ms": s1_min,
            "median_ms": s1_med,
            "p95_ms": s1_p95,
            "max_ms": s1_max,
            "ram_mb": h_s1.get("process_ram_mb"),
            "peak_vram_mb": h_s1.get("peak_vram_mb"),
            "cache_size": h_s1.get("cache_size"),
        },
        "stage2_concurrent_20": {
            "count": len(s2_latencies),
            "min_ms": s2_min,
            "median_ms": s2_med,
            "p95_ms": s2_p95,
            "max_ms": s2_max,
            "ram_mb": h_s2.get("process_ram_mb"),
            "peak_vram_mb": h_s2.get("peak_vram_mb"),
            "cache_size": h_s2.get("cache_size"),
        },
        "stage3_accurate_10": {
            "count": len(s3_latencies),
            "min_ms": s3_min,
            "median_ms": s3_med,
            "p95_ms": s3_p95,
            "max_ms": s3_max,
            "ram_mb": h_s3.get("process_ram_mb"),
            "peak_vram_mb": h_s3.get("peak_vram_mb"),
            "cache_size": h_s3.get("cache_size"),
        },
        "final": {
            "ram_mb": h_s3.get("process_ram_mb"),
            "peak_vram_mb": h_s3.get("peak_vram_mb"),
            "cache_size": h_s3.get("cache_size"),
            "cache_mb": h_s3.get("cache_memory_mb"),
            "ram_growth_mb": h_s3.get("process_ram_mb") - h_init.get("process_ram_mb"),
            "errors": len(errors),
        }
    }
    with open(os.path.join("data", "stress_test_results.json"), "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)

    if errors:
        print("\nFAIL: Errors were reported during stress test:")
        for err in errors:
            print("  -", err)
        sys.exit(1)
    else:
        print("\nSUCCESS: All stress tests passed with 0 errors!")
        sys.exit(0)

if __name__ == "__main__":
    main()
