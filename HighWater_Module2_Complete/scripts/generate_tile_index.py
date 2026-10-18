"""Dump processor.build_tile_index() to JSON for client-side (map.html draw-box
mode) use — avoids any backend: the map just fetches this static file.

Run: python scripts/generate_tile_index.py --input data/raw --out output/tile_index.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from flood_analysis import processor as proc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    index = proc.build_tile_index(args.input)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(index, fh)
    print(f"Wrote {len(index)} tiles to {args.out}")


if __name__ == "__main__":
    main()
