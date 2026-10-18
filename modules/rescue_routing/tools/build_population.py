# untested: needs network
"""Production builder for population_zones.json from OSM and Spanish INE census data."""

import json
from pathlib import Path


def fetch_osm_building_population_estimates(bbox: tuple[float, float, float, float]) -> dict:
    """Query OSM Overpass API for residential building footprints and estimate occupancy."""
    # Production implementation would use requests / overpy:
    # 1. Query [out:json]; (way["building"="residential"](bbox); relation["building"="residential"](bbox);); out geom;
    # 2. Compute residential floor area from polygon geometry.
    # 3. Multiply by Zaragoza municipal density factors (~35 m2 per resident).
    # 4. Aggregate within Voronoi catchment polygons around zone nodes.
    raise NotImplementedError("Network access required for live Overpass queries")


def main():
    """Build and write population_zones.json from live network queries."""
    output_path = Path("data/population_zones.json")
    print(f"Would query OpenStreetMap and INE census data for Zaragoza sector and write to {output_path}")


if __name__ == "__main__":
    main()
