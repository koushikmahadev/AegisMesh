"""Synthetic offline tests for earthquake mode."""
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from flood_analysis import eq_loader
from flood_analysis import processor as proc


def test_parse_shakemap_grid_synthetic(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<shakemap_grid xmlns="http://earthquake.usgs.gov/eqcenter/shakemap" event_id="test_eq">
  <grid_field index="1" name="LON" units="dd" />
  <grid_field index="2" name="LAT" units="dd" />
  <grid_field index="3" name="MMI" units="intensity" />
  <grid_field index="4" name="PGA" units="%g" />
  <grid_data>
    10.0 20.0 5.0 0.1
    11.0 20.0 6.0 0.2
    10.0 21.0 7.0 0.3
    11.0 21.0 8.0 0.4
  </grid_data>
</shakemap_grid>
"""
    grid_file = tmp_path / "grid.xml"
    grid_file.write_text(xml_content)

    grid = eq_loader.parse_shakemap_grid(str(grid_file))
    lon, lat, mmi = grid
    assert len(lon) == 4
    assert len(lat) == 4
    assert len(mmi) == 4
    assert np.allclose(lon, [10.0, 11.0, 10.0, 11.0])
    assert np.allclose(lat, [20.0, 20.0, 21.0, 21.0])
    assert np.allclose(mmi, [5.0, 6.0, 7.0, 8.0])


def test_sample_mmi_bilinear_interpolation():
    # 2x2 grid:
    # lat 20.0, lon 10.0 -> MMI 4.0
    # lat 20.0, lon 11.0 -> MMI 6.0
    # lat 21.0, lon 10.0 -> MMI 8.0
    # lat 21.0, lon 11.0 -> MMI 10.0
    lons = np.array([10.0, 11.0, 10.0, 11.0])
    lats = np.array([20.0, 20.0, 21.0, 21.0])
    mmi = np.array([4.0, 6.0, 8.0, 10.0])
    grid = (lons, lats, mmi)

    # Exact corners
    assert eq_loader.sample_mmi(grid, 10.0, 20.0) == pytest.approx(4.0)
    assert eq_loader.sample_mmi(grid, 11.0, 20.0) == pytest.approx(6.0)
    assert eq_loader.sample_mmi(grid, 10.0, 21.0) == pytest.approx(8.0)
    assert eq_loader.sample_mmi(grid, 11.0, 21.0) == pytest.approx(10.0)

    # Midpoints
    assert eq_loader.sample_mmi(grid, 10.5, 20.0) == pytest.approx(5.0)
    assert eq_loader.sample_mmi(grid, 10.5, 21.0) == pytest.approx(9.0)
    assert eq_loader.sample_mmi(grid, 10.0, 20.5) == pytest.approx(6.0)
    assert eq_loader.sample_mmi(grid, 11.0, 20.5) == pytest.approx(8.0)

    # Center
    assert eq_loader.sample_mmi(grid, 10.5, 20.5) == pytest.approx(7.0)

    # Vector query
    res = eq_loader.sample_mmi(grid, [10.0, 10.5], [20.0, 20.5])
    assert np.allclose(res, [4.0, 7.0])


def test_load_eq_features_threshold_and_dedup(tmp_path):
    # Setup tiny synthetic grid: MMI 6.0 at (10.0, 20.0), 9.0 at (11.0, 21.0)
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<shakemap_grid xmlns="http://earthquake.usgs.gov/eqcenter/shakemap" event_id="test_eq">
  <grid_field index="1" name="LON" units="dd" />
  <grid_field index="2" name="LAT" units="dd" />
  <grid_field index="3" name="MMI" units="intensity" />
  <grid_data>
    10.0 20.0 6.0
    11.0 20.0 7.0
    10.0 21.0 8.0
    11.0 21.0 9.0
  </grid_data>
</shakemap_grid>
"""
    (tmp_path / "grid.xml").write_text(xml_content)

    # Buildings: b1 near (10.0, 20.0) -> MMI ~6.0 (<7.0, not flooded)
    #            b2 near (11.0, 21.0) -> MMI ~9.0 (>=7.0, flooded)
    #            b3 duplicate of b1 with same feature["id"] -> should be deduplicated
    b_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "way/101",
                "properties": {"building": "yes"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.0, 20.0], [10.01, 20.0], [10.01, 20.01], [10.0, 20.01], [10.0, 20.0]]],
                },
            },
            {
                "type": "Feature",
                "id": "way/102",
                "properties": {"building": "yes"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.99, 20.99], [11.0, 20.99], [11.0, 21.0], [10.99, 21.0], [10.99, 20.99]]],
                },
            },
            {
                "type": "Feature",
                "id": "way/101",
                "properties": {"building": "yes"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.0, 20.0], [10.01, 20.0], [10.01, 20.01], [10.0, 20.01], [10.0, 20.0]]],
                },
            },
        ],
    }
    (tmp_path / "buildings.geojson").write_text(json.dumps(b_geojson))

    # Roads: r1 across (10.0, 20.0) -> max MMI ~6.0 (< 8.0, not flooded)
    #        r2 connecting (10.0, 20.0) to (11.0, 21.0) -> max MMI 9.0 (>= 8.0, flooded)
    #        r3 a closed way polygon road -> boundary should be converted to line
    r_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "way/201",
                "properties": {"highway": "residential"},
                "geometry": {"type": "LineString", "coordinates": [[10.0, 20.0], [10.05, 20.05]]},
            },
            {
                "type": "Feature",
                "id": "way/202",
                "properties": {"highway": "primary"},
                "geometry": {"type": "LineString", "coordinates": [[10.0, 20.0], [11.0, 21.0]]},
            },
            {
                "type": "Feature",
                "id": "way/203",
                "properties": {"highway": "pedestrian", "area": "yes"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.5, 20.5], [10.6, 20.5], [10.6, 20.6], [10.5, 20.6], [10.5, 20.5]]],
                },
            },
        ],
    }
    (tmp_path / "roads.geojson").write_text(json.dumps(r_geojson))

    features = eq_loader.load_eq_features(str(tmp_path), mmi_building=7.0, mmi_road=8.0)
    assert len(features) == 5  # 2 buildings (deduped from 3) + 3 roads

    b_map = {f.id: f for f in features if f.kind == "building"}
    assert len(b_map) == 2
    assert not b_map["way/101"].flooded
    assert b_map["way/101"].hazard_value < 7.0
    assert b_map["way/102"].flooded
    assert b_map["way/102"].hazard_value >= 7.0

    r_map = {f.id: f for f in features if f.kind == "road"}
    assert len(r_map) == 3
    assert not r_map["way/201"].flooded
    assert r_map["way/202"].flooded
    assert r_map["way/202"].hazard_value >= 8.0
    # Polygon road was handled via boundary LineString
    assert r_map["way/203"].geometry.geom_type in ("LineString", "MultiLineString")


def test_earthquake_zones_json_contract(tmp_path):
    aoi = box(10.0, 20.0, 10.05, 20.05)
    utm_epsg, fwd, inv = proc.to_utm_transformer(aoi)

    # 1 flooded building, 1 dry building, 1 flooded road
    b_flooded = proc.Feature(
        id="way/1", kind="building", flooded=True, geometry=Point(10.01, 20.01).buffer(0.001), hazard_value=8.5
    )
    b_dry = proc.Feature(
        id="way/2", kind="building", flooded=False, geometry=Point(10.04, 20.04).buffer(0.001), hazard_value=6.5
    )
    r_flooded = proc.Feature(
        id="way/3", kind="road", flooded=True, geometry=LineString([(10.01, 20.01), (10.02, 20.02)]), hazard_value=8.2
    )

    features = [b_flooded, b_dry, r_flooded]
    extent_utm = proc.derive_flood_extent(features, fwd)
    zones = proc.build_zones(features, aoi, fwd, inv, extent_utm)

    assert len(zones) >= 1
    z0 = zones[0]
    for required_key in ["zone_id", "flooded_percent", "exposed_buildings", "accessibility"]:
        assert required_key in z0

    assert z0["exposed_buildings"] <= z0["total_buildings"]
    assert 0.0 <= z0["flooded_percent"] <= 100.0
    assert z0["accessibility"] in ("ACCESSIBLE", "PARTIAL", "BLOCKED", "UNKNOWN")


def test_cli_run_earthquake_end_to_end_and_schema(tmp_path):
    from pathlib import Path
    import jsonschema
    from flood_analysis import cli

    input_dir = tmp_path / "eq_raw"
    input_dir.mkdir(parents=True)
    out_dir = tmp_path / "eq_out"

    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<shakemap_grid xmlns="http://earthquake.usgs.gov/eqcenter/shakemap" event_id="test_eq">
  <grid_field index="1" name="LON" units="dd" />
  <grid_field index="2" name="LAT" units="dd" />
  <grid_field index="3" name="MMI" units="intensity" />
  <grid_data>
    10.0 20.0 6.0
    11.0 20.0 7.0
    10.0 21.0 8.0
    11.0 21.0 9.0
  </grid_data>
</shakemap_grid>
"""
    (input_dir / "grid.xml").write_text(xml_content)

    b_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "way/101",
                "properties": {"building": "yes"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.0, 20.0], [10.01, 20.0], [10.01, 20.01], [10.0, 20.01], [10.0, 20.0]]],
                },
            },
            {
                "type": "Feature",
                "id": "way/102",
                "properties": {"building": "yes"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.99, 20.99], [11.0, 20.99], [11.0, 21.0], [10.99, 21.0], [10.99, 20.99]]],
                },
            },
        ],
    }
    (input_dir / "buildings.geojson").write_text(json.dumps(b_geojson))

    r_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "way/201",
                "properties": {"highway": "residential"},
                "geometry": {"type": "LineString", "coordinates": [[10.0, 20.0], [10.05, 20.05]]},
            },
            {
                "type": "Feature",
                "id": "way/202",
                "properties": {"highway": "primary"},
                "geometry": {"type": "LineString", "coordinates": [[10.0, 20.0], [11.0, 21.0]]},
            },
        ],
    }
    (input_dir / "roads.geojson").write_text(json.dumps(r_geojson))

    metadata, zones = cli.run(
        str(input_dir),
        str(out_dir),
        hazard="earthquake",
        mmi_building=7.0,
        mmi_road=8.0,
    )

    assert (out_dir / "flood_extent.geojson").exists()
    assert (out_dir / "roads_status.geojson").exists()
    assert (out_dir / "buildings_exposed.geojson").exists()
    assert (out_dir / "zones.json").exists()
    assert (out_dir / "metadata.json").exists()

    with open(out_dir / "zones.json") as f:
        zones_data = json.load(f)

    schema_path = Path(__file__).resolve().parent.parent / "contracts" / "zones.schema.json"
    with open(schema_path) as f:
        schema = json.load(f)

    jsonschema.validate(instance=zones_data, schema=schema)
    assert metadata["hazard"] == "earthquake"

