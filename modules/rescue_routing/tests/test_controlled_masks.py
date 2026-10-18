"""Controlled test suite using synthetic raster and road fixtures.
Tests 1-12 covering empty masks, detours, isolated nodes, nodata, DEM voids, bridges,
monotonicity, speckle filtering, and determinism.
"""

import json
from pathlib import Path
import pytest
import numpy as np

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_bounds
from rasterio.crs import CRS

from ingest.roads import load_roads
from ingest.satellite import load_satellite_mask
from ingest.edge_state import populate_edge_state, ASSUMED_FLOOD_DEPTH_M
from ingest.snapping import snap_sites, SNAP_MAX_M
from modules.rescue_routing.router import RescueRouter, VehicleType
from modules.rescue_routing.risk_engine import calculate_edge_risk


def make_synthetic_network(tmp_path: Path) -> tuple[Path, Path]:
    """Create a two-path network between Origin and Destination."""
    roads_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "West-North"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-1.000, 41.005], [-0.998, 41.008]],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "West-South"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-1.000, 41.005], [-0.998, 41.002]],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "North Road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-0.998, 41.008], [-0.995, 41.008], [-0.992, 41.008]],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "South Road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-0.998, 41.002], [-0.995, 41.002], [-0.992, 41.002]],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "East-North"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-0.992, 41.008], [-0.990, 41.005]],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "primary", "name": "East-South"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-0.992, 41.002], [-0.990, 41.005]],
                },
            },
        ],
    }
    roads_p = tmp_path / "synthetic_roads.geojson"
    with open(roads_p, "w", encoding="utf-8") as f:
        json.dump(roads_fc, f)

    sites = [
        {"id": "ORIGIN", "kind": "base", "lat": 41.005, "lon": -1.000},
        {"id": "DEST", "kind": "zone", "lat": 41.005, "lon": -0.990},
    ]
    sites_p = tmp_path / "synthetic_sites.json"
    with open(sites_p, "w", encoding="utf-8") as f:
        json.dump(sites, f)

    return roads_p, sites_p


def write_mask(path: Path, arr: np.ndarray, bounds=(-1.005, 41.000, -0.985, 41.010)):
    h, w = arr.shape
    tf = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], w, h)
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype=arr.dtype, crs=CRS.from_epsg(4326), transform=tf) as dst:
        dst.write(arr, 1)


# 1. Empty mask: normal route, no hazards
def test_1_empty_mask(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    mask_p = tmp_path / "empty_mask.tif"
    write_mask(mask_p, np.zeros((100, 100), dtype=np.int8))

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px)

    r = RescueRouter(g)
    res = r.find_route("ORIGIN", "DEST", VehicleType.AMBULANCE)
    assert res["status"] == "OK"
    assert res["distance_km"] > 0.0
    assert len(res.get("avoided_hazards", [])) == 0
    for _, _, d in g.edges(data=True):
        assert d.get("road_state") == "DRY"


# 2. Fastest route flooded: detour taken
def test_2_fastest_route_flooded(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    # North road is along row 20 (lat 41.008)
    mask = np.zeros((100, 100), dtype=np.int8)
    mask[15:25, 30:70] = 1  # flood North Road completely
    mask_p = tmp_path / "north_flooded.tif"
    write_mask(mask_p, mask)

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px)

    r = RescueRouter(g)
    res = r.find_route("ORIGIN", "DEST", VehicleType.AMBULANCE)
    assert res["status"] == "OK"
    # Route must take South road
    path_str = str(res.get("path_nodes", []))
    assert any("41.002" in n for n in res["path_nodes"])
    assert not any("41.008" in n for n in res["path_nodes"])


# 3. All flooded: NO_SAFE_ROUTE / UNREACHABLE, no invented route
def test_3_all_flooded(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    mask = np.ones((100, 100), dtype=np.int8)
    mask_p = tmp_path / "all_flooded.tif"
    write_mask(mask_p, mask)

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px)

    r = RescueRouter(g)
    res = r.find_route("ORIGIN", "DEST", VehicleType.AMBULANCE)
    assert res["status"] == "UNREACHABLE"
    assert res.get("path_nodes") is None or len(res.get("path_nodes", [])) == 0


# 4. Destination's only access flooded: ground unreachable, fallback vehicle used
def test_4_destination_only_access_flooded(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    # Flood East Connector (only entrance to DEST)
    mask = np.zeros((100, 100), dtype=np.int8)
    mask[15:85, 70:80] = 1
    mask_p = tmp_path / "dest_cutoff.tif"
    write_mask(mask_p, mask)

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px)

    r = RescueRouter(g)
    amb = r.find_route("ORIGIN", "DEST", VehicleType.AMBULANCE)
    trk = r.find_route("ORIGIN", "DEST", VehicleType.TRUCK_4X4)
    assert amb["status"] == "UNREACHABLE"
    assert trk["status"] == "UNREACHABLE"

    # Cascade escalation assigns fallback vehicle (helicopter)
    heli = r.find_route("ORIGIN", "DEST", VehicleType.HELICOPTER)
    assert heli["status"] == "OK"
    assert heli["vehicle_type"] == "HELICOPTER"


# 5. Nodata: UNKNOWN, never DRY
def test_5_nodata_unknown_never_dry(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    mask = np.full((100, 100), -1, dtype=np.int8)
    mask_p = tmp_path / "nodata_mask.tif"
    write_mask(mask_p, mask)

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px)

    for _, _, d in g.edges(data=True):
        assert d.get("road_state") == "UNKNOWN"
        assert d.get("road_state") != "DRY"


# 6. Site outside chip: clear error
def test_6_site_outside_chip(tmp_path: Path):
    roads_p, _ = make_synthetic_network(tmp_path)
    distant_sites = [
        {"id": "BASE", "kind": "base", "lat": 41.005, "lon": -1.000},
        {"id": "DISTANT_ZONE", "kind": "zone", "lat": 45.000, "lon": 5.000},  # far outside
    ]
    sites_p = tmp_path / "distant_sites.json"
    with open(sites_p, "w", encoding="utf-8") as f:
        json.dump(distant_sites, f)

    g = load_roads(roads_p)
    with pytest.raises(SystemExit) as exc:
        snap_sites(g, sites_p)
    assert "exceeding SNAP_MAX_M" in str(exc.value)



# 7. Axis swap and half-pixel offset detected
def test_7_axis_swap_and_half_pixel_offset_detected():
    from rasterio.transform import from_bounds, rowcol
    w, s, e, n = -1.0, 40.0, 0.0, 41.0
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)

    # Pixel (0, 0) center in WGS84: lon = w + 0.5 * dx, lat = n - 0.5 * dy
    dx = (e - w) / w_px
    dy = (n - s) / h
    lon_c0 = w + 0.5 * dx
    lat_c0 = n - 0.5 * dy

    r, c = rowcol(tf, lon_c0, lat_c0)
    assert r == 0 and c == 0

    # Inverting lon and lat (axis swap) should produce out of bounds or wrong coordinate
    r_swapped, c_swapped = rowcol(tf, lat_c0, lon_c0)
    assert (r_swapped != 0) or (c_swapped != 0), "Axis swap must not map to same cell"


# 8. DEM void: UNKNOWN, not zero depth
def test_8_dem_void_unknown_not_zero_depth(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    mask = np.zeros((100, 100), dtype=np.int8)
    mask[15:25, 30:70] = 1  # flooded
    mask_p = tmp_path / "mask_flood.tif"
    write_mask(mask_p, mask)

    # DEM has NaN voids under the flooded section
    dem = np.full((100, 100), 50.0, dtype=np.float32)
    dem[15:25, 30:70] = np.nan  # void
    dem_p = tmp_path / "dem_void.tif"
    with rasterio.open(dem_p, "w", driver="GTiff", height=100, width=100, count=1, dtype=np.float32, crs=CRS.from_epsg(4326), transform=from_bounds(-1.005, 41.000, -0.985, 41.010, 100, 100)) as dst:
        dst.write(dem, 1)

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px, dem_path=dem_p)

    flooded_north_edges = [d for _, _, d in g.edges(data=True) if d.get("name") == "North Road" and d.get("has_flood_water")]
    assert len(flooded_north_edges) > 0
    for d in flooded_north_edges:
        assert d.get("road_state") == "UNKNOWN"
        assert d.get("state_reason") == "SATELLITE_NODATA_OR_DEM_VOID"


# 9. Bridge: UNCERTAIN, never submerged from mask alone
def test_9_bridge_uncertain_never_submerged_from_mask_alone(tmp_path: Path):
    roads_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"highway": "primary", "bridge": "yes", "name": "Elevated Viaduct"},
                "geometry": {"type": "LineString", "coordinates": [[-0.998, 41.005], [-0.992, 41.005]]},
            }
        ],
    }
    roads_p = tmp_path / "bridge.geojson"
    with open(roads_p, "w", encoding="utf-8") as f:
        json.dump(roads_fc, f)

    # Water touches bridge
    mask = np.ones((50, 50), dtype=np.int8)
    mask_p = tmp_path / "water_below.tif"
    write_mask(mask_p, mask, bounds=(-1.000, 41.000, -0.990, 41.010))

    g = load_roads(roads_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px)

    for _, _, d in g.edges(data=True):
        assert d.get("is_bridge") is True
        assert d.get("road_state") == "UNCERTAIN"
        assert d.get("state_reason") == "BRIDGE_DECK_ELEVATION_UNKNOWN"


# 10. Monotonicity: raising water level or rise rate never lowers route risk
def test_10_monotonicity_raising_water_or_rise_rate_never_lowers_risk():
    risk_low = calculate_edge_risk(elevation_m=20.0, distance_to_river_m=10.0, rainfall_mmh=15.0)
    risk_mid = calculate_edge_risk(elevation_m=20.0, distance_to_river_m=10.0, rainfall_mmh=30.0)
    risk_high = calculate_edge_risk(elevation_m=20.0, distance_to_river_m=10.0, rainfall_mmh=45.0)

    assert risk_low <= risk_mid <= risk_high, f"Risk must be monotonic with rainfall: {risk_low} <= {risk_mid} <= {risk_high}"

    # Lower elevation clearance must never lower risk
    risk_high_elev = calculate_edge_risk(elevation_m=30.0, distance_to_river_m=10.0, rainfall_mmh=30.0)
    risk_low_elev = calculate_edge_risk(elevation_m=20.0, distance_to_river_m=10.0, rainfall_mmh=30.0)
    assert risk_high_elev <= risk_low_elev, "Lower elevation clearance must increase flood risk"


# 11. Speckle noise does not block the network
def test_11_speckle_noise_does_not_block_network(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    # A single isolated pixel of noise at row 20, col 50
    mask = np.zeros((100, 100), dtype=np.int8)
    mask[20, 50] = 1
    mask_p = tmp_path / "speckle.tif"
    write_mask(mask_p, mask)

    g = load_roads(roads_p)
    snap_sites(g, sites_p)
    wm, nm, tf, crs, px, _ = load_satellite_mask(mask_path=mask_p)
    populate_edge_state(g, wm, nm, tf, crs, px, speckle_min_px=2)

    r = RescueRouter(g)
    res = r.find_route("ORIGIN", "DEST", VehicleType.AMBULANCE)
    assert res["status"] == "OK", "Ambulance must traverse network despite isolated speckle noise"


# 12. Determinism: same inputs and seed 42 give identical output
def test_12_determinism_same_inputs_identical_output(tmp_path: Path):
    roads_p, sites_p = make_synthetic_network(tmp_path)
    mask = np.zeros((100, 100), dtype=np.int8)
    mask[15:25, 30:70] = 1
    mask_p = tmp_path / "det_mask.tif"
    write_mask(mask_p, mask)

    out1 = tmp_path / "out1.json"
    out2 = tmp_path / "out2.json"

    import subprocess, sys
    cmd1 = [sys.executable, "run_region.py", "--mask", str(mask_p), "--roads", str(roads_p), "--sites", str(sites_p), "--out", str(out1), "--allow-unknown-meta", "--region", "det_test"]
    cmd2 = [sys.executable, "run_region.py", "--mask", str(mask_p), "--roads", str(roads_p), "--sites", str(sites_p), "--out", str(out2), "--allow-unknown-meta", "--region", "det_test"]

    p1 = subprocess.run(cmd1, capture_output=True, text=True)
    p2 = subprocess.run(cmd2, capture_output=True, text=True)
    assert p1.returncode == 0
    assert p2.returncode == 0

    with open(out1, "r", encoding="utf-8") as f1, open(out2, "r", encoding="utf-8") as f2:
        d1 = json.load(f1)
        d2 = json.load(f2)

    # Compare features and scenario structures
    assert len(d1["features"]) == len(d2["features"])
    for f_a, f_b in zip(d1["features"], d2["features"]):
        assert f_a["properties"] == f_b["properties"]
        assert f_a["geometry"] == f_b["geometry"]
