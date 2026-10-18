"""Deterministic sample region generator for testing and demonstration.

Generates:
1. data/sample_region/mask.tif (GeoTIFF water mask)
2. data/sample_region/roads.geojson (Road network with connectors)
3. data/sample_region/sites.json (Sites with base, zone, ramp)
4. routes_region.sample.json (via run_region.py)
5. routes.sample.json (via run_demo.py)
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS


def make_sample_dataset(out_dir: str | Path = "data/sample_region") -> tuple[Path, Path, Path]:
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    # 1. roads.geojson
    roads_p = out_p / "roads.geojson"
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
            {
                "type": "Feature",
                "properties": {"highway": "secondary", "name": "Ramp Access Road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-0.995, 41.002], [-0.995, 41.005]],
                },
            },
        ],
    }
    with open(roads_p, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    # 2. sites.json
    sites_p = out_p / "sites.json"
    sites = [
        {"id": "SAMPLE_BASE", "kind": "base", "lat": 41.005, "lon": -1.000},
        {"id": "SAMPLE_ZONE", "kind": "zone", "lat": 41.005, "lon": -0.990, "residents": 450},
        {"id": "SAMPLE_RAMP", "kind": "ramp", "lat": 41.005, "lon": -0.995},
    ]
    with open(sites_p, "w", encoding="utf-8") as f:
        json.dump(sites, f, indent=2)

    # 3. mask.tif
    mask_p = out_p / "mask.tif"
    w, s, e, n = -1.002, 41.000, -0.988, 41.010
    h, w_px = 100, 100
    tf = from_bounds(w, s, e, n, w_px, h)
    crs = CRS.from_epsg(4326)

    # Flood band across North road: row 10 to 30, cols 30 to 70
    mask = np.zeros((h, w_px), dtype=np.int8)
    mask[10:30, 30:70] = 1

    with rasterio.open(
        mask_p,
        "w",
        driver="GTiff",
        height=h,
        width=w_px,
        count=1,
        dtype=np.int8,
        crs=crs,
        transform=tf,
    ) as dst:
        dst.write(mask, 1)

    print(f"Generated sample dataset in {out_p}:")
    print(f"  - {roads_p}")
    print(f"  - {sites_p}")
    print(f"  - {mask_p}")

    return mask_p, roads_p, sites_p


def main():
    mask_p, roads_p, sites_p = make_sample_dataset()

    # Generate routes_region.sample.json
    region_sample_out = Path("routes_region.sample.json")
    print(f"\nRunning run_region.py -> {region_sample_out}...")
    cmd_region = [
        sys.executable,
        "run_region.py",
        "--image", str(mask_p),
        "--roads", str(roads_p),
        "--sites", str(sites_p),
        "--region", "sample_region",
        "--out", str(region_sample_out),
    ]
    subprocess.run(cmd_region, check=True)

    # Generate routes.sample.json
    demo_sample_out = Path("routes.sample.json")
    print(f"\nRunning run_demo.py --no-pause...")
    cmd_demo = [
        sys.executable,
        "run_demo.py",
        "--no-pause",
    ]
    subprocess.run(cmd_demo, check=True)
    if Path("routes.json").exists():
        shutil.copy("routes.json", demo_sample_out)
        print(f"Saved {demo_sample_out}")

    print("\nSUCCESS: make_sample_region completed successfully.")


if __name__ == "__main__":
    main()
