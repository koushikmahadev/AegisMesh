"""Tests for satellite-driven region routing pipeline."""

import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_bounds
from rasterio.crs import CRS
import jsonschema

from ingest.roads import load_roads
from ingest.satellite import load_satellite_mask, compute_otsu_threshold
from ingest.edge_state import populate_edge_state, MIN_FLOOD_RUN_M, ASSUMED_FLOOD_DEPTH_M
from ingest.snapping import snap_sites, SNAP_MAX_M
from modules.rescue_routing.router import RescueRouter, VehicleType


def create_synthetic_road_geojson(path: Path) -> None:
    """Create a GeoJSON with parallel north and south roads connecting Base and Zone."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "West Connector"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-1.000, 41.005], [-0.998, 41.008], [-0.998, 41.002]],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "North Road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-0.998, 41.008],
                        [-0.995, 41.008],
                        [-0.992, 41.008],
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "South Road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-0.998, 41.002],
                        [-0.995, 41.002],
                        [-0.992, 41.002],
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "East Connector"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-0.992, 41.008], [-0.990, 41.005], [-0.992, 41.002]],
                },
            },
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)


def create_sites_json(path: Path) -> None:
    """Create sites JSON with a base, zone with residents, and a distant site."""
    sites = [
        {"id": "BASE_HOSPITAL", "kind": "base", "lat": 41.005, "lon": -1.000},
        {"id": "ZONE_COMMUNITY", "kind": "zone", "lat": 41.005, "lon": -0.990, "residents": 500},
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sites, f, indent=2)


def test_parallel_roads_avoidance_and_boat_pass(tmp_path: Path):
    """100x100 synthetic mask: router picks dry parallel road; when both flooded, boat passes."""
    roads_p = tmp_path / "roads.geojson"
    create_synthetic_road_geojson(roads_p)
    sites_p = tmp_path / "sites.json"
    create_sites_json(sites_p)

    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)
    crs = CRS.from_epsg(4326)

    # 1. Flood band only across North road (lat ~ 41.008 is in top ~20% of rows: rows 10 to 30)
    mask1 = np.zeros((h, w_px), dtype=np.int8)
    mask1[10:30, 30:70] = 1  # water across North Road

    mask_p1 = tmp_path / "mask_north.tif"
    with rasterio.open(mask_p1, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.int8, crs=crs, transform=tf) as dst:
        dst.write(mask1, 1)

    g1 = load_roads(roads_p)
    snap_sites(g1, sites_p)
    water_m1, nodata_m1, transform1, crs1, px_m1, _ = load_satellite_mask(mask_path=mask_p1)
    populate_edge_state(g1, water_m1, nodata_m1, transform1, crs1, px_m1)

    r1 = RescueRouter(g1)
    amb_route = r1.find_route("BASE_HOSPITAL", "ZONE_COMMUNITY", VehicleType.AMBULANCE)
    assert amb_route["status"] == "OK"
    # Router must pick the South Road to bypass the flooded North Road
    south_nodes = [node for node in amb_route["path_nodes"] if "41.002" in node]
    assert len(south_nodes) > 0, "Ambulance should route through South Road"

    # 2. Flood band across BOTH roads (North and South corridors submerged)
    mask2 = np.ones((h, w_px), dtype=np.int8)

    mask_p2 = tmp_path / "mask_both.tif"
    with rasterio.open(mask_p2, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.int8, crs=crs, transform=tf) as dst:
        dst.write(mask2, 1)

    g2 = load_roads(roads_p)
    snap_sites(g2, sites_p)
    water_m2, nodata_m2, transform2, crs2, px_m2, _ = load_satellite_mask(mask_path=mask_p2)
    populate_edge_state(g2, water_m2, nodata_m2, transform2, crs2, px_m2)

    r2 = RescueRouter(g2)
    amb_both = r2.find_route("BASE_HOSPITAL", "ZONE_COMMUNITY", VehicleType.AMBULANCE)
    trk_both = r2.find_route("BASE_HOSPITAL", "ZONE_COMMUNITY", VehicleType.TRUCK_4X4)
    boat_both = r2.find_route("BASE_HOSPITAL", "ZONE_COMMUNITY", VehicleType.RESCUE_BOAT)

    assert amb_both["status"] == "UNREACHABLE", "Ambulance cannot cross flooded roads"
    assert trk_both["status"] == "UNREACHABLE", "Truck cannot cross roads with 0.6m depth"
    assert boat_both["status"] == "OK", "Rescue boat passes on water depth >= 0.5m"


def test_dem_fwdet_vs_no_dem_depth(tmp_path: Path):
    """DEM case: depth equals water surface minus ground; no-DEM case uses 0.6m."""
    roads_p = tmp_path / "roads.geojson"
    create_synthetic_road_geojson(roads_p)
    sites_p = tmp_path / "sites.json"
    create_sites_json(sites_p)

    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)
    crs = CRS.from_epsg(4326)

    # water mask on valley: row 10 to 30
    mask = np.zeros((h, w_px), dtype=np.int8)
    mask[10:30, 30:70] = 1

    mask_p = tmp_path / "mask.tif"
    with rasterio.open(mask_p, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.int8, crs=crs, transform=tf) as dst:
        dst.write(mask, 1)

    # 1. No DEM case -> depth should be ASSUMED_FLOOD_DEPTH_M (0.6m)
    g_no_dem = load_roads(roads_p)
    snap_sites(g_no_dem, sites_p)
    wm, nm, tf_m, crs_m, px_m, _ = load_satellite_mask(mask_path=mask_p)
    dep_meth, risk_m = populate_edge_state(g_no_dem, wm, nm, tf_m, crs_m, px_m, dem_path=None)

    assert dep_meth == "satellite_mask_assumed"
    assert risk_m == "heuristic_uncalibrated_no_dem"
    north_edge_no_dem = None
    for u, v, d in g_no_dem.edges(data=True):
        if d.get("name") == "North Road":
            north_edge_no_dem = d
            break
    assert north_edge_no_dem is not None
    assert north_edge_no_dem["current_water_depth_meters"] == ASSUMED_FLOOD_DEPTH_M
    assert north_edge_no_dem["elevation_meters"] is None

    # 2. With DEM: valley floor is 100.0m, shoreline boundary is 104.0m
    dem = np.full((h, w_px), 104.0, dtype=np.float32)
    dem[12:28, 32:68] = 100.0  # deep center: depth should be roughly 104.0 - 100.0 = 4.0m

    dem_p = tmp_path / "dem.tif"
    with rasterio.open(dem_p, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.float32, crs=crs, transform=tf) as dst:
        dst.write(dem, 1)

    g_dem = load_roads(roads_p)
    snap_sites(g_dem, sites_p)
    dep_meth_dem, risk_m_dem = populate_edge_state(g_dem, wm, nm, tf_m, crs_m, px_m, dem_path=dem_p)

    assert dep_meth_dem == "satellite_mask_dem"
    assert risk_m_dem == "heuristic_uncalibrated"
    north_edge_dem = None
    for u, v, d in g_dem.edges(data=True):
        if d.get("name") == "North Road":
            north_edge_dem = d
            break
    assert north_edge_dem is not None
    # depth should be roughly 4.0m (within 10%)
    assert 3.5 <= north_edge_dem["current_water_depth_meters"] <= 4.5
    assert north_edge_dem["elevation_meters"] == 100.0


def test_short_flood_run_ignored_and_nodata_gap(tmp_path: Path):
    """Flooded run under 20m is ignored as speckle; nodata > 50% gives GAP coverage."""
    roads_p = tmp_path / "roads.geojson"
    create_synthetic_road_geojson(roads_p)
    sites_p = tmp_path / "sites.json"
    create_sites_json(sites_p)

    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)
    crs = CRS.from_epsg(4326)

    # 1 pixel of water across North road (approx 11 meters < MIN_FLOOD_RUN_M 20m)
    # North road is along row 20 (lat 41.008), col 50
    mask = np.zeros((h, w_px), dtype=np.int8)
    mask[20, 50] = 1

    # Nodata on South road: row 80 (lat 41.002), cols 30 to 70
    mask[75:85, 30:70] = -1

    mask_p = tmp_path / "speckle_nodata.tif"
    with rasterio.open(mask_p, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.int8, crs=crs, transform=tf) as dst:
        dst.write(mask, 1)

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf_m, crs_m, px_m, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf_m, crs_m, px_m)

    north_edge = None
    south_edge = None
    for u, v, d in g.edges(data=True):
        if d.get("name") == "North Road":
            north_edge = d
        elif d.get("name") == "South Road":
            south_edge = d

    # North road had 1 pixel = ~11m run, should be ignored
    assert north_edge["current_water_depth_meters"] == 0.0
    assert north_edge["satellite_coverage"] == "OK"

    # South road has > 50% nodata
    assert south_edge["satellite_coverage"] == "GAP"


def test_crs_invariance_wgs84_vs_utm(tmp_path: Path):
    """The same mask in EPSG:4326 and EPSG:32630 yields identical routing."""
    from rasterio.warp import calculate_default_transform, reproject, Resampling

    roads_p = tmp_path / "roads.geojson"
    create_synthetic_road_geojson(roads_p)
    sites_p = tmp_path / "sites.json"
    create_sites_json(sites_p)

    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf_4326 = from_bounds(w, s, e, n, w_px, h)
    crs_4326 = CRS.from_epsg(4326)

    # Flood North road
    mask_4326 = np.zeros((h, w_px), dtype=np.int8)
    mask_4326[10:30, 30:70] = 1

    mask_p_4326 = tmp_path / "mask_4326.tif"
    with rasterio.open(mask_p_4326, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.int8, crs=crs_4326, transform=tf_4326) as dst:
        dst.write(mask_4326, 1)

    # Reproject to EPSG:32630 (UTM 30N)
    crs_32630 = CRS.from_epsg(32630)
    tf_32630, width_30, height_30 = calculate_default_transform(crs_4326, crs_32630, w_px, h, left=w, bottom=s, right=e, top=n)
    mask_32630 = np.zeros((height_30, width_30), dtype=np.int8)

    reproject(
        source=mask_4326,
        destination=mask_32630,
        src_transform=tf_4326,
        src_crs=crs_4326,
        dst_transform=tf_32630,
        dst_crs=crs_32630,
        resampling=Resampling.nearest,
    )

    mask_p_32630 = tmp_path / "mask_32630.tif"
    with rasterio.open(mask_p_32630, "w", driver="GTiff", height=height_30, width=width_30, count=1, dtype=np.int8, crs=crs_32630, transform=tf_32630) as dst:
        dst.write(mask_32630, 1)

    # Run routing on EPSG:4326
    g_4326 = load_roads(roads_p)
    snap_sites(g_4326, sites_p)
    wm1, nm1, tf1, crs1, px1, _ = load_satellite_mask(mask_path=mask_p_4326)
    populate_edge_state(g_4326, wm1, nm1, tf1, crs1, px1)
    route_4326 = RescueRouter(g_4326).find_route("BASE_HOSPITAL", "ZONE_COMMUNITY", VehicleType.AMBULANCE)

    # Run routing on EPSG:32630
    g_32630 = load_roads(roads_p)
    snap_sites(g_32630, sites_p)
    wm2, nm2, tf2, crs2, px2, _ = load_satellite_mask(mask_path=mask_p_32630)
    populate_edge_state(g_32630, wm2, nm2, tf2, crs2, px2)
    route_32630 = RescueRouter(g_32630).find_route("BASE_HOSPITAL", "ZONE_COMMUNITY", VehicleType.AMBULANCE)

    assert route_4326["status"] == route_32630["status"] == "OK"
    assert route_4326["path_nodes"] == route_32630["path_nodes"]


def test_png_bounds_and_sar_otsu(tmp_path: Path):
    """PNG + bounds produces same mask as GeoTIFF; SAR backscatter triggers Otsu threshold."""
    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)
    crs = CRS.from_epsg(4326)

    # 1. Test PNG + bounds
    mask_data = np.zeros((h, w_px), dtype=np.uint8)
    mask_data[10:30, 30:70] = 1

    png_p = tmp_path / "mask.png"
    with rasterio.open(png_p, "w", driver="PNG", height=h, width=w_px, count=1, dtype=np.uint8) as dst:
        dst.write(mask_data, 1)

    wm_png, nm_png, tf_png, crs_png, px_png, src_png = load_satellite_mask(mask_path=png_p, bounds=[w, s, e, n])
    assert wm_png.sum() == (mask_data == 1).sum()
    assert src_png == "mask"

    # 2. Test SAR Otsu
    sar_data = np.full((h, w_px), -10.0, dtype=np.float32)  # land at -10 dB
    sar_data[10:30, 30:70] = -22.0  # water at -22 dB (dark backscatter)

    sar_p = tmp_path / "sar.tif"
    with rasterio.open(sar_p, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.float32, crs=crs, transform=tf) as dst:
        dst.write(sar_data, 1)

    wm_sar, nm_sar, tf_sar, crs_sar, px_sar, src_sar = load_satellite_mask(sar_path=sar_p)
    assert src_sar == "sar_otsu"
    # Otsu threshold should correctly classify the -22 dB region as water
    water_detected_pct = wm_sar[10:30, 30:70].mean()
    land_detected_pct = wm_sar[~((np.arange(h)[:, None] >= 10) & (np.arange(h)[:, None] < 30) & (np.arange(w_px)[None, :] >= 30) & (np.arange(w_px)[None, :] < 70))].mean()
    assert water_detected_pct == 1.0, "SAR Otsu must identify water band"
    assert land_detected_pct == 0.0, "SAR Otsu must not mark land as water"


def test_site_snap_failure_message(tmp_path: Path):
    """Site distant (> 500m) from road network exits with clear error message."""
    roads_p = tmp_path / "roads.geojson"
    create_synthetic_road_geojson(roads_p)

    # Site far away at lon 0.0, lat 0.0 (thousands of km away)
    far_site = [{"id": "ISOLATED_BASE", "kind": "base", "lat": 0.0, "lon": 0.0}]
    sites_p = tmp_path / "far_site.json"
    with open(sites_p, "w", encoding="utf-8") as f:
        json.dump(far_site, f)

    g = load_roads(roads_p)
    with pytest.raises(SystemExit) as excinfo:
        snap_sites(g, sites_p)

    err_msg = str(excinfo.value)
    assert "ISOLATED_BASE" in err_msg
    assert "exceeding SNAP_MAX_M" in err_msg


def test_regional_routes_valid_schema_and_zaragoza_regression(tmp_path: Path):
    """Regional routes.json passes schema validation; Zaragoza demo output is unchanged."""
    roads_p = tmp_path / "roads.geojson"
    create_synthetic_road_geojson(roads_p)
    sites_p = tmp_path / "sites.json"
    create_sites_json(sites_p)

    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)
    crs = CRS.from_epsg(4326)

    mask = np.zeros((h, w_px), dtype=np.int8)
    mask[10:30, 30:70] = 1
    mask_p = tmp_path / "mask.tif"
    with rasterio.open(mask_p, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.int8, crs=crs, transform=tf) as dst:
        dst.write(mask, 1)

    out_p = tmp_path / "routes_region.json"

    # Run run_region.py CLI
    cmd = [
        sys.executable,
        "run_region.py",
        "--mask", str(mask_p),
        "--roads", str(roads_p),
        "--sites", str(sites_p),
        "--acquired", "2026-10-14T10:00:00",
        "--as-of", "2026-10-14T11:00:00",
        "--out", str(out_p),
        "--region", "synthetic_test_basin",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"run_region.py failed:\n{proc.stderr}\n{proc.stdout}"

    # Load output and validate with schema.json
    with open(out_p, "r", encoding="utf-8") as f:
        region_data = json.load(f)
    with open("schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)

    jsonschema.validate(instance=region_data, schema=schema)
    assert region_data["schema_version"] == "2.3"
    assert "flood_extent" in region_data
    assert region_data["flood_extent"]["type"] == "MultiPolygon"
    assert region_data["provenance"]["region"] == "synthetic_test_basin"

    # Coordinates inside mask bounds
    for feat in region_data["features"]:
        geom = feat.get("geometry")
        if geom and geom.get("coordinates"):
            for coord in geom["coordinates"]:
                lon, lat = coord[0], coord[1]
                assert w - 0.01 <= lon <= e + 0.01
                assert s - 0.01 <= lat <= n + 0.01

    # Verify Zaragoza demo output is unchanged
    with open("contract/routes_v2_1_1.json", "r", encoding="utf-8") as f:
        contract_data = json.load(f)
    with open("routes.json", "r", encoding="utf-8") as f:
        zaragoza_data = json.load(f)

    # Baseline features 0-8 match contract, remaining 5 match scenario 5
    assert len(zaragoza_data["features"]) == 14
    for idx in range(9):
        assert zaragoza_data["features"][idx]["properties"]["scenario_id"] == contract_data["features"][idx]["properties"]["scenario_id"]
    for idx in range(9, 14):
        assert zaragoza_data["features"][idx]["properties"]["scenario_id"] == "scenario_5_full_cascade"
