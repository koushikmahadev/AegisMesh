"""
FloodWatch Prewarming Script (Phase 4B).
Populates the in-memory LRU cache so subsequent clicks are instantaneous (sub-30ms).

Usage:
  python scripts/prewarm.py [demo|all|path_to_tile_list.txt]
"""
import sys
import os
import json
import time
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")

SERVER_URL = os.getenv("FW_SERVER_URL", "http://127.0.0.1:8000")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "FloodWatch-Prewarm"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    target_arg = sys.argv[1] if len(sys.argv) > 1 else "demo"
    print(f"=======================================================")
    print(f"FloodWatch Cache Prewarm: Target = '{target_arg}'")
    print(f"Server Target: {SERVER_URL}")
    print(f"=======================================================")

    # Wait for server health
    print("Checking server health...")
    healthy = False
    for _ in range(30):
        try:
            h = fetch_json(f"{SERVER_URL}/api/health")
            if h.get("status") == "ok":
                healthy = True
                print(f"Server online. Active device: {h.get('device')}, initial cache: {h.get('cache_size')} tiles.")
                break
        except Exception:
            time.sleep(1)

    if not healthy:
        print(f"Error: Could not connect to FloodWatch server at {SERVER_URL}")
        sys.exit(1)

    # Determine targets: list of (tile_id, mode)
    targets = []
    if target_arg.lower() == "demo":
        demo_path = os.path.join(DATA_DIR, "demo_tiles.json")
        with open(demo_path, "r", encoding="utf-8") as f:
            demos = json.load(f)
        for d in demos:
            targets.append((d["tile_id"], "fast"))
            targets.append((d["tile_id"], "accurate"))
    elif target_arg.lower() == "all":
        tiles = fetch_json(f"{SERVER_URL}/api/tiles")
        for tid in tiles:
            targets.append((tid, "fast"))
        # Also prewarm demo in accurate
        demo_path = os.path.join(DATA_DIR, "demo_tiles.json")
        if os.path.exists(demo_path):
            with open(demo_path, "r", encoding="utf-8") as f:
                demos = json.load(f)
            for d in demos:
                targets.append((d["tile_id"], "accurate"))
    elif os.path.isfile(target_arg):
        with open(target_arg, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        for l in lines:
            parts = l.split()
            tid = parts[0]
            m = parts[1] if len(parts) > 1 else "fast"
            targets.append((tid, m))
    else:
        # Single tile ID
        targets.append((target_arg, "fast"))

    print(f"Prewarming {len(targets)} cache entries...")
    t0 = time.perf_counter()
    succeeded = 0
    failed = 0

    for idx, (tid, mode) in enumerate(targets, 1):
        url = f"{SERVER_URL}/api/analyze/{tid}?mode={mode}"
        t_req = time.perf_counter()
        try:
            res = fetch_json(url)
            dt = (time.perf_counter() - t_req) * 1000
            net = res.get("net_intrusion_pct", 0.0)
            cached_flag = res.get("cached", False)

            # Pre-generate / fetch masks
            if "masks" in res:
                urllib.request.urlopen(f"{SERVER_URL}{res['masks']['before']}", timeout=10)
                urllib.request.urlopen(f"{SERVER_URL}{res['masks']['after']}", timeout=10)

            print(f"[{idx:3d}/{len(targets)}] Tile {tid:<8} ({mode:<8}) -> {dt:6.1f} ms | Net: {net:>6.2f}% | Cached: {cached_flag}")
            succeeded += 1
        except Exception as e:
            print(f"[{idx:3d}/{len(targets)}] Tile {tid:<8} ({mode:<8}) -> FAILED: {e}")
            failed += 1

    total_dt = time.perf_counter() - t0
    final_health = fetch_json(f"{SERVER_URL}/api/health")
    print(f"\n=======================================================")
    print(f"Prewarm Finished in {total_dt:.2f} seconds")
    print(f"Successful: {succeeded} | Failed: {failed}")
    print(f"Total Cache Entries: {final_health.get('cache_size')} / {final_health.get('cache_capacity')}")
    print(f"Cache Memory Usage:  {final_health.get('cache_memory_mb')} MB")
    print(f"Process RAM RSS:     {final_health.get('process_ram_mb')} MB")
    print(f"Peak GPU VRAM:       {final_health.get('peak_vram_mb')} MB")
    print(f"=======================================================")

if __name__ == "__main__":
    main()
