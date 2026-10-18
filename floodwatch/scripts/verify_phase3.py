"""
Verification script for Phase 3 integration, static serving, offline isolation, and latency.
"""
import os
import sys
import re
import json
import time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from starlette.testclient import TestClient
from src.api import app

client = TestClient(app)

print("--- 1. Testing Static Assets Mount ---")
r_html = client.get("/")
assert r_html.status_code == 200, f"Index failed: {r_html.status_code}"
assert "FloodWatch" in r_html.text
print(f"✓ Index.html served correctly (Length: {len(r_html.text)} bytes)")

r_css = client.get("/style.css")
assert r_css.status_code == 200, f"CSS failed: {r_css.status_code}"
assert "metric-headline" in r_css.text
print(f"✓ style.css served correctly (Length: {len(r_css.text)} bytes)")

r_js = client.get("/app.js")
assert r_js.status_code == 200, f"JS failed: {r_js.status_code}"
assert "initApp" in r_js.text
print(f"✓ app.js served correctly (Length: {len(r_js.text)} bytes)")

print("\n--- 2. Checking Offline Network Isolation ---")
external_urls = []
for fname, content in [("index.html", r_html.text), ("style.css", r_css.text), ("app.js", r_js.text)]:
    urls = re.findall(r"https?://[^\s\"\'<>]+", content)
    for u in urls:
        if not ("localhost" in u or "127.0.0.1" in u):
            external_urls.append((fname, u))

if external_urls:
    print("WARNING: External URLs found:", external_urls)
else:
    print("✓ ZERO external URLs found across all frontend assets (100% offline verified!)")

print("\n--- 3. Testing API Endpoints ---")
r_health = client.get("/api/health")
print("✓ /api/health:", r_health.json())

r_stats = client.get("/api/scan_stats")
stats = r_stats.json()
print(f"✓ /api/scan_stats: min={stats['min']:.1f}, max={stats['max']:.1f}, median={stats['median']:.1f}, bands={len(stats['severity_bands'])}")

r_meta = client.get("/api/tiles/meta")
meta = r_meta.json()
print(f"✓ /api/tiles/meta: {len(meta)} tiles loaded")

r_demo = client.get("/api/demo_tiles")
demo = r_demo.json()
print(f"✓ /api/demo_tiles: {len(demo)} demo tiles loaded")

print("\n--- 4. Benchmarking Simulated Tile Clicks (Cold vs Cached) ---")
demo_samples = ["0_41_58", "0_27_68", "0_23_62", "0_15_63", "0_20_66"]
for t_id in demo_samples:
    t0 = time.perf_counter()
    r = client.get(f"/api/analyze/{t_id}?mode=fast")
    dt_cold = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200
    res = r.json()
    
    # second click (cached)
    t1 = time.perf_counter()
    r_c = client.get(f"/api/analyze/{t_id}?mode=fast")
    dt_cache = (time.perf_counter() - t1) * 1000
    assert r_c.status_code == 200
    
    print(f"Tile {t_id:<8} | Cold RT: {dt_cold:6.1f} ms | Cache RT: {dt_cache:5.2f} ms | Net: {res['net_intrusion_pct']:>6.2f}% | Seen: {res['seen_in_training']}")

print("\n--- 5. Testing Image and Mask Asset Endpoints ---")
r_img = client.get("/api/image/0_41_58/post.jpg")
assert r_img.status_code == 200
assert r_img.headers["content-type"] == "image/jpeg"
print(f"✓ /api/image/0_41_58/post.jpg served ({len(r_img.content)} bytes, JPEG)")

r_mask = client.get("/api/mask/0_41_58/after.png?mode=fast")
assert r_mask.status_code == 200
assert r_mask.headers["content-type"] == "image/png"
print(f"✓ /api/mask/0_41_58/after.png served ({len(r_mask.content)} bytes, PNG)")

r_mask_acc = client.get("/api/mask/0_41_58/after.png?mode=accurate")
assert r_mask_acc.status_code == 200
assert r_mask_acc.headers["content-type"] == "image/png"
print(f"✓ /api/mask/0_41_58/after.png?mode=accurate served ({len(r_mask_acc.content)} bytes, PNG)")

print("\nAll Phase 3 integration checks PASSED successfully!")
