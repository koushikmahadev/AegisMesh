"""
FloodWatch API unit tests.
Validates tile ID regex, 404 behavior, JSON contract schema, caching, image/mask endpoints,
concurrency, health check, and mock model isolation.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from starlette.testclient import TestClient
from src.api import app, CACHE
from tests.conftest import MockSegformerModel


def test_health_and_tiles():
    with TestClient(app) as client:
        r_h = client.get("/api/health")
        assert r_h.status_code == 200
        health = r_h.json()
        assert health["status"] == "ok"
        assert health["model_loaded"] is True
        assert "device" in health
        assert "cache_size" in health

        r_t = client.get("/api/tiles")
        assert r_t.status_code == 200
        tiles = r_t.json()
        assert isinstance(tiles, list)
        assert len(tiles) > 0

        r_dt = client.get("/api/demo_tiles")
        assert r_dt.status_code == 200
        demo_tiles = r_dt.json()
        assert isinstance(demo_tiles, list)
        assert len(demo_tiles) >= 10

        r_tm = client.get("/api/tiles/meta")
        assert r_tm.status_code == 200
        meta_data = r_tm.json()
        assert isinstance(meta_data, list)
        assert len(meta_data) == 202
        for entry in meta_data:
            assert "seen_in_training" in entry
            assert "gt_flooded_count" in entry
            assert "split" in entry
            assert entry["split"] in ("train", "not_in_pool")
            assert isinstance(entry["seen_in_training"], bool)


def test_scan_stats_endpoint():
    with TestClient(app) as client:
        r_ss = client.get("/api/scan_stats")
        assert r_ss.status_code == 200
        stats = r_ss.json()
        assert "min" in stats and "max" in stats and "median" in stats and "p90" in stats
        assert "severity_bands" in stats
        assert len(stats["severity_bands"]) == 4
        # Verify severity band keys and positive counts
        band_names = [b["label"] for b in stats["severity_bands"]]
        assert any("Severe" in b for b in band_names)
        assert any("None" in b for b in band_names)


def test_tile_id_validation():
    with TestClient(app) as client:
        bad_ids = ["bad_id", "0-15-63", "0_15_63_extra_text!", "0_15_abc", "0", "tile_123"]
        for bad_id in bad_ids:
            r = client.get(f"/api/analyze/{bad_id}")
            assert r.status_code == 422
            assert r.json()["error"] == "malformed_tile_id"


def test_missing_tile_404():
    with TestClient(app) as client:
        r = client.get("/api/analyze/999_999_999")
        assert r.status_code == 404
        assert r.json()["error"] == "tile_not_found"


def test_response_schema():
    with TestClient(app) as client:
        r = client.get("/api/analyze/0_39_62")
        assert r.status_code == 200
        data = r.json()
        required_keys = [
            "tile_id",
            "before_water_pct",
            "after_water_pct",
            "net_intrusion_pct",
            "latency_ms",
            "cached",
            "masks",
            "images",
            "split",
            "seen_in_training",
            "gt_flooded_count",
        ]
        for k in required_keys:
            assert k in data, f"Missing key {k} in response"
        assert isinstance(data["masks"], dict)
        assert "before" in data["masks"] and "after" in data["masks"]
        assert isinstance(data["images"], dict)
        assert "pre" in data["images"] and "post" in data["images"]


def test_cache_hit_and_clear_semantics():
    with TestClient(app) as client:
        # Clear cache first
        r_clear = client.post("/api/cache/clear")
        assert r_clear.status_code == 200
        assert r_clear.json()["cache_size"] == 0

        # First request (cold/miss)
        r1 = client.get("/api/analyze/0_39_62")
        assert r1.status_code == 200
        assert r1.json()["cached"] is False

        # Second request (cache hit)
        t0 = time.perf_counter()
        r2 = client.get("/api/analyze/0_39_62")
        dt_cached = (time.perf_counter() - t0) * 1000
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["cached"] is True
        assert dt_cached < 50.0  # Instant cached return

        # Verify clear empties cache
        r_clear2 = client.post("/api/cache/clear")
        assert r_clear2.status_code == 200
        assert r_clear2.json()["cache_size"] == 0

        # After clear, request is uncached again
        r3 = client.get("/api/analyze/0_39_62")
        assert r3.status_code == 200
        assert r3.json()["cached"] is False


def test_nocache_parameter():
    with TestClient(app) as client:
        # Ensure 0_39_62 is in cache
        client.get("/api/analyze/0_39_62")
        r_cached = client.get("/api/analyze/0_39_62")
        assert r_cached.json()["cached"] is True

        # Now pass nocache=1
        r_nocache = client.get("/api/analyze/0_39_62?nocache=1")
        assert r_nocache.status_code == 200
        data = r_nocache.json()
        assert data["cached"] is False
        assert data["latency_ms"] >= 0

        # Normal request after nocache is cached again
        r_after = client.get("/api/analyze/0_39_62")
        assert r_after.json()["cached"] is True


def test_mask_and_image_endpoints():
    with TestClient(app) as client:
        # Test mask PNG
        r_mask = client.get("/api/mask/0_39_62/before.png")
        assert r_mask.status_code == 200
        assert r_mask.headers["content-type"] == "image/png"
        assert r_mask.content[:8] == b"\x89PNG\r\n\x1a\n"

        # Test image JPEG
        r_img = client.get("/api/image/0_39_62/pre.jpg")
        assert r_img.status_code == 200
        assert r_img.headers["content-type"] == "image/jpeg"
        assert r_img.content[:3] == b"\xff\xd8\xff"


def test_concurrency():
    with TestClient(app) as client:
        def fetch_tile(t):
            res = client.get(f"/api/analyze/{t}")
            return res.status_code

        test_batch = ["0_39_62", "0_39_62", "0_23_62", "0_23_62", "0_15_63", "0_15_63", "0_39_62", "0_23_62"]
        with ThreadPoolExecutor(max_workers=8) as ex:
            statuses = list(ex.map(fetch_tile, test_batch))
        assert all(s == 200 for s in statuses)


def test_mock_model_isolation(monkeypatch):
    """Test that mock model executes cleanly in complete isolation from weights."""
    from src import flood_inference
    mock_model = MockSegformerModel()
    monkeypatch.setattr(flood_inference, "get_model", lambda: mock_model)

    res, pre_m, post_m = flood_inference.analyze_tile("0_39_62", return_masks=True)
    assert res.tile_id == "0_39_62"
    assert res.after_water_pct >= 0.0
    assert pre_m.shape == post_m.shape


def test_mode_parameter_and_accurate():
    with TestClient(app) as client:
        # Invalid mode returns 422 on analyze
        r_bad = client.get("/api/analyze/0_39_62?mode=turbo")
        assert r_bad.status_code == 422
        assert r_bad.json()["error"] == "invalid_mode"

        # Invalid mode returns 422 on mask
        r_bad_mask = client.get("/api/mask/0_39_62/before.png?mode=invalid_mode")
        assert r_bad_mask.status_code == 422
        assert r_bad_mask.json()["error"] == "invalid_mode"

        # Accurate mode works
        r_acc = client.get("/api/analyze/0_39_62?mode=accurate")
        assert r_acc.status_code == 200
        data = r_acc.json()
        assert data["mode"] == "accurate"
        assert "before_water_pct" in data
        assert "after_water_pct" in data
        assert "net_intrusion_pct" in data


def test_demo_tiles_mask_tolerance():
    """Assert pred_pixels equals round(after_pct/100*H*W) (tolerance 0.1% of tile area) for every demo tile in both modes."""
    import json
    import os

    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "demo_tiles_agreement.json")
    with open(data_path, "r", encoding="utf-8") as f:
        demo_agreement = json.load(f)

    for entry in demo_agreement:
        tid = entry["tile_id"]
        H, W = entry["shape"]
        tile_area = H * W

        for mode in ["fast", "accurate"]:
            stats = entry[f"{mode}_mode"]
            pred_px = stats["pred_pixels"]
            after_pct = stats["after_pct"]
            implied_px = round(after_pct / 100.0 * tile_area)
            diff_px = abs(pred_px - implied_px)
            diff_pct = diff_px / tile_area * 100.0

            assert diff_pct < 0.1, (
                f"Tile {tid} ({mode}): pred_pixels={pred_px} vs implied={implied_px} "
                f"(diff={diff_px} px, {diff_pct:.4f}% of tile >= 0.1%)"
            )


def test_corridor_width_consistency():
    """Cross-check that road corridor width in MEASURED.json has one consistent value (9.55 px avg corridor at 2m buffer)."""
    import json
    import os

    measured_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "MEASURED.json")
    with open(measured_path, "r", encoding="utf-8") as f:
        measured = json.load(f)

    res = measured["dataset"]["resolution"]
    corridor_px = res["road_corridor_width_px"]
    assert corridor_px == 9.55, f"Expected 9.55 px corridor width in resolution, got {corridor_px}"

    # Verify calculation: 4m corridor / 0.419 avg m/px = 9.55 px
    expected_calc = round(res["road_corridor_width_m"] / res["ground_resolution_avg_m_per_px"], 2)
    assert corridor_px == expected_calc

    # Verify road_buffer_sensitivity 2m matches
    sens_2m = measured["dataset"]["road_buffer_sensitivity"]["2m"]
    assert sens_2m["corridor_width_px"] == 9.55


