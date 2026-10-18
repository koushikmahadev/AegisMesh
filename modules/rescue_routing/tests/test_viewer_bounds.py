"""Test suite for 3D viewer bounds validation and coordinate fail-loud mechanism.

Ensures the viewer rejects coordinate mismatches (lon/lat swaps, mismatched demo/region runs)
and validates single-source-of-truth invariants.
"""

import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.rescue_routing.show_3d import check_layer_bounds, build_viewer_html


def test_unit_check_layer_bounds():
    """Unit test for check_layer_bounds helper function."""
    dem_bounds_allowed = (-1.0, 38.0, 0.0, 39.0)
    dem_bounds_orig = (-0.98, 38.02, -0.02, 38.98)

    # Valid points inside
    in_pts = [(-0.5, 38.5), (-0.7, 38.2), (-0.1, 38.9)]
    res = check_layer_bounds("roads", in_pts, dem_bounds_allowed, dem_bounds_orig)
    assert res["total"] == 3
    assert res["inside"] == 3

    # Out of bounds points must exit
    out_pts = [(-0.5, 38.5), (2.5, 48.0)]
    with pytest.raises(SystemExit) as exc_info:
        check_layer_bounds("roads", out_pts, dem_bounds_allowed, dem_bounds_orig)
    assert "COORDINATE MISMATCH" in str(exc_info.value)


def test_demo_routes_on_region_dem_fails(tmp_path):
    """Fixture test: Zaragoza demo routes (approx 41.6N, -0.9W) on Orihuela region DEM (approx 38.1N, -0.75W).
    
    Must fail loudly with exit code != 0 and 'COORDINATE MISMATCH' before drawing.
    """
    demo_routes = REPO_ROOT / "routes.json"
    region_dem = REPO_ROOT / "data" / "region" / "dem.tif"

    assert demo_routes.exists(), "Demo routes.json must exist"
    assert region_dem.exists(), "Region DEM GeoTIFF must exist"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "show_3d.py"),
        "--routes", str(demo_routes),
        "--dem", str(region_dem),
        "--out", str(tmp_path / "out_viewer.html")
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode != 0, f"show_3d should fail when mixing demo routes with region DEM, got code {proc.returncode}"
    combined_output = proc.stdout + "\n" + proc.stderr
    assert "COORDINATE MISMATCH" in combined_output
    assert not (tmp_path / "out_viewer.html").exists(), "Viewer HTML must NOT be created when bounds mismatch occurs"


def test_swapped_lon_lat_fails(tmp_path):
    """Lon/lat swap test: Inverting (lon, lat) to (lat, lon) must fail loudly with COORDINATE MISMATCH."""
    region_routes = REPO_ROOT / "routes_region.json"
    region_dem = REPO_ROOT / "data" / "region" / "dem.tif"

    assert region_routes.exists(), "routes_region.json must exist"
    with open(region_routes, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Invert coordinates in network and features: [x, y] -> [y, x]
    swapped_data = copy.deepcopy(data)
    for feat in swapped_data.get("network", {}).get("features", []):
        coords = feat.get("geometry", {}).get("coordinates", [])
        feat["geometry"]["coordinates"] = [[c[1], c[0]] for c in coords]
    for feat in swapped_data.get("features", []):
        coords = feat.get("geometry", {}).get("coordinates", [])
        feat["geometry"]["coordinates"] = [[c[1], c[0]] for c in coords]

    swapped_file = tmp_path / "swapped_routes.json"
    with open(swapped_file, "w", encoding="utf-8") as f:
        json.dump(swapped_data, f)

    cmd = [
        sys.executable,
        str(REPO_ROOT / "show_3d.py"),
        "--routes", str(swapped_file),
        "--dem", str(region_dem),
        "--out", str(tmp_path / "out_swapped.html")
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode != 0, "show_3d should fail with inverted lon/lat coordinates"
    combined_output = proc.stdout + "\n" + proc.stderr
    assert "COORDINATE MISMATCH" in combined_output
    assert not (tmp_path / "out_swapped.html").exists()


def test_region_routes_on_region_dem_succeeds(tmp_path):
    """Regional routes and DEM match correctly: must succeed and produce viewer < 15MB."""
    region_routes = REPO_ROOT / "routes_region.json"
    region_dem = REPO_ROOT / "data" / "region" / "dem.tif"
    out_file = tmp_path / "routes_3d_viewer.html"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "show_3d.py"),
        "--routes", str(region_routes),
        "--dem", str(region_dem),
        "--out", str(out_file)
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"show_3d failed with valid region inputs:\n{proc.stderr}\n{proc.stdout}"
    assert out_file.exists(), "Viewer HTML must be generated"
    file_size_mb = out_file.stat().st_size / (1024 * 1024)
    assert file_size_mb < 15.0, f"Viewer HTML file size ({file_size_mb:.2f} MB) must be under 15 MB"
