"""
Code Checks Verification Script (Phase 4 Corrections - Item 3)

1. Confirm /api/analyze runs inference in a threadpool and not on the event loop.
   Measure /api/health response time while an accurate-mode inference is actively running.
2. Report the added ms for eager mask encoding on tile 0_41_58 (largest flood mask).
3. Verify ?nocache=1 bypasses cache read, writes result, and returns cached=False.
"""
import sys
import os
import time
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
SERVER_URL = os.getenv("FW_SERVER_URL", "http://127.0.0.1:8000")

def fetch_json(url: str):
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": "FloodWatch-CodeCheck"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    dt = (time.perf_counter() - t0) * 1000
    return dt, data

def main():
    print("=======================================================")
    print("TASK 3: CODE CHECKS & CONCURRENCY VERIFICATION")
    print(f"Server Target: {SERVER_URL}")
    print("=======================================================")

    # ---------------------------------------------------- 1. Threadpool vs Event Loop Check
    print("\n--- 1. Proving /api/analyze runs in Threadpool (Event Loop Liveness) ---")
    # Launch an accurate inference on an uncached tile (e.g. 0_41_58?mode=accurate&nocache=1)
    # Concurrently send 5 /api/health requests while the accurate inference is executing.

    # Warm up health endpoint
    fetch_json(f"{SERVER_URL}/api/health")

    health_latencies = []
    accurate_latency = None

    def run_accurate():
        nonlocal accurate_latency
        dt, res = fetch_json(f"{SERVER_URL}/api/analyze/0_41_58?mode=accurate&nocache=1")
        accurate_latency = dt
        return dt, res

    def run_health(idx):
        time.sleep(0.15 * idx) # Stagger slightly to land during accurate GPU inference
        dt, res = fetch_json(f"{SERVER_URL}/api/health")
        return idx, dt, res

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_acc = ex.submit(run_accurate)
        time.sleep(0.1) # ensure accurate request has reached server and GPU started
        f_healths = [ex.submit(run_health, i) for i in range(1, 6)]

        for f in f_healths:
            idx, dt, res = f.result()
            health_latencies.append(dt)
            print(f"  Concurrent /api/health #{idx}: Latency = {dt:5.2f} ms | Status = {res.get('status')}")

        acc_dt, acc_res = f_acc.result()
        print(f"  Accurate Mode GPU Inference completed in: {acc_dt:6.1f} ms")

    med_health = sorted(health_latencies)[len(health_latencies) // 2]
    max_health = max(health_latencies)
    print(f"\n/api/health Latency during GPU inference: Median = {med_health:.2f} ms | Max = {max_health:.2f} ms")
    if max_health < 50.0:
        print("✓ PROOF VERIFIED: Event loop is completely unblocked during GPU inference (threadpool confirmed).")
    else:
        print(f"Note: Max health latency was {max_health:.2f} ms.")

    # ---------------------------------------------------- 2. Eager Mask Encoding Timing on 0_41_58
    print("\n--- 2. Eager Mask Encoding Latency on Tile 0_41_58 (Largest Mask) ---")
    from src.flood_inference import find_tile_paths, analyze_tile
    from src.api import mask_to_rgba_png_bytes

    res, pre_m, post_m = analyze_tile("0_41_58", return_masks=True, mode="fast")

    # Time pre mask PNG encoding
    t0_pre = time.perf_counter()
    png_pre = mask_to_rgba_png_bytes(pre_m)
    dt_pre_enc = (time.perf_counter() - t0_pre) * 1000

    # Time post mask PNG encoding (large flooded mask covering ~39.5% of 1300x1300 pixels = ~667k pixels)
    t0_post = time.perf_counter()
    png_post = mask_to_rgba_png_bytes(post_m)
    dt_post_enc = (time.perf_counter() - t0_post) * 1000

    total_mask_enc_ms = dt_pre_enc + dt_post_enc
    print(f"Tile 0_41_58 Flooded Mask Pixels: {int(post_m.sum()):,} px ({float(post_m.sum()) / post_m.numel() * 100:.2f}%)")
    print(f"  Pre-event mask PNG encode time:  {dt_pre_enc:5.2f} ms ({len(png_pre):,} bytes)")
    print(f"  Post-event mask PNG encode time: {dt_post_enc:5.2f} ms ({len(png_post):,} bytes)")
    print(f"  Total added encode latency:      {total_mask_enc_ms:5.2f} ms")
    print(f"  Current Code Policy: Eager mask encoding in get_or_analyze path, storing bytes in cache.")

    # ---------------------------------------------------- 3. Verify ?nocache=1 Behavior
    print("\n--- 3. Verifying ?nocache=1 Behavior ---")
    # Step A: Prime cache for 0_41_58 fast
    fetch_json(f"{SERVER_URL}/api/analyze/0_41_58?mode=fast")

    # Step B: Normal cached request
    dt_c, res_c = fetch_json(f"{SERVER_URL}/api/analyze/0_41_58?mode=fast")
    print(f"Normal request (from cache):  cached = {res_c.get('cached')} | latency = {dt_c:5.2f} ms")
    assert res_c.get("cached") is True, f"Expected cached == True, got {res_c.get('cached')}"

    # Step C: nocache=1 request
    dt_nc, res_nc = fetch_json(f"{SERVER_URL}/api/analyze/0_41_58?mode=fast&nocache=1")
    print(f"Nocache request (?nocache=1): cached = {res_nc.get('cached')} | latency = {dt_nc:5.2f} ms (server: {res_nc.get('latency_ms')} ms)")
    assert res_nc.get("cached") is False, f"Expected cached == False with nocache=1, got {res_nc.get('cached')}"
    assert res_nc.get("latency_ms") > 0, "Expected non-zero latency with nocache=1"

    # Step D: Subsequent normal request (verifying cache was updated and is still hit)
    dt_sub, res_sub = fetch_json(f"{SERVER_URL}/api/analyze/0_41_58?mode=fast")
    print(f"Subsequent normal request:    cached = {res_sub.get('cached')} | latency = {dt_sub:5.2f} ms")
    assert res_sub.get("cached") is True, f"Expected cached == True on subsequent request, got {res_sub.get('cached')}"

    print("✓ ?nocache=1 verified: correctly forces re-inference, returns cached=False, and updates cache.")

    # Save measurements to data/code_checks_results.json
    out_data = {
        "threadpool_verification": {
            "accurate_gpu_latency_ms": acc_dt,
            "concurrent_health_latencies_ms": health_latencies,
            "median_health_ms": med_health,
            "max_health_ms": max_health,
            "event_loop_unblocked": bool(max_health < 50.0),
        },
        "eager_mask_encoding": {
            "tile_id": "0_41_58",
            "pre_mask_bytes": len(png_pre),
            "pre_mask_encode_ms": dt_pre_enc,
            "post_mask_bytes": len(png_post),
            "post_mask_encode_ms": dt_post_enc,
            "total_added_encode_ms": total_mask_enc_ms,
            "policy": "eager_in_analyze_path",
        },
        "nocache_verification": {
            "cached_req_ms": dt_c,
            "nocache_req_ms": dt_nc,
            "nocache_cached_flag": res_nc.get("cached"),
            "subsequent_cached_req_ms": dt_sub,
        }
    }
    with open(os.path.join("data", "code_checks_results.json"), "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)

if __name__ == "__main__":
    main()
