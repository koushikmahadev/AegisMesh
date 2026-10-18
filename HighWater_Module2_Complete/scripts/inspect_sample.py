"""Inspect real SN8 Germany files and print CRS/schema info. Run: python scripts/inspect_sample.py"""
import csv
import glob
import json
from collections import Counter

import rasterio

RAW = "data/raw"


def inspect_raster(path):
    with rasterio.open(path) as ds:
        print(f"  {path}")
        print(f"    crs={ds.crs} bounds={ds.bounds}")
        print(f"    transform={ds.transform}")
        print(f"    res={ds.res} width={ds.width} height={ds.height}")
        print(f"    count={ds.count} dtype={ds.dtypes} nodata={ds.nodata}")
        if ds.count >= 1:
            band = ds.read(1)
            print(f"    band1 value counts (top 10): {Counter(band.flatten().tolist()).most_common(10)}")


def inspect_annotations():
    files = sorted(glob.glob(f"{RAW}/annotations/*.geojson"))
    print(f"annotation files: {len(files)}")
    d = json.load(open(files[0]))
    print(f"  sample file: {files[0]}")
    print(f"  crs: {d.get('crs')}")
    geom_types = Counter()
    flooded_vals = Counter()
    building_vals = Counter()
    highway_present = 0
    building_present = 0
    for fp in files:
        dd = json.load(open(fp))
        for f in dd["features"]:
            p = f["properties"]
            geom_types[f["geometry"]["type"]] += 1
            flooded_vals[p.get("flooded")] += 1
            if p.get("building") is not None:
                building_present += 1
                building_vals[p.get("building")] += 1
            if p.get("highway") is not None:
                highway_present += 1
    print(f"  geometry types across all tiles: {geom_types}")
    print(f"  flooded attribute values: {flooded_vals}")
    print(f"  building attribute values: {building_vals}")
    print(f"  features with building tag: {building_present}, with highway tag: {highway_present}")


def inspect_csv(path, n=3):
    with open(path) as f:
        r = csv.DictReader(f)
        rows = []
        for i, row in enumerate(r):
            if i < n:
                rows.append(row)
        print(f"  {path}")
        print(f"    header: {r.fieldnames}")
        for row in rows:
            print(f"    row: {row}")


def main():
    print("=== Rasters (PRE-event sample) ===")
    pre = sorted(glob.glob(f"{RAW}/PRE-event/*.tif"))[0]
    inspect_raster(pre)
    print("=== Rasters (POST-event sample) ===")
    post = sorted(glob.glob(f"{RAW}/POST-event/*.tif"))[0]
    inspect_raster(post)
    print("=== Annotations (vector geojson, all tiles) ===")
    inspect_annotations()
    print("=== CSVs ===")
    inspect_csv(f"{RAW}/Germany_Training_Public_label_image_mapping.csv")
    inspect_csv(f"{RAW}/Germany_Training_Public_reference.csv")


if __name__ == "__main__":
    main()
