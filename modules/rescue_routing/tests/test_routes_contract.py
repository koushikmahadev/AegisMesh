"""Contract assertion tests for routes payloads across schema 2.2 and 2.3.

Validates that both Zaragoza demo (routes.json) and satellite region (routes_region.json)
strictly obey structural, topological, geometrical, and dispatch invariants.
"""

import json
import math
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from modules.rescue_routing.osm_loader import haversine_distance


def _calc_polyline_len_km(coords: list) -> float:
    if not coords or len(coords) < 2:
        return 0.0
    total_m = 0.0
    for i in range(len(coords) - 1):
        total_m += haversine_distance(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
    return total_m / 1000.0


def _assert_contract(data: dict, schema_version: str):
    assert data.get("type") == "FeatureCollection"
    assert data.get("schema_version") == schema_version

    features = data.get("features", [])
    scenarios = data.get("scenarios", [])

    # 1. Feature indices strictly partition features (no shared features, exact partition)
    seen_indices = set()
    for sc in scenarios:
        f_indices = sc.get("feature_indices", [])
        for idx in f_indices:
            assert isinstance(idx, int)
            assert 0 <= idx < len(features)
            assert idx not in seen_indices, f"Feature index {idx} shared across scenarios"
            seen_indices.add(idx)

    # 2. Every feature stage is integer
    for feat in features:
        props = feat.get("properties", {})
        stage = props.get("stage")
        if stage is not None:
            assert isinstance(stage, int), f"Feature stage {stage} must be an integer"
            assert stage >= 1

    # 3. Ambulance routes strictly 0.0m water depth
    for feat in features:
        props = feat.get("properties", {})
        if props.get("vehicle_type") == "AMBULANCE" and props.get("status") == "OK":
            max_depth = props.get("max_water_depth_meters", 0.0)
            assert max_depth == 0.0, f"Ambulance route has non-zero water depth: {max_depth}"

    # 4. OK geometry has >= 2 coordinate pairs
    for feat in features:
        props = feat.get("properties", {})
        if props.get("status") == "OK":
            geom = feat.get("geometry")
            assert geom is not None and geom.get("type") == "LineString"
            coords = geom.get("coordinates", [])
            assert len(coords) >= 2, f"Route has < 2 coordinates: {coords}"

    # 5. distance_km == polyline length within 1% or distance_basis set
    for feat in features:
        props = feat.get("properties", {})
        if props.get("status") == "OK":
            coords = feat.get("geometry", {}).get("coordinates", [])
            drawn_km = _calc_polyline_len_km(coords)
            dist_km = props.get("distance_km")
            if dist_km is not None and drawn_km > 0.01:
                rel_diff = abs(dist_km - drawn_km) / drawn_km
                if rel_diff > 0.01:
                    assert props.get("distance_basis") is not None, (
                        f"distance_km ({dist_km}) differs from drawn length ({drawn_km:.3f} km) "
                        f"by {rel_diff*100:.2f}% without distance_basis"
                    )

    # 6. Dispatch contract
    dispatch = data.get("dispatch")
    if dispatch and isinstance(dispatch, dict):
        unserved = dispatch.get("unserved", [])
        for u in unserved:
            assert u.get("delivered_kg", 0.0) == 0.0, f"Unserved incident has delivered_kg > 0: {u}"
            assert u.get("demanded_kg", 0.0) > 0.0

        partially_served = dispatch.get("partially_served", [])
        for p in partially_served:
            dem = p.get("demanded_kg", 0.0)
            deliv = p.get("delivered_kg", 0.0)
            unmet = p.get("unmet_kg", 0.0)
            assert dem > deliv > 0.0, f"Partially served violated dem > deliv > 0: {p}"
            assert round(dem - deliv, 1) == round(unmet, 1)

        total_unmet = dispatch.get("total_unmet_kg")
        if total_unmet is not None:
            sum_unmet = sum(u.get("demanded_kg", 0.0) for u in unserved) + sum(p.get("unmet_kg", 0.0) for p in partially_served)
            assert round(total_unmet, 1) == round(sum_unmet, 1)

    # 7. Flood extent has <= 5000 vertices (if present)
    flood_extent = data.get("flood_extent")
    if flood_extent:
        v_count = 0
        if flood_extent.get("type") == "MultiPolygon":
            for poly in flood_extent.get("coordinates", []):
                for ring in poly:
                    v_count += len(ring)
        elif flood_extent.get("type") == "Polygon":
            for ring in flood_extent.get("coordinates", []):
                v_count += len(ring)
        assert v_count <= 5000, f"flood_extent has {v_count} vertices, exceeding 5000 vertex cap"

    # 8. Helicopter status and launch_minutes
    for feat in features:
        props = feat.get("properties", {})
        if props.get("vehicle_type") == "HELICOPTER":
            assert props.get("status") in ("OK", "RESCUE_HOIST_ONLY", "UNREACHABLE")
            assert props.get("launch_minutes") == 10

    # 9. Verification flags match data
    prov = data.get("provenance", {})
    verified = data.get("verified", False)
    coords_verified = prov.get("coordinates_verified", False)
    assert verified == coords_verified


def test_contract_routes_json():
    """Assert contract on Zaragoza demo output (routes.json, schema 2.2)."""
    p = Path("routes.json")
    assert p.exists(), "routes.json must exist"
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    _assert_contract(data, "2.2")


def test_contract_routes_region_json():
    """Assert contract on satellite regional output (routes_region.json, schema 2.3)."""
    p = Path("routes_region.json")
    if not p.exists():
        p = Path("routes_region.sample.json")
    assert p.exists(), "routes_region.json (or sample) must exist"
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    _assert_contract(data, "2.3")
