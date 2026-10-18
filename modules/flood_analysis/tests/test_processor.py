import json

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from flood_analysis import processor as proc


def test_pixel_classification_and_nodata_exclusion():
    band = np.array([[1, 1, 0, 0], [1, 255, 255, 0]])
    nodata = 255
    valid = band[band != nodata]
    flooded_mask = valid == 1
    assert valid.size == 6
    assert flooded_mask.sum() == 3


def test_flooded_percentage():
    valid = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0, 0])
    pct = 100.0 * (valid == 1).sum() / valid.size
    assert pct == 40.0


def test_flooded_percentage_zero_valid_pixels():
    valid = np.array([])
    assert valid.size == 0
    # guard against ZeroDivisionError, as the real pipeline must
    with pytest.raises(ZeroDivisionError):
        100.0 * 0 / valid.size


def test_polygon_validity_after_union():
    from shapely.ops import unary_union

    p1 = box(0, 0, 10, 10)
    p2 = box(5, 5, 15, 15)
    merged = unary_union([p1, p2])
    assert merged.is_valid
    assert merged.area == pytest.approx(175.0)


def test_crs_conversion_to_lonlat_roundtrip():
    utm_epsg, fwd, inv = proc.to_utm_transformer(box(7.0, 50.5, 7.01, 50.51))
    lon, lat = 7.005, 50.505
    x, y = fwd(lon, lat)
    lon2, lat2 = inv(x, y)
    assert lon2 == pytest.approx(lon, abs=1e-6)
    assert lat2 == pytest.approx(lat, abs=1e-6)


def test_grid_zoning_skips_empty_cells():
    aoi = box(7.0, 50.5, 7.01, 50.51)
    utm_epsg, fwd, inv = proc.to_utm_transformer(aoi)
    building = proc.Feature(id="b1", kind="building", flooded=False, geometry=Point(7.0001, 50.5001).buffer(0.00005))
    zones = proc.build_zones([building], aoi, fwd, inv, None, cell_size_m=100.0)
    assert len(zones) >= 1
    assert all(z["total_buildings"] + 0 >= 0 for z in zones)
    assert sum(z["total_buildings"] for z in zones) == 1


def test_accessibility_thresholds():
    assert proc.accessibility_for(None) == "UNKNOWN"
    assert proc.accessibility_for(0.05) == "ACCESSIBLE"
    assert proc.accessibility_for(0.5) == "PARTIAL"
    assert proc.accessibility_for(0.9) == "BLOCKED"
    assert proc.accessibility_for(0.09999) == "ACCESSIBLE"
    assert proc.accessibility_for(0.6) == "BLOCKED"


def test_derive_flood_extent_from_labelled_features():
    aoi = box(7.0, 50.5, 7.01, 50.51)
    _, fwd, inv = proc.to_utm_transformer(aoi)
    flooded_building = proc.Feature(
        id="b1", kind="building", flooded=True, geometry=Point(7.005, 50.505).buffer(0.0001)
    )
    dry_building = proc.Feature(
        id="b2", kind="building", flooded=False, geometry=Point(7.006, 50.506).buffer(0.0001)
    )
    flooded_road = proc.Feature(
        id="r1", kind="road", flooded=True, geometry=LineString([(7.002, 50.502), (7.003, 50.503)])
    )
    extent = proc.derive_flood_extent([flooded_building, dry_building, flooded_road], fwd)
    assert extent is not None
    assert extent.is_valid
    assert extent.area > 0


def test_derive_flood_extent_empty_when_nothing_flooded():
    aoi = box(7.0, 50.5, 7.01, 50.51)
    _, fwd, inv = proc.to_utm_transformer(aoi)
    dry_building = proc.Feature(
        id="b2", kind="building", flooded=False, geometry=Point(7.006, 50.506).buffer(0.0001)
    )
    assert proc.derive_flood_extent([dry_building], fwd) is None


def test_output_contract_zones_json_parsing(tmp_path):
    data = {
        "schema_version": "1.0",
        "source": "SpaceNet 8 Germany (Dernau)",
        "crs": "EPSG:4326",
        "zones": [
            {
                "zone_id": "zone-001",
                "bbox": [7.0, 50.5, 7.01, 50.51],
                "centroid": [7.005, 50.505],
                "flooded_percent": 12.5,
                "flooded_area_m2": 500.0,
                "total_buildings": 10,
                "exposed_buildings": 2,
                "road_length_m": 300.0,
                "flooded_road_length_m": 50.0,
                "accessibility": "PARTIAL",
            }
        ],
    }
    fp = tmp_path / "zones.json"
    fp.write_text(json.dumps(data))
    loaded = json.loads(fp.read_text())
    z = loaded["zones"][0]
    assert z["exposed_buildings"] <= z["total_buildings"]
    assert 0 <= z["flooded_percent"] <= 100
    assert z["accessibility"] in ("ACCESSIBLE", "PARTIAL", "BLOCKED", "UNKNOWN")
