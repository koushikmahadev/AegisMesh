"""
Unit tests for GeoJSON export and validation (FloodWatch v1.1).

Verifies:
1. RFC 7946 GeoJSON validity, closed rings, bounds compliance, [-180, 180] lon, [-90, 90] lat.
2. Agreement between polygon UTM area and mask_pixels * pixel_area within stated tolerance.
3. Empty mask produces an empty FeatureCollection, not an error.
"""
from __future__ import annotations

import json
import os
import pytest
import numpy as np
import rasterio
from rasterio.warp import transform_geom
from shapely.geometry import shape, mapping

from scripts.export_geojson import (
    REPO_ROOT,
    EXPORTS_DIR,
    CRS_WGS84,
    CRS_UTM32N,
    MIN_AREA_M2,
    SIMPLIFY_TOLERANCE_METERS,
    vectorize_mask,
    export_predicted_extent,
    get_tile_transform_and_pixel_area,
)


def extract_rings(geom: dict) -> list[list[list[float]]]:
    """Extract all rings from a Polygon or MultiPolygon geometry."""
    g_type = geom.get("type")
    coords = geom.get("coordinates", [])
    rings = []
    if g_type == "Polygon":
        for ring in coords:
            rings.append(ring)
    elif g_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                rings.append(ring)
    return rings


def extract_all_points(geom: dict) -> list[list[float]]:
    """Flatten all coordinate points from any GeoJSON geometry."""
    g_type = geom.get("type")
    coords = geom.get("coordinates", [])
    points = []
    if g_type == "Point":
        points.append(coords)
    elif g_type in ("LineString", "MultiPoint"):
        points.extend(coords)
    elif g_type in ("Polygon", "MultiLineString"):
        for part in coords:
            points.extend(part)
    elif g_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                points.extend(ring)
    return points


@pytest.mark.parametrize("filename,is_predicted", [
    ("flood_extent_predicted_fast.geojson", True),
    ("flood_extent_predicted_accurate.geojson", True),
    ("flood_extent_groundtruth.geojson", False),
])
def test_geojson_validity_and_bounds(filename: str, is_predicted: bool):
    """
    Test 1:
    - Valid GeoJSON parsing and FeatureCollection structure
    - Every ring is closed (first point equals last)
    - Coordinates are within [-180, 180] longitude and [-90, 90] latitude
    - Coordinates lie strictly within source tile's bounding box
    """
    filepath = os.path.join(EXPORTS_DIR, filename)
    assert os.path.exists(filepath), f"Export file missing: {filepath}"

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("type") == "FeatureCollection"
    features = data.get("features", [])
    assert isinstance(features, list)

    bounds_cache: dict[str, tuple[float, float, float, float]] = {}

    for feat in features:
        assert feat.get("type") == "Feature"
        props = feat.get("properties", {})
        tile_id = props.get("tile_id")
        assert tile_id, "Missing tile_id property"

        if is_predicted:
            assert props.get("provenance") == "derived"
            assert props.get("source") == "FloodWatch SegFormer-B0 checkpoints_joint"
            assert props.get("model_class") == 1
            assert props.get("mask_pixels") > 0
            assert "in_training_pool" in props
            assert isinstance(props["in_training_pool"], bool)
        else:
            assert props.get("provenance") == "observed"
            assert props.get("source") == "SpaceNet 8 annotations"
            assert props.get("flooded") == "yes"
            assert props.get("feature_type") in ("building", "road")
            assert "in_training_pool" in props

        geom = feat.get("geometry", {})
        assert geom.get("type") in ("Polygon", "MultiPolygon", "LineString", "MultiLineString")

        # 1. Check all rings are closed and have >= 4 coordinates
        rings = extract_rings(geom)
        for ring in rings:
            assert len(ring) >= 4, f"Ring must have >= 4 coordinates: {len(ring)}"
            assert ring[0] == ring[-1], f"Ring is not closed: {ring[0]} != {ring[-1]}"

        # 2. Check coordinates lie in valid geographic range and tile bounds
        if tile_id not in bounds_cache:
            _, _, b = get_tile_transform_and_pixel_area(tile_id)
            bounds_cache[tile_id] = b

        b_left, b_bottom, b_right, b_top = bounds_cache[tile_id]
        margin = 1e-5  # ~1m tolerance for edge alignment

        points = extract_all_points(geom)
        for pt in points:
            lon, lat = pt[0], pt[1]
            assert -180.0 <= lon <= 180.0, f"Longitude {lon} outside [-180, 180]"
            assert -90.0 <= lat <= 90.0, f"Latitude {lat} outside [-90, 90]"
            assert b_left - margin <= lon <= b_right + margin, (
                f"Lon {lon} outside tile {tile_id} bounds [{b_left}, {b_right}]"
            )
            assert b_bottom - margin <= lat <= b_top + margin, (
                f"Lat {lat} outside tile {tile_id} bounds [{b_bottom}, {b_top}]"
            )


@pytest.mark.parametrize("filename,mode", [
    ("flood_extent_predicted_fast.geojson", "fast"),
    ("flood_extent_predicted_accurate.geojson", "accurate"),
])
def test_polygon_utm_area_vs_pixel_area(filename: str, mode: str):
    """
    Test 2:
    The polygon area (computed in UTM Zone 32N) agrees with mask_pixels x pixel area
    within a stated tolerance (6.0% per-tile upper bound with MIN_AREA_M2 = 9.0 m^2).

    Root cause of the highest-diff tiles:
    - With MIN_AREA_M2 = 9.0 m^2, tiny slivers < 9 m^2 (which had 30-60% simplification loss)
      are eliminated.
    - 0_23_62 accurate: max diff drops from 6.13% to 5.36%.
    - 0_20_66 accurate: diff drops from 5.77% to 5.30%.
    - Large contiguous flood tiles (0_41_58, 0_41_59) remain < 0.05%.

    Measured per-tile maxima:
      Fast mode max:     0_28_63 3.21%
      Accurate mode max: 0_23_62 5.36%

    Stated tolerance: <= 6.0% (tightened from 6.5% following 9 m^2 filter).
    """
    filepath = os.path.join(EXPORTS_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Group features by tile_id
    tile_features: dict[str, list[dict]] = {}
    for feat in data.get("features", []):
        tid = feat["properties"]["tile_id"]
        tile_features.setdefault(tid, []).append(feat)

    measured_differences = {}

    for tile_id, feats in tile_features.items():
        transform, px_area_utm, _ = get_tile_transform_and_pixel_area(tile_id)
        total_pixels = sum(f["properties"]["mask_pixels"] for f in feats)
        expected_utm_area = total_pixels * px_area_utm

        actual_utm_area = 0.0
        for f in feats:
            geom_4326 = f["geometry"]
            geom_utm = transform_geom(CRS_WGS84, CRS_UTM32N, geom_4326)
            s_utm = shape(geom_utm)
            actual_utm_area += s_utm.area

        diff_pct = abs(actual_utm_area - expected_utm_area) / expected_utm_area * 100.0
        measured_differences[tile_id] = {
            "pixels": total_pixels,
            "actual_utm_m2": round(actual_utm_area, 2),
            "expected_utm_m2": round(expected_utm_area, 2),
            "diff_pct": round(diff_pct, 4),
        }

        # Stated tolerance: <= 6.0% (measured max is 5.36% on 0_23_62)
        assert diff_pct <= 6.0, (
            f"Tile {tile_id} area diff {diff_pct:.2f}% exceeds tolerance 6.0% "
            f"(actual: {actual_utm_area:.1f} m2, expected: {expected_utm_area:.1f} m2)"
        )

    # Verify that area differences were measured and within expectations
    assert len(measured_differences) > 0


def test_empty_mask_produces_empty_feature_collection(tmp_path):
    """
    Test 3:
    A tile with an empty mask (or all zeros) produces an empty FeatureCollection, not an error.
    """
    # 1. Test vectorize_mask with all-zero array
    dummy_transform = rasterio.Affine(3.7e-6, 0.0, 7.0, 0.0, -3.7e-6, 50.0)
    zero_mask = np.zeros((100, 100), dtype=np.uint8)
    feat_data, kept_cnt, dropped_cnt, utm_area = vectorize_mask(
        zero_mask, dummy_transform, min_area_m2=MIN_AREA_M2, simplify_tolerance_meters=SIMPLIFY_TOLERANCE_METERS
    )
    assert feat_data == []
    assert kept_cnt == 0
    assert dropped_cnt == 0
    assert utm_area == 0.0

    # 2. Test export_predicted_extent on dry tile known to have 0 water
    out_file = os.path.join(str(tmp_path), "empty_test.geojson")
    stats = export_predicted_extent(
        tile_ids=["0_15_63"],  # Dry tile
        mode="fast",
        output_path=out_file,
        pool_map={"0_15_63": False},
    )
    assert os.path.exists(out_file)
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("type") == "FeatureCollection"
    assert data.get("features") == []
    assert stats["total_polygons"] == 0
    assert stats["total_pixels"] == 0
