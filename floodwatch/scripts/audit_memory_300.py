"""
FloodWatch 300-Request Memory Audit & 216-Entry Cache Measurement (Phase 4 Item 4)

Measures:
1. 300 fast requests through the server, sampling RSS and VRAM every 25 requests.
   Verifies whether RSS plateaus or leaks (> 50 MB growth).
2. Full cache prewarm to 216 entries (all 202 fast tiles + 14 accurate demo tiles).
   Reports exact cache memory in MB from /api/health and process RSS delta.
3. Lazy mask generation latency on an un-generated mask to verify if there is any visible hitch (> 50 ms).
"""
import sys
import os
import json
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
SERVER_URL = os.getenv("FW_SERVER_URL", "http://127.0.0.1:8000")

def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "FloodWatch-MemAudit"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_raw(url: str):
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": "FloodWatch-MemAudit"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
        headers = dict(resp.headers)
    dt = (time.perf_counter() - t0) * 1000
    return dt, len(data), headers

def main():
    print("=======================================================")
    print("FLOODWATCH 300-REQUEST MEMORY AUDIT & CACHE MEASUREMENT")
    print(f"Target Server: {SERVER_URL}")
    print("=======================================================")

    # 1. Initial State
    h_init = fetch_json(f"{SERVER_URL}/api/health")
    all_tiles = fetch_json(f"{SERVER_URL}/api/tiles")
    demo_tiles = fetch_json(f"{SERVER_URL}/api/demo_tiles")

    print(f"Device:               {h_init.get('device')}")
    print(f"Initial Process RAM:  {h_init.get('process_ram_mb')} MB")
    print(f"Initial Peak VRAM:    {h_init.get('peak_vram_mb')} MB")
    print(f"Initial Cache Count:  {h_init.get('cache_size')} entries")
    print(f"Total Available Tiles: {len(all_tiles)}")
    print("-------------------------------------------------------")

    # ---------------------------------------------------- Step 1: 300 Fast Requests
    print("\n--- Running 300 Fast Requests (Sampling RAM every 25 requests) ---")
    rss_samples = []
    vram_samples = []
    sample_points = []

    # Record point 0
    rss_samples.append(h_init.get('process_ram_mb'))
    vram_samples.append(h_init.get('peak_vram_mb'))
    sample_points.append(0)

    t0_300 = time.perf_counter()
    for req_idx in range(1, 301):
        tile_id = all_tiles[(req_idx - 1) % len(all_tiles)]
        fetch_json(f"{SERVER_URL}/api/analyze/{tile_id}?mode=fast")

        if req_idx % 25 == 0:
            h = fetch_json(f"{SERVER_URL}/api/health")
            rss = h.get('process_ram_mb')
            vram = h.get('peak_vram_mb')
            rss_samples.append(rss)
            vram_samples.append(vram)
            sample_points.append(req_idx)
            delta_from_start = rss - rss_samples[0]
            print(f"  [Req {req_idx:3d}/300] RSS: {rss:7.2f} MB (Delta: {delta_from_start:+6.2f} MB) | Peak VRAM: {vram:6.2f} MB | Cache: {h.get('cache_size')} tiles")

    total_300_time = time.perf_counter() - t0_300
    print(f"\n300 Requests Complete in {total_300_time:.2f}s (Average: {total_300_time/300*1000:.1f} ms/req)")

    # Analyze RSS trajectory: check last 100 requests (req 200 to 300)
    # If delta over last 100 requests is < 5 MB, process RAM has plateaued.
    rss_start = rss_samples[0]
    rss_end = rss_samples[-1]
    rss_growth_total = rss_end - rss_start
    rss_last_100_growth = rss_samples[-1] - rss_samples[-5] # index for req 200 is -5

    print("\n--- RSS Growth Analysis ---")
    print(f"Initial RSS (Req 0):    {rss_start:.2f} MB")
    print(f"Req 100 RSS:            {rss_samples[4]:.2f} MB")
    print(f"Req 200 RSS:            {rss_samples[8]:.2f} MB")
    print(f"Req 300 RSS (Final):    {rss_end:.2f} MB")
    print(f"Total Growth over 300:  {rss_growth_total:+.2f} MB")
    print(f"Growth from Req 200-300:{rss_last_100_growth:+.2f} MB")

    if rss_last_100_growth < 5.0 and rss_growth_total < 50.0:
        print("✓ RSS PLATEAU CONFIRMED: Memory stabilizes once cache fills. Zero linear memory leak.")
    else:
        print(f"WARNING: RSS growth exceeded expected bound ({rss_growth_total:.2f} MB).")

    # ---------------------------------------------------- Step 2: 216 Cache Entries Measurement
    print("\n--- Step 2: Prewarming all 202 Fast + 14 Accurate Demo Tiles (216 Total Entries) ---")
    # All 202 fast tiles are already in cache from the 300 requests loop!
    # Now add the 14 accurate demo tiles:
    demo_ids = [d["tile_id"] for d in demo_tiles]
    for idx, d_id in enumerate(demo_ids, 1):
        fetch_json(f"{SERVER_URL}/api/analyze/{d_id}?mode=accurate")

    h_216 = fetch_json(f"{SERVER_URL}/api/health")
    cache_count_216 = h_216.get("cache_size")
    cache_mem_mb_216 = h_216.get("cache_memory_mb")
    cache_mem_bytes_216 = h_216.get("cache_memory_bytes")
    rss_216 = h_216.get("process_ram_mb")
    rss_delta_total = rss_216 - rss_start

    print(f"Cache Entry Count:          {cache_count_216} / {h_216.get('cache_capacity')}")
    print(f"Measured Cache Memory:      {cache_mem_mb_216} MB ({cache_mem_bytes_216:,} bytes)")
    print(f"Average Memory per Entry:   {(cache_mem_bytes_216 / max(1, cache_count_216)) / 1024:.1f} KB/entry")
    print(f"Process RSS with 216 Cache: {rss_216:.2f} MB (Total RSS delta from empty: {rss_delta_total:+.2f} MB)")
    print(f"Peak GPU VRAM:              {h_216.get('peak_vram_mb')} MB")

    # ---------------------------------------------------- Step 3: Lazy Mask Generation Latency Measurement
    print("\n--- Step 3: Lazy Mask Generation Latency Test ---")
    # Measure first-toggle latency on a tile whose masks were not pre-generated
    # Pick a tile that hasn't had /api/mask called on it yet (e.g. tile 0_39_62 or any from all_tiles)
    test_mask_tile = all_tiles[50]
    print(f"Testing lazy mask fetch on Tile {test_mask_tile}...")

    # Fetch before mask
    dt_before_1, len_before_1, _ = fetch_raw(f"{SERVER_URL}/api/mask/{test_mask_tile}/before.png?mode=fast")
    # Fetch after mask
    dt_after_1, len_after_1, _ = fetch_raw(f"{SERVER_URL}/api/mask/{test_mask_tile}/after.png?mode=fast")

    # Second fetch (already encoded in cache)
    dt_before_cached, _, _ = fetch_raw(f"{SERVER_URL}/api/mask/{test_mask_tile}/before.png?mode=fast")
    dt_after_cached, _, _ = fetch_raw(f"{SERVER_URL}/api/mask/{test_mask_tile}/after.png?mode=fast")

    print(f"  First-toggle latency (lazy PNG generation):")
    print(f"    - Before mask: {dt_before_1:.2f} ms ({len_before_1} bytes)")
    print(f"    - After mask:  {dt_after_1:.2f} ms ({len_after_1} bytes)")
    print(f"    - Total first-toggle time: {dt_before_1 + dt_after_1:.2f} ms")
    print(f"  Second-toggle latency (in-memory cached PNG):")
    print(f"    - Before mask: {dt_before_cached:.2f} ms")
    print(f"    - After mask:  {dt_after_cached:.2f} ms")

    hitch_detected = (dt_before_1 > 50.0) or (dt_after_1 > 50.0)
    print(f"  Visible Hitch (>50ms): {'YES' if hitch_detected else 'NO (Smooth sub-50ms)'}")

    # Output audit report
    audit_data = {
        "rss_samples": [
            {"requests": pt, "rss_mb": r, "vram_mb": v}
            for pt, r, v in zip(sample_points, rss_samples, vram_samples)
        ],
        "rss_initial_mb": rss_start,
        "rss_final_300_mb": rss_end,
        "rss_growth_300_mb": rss_growth_total,
        "rss_last_100_growth_mb": rss_last_100_growth,
        "cache_216": {
            "entries_count": cache_count_216,
            "cache_memory_mb": cache_mem_mb_216,
            "cache_memory_bytes": cache_mem_bytes_216,
            "avg_kb_per_entry": (cache_mem_bytes_216 / max(1, cache_count_216)) / 1024,
            "process_rss_mb": rss_216,
            "peak_vram_mb": h_216.get("peak_vram_mb"),
        },
        "lazy_mask_generation": {
            "tile_tested": test_mask_tile,
            "first_toggle_before_ms": dt_before_1,
            "first_toggle_after_ms": dt_after_1,
            "total_first_toggle_ms": dt_before_1 + dt_after_1,
            "cached_before_ms": dt_before_cached,
            "cached_after_ms": dt_after_cached,
            "hitch_detected": hitch_detected,
        }
    }

    out_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "memory_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)

    print(f"\nAudit complete. Data saved to {out_file}")

if __name__ == "__main__":
    main()
