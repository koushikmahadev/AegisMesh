"""Generate demo fixture for run_region.py verification."""

import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

def generate_fixture(out_dir: str = "fixture_demo") -> tuple[Path, Path, Path, Path]:
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)
    crs = CRS.from_epsg(4326)

    # 1. Mask with flooded channel
    mask = np.zeros((h, w_px), dtype=np.int8)
    mask[15:35, 30:70] = 1  # water across North Road
    mask_p = out_p / "mask.tif"
    with rasterio.open(mask_p, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.int8, crs=crs, transform=tf) as dst:
        dst.write(mask, 1)

    # 2. DEM
    dem = np.full((h, w_px), 110.0, dtype=np.float32)
    dem[15:35, 30:70] = 105.0
    dem_p = out_p / "dem.tif"
    with rasterio.open(dem_p, "w", driver="GTiff", height=h, width=w_px, count=1, dtype=np.float32, crs=crs, transform=tf) as dst:
        dst.write(dem, 1)

    # 3. Roads GeoJSON
    roads_p = out_p / "roads.geojson"
    roads_fc = {
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
                "properties": {"highway": "primary", "name": "East Connector"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-0.992, 41.008], [-0.990, 41.005], [-0.992, 41.002]],
                },
            },
        ],
    }
    with open(roads_p, "w", encoding="utf-8") as f:
        json.dump(roads_fc, f, indent=2)

    # 4. Sites JSON
    sites_p = out_p / "sites.json"
    sites = [
        {"id": "BASE_STATION", "kind": "base", "lat": 41.005, "lon": -1.000},
        {"id": "ZONE_RIVER_VILLAGE", "kind": "zone", "lat": 41.005, "lon": -0.990, "residents": 600},
    ]
    with open(sites_p, "w", encoding="utf-8") as f:
        json.dump(sites, f, indent=2)

    return mask_p, dem_p, roads_p, sites_p

if __name__ == "__main__":
    m, d, r, s = generate_fixture()
    print(f"Generated fixture in fixture_demo/:\n  mask: {m}\n  dem: {d}\n  roads: {r}\n  sites: {s}")
