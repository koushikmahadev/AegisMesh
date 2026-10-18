"""Alignment verification tool for satellite-driven rescue routing pipeline.

Checks:
1. Water depth alignment: edges with current_water_depth_meters > 0 vs water mask pixels under sampled points.
2. Flood extent vertex cap: total vertices in un-decimated mask polygons vs kept vertices in routes payload + retained area ratio.
3. Spatial bounds alignment: mask bounds vs road network bounding box.
4. Baseline vs Predictive route comparison: path_nodes identity, titles, and advisories.
5. 2D visualization export: georeferenced PNG showing mask, submerged edges, and vehicle routes.
"""

import argparse
import json
import math
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import rasterio
import rasterio.features
from scipy.ndimage import binary_dilation

from ingest.edge_state import _sample_polyline


def check_alignment(
    routes_path: str | Path,
    mask_path: str | Path | None = None,
    png_out_path: str | Path = "data/alignment_check.png",
) -> dict:
    """Run comprehensive alignment and consistency checks."""
    routes_p = Path(routes_path)
    if not routes_p.exists():
        sys.exit(f"FAIL: Routes file not found: {routes_p}")

    with open(routes_p, "r", encoding="utf-8") as f:
        routes_data = json.load(f)

    if mask_path is None:
        cand_masks = [
            Path("data/satellite_raw/Spain_sample_flood.tif"),
            Path("data/sample_region/mask.tif"),
        ]
        mask_p = next((p for p in cand_masks if p.exists()), None)
        if mask_p is None:
            sys.exit("FAIL: No satellite mask found and none provided as argument.")
    else:
        mask_p = Path(mask_path)
        if not mask_p.exists():
            sys.exit(f"FAIL: Mask file not found: {mask_p}")

    print("==================================================")
    print("   REGIONAL SATELLITE ROUTING ALIGNMENT CHECK     ")
    print("==================================================")
    print(f"Routes File: {routes_p}")
    print(f"Mask File:   {mask_p}\n")

    with rasterio.open(mask_p) as src:
        water_mask = src.read(1)
        transform = src.transform
        crs = src.crs
        mask_bounds = src.bounds
        h, w = water_mask.shape

    inv_tf = ~transform

    # ----------------------------------------------------
    # (a) Water Depth Alignment Check
    # ----------------------------------------------------
    network_features = routes_data.get("network", {}).get("features", [])
    if not network_features:
        network_features = [
            f for f in routes_data.get("features", [])
            if f.get("properties", {}).get("layer") == "network"
        ]
    total_edges = len(network_features)
    submerged_edges = []
    dry_edges = []

    for feat in network_features:
        props = feat.get("properties", {})
        depth = props.get("current_water_depth_meters", props.get("depth", 0.0))
        if depth > 0.0 or props.get("has_flood_water", False):
            submerged_edges.append(feat)
        else:
            dry_edges.append(feat)

    num_submerged = len(submerged_edges)
    zero_pixel_submerged = 0

    for feat in submerged_edges:
        coords = feat.get("geometry", {}).get("coordinates", [])
        if not coords:
            continue
        lons, lats, step = _sample_polyline(coords)
        cols = np.floor(inv_tf.a * lons + inv_tf.b * lats + inv_tf.c).astype(int)
        rows = np.floor(inv_tf.d * lons + inv_tf.e * lats + inv_tf.f).astype(int)

        valid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        r_valid = rows[valid]
        c_valid = cols[valid]

        water_px_count = int(np.sum(water_mask[r_valid, c_valid] == 1)) if len(r_valid) > 0 else 0
        if water_px_count == 0:
            zero_pixel_submerged += 1

    print("[CHECK A] Edge Water Depth vs Satellite Mask Sampling:")
    print(f"  - Total network edges: {total_edges}")
    print(f"  - Edges with current_water_depth_meters > 0: {num_submerged}")
    print(f"  - Submerged edges with 0 water-mask pixels under sampled points: {zero_pixel_submerged} (expected: ~0)")
    if zero_pixel_submerged == 0:
        print("  -> PASS: 100% of submerged edges intersect observed satellite water pixels.\n")
    else:
        print(f"  -> WARNING: {zero_pixel_submerged} submerged edge(s) lack direct water pixel intersection.\n")

    # ----------------------------------------------------
    # (b) Flood Extent Vertex Cap Check & Retained Area Ratio
    # ----------------------------------------------------
    shapes_gen = rasterio.features.shapes(
        water_mask.astype(np.uint8),
        mask=(water_mask == 1),
        transform=transform,
    )
    total_mask_vertices = 0
    for geom, val in shapes_gen:
        if val == 1:
            for ring in geom.get("coordinates", []):
                total_mask_vertices += len(ring)

    flood_extent = routes_data.get("flood_extent", {})
    fe_coords = flood_extent.get("coordinates", [])
    kept_vertices = 0
    if flood_extent.get("type") == "MultiPolygon":
        for poly in fe_coords:
            for ring in poly:
                kept_vertices += len(ring)
    elif flood_extent.get("type") == "Polygon":
        for ring in fe_coords:
            kept_vertices += len(ring)

    prov = routes_data.get("provenance", {})
    area_ratio = prov.get("flood_extent_retained_area_ratio", 1.0)
    is_truncated = bool(total_mask_vertices > 5000 or kept_vertices < total_mask_vertices)

    print("[CHECK B] Flood Extent Decimation & Retained Area Ratio:")
    print(f"  - Total un-decimated polygon vertices in mask: {total_mask_vertices}")
    print(f"  - Kept vertices in routes.json flood_extent:   {kept_vertices}")
    print(f"  - Retained area ratio after simplification:    {area_ratio:.4f} (target: >= 0.98)")
    print(f"  - Decimated by vertex cap:                     {is_truncated}")
    if is_truncated:
        reduction_pct = (1.0 - kept_vertices / max(total_mask_vertices, 1)) * 100.0
        print(f"  -> Cap triggered: payload geometry reduced by {reduction_pct:.1f}% to prevent frontend payload bloat.\n")
    else:
        print("  -> Under vertex cap: full geometry preserved without decimation.\n")

    # ----------------------------------------------------
    # (c) Spatial Bounds Alignment Check
    # ----------------------------------------------------
    road_lons, road_lats = [], []
    for feat in network_features:
        for c in feat.get("geometry", {}).get("coordinates", []):
            road_lons.append(c[0])
            road_lats.append(c[1])

    if road_lons and road_lats:
        road_bounds = (min(road_lons), min(road_lats), max(road_lons), max(road_lats))
    else:
        road_bounds = (0.0, 0.0, 0.0, 0.0)

    mb = (mask_bounds.left, mask_bounds.bottom, mask_bounds.right, mask_bounds.top)
    is_contained = bool(
        mb[0] <= road_bounds[0] and
        mb[1] <= road_bounds[1] and
        road_bounds[2] <= mb[2] and
        road_bounds[3] <= mb[3]
    )

    print("[CHECK C] Spatial Coordinate Bounds Alignment (WGS84 [W, S, E, N]):")
    print(f"  - Mask bounds: [{mb[0]:.6f}, {mb[1]:.6f}, {mb[2]:.6f}, {mb[3]:.6f}]")
    print(f"  - Road bounds: [{road_bounds[0]:.6f}, {road_bounds[1]:.6f}, {road_bounds[2]:.6f}, {road_bounds[3]:.6f}]")
    print(f"  - Road network completely within mask boundary: {is_contained}")
    if is_contained:
        print("  -> PASS: Roads perfectly contained within the satellite observation raster.\n")
    else:
        print("  -> NOTICE: Partial spatial coverage between raster footprint and network.\n")

    # ----------------------------------------------------
    # Route Comparison (Baseline vs Predictive)
    # ----------------------------------------------------
    print("[CHECK D] Baseline vs Predictive Route Comparison:")
    scenarios = routes_data.get("scenarios", [])
    features = routes_data.get("features", [])

    base_scenarios = [s for s in scenarios if "scenario_1_baseline" in s.get("id", "")]
    pred_scenarios = [s for s in scenarios if "scenario_2a_predictive" in s.get("id", "")]

    routes_identical_overall = False
    for b_sc in base_scenarios:
        b_idx = b_sc.get("feature_indices", [None])[0]
        b_feat = features[b_idx] if b_idx is not None and b_idx < len(features) else {}
        b_props = b_feat.get("properties", {})
        orig = b_props.get("origin")
        dest = b_props.get("destination")

        p_sc = None
        for cand in pred_scenarios:
            c_idx = cand.get("feature_indices", [None])[0]
            c_feat = features[c_idx] if c_idx is not None and c_idx < len(features) else {}
            c_props = c_feat.get("properties", {})
            if c_props.get("origin") == orig and c_props.get("destination") == dest:
                p_sc = cand
                p_feat = c_feat
                break

        if p_sc:
            b_status = b_props.get("status")
            p_status = p_feat.get("properties", {}).get("status")
            b_nodes = b_props.get("path_nodes", [])
            p_nodes = p_feat.get("properties", {}).get("path_nodes", [])

            print(f"  Corridor: {orig} -> {dest}")
            print(f"    - Baseline:   '{b_sc.get('title')}' (status: {b_status}, nodes: {len(b_nodes)})")
            print(f"    - Predictive: '{p_sc.get('title')}' (status: {p_status}, nodes: {len(p_nodes)})")
            print(f"    - Advisory:   '{p_sc.get('advisory', p_feat.get('properties', {}).get('advisory_note', 'NONE'))}'")

            if b_status == "OK" and p_status == "OK":
                same_nodes = (b_nodes == p_nodes)
                if same_nodes:
                    routes_identical_overall = True
                print(f"    - Same path_nodes: {same_nodes}")
                if same_nodes:
                    print("    -> REPORT: Predictive scenario route EQUALS baseline route (no detour). Advisory and title set accordingly.\n")
                else:
                    print("    -> REPORT: Predictive scenario diverged with detour.\n")
            else:
                print(f"    -> Destination status under baseline: {b_status}, predictive: {p_status} (severed corridor).\n")

    # ----------------------------------------------------
    # 2D Map PNG Export (Mask, Submerged Edges, and Routes)
    # ----------------------------------------------------
    print("[EXPORT] Generating 2D PNG Map (Mask + Submerged Edges + Routes)...")
    rgb = np.full((h, w, 3), 245, dtype=np.uint8)  # Dry land canvas
    rgb[water_mask == 1] = [147, 197, 253]        # Satellite flood water (light blue)

    # 1. Rasterize dry roads (slate gray)
    dry_geoms = [
        f["geometry"] for f in dry_edges
        if f.get("geometry")
    ]
    if dry_geoms:
        dry_mask = rasterio.features.rasterize(dry_geoms, out_shape=(h, w), transform=transform, default_value=1)
        rgb[dry_mask == 1] = [148, 163, 184]  # #94A3B8

    # 2. Rasterize submerged edges (red, dilated for visibility)
    sub_geoms = [f["geometry"] for f in submerged_edges if f.get("geometry")]
    if sub_geoms:
        sub_mask = rasterio.features.rasterize(sub_geoms, out_shape=(h, w), transform=transform, default_value=1)
        sub_dilated = binary_dilation(sub_mask.astype(bool), iterations=1)
        rgb[sub_dilated] = [239, 68, 68]  # #EF4444

    # 3. Rasterize routes by vehicle palette
    route_colors = {
        "AMBULANCE": [37, 99, 235],    # #2563EB Blue
        "TRUCK_4X4": [249, 115, 22],   # #F97316 Orange
        "RESCUE_BOAT": [6, 182, 212],  # #06B6D4 Cyan
        "HELICOPTER": [139, 92, 246],  # #8B5CF6 Purple
    }

    for vt, col in route_colors.items():
        v_geoms = [
            f.get("geometry") for f in features
            if f.get("geometry") and f.get("geometry", {}).get("type") == "LineString"
            and f.get("properties", {}).get("vehicle_type") == vt
            and f.get("properties", {}).get("status") == "OK"
        ]
        if v_geoms:
            r_mask = rasterio.features.rasterize(v_geoms, out_shape=(h, w), transform=transform, default_value=1)
            r_dilated = binary_dilation(r_mask.astype(bool), iterations=2)
            rgb[r_dilated] = col

    out_png = Path(png_out_path)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_png,
        "w",
        driver="PNG",
        height=h,
        width=w,
        count=3,
        dtype="uint8",
        transform=transform,
        crs=crs,
    ) as dst:
        dst.write(rgb.transpose(2, 0, 1))

    # Also save to root if different
    root_png = Path("alignment_check.png")
    if root_png.resolve() != out_png.resolve():
        with rasterio.open(
            root_png,
            "w",
            driver="PNG",
            height=h,
            width=w,
            count=3,
            dtype="uint8",
            transform=transform,
            crs=crs,
        ) as dst:
            dst.write(rgb.transpose(2, 0, 1))

    print(f"  -> SUCCESS: Saved 2D alignment map to {out_png} ({out_png.stat().st_size:,} bytes)")
    if root_png.resolve() != out_png.resolve():
        print(f"  -> SUCCESS: Saved mirror copy to {root_png} ({root_png.stat().st_size:,} bytes)\n")

    return {
        "num_submerged": num_submerged,
        "zero_pixel_submerged": zero_pixel_submerged,
        "total_mask_vertices": total_mask_vertices,
        "kept_vertices": kept_vertices,
        "retained_area_ratio": area_ratio,
        "is_truncated": is_truncated,
        "mask_bounds": mb,
        "road_bounds": road_bounds,
        "routes_identical": routes_identical_overall,
        "png_path": str(out_png),
    }


def main():
    parser = argparse.ArgumentParser(description="Regional satellite rescue routing alignment check tool.")
    parser.add_argument("routes", help="Path to regional routes JSON (e.g. routes_region.json)")
    parser.add_argument("mask", nargs="?", default=None, help="Path to satellite flood mask GeoTIFF (optional if in data/satellite_raw/)")
    parser.add_argument("--png", default="data/alignment_check.png", help="Path to export 2D PNG")
    args = parser.parse_args()

    check_alignment(args.routes, args.mask, png_out_path=args.png)


if __name__ == "__main__":
    main()
