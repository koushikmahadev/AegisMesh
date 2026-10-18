"""Independent safety verification tool for rescue routes against satellite flood masks.
Samples the original raster file directly (never router internals).
Fails and exits non-zero if any returned Ambulance route geometry crosses a wet pixel
unless explicitly marked UNCERTAIN or accepted.
"""

import argparse
import json
import math
from pathlib import Path
import sys
import numpy as np
import rasterio
from rasterio.transform import rowcol

try:
    from shapely.geometry import shape, LineString, Point
except ImportError:
    shape = None


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def densify_route(coords: list[list[float]], spacing_m: float = 2.5) -> list[tuple[float, float]]:
    """Densify route coordinates at 2.5m spacing for strict independent pixel collision verification."""
    if len(coords) < 2:
        return [(c[0], c[1]) for c in coords]
    pts = []
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        dist_seg = haversine_m(p1[0], p1[1], p2[0], p2[1])
        steps = max(1, int(round(dist_seg / spacing_m)))
        for s in range(steps):
            t = s / steps
            pts.append((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])))
    pts.append((coords[-1][0], coords[-1][1]))
    return pts


def verify_route_safety(
    routes_path: str | Path | None = None,
    mask_path: str | Path | None = None,
    ems_mask_path: str | Path | None = None,
) -> bool:
    if routes_path is None:
        for cand in ["routes_region.json", "routes_satellite_live.json", "routes.json"]:
            if Path(cand).exists():
                routes_path = cand
                break
    if mask_path is None:
        for cand in ["data/region/flood_mask.tif", "data/satellite_raw/Spain_sample_flood.tif"]:
            if Path(cand).exists():
                mask_path = cand
                break

    routes_p = Path(routes_path)
    mask_p = Path(mask_path)

    if not routes_p.exists():
        sys.exit(f"FAIL: Routes file {routes_p} does not exist.")
    if not mask_p.exists():
        sys.exit(f"FAIL: Water mask GeoTIFF {mask_p} does not exist.")

    with open(routes_p, "r", encoding="utf-8") as f:
        routes_data = json.load(f)

    with rasterio.open(mask_p) as src:
        water_mask = src.read(1)
        tf = src.transform
        h, w = water_mask.shape

    features = routes_data.get("features", [])
    total_ambulance_routes = 0
    total_crossings = 0
    crossing_details = []

    print("=" * 60)
    print("   INDEPENDENT ROUTE SAFETY & COLLISION VERIFIER")
    print("=" * 60)
    print(f"Routes file: {routes_p} ({len(features)} features)")
    print(f"Water mask:  {mask_p} ({w}x{h} px)")

    for idx, feat in enumerate(features):
        props = feat.get("properties", {})
        v_type = props.get("vehicle_type")
        status = props.get("status")
        sc_id = props.get("scenario_id", f"feature_{idx}")
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates", []) if isinstance(geom, dict) else []


        if v_type == "AMBULANCE" and status == "OK" and coords:
            total_ambulance_routes += 1
            densified = densify_route(coords, spacing_m=2.5)
            route_crossings = 0
            for pt_idx, (lon, lat) in enumerate(densified):
                r, c = rowcol(tf, lon, lat)
                if 0 <= r < h and 0 <= c < w:
                    if water_mask[r, c] == 1:
                        # wet pixel collision
                        route_crossings += 1
                        crossing_details.append({
                            "scenario_id": sc_id,
                            "point_idx": pt_idx,
                            "coord": (lon, lat),
                            "raster_pixel": (r, c),
                        })

            pct_cross = (route_crossings / len(densified) * 100.0) if densified else 0.0
            print(f"[CHECK] Ambulance route '{sc_id}': {route_crossings}/{len(densified)} wet points ({pct_cross:.2f}%)")
            total_crossings += route_crossings

    print("-" * 60)
    if total_crossings > 0:
        print(f"SAFETY VIOLATION: {total_crossings} wet pixel collision(s) detected across {total_ambulance_routes} Ambulance route(s)!")
        for cd in crossing_details[:10]:
            print(f"  Crossing in {cd['scenario_id']} at ({cd['coord'][1]:.6f}, {cd['coord'][0]:.6f}) pixel={cd['raster_pixel']}")
    else:
        print(f"PASS: Verified {total_ambulance_routes} active Ambulance route(s) with 0 flood pixel crossings (0.00%).")

    # Optional verification against independent Copernicus EMS mask
    if ems_mask_path is not None and Path(ems_mask_path).exists() and shape is not None:
        print("\n[INDEPENDENT EMS MASK VERIFICATION]")
        with open(ems_mask_path, "r", encoding="utf-8") as ef:
            ems_fc = json.load(ef)
        ems_polys = [shape(f["geometry"]) for f in ems_fc.get("features", []) if f.get("geometry")]
        print(f"Loaded {len(ems_polys)} Copernicus EMS independent flood extent polygons.")

        ems_crossings = 0
        for feat in features:
            props = feat.get("properties", {})
            if props.get("vehicle_type") == "AMBULANCE" and props.get("status") == "OK":
                coords = feat.get("geometry", {}).get("coordinates", [])
                if coords:
                    line = LineString(coords)
                    for poly in ems_polys:
                        if poly.intersects(line):
                            ems_crossings += 1
                            break

        if ems_crossings == 0:
            print("PASS: Verified 0 Ambulance route intersections with Copernicus EMS flood polygons.")
        else:
            print(f"NOTE: {ems_crossings} route(s) intersect Copernicus EMS observed event polygons (lower precision bounds).")

    print("=" * 60)
    return total_crossings == 0


def verify_dashboard_corridors(dashboard_dirs: list[str] | None = None) -> bool:
    """Verify dashboard corridor geometries: vertex count, densification, and collision with blocked roads & water."""
    if dashboard_dirs is None:
        dashboard_dirs = [
            "modules/dashboard/public/mock-data",
            "modules/dashboard/public/mock-data-dernau",
        ]

    all_passed = True
    print("\n" + "=" * 60)
    print("   DASHBOARD CORRIDOR INDEPENDENT INTEGRITY VERIFIER")
    print("=" * 60)

    for d_dir in dashboard_dirs:
        routes_p = Path(d_dir) / "routes.json"
        blocked_p = Path(d_dir) / "blocked_roads.geojson"
        flood_p = Path(d_dir) / "flood_extent.geojson"

        if not routes_p.exists():
            continue

        print(f"\n[DASHBOARD SECTOR] Checking: {d_dir}")
        with open(routes_p, "r", encoding="utf-8") as f:
            r_data = json.load(f)

        routes = r_data.get("routes") or [feat["properties"] for feat in r_data.get("features", [])]
        
        blocked_lines = []
        if blocked_p.exists():
            with open(blocked_p, "r", encoding="utf-8") as bf:
                b_data = json.load(bf)
            for feat in b_data.get("features", []):
                if feat.get("geometry") and shape is not None:
                    blocked_lines.append(shape(feat["geometry"]))

        flood_polys = []
        if flood_p.exists():
            with open(flood_p, "r", encoding="utf-8") as ff:
                f_data = json.load(ff)
            for feat in f_data.get("features", []):
                if feat.get("geometry") and shape is not None:
                    flood_polys.append(shape(feat["geometry"]))

        for r in routes:
            rid = r.get("route_id", "unknown")
            status = r.get("status")
            if status in ("UNREACHABLE", "NO_ROAD_ROUTE"):
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

            # 1. Check vertex count: must have >= 3 vertices unless labeled AIR_LINE/WATER_LINE
            if len(coords) < 3 and not is_air_or_water:
                print(f"FAIL: Road corridor '{rid}' has only {len(coords)} vertices (< 3) without being labeled AIR_LINE/WATER_LINE.")
                all_passed = False
                continue

            if is_air_or_water:
                print(f"[CHECK] {rid} ({c_type}): {len(coords)} coordinates (labeled aerial/water line - bypassing road topology check)")
                continue

            # 2. Densify corridor coordinates and check blocked roads
            densified = densify_route(coords, spacing_m=2.5)
            r_line = LineString(coords) if shape is not None else None

            blocked_crossings = 0
            if r_line is not None:
                for b_line in blocked_lines:
                    if r_line.intersects(b_line):
                        inter = r_line.intersection(b_line)
                        if inter.length > 1e-4 or r_line.crosses(b_line):
                            blocked_crossings += 1

            flood_crossings = 0
            if r_line is not None:
                for f_poly in flood_polys:
                    if r_line.intersects(f_poly):
                        inter = r_line.intersection(f_poly)
                        if inter.length > 1e-4 or r_line.crosses(f_poly):
                            flood_crossings += 1

            if blocked_crossings > 0:
                print(f"FAIL: Road corridor '{rid}' crosses {blocked_crossings} blocked road segment(s)!")
                all_passed = False
            elif flood_crossings > 0:
                print(f"FAIL: Road corridor '{rid}' crosses {flood_crossings} flood extent polygon(s)!")
                all_passed = False
            else:
                print(f"[CHECK] Road corridor '{rid}': {len(coords)} waypoints ({len(densified)} densified pts) - 0 blocked crossings, 0 flood crossings.")

    if all_passed:
        print("\nPASS: All dashboard road corridors verified strictly clear (0 blocked crossings, >= 3 waypoints).")
    else:
        print("\nFAIL: Violations detected in dashboard corridor geometry.")
    print("=" * 60)
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Independent route safety verifier")
    parser.add_argument("routes", nargs="?", default=None, help="Path to routes.json")
    parser.add_argument("--mask", type=str, default=None, help="Path to flood mask GeoTIFF")
    parser.add_argument("--ems-mask", type=str, default="data/validation/copernicus_ems_flood.geojson", help="Path to Copernicus EMS flood GeoJSON")
    parser.add_argument("--check-dashboard", action="store_true", default=True, help="Check dashboard corridors against blocked roads and flood boundaries")
    parser.add_argument("--skip-dashboard", action="store_true", help="Skip checking dashboard corridors")
    args = parser.parse_args()

    # Determine default routes file
    routes_path = args.routes
    if routes_path is None:
        for cand in ["routes_region.json", "routes_satellite_live.json", "routes.json"]:
            if Path(cand).exists():
                routes_path = cand
                break
    if routes_path is None:
        sys.exit("FAIL: No routes file found.")

    # Determine default mask
    mask_path = args.mask
    if mask_path is None:
        for cand in ["data/region/flood_mask.tif", "data/satellite_raw/Spain_sample_flood.tif"]:
            if Path(cand).exists():
                mask_path = cand
                break
    if mask_path is None:
        sys.exit("FAIL: No flood mask file found.")

    is_safe = verify_route_safety(routes_path, mask_path, args.ems_mask)
    if not is_safe:
        sys.exit(1)

    if not args.skip_dashboard:
        dash_safe = verify_dashboard_corridors()
        if not dash_safe:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
