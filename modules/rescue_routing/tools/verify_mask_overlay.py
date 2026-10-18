"""Independent mask-to-road verification and overlay analysis.
Verifies spatial alignment, evaluates false-positive and false-negative road classifications,
and exports QGIS layers and overlay visualization.
"""

import argparse
import json
import math
from pathlib import Path
import sys
import numpy as np
import rasterio
from rasterio.transform import rowcol
import rasterio.features
from shapely.geometry import shape, mapping
from scipy.ndimage import distance_transform_edt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def sample_segment_independent(coords: list[list[float]], spacing_m: float = 2.5) -> list[tuple[float, float]]:
    """Densify segment geometry at half the router spacing (2.5m)."""
    if len(coords) < 2:
        return [(c[0], c[1]) for c in coords]
    pts = []
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        seg_dist = haversine_m(p1[0], p1[1], p2[0], p2[1])
        num_steps = max(1, int(round(seg_dist / spacing_m)))
        for s in range(num_steps):
            t = s / num_steps
            pts.append((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])))
    pts.append((coords[-1][0], coords[-1][1]))
    return pts


def main():
    parser = argparse.ArgumentParser(description="Verify satellite water mask against road network")
    parser.add_argument("routes", nargs="?", default="routes_region.json", help="Path to regional routes.json")
    parser.add_argument("--mask", type=str, default="data/region/flood_mask.tif", help="Path to original flood mask GeoTIFF")
    parser.add_argument("--threshold", type=float, default=0.20, help="Wet fraction threshold for flood classification")
    parser.add_argument("--out-dir", type=str, default="out/qgis", help="Output directory for QGIS layers and overlay.png")
    args = parser.parse_args()

    routes_path = Path(args.routes)
    mask_path = Path(args.mask)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not routes_path.exists():
        sys.exit(f"Routes file {routes_path} not found.")
    if not mask_path.exists():
        sys.exit(f"Mask file {mask_path} not found.")

    with open(routes_path, "r", encoding="utf-8") as f:
        routes_data = json.load(f)

    # Read original mask directly
    with rasterio.open(mask_path) as src:
        mask_arr = src.read(1)
        tf = src.transform
        crs = src.crs
        h, w = mask_arr.shape

    is_water = (mask_arr == 1)
    dist_to_wet_px = distance_transform_edt(~is_water)

    # Extract road features from routes network or visual package
    network_fc = routes_data.get("network", {})
    features = network_fc.get("features", [])
    if not features:
        # Fallback to visual package if available
        vis_p = Path("data/visual_package_orihuela.geojson")
        if vis_p.exists():
            with open(vis_p, "r", encoding="utf-8") as vf:
                vpkg = json.load(vf)
                features = [f for f in vpkg.get("features", []) if f.get("properties", {}).get("layer") == "Filtered Road Network"]

    print("=" * 60)
    print("   MASK-TO-ROAD INDEPENDENT VERIFIER")
    print("=" * 60)
    print(f"Mask: {mask_path} ({w}x{h} px) | Road features: {len(features)}")
    print(f"Sampling spacing: 2.5m (independent half-spacing) | Threshold: {args.threshold:.2f}")

    false_positives = []
    false_negatives = []
    evaluated_segments = []

    for idx, feat in enumerate(features):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue

        sampled_pts = sample_segment_independent(coords, spacing_m=2.5)
        wet_samples = 0
        min_dist_to_water = float("inf")
        valid_samples = 0

        for lon, lat in sampled_pts:
            r, c = rowcol(tf, lon, lat)
            if 0 <= r < h and 0 <= c < w:
                valid_samples += 1
                if mask_arr[r, c] == 1:
                    wet_samples += 1
                dist_px = dist_to_wet_px[r, c]
                if dist_px < min_dist_to_water:
                    min_dist_to_water = dist_px

        wet_fraction = (wet_samples / valid_samples) if valid_samples > 0 else 0.0
        router_state = props.get("road_state") or props.get("status")
        is_router_flooded = (router_state not in ("DRY", "dry")) and (props.get("depth_meters", 0.0) > 0.0 or props.get("has_flood_water", False) or router_state in ("submerged", "FLOODED_IMPASSABLE", "FLOODED_PASSABLE"))

        seg_info = {
            "id": props.get("name") or f"seg_{idx}",
            "road_state": router_state,
            "depth_meters": props.get("depth_meters", 0.0),
            "wet_fraction": round(wet_fraction, 4),
            "min_dist_water_px": round(min_dist_to_water, 2) if min_dist_to_water != float("inf") else None,
            "coords": coords,
            "sampled_count": valid_samples,
        }
        evaluated_segments.append(seg_info)

        # Flag false positive: marked flooded, but wet fraction < threshold and nearest wet pixel > 1.5 px
        if is_router_flooded and wet_fraction < args.threshold and min_dist_to_water > 1.5:
            false_positives.append(seg_info)

        # Flag false negative: marked dry, but wet fraction >= threshold
        if (not is_router_flooded) and wet_fraction >= args.threshold:
            false_negatives.append(seg_info)

    total_segs = max(1, len(evaluated_segments))
    fp_ratio = len(false_positives) / total_segs
    fn_ratio = len(false_negatives) / total_segs

    print(f"Total road segments analyzed: {total_segs}")
    print(f"False Positives: {len(false_positives)} ({fp_ratio*100:.2f}%)")
    print(f"False Negatives: {len(false_negatives)} ({fn_ratio*100:.2f}%)")

    # Worst 10 segments
    mismatches = false_positives + false_negatives
    mismatches.sort(key=lambda s: abs(s["wet_fraction"] - (1.0 if "flooded" in str(s["road_state"]).lower() else 0.0)), reverse=True)
    print("\nWorst 10 Mismatch Segments:")
    for rank, seg in enumerate(mismatches[:10], 1):
        mid_c = seg["coords"][len(seg["coords"]) // 2]
        print(f"  {rank:>2}. [{seg['id']}] State={seg['road_state']} | WetFraction={seg['wet_fraction']:.3f} | DistToWater={seg['min_dist_water_px']} px | Midpoint=({mid_c[1]:.5f}, {mid_c[0]:.5f})")

    # 1. Export filled mask polygons to QGIS
    shapes_gen = rasterio.features.shapes(
        mask_arr.astype(np.uint8),
        mask=(mask_arr == 1),
        transform=tf,
    )
    mask_features = []
    for geom, val in shapes_gen:
        if val == 1:
            poly_shp = shape(geom).simplify(0.0001)
            if not poly_shp.is_empty:
                mask_features.append({
                    "type": "Feature",
                    "geometry": mapping(poly_shp),
                    "properties": {
                        "layer": "Filled Satellite Flood Mask",
                        "fill": "#2563EB",
                        "fill_opacity": 0.50,
                        "stroke": "#1D4ED8",
                        "stroke_width": 2,
                    },
                })
    with open(out_dir / "filled_mask.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": mask_features}, f, indent=2)

    # 2. Export road status layers
    road_out_features = []
    for seg in evaluated_segments:
        road_out_features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": seg["coords"]},
            "properties": {
                "name": seg["id"],
                "road_state": seg["road_state"],
                "depth_meters": seg["depth_meters"],
                "wet_fraction": seg["wet_fraction"],
                "min_dist_water_px": seg["min_dist_water_px"],
            },
        })
    with open(out_dir / "roads_status.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": road_out_features}, f, indent=2)

    # 3. Export mismatch segments
    mismatch_features = []
    for seg in mismatches:
        mtype = "False Positive" if seg in false_positives else "False Negative"
        mismatch_features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": seg["coords"]},
            "properties": {
                "name": seg["id"],
                "mismatch_type": mtype,
                "road_state": seg["road_state"],
                "wet_fraction": seg["wet_fraction"],
                "min_dist_water_px": seg["min_dist_water_px"],
            },
        })
    with open(out_dir / "mismatch_segments.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": mismatch_features}, f, indent=2)

    # 4. Generate out/qgis/overlay.png using matplotlib
    fig, ax = plt.subplots(figsize=(12, 10), dpi=200)

    # Plot filled mask raster in background
    # Extent: [left, right, bottom, top]
    bounds = rasterio.transform.array_bounds(h, w, tf)
    extent = [bounds[0], bounds[2], bounds[1], bounds[3]]

    # Water mask as blue overlay
    mask_rgba = np.zeros((h, w, 4), dtype=np.float32)
    mask_rgba[is_water] = [0.23, 0.51, 0.96, 0.55]  # semi-transparent blue
    ax.imshow(mask_rgba, extent=extent, origin="upper", zorder=1)

    # Plot roads by status
    color_map = {
        "DRY": "#22C55E",
        "FLOODED_PASSABLE": "#EAB308",
        "FLOODED_IMPASSABLE": "#EF4444",
        "UNCERTAIN": "#F97316",
        "UNKNOWN": "#94A3B8",
    }
    for seg in evaluated_segments:
        c = color_map.get(str(seg["road_state"]).upper(), "#22C55E" if "dry" in str(seg["road_state"]).lower() else "#EF4444")
        xs = [pt[0] for pt in seg["coords"]]
        ys = [pt[1] for pt in seg["coords"]]
        ax.plot(xs, ys, color=c, linewidth=1.5, alpha=0.85, zorder=2)

    # Highlight worst mismatches
    for seg in mismatches[:15]:
        xs = [pt[0] for pt in seg["coords"]]
        ys = [pt[1] for pt in seg["coords"]]
        ax.plot(xs, ys, color="#EC4899", linewidth=3.0, alpha=0.95, zorder=3)

    ax.set_title("Mask-to-Road Verification: Satellite Flood vs Road Classification", fontsize=14, pad=12)
    ax.set_xlabel("Longitude (deg WGS84)")
    ax.set_ylabel("Latitude (deg WGS84)")

    legend_elements = [
        Patch(facecolor="#2563EB", edgecolor="#1D4ED8", alpha=0.55, label="Satellite Flood Mask (Filled)"),
        Line2D([0], [0], color="#22C55E", lw=2, label="DRY Road"),
        Line2D([0], [0], color="#EF4444", lw=2, label="FLOODED_IMPASSABLE Road"),
        Line2D([0], [0], color="#EAB308", lw=2, label="FLOODED_PASSABLE Road"),
        Line2D([0], [0], color="#F97316", lw=2, label="UNCERTAIN Road"),
        Line2D([0], [0], color="#EC4899", lw=3, label="Mismatch / False Positive"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", framealpha=0.9)
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])

    overlay_png = out_dir / "overlay.png"
    plt.tight_layout()
    plt.savefig(overlay_png, dpi=200)
    plt.close()

    print(f"\nSUCCESS: Exported QGIS package to {out_dir}/")
    print(f"  - {out_dir / 'filled_mask.geojson'}")
    print(f"  - {out_dir / 'roads_status.geojson'}")
    print(f"  - {out_dir / 'mismatch_segments.geojson'}")
    print(f"  - {overlay_png} ({overlay_png.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
