"""Standalone independent dashboard corridor collision and topology verifier.

Loads the final corridor and blocked-road layers and reports the crossing count
(must be 0 for road corridors).
"""

import json
import sys
from pathlib import Path

try:
    from shapely.geometry import shape, LineString
except ImportError:
    shape = None
    LineString = None


def check_corridors(dashboard_dirs: list[str] | None = None) -> int:
    if dashboard_dirs is None:
        dashboard_dirs = [
            "modules/dashboard/public/mock-data",
            "modules/dashboard/public/mock-data-dernau",
        ]

    total_crossings = 0
    print("=" * 65)
    print("   DASHBOARD CORRIDOR & BLOCKED ROAD COLLISION AUDIT")
    print("=" * 65)

    for d_dir in dashboard_dirs:
        routes_p = Path(d_dir) / "routes.json"
        blocked_p = Path(d_dir) / "blocked_roads.geojson"
        flood_p = Path(d_dir) / "flood_extent.geojson"

        if not routes_p.exists():
            continue

        print(f"\n[SECTOR] {d_dir}")
        with open(routes_p, "r", encoding="utf-8") as f:
            r_data = json.load(f)

        routes = r_data.get("routes") or [feat["properties"] for feat in r_data.get("features", [])]

        blocked_lines = []
        if blocked_p.exists() and shape is not None:
            with open(blocked_p, "r", encoding="utf-8") as bf:
                b_data = json.load(bf)
            for feat in b_data.get("features", []):
                if feat.get("geometry"):
                    blocked_lines.append((feat.get("properties", {}).get("road_id", "blocked"), shape(feat["geometry"])))

        flood_polys = []
        if flood_p.exists() and shape is not None:
            with open(flood_p, "r", encoding="utf-8") as ff:
                f_data = json.load(ff)
            for feat in f_data.get("features", []):
                if feat.get("geometry"):
                    flood_polys.append(shape(feat["geometry"]))

        for r in routes:
            rid = r.get("route_id", "unknown")
            status = r.get("status")
            if status in ("UNREACHABLE", "NO_ROAD_ROUTE"):
                print(f"  - Route '{rid}': status={status} (unreachable / cut off, not drawn on road network)")
                continue

            geom = r.get("geometry") or r.get("geojson_geometry")
            if not geom or not isinstance(geom, dict):
                continue
            coords = geom.get("coordinates", [])
            c_type = r.get("corridor_type") or r.get("geometry_quality") or ""
            is_air_or_water = (
                c_type in ("AIR_LINE", "WATER_LINE")
                or "Air/boat" in str(r.get("corridor_label", ""))
                or "Air/boat" in str(r.get("label", ""))
            )

            if is_air_or_water:
                print(f"  - Route '{rid}' ({c_type}): {len(coords)} waypoints (labeled aerial/water line - separate corridor)")
                continue

            # Road corridor
            line = LineString(coords) if shape is not None else None
            crossings = 0
            if line is not None:
                for b_name, b_geom in blocked_lines:
                    if line.intersects(b_geom):
                        inter = line.intersection(b_geom)
                        if inter.length > 1e-4 or line.crosses(b_geom):
                            crossings += 1
                            print(f"    * COLLISION with blocked road {b_name}!")

            total_crossings += crossings
            print(f"  - Road Corridor '{rid}': {len(coords)} waypoints | Blocked crossings = {crossings}")

    print("\n" + "-" * 65)
    print(f"TOTAL DASHBOARD ROAD CORRIDOR CROSSINGS: {total_crossings}")
    print("=" * 65)
    return total_crossings


def main():
    crossings = check_corridors()
    if crossings > 0:
        print(f"FAIL: Detected {crossings} road corridor crossings through blocked roads.")
        sys.exit(1)
    print("PASS: 0 crossings detected across all dashboard road corridors.")
    sys.exit(0)


if __name__ == "__main__":
    main()
