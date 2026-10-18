"""CLI: python -m flood_analysis.cli --input data/raw --out output"""
import argparse
import json
import os

from flood_analysis import processor as proc

# Contiguous 6x4 block of SN8 Germany tiles (rows 36-41, cols 59-62) with a
# mix of flooded and non-flooded buildings/roads, all present in the dataset.
AOI_TILE_IDS = [
    f"0_{row}_{col}" for row in range(36, 42) for col in range(59, 63)
]


def run(input_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    features = proc.load_tile_features(input_dir, AOI_TILE_IDS)
    if not features:
        raise RuntimeError(f"No building/road features found for tiles {AOI_TILE_IDS}")

    aoi = proc.build_aoi(features)
    utm_epsg, fwd, inv = proc.to_utm_transformer(aoi)

    flood_extent_utm = proc.derive_flood_extent(features, fwd)
    zones = proc.build_zones(features, aoi, fwd, inv, flood_extent_utm)

    flood_extent_geojson = proc.flood_extent_to_geojson(flood_extent_utm, inv)
    roads_geojson = proc.features_to_geojson(features, "road", inv)
    buildings_geojson = proc.features_to_geojson(features, "building", inv)

    buildings = [f for f in features if f.kind == "building"]
    roads = [f for f in features if f.kind == "road"]
    flooded_buildings = sum(1 for f in buildings if f.flooded)
    flooded_roads = sum(1 for f in roads if f.flooded)

    with open(f"{out_dir}/flood_extent.geojson", "w") as fh:
        json.dump(flood_extent_geojson, fh)
    with open(f"{out_dir}/roads_status.geojson", "w") as fh:
        json.dump(roads_geojson, fh)
    with open(f"{out_dir}/buildings_exposed.geojson", "w") as fh:
        json.dump(buildings_geojson, fh)
    with open(f"{out_dir}/zones.json", "w") as fh:
        json.dump(
            {
                "schema_version": "1.0",
                "source": "SpaceNet 8 Germany (Dernau)",
                "crs": "EPSG:4326",
                "zones": zones,
            },
            fh,
            indent=2,
        )

    minlon, minlat, maxlon, maxlat = aoi.bounds
    metadata = {
        "dataset": "SpaceNet 8 Flood Detection Challenge, Germany training set (Dernau area, June 2021 Western Europe floods)",
        "license": "CC BY-SA 4.0 (annotations); Maxar imagery stated as CC BY-NC 4.0 in the SN8 paper — imagery itself is not redistributed here, only small derived vector outputs",
        "attribution": "SpaceNet 8 (SpaceNet on Amazon Web Services), Maxar Technologies",
        "aoi_tiles": AOI_TILE_IDS,
        "aoi_bbox_lonlat": [minlon, minlat, maxlon, maxlat],
        "input_crs": "OGC:CRS84 (lon/lat, equivalent to EPSG:4326) — annotation geojson files",
        "input_resolution": "vector annotations (no fixed raster resolution); PRE/POST tif imagery in the raw data is ~0.3-0.4m/pixel RGB, not used in this derivation",
        "output_crs": "EPSG:4326 for GeoJSON outputs; EPSG " + utm_epsg.split(":")[1] + " used internally for area/length calculations",
        "label_semantics": "Each annotation feature has 'building' or 'highway' tag (not both); 'flooded' == 'yes' means flooded, missing/None means not flooded. These are human-labelled ground truth, not model predictions.",
        "flooded_attribute_definition": "flooded = (properties.flooded == 'yes'), read directly from SN8 annotation geojson",
        "flood_extent_method": "No flood-extent raster exists in this dataset (PRE/POST tifs are plain RGB imagery). flood_extent.geojson is DERIVED from labelled flooded buildings (polygons) and labelled flooded roads (lines buffered by "
        + str(proc.ROAD_BUFFER_M)
        + "m), unioned and simplified. It is not a measured water boundary.",
        "exposed_buildings_definition": "Count of buildings in a zone with labelled flooded == 'yes' (ground truth label, not a flood-extent intersection, to avoid circularity with the derived flood extent)",
        "grid_config": {"cell_size_m": proc.GRID_CELL_SIZE_M, "crs_used_for_grid": utm_epsg},
        "accessibility_thresholds": {
            "ACCESSIBLE": f"flooded_road_length / road_length < {proc.ACCESSIBILITY_THRESHOLDS['ACCESSIBLE']}",
            "PARTIAL": f"< {proc.ACCESSIBILITY_THRESHOLDS['PARTIAL']}",
            "BLOCKED": f">= {proc.ACCESSIBILITY_THRESHOLDS['PARTIAL']}",
            "UNKNOWN": "no road data in zone",
        },
        "area_length_method": "Computed in UTM zone " + utm_epsg + " (local projected CRS), not in degrees",
        "counts": {
            "total_buildings": len(buildings),
            "flooded_buildings": flooded_buildings,
            "total_roads": len(roads),
            "flooded_roads": flooded_roads,
            "zone_count": len(zones),
        },
        "limitations": [
            "flood_extent.geojson is derived from labelled flooded buildings/roads, not a measured water boundary (no flood raster in this dataset).",
            "AOI is a fixed 6x4 tile block chosen for a mix of flooded/non-flooded features, not the full Dernau extent.",
            "Dataset covers a single flood event (June 2021); not generalizable without re-running on other AOIs.",
        ],
    }
    with open(f"{out_dir}/metadata.json", "w") as fh:
        json.dump(metadata, fh, indent=2)

    return metadata, zones


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/raw")
    parser.add_argument("--out", default="output")
    args = parser.parse_args()
    metadata, zones = run(args.input, args.out)
    print(f"Wrote {len(zones)} zones, {metadata['counts']} to {args.out}")


if __name__ == "__main__":
    main()
