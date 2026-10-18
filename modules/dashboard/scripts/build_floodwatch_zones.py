"""
build_floodwatch_zones.py
Deterministic generator for modules/dashboard/public/mock-data-floodwatch/zones.json

Rules (per Phase specifications):
- No risk thresholds or scores: risk_level is strictly "UNKNOWN", risk_score is null for every tile.
- List sorted by observed flooded feature count (descending).
- No invented values: omitted needs_survey, flooded_percent, flooded_area_km2, total_buildings, accessibility.
- exposed_buildings = observed flooded building count from flood_extent_groundtruth.geojson.
- reasons = only real counts: observed buildings/roads, model mask pixels per mode, and training pool status.
- Tile footprint geometry extracted from real GeoTIFF bounds (EPSG:4326 WGS84) in floodwatch/data/raw/.
- in_training_pool strictly matches FloodWatch recorded pool (false for 0_15_63, 0_15_68, 0_15_65, 0_20_66; true for others).
"""

import os
import sys
import glob
import json
from datetime import datetime, timezone

try:
    import rasterio
except ImportError:
    print("Error: rasterio is required to extract GeoTIFF bounds.", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DASHBOARD_DIR = os.path.join(REPO_ROOT, "modules", "dashboard")
MOCK_DIR = os.path.join(DASHBOARD_DIR, "public", "mock-data-floodwatch")
RAW_DIR = os.path.join(REPO_ROOT, "floodwatch", "data", "raw")

DEMO_TILES = [
    "0_41_58", "0_27_68", "0_41_59", "0_30_63", "0_27_67", "0_28_63",
    "0_23_62", "0_29_66", "0_40_62", "0_39_62", "0_15_63", "0_15_68",
    "0_15_65", "0_20_66"
]

NOT_IN_POOL = {"0_15_63", "0_15_68", "0_15_65", "0_20_66"}


def get_tile_bounds(tile_id):
    """Extract EPSG:4326 bounding box [left, bottom, right, top] from real GeoTIFF."""
    pre_matches = glob.glob(os.path.join(RAW_DIR, "PRE-event", f"*{tile_id}*.tif"))
    post_matches = glob.glob(os.path.join(RAW_DIR, "POST-event", f"*{tile_id}*.tif"))
    matches = pre_matches if pre_matches else post_matches
    if not matches:
        return None

    with rasterio.open(matches[0]) as src:
        b = src.bounds
        return {
            "left": float(b.left),
            "bottom": float(b.bottom),
            "right": float(b.right),
            "top": float(b.top),
        }


def main():
    gt_path = os.path.join(MOCK_DIR, "flood_extent_groundtruth.geojson")
    fast_path = os.path.join(MOCK_DIR, "flood_extent_predicted_fast.geojson")
    acc_path = os.path.join(MOCK_DIR, "flood_extent_predicted_accurate.geojson")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)
    with open(fast_path, "r", encoding="utf-8") as f:
        fast_data = json.load(f)
    with open(acc_path, "r", encoding="utf-8") as f:
        acc_data = json.load(f)

    zones = []

    for tile_id in DEMO_TILES:
        gt_feats = [f for f in gt_data.get("features", []) if f.get("properties", {}).get("tile_id") == tile_id]
        bldg_count = sum(1 for f in gt_feats if f.get("properties", {}).get("feature_type") == "building")
        road_count = sum(1 for f in gt_feats if f.get("properties", {}).get("feature_type") == "road")
        total_gt_count = len(gt_feats)

        fast_feats = [f for f in fast_data.get("features", []) if f.get("properties", {}).get("tile_id") == tile_id]
        fast_pixels = sum(f.get("properties", {}).get("mask_pixels", 0) for f in fast_feats)

        acc_feats = [f for f in acc_data.get("features", []) if f.get("properties", {}).get("tile_id") == tile_id]
        acc_pixels = sum(f.get("properties", {}).get("mask_pixels", 0) for f in acc_feats)

        in_training = tile_id not in NOT_IN_POOL
        pool_status_text = "In model training pool" if in_training else "Not in the training pool"

        reasons = [
            f"{bldg_count} observed flooded buildings, {road_count} observed flooded roads ({total_gt_count} total)",
            f"Model detected mask pixels: {fast_pixels} (fast mode), {acc_pixels} (accurate mode)",
            pool_status_text,
        ]

        bounds = get_tile_bounds(tile_id)
        geometry = None
        if bounds:
            left, bottom, right, top = bounds["left"], bounds["bottom"], bounds["right"], bounds["top"]
            geometry = {
                "type": "Polygon",
                "coordinates": [
                    [
                        [left, bottom],
                        [right, bottom],
                        [right, top],
                        [left, top],
                        [left, bottom],
                    ]
                ],
            }

        zone_entry = {
            "zone_id": tile_id,
            "name": f"Tile {tile_id}",
            "risk_level": "UNKNOWN",
            "risk_score": None,
            "observed_flooded_count": total_gt_count,
            "exposed_buildings": bldg_count,
            "in_training_pool": in_training,
            "reasons": reasons,
        }

        if geometry:
            zone_entry["geometry"] = geometry

        zones.append((total_gt_count, zone_entry))

    # Sort descending by observed flooded feature count
    zones.sort(key=lambda x: x[0], reverse=True)
    sorted_zones = [z[1] for z in zones]

    out_payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_mode": "demo",
        "source": "SpaceNet 8 / FloodWatch SegFormer-B0",
        "study_area": "SpaceNet 8 Germany AOI (FloodWatch)",
        "crs": "EPSG:4326",
        "zones": sorted_zones,
    }

    out_file = os.path.join(MOCK_DIR, "zones.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2)

    print(f"Successfully generated {out_file} with {len(sorted_zones)} zones.")
    for idx, z in enumerate(sorted_zones, 1):
        print(f"  {idx}. {z['zone_id']}: {z['observed_flooded_count']} flooded features, in_pool={z['in_training_pool']}")


if __name__ == "__main__":
    main()
