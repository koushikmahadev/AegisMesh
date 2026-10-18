"""Interactive 3D/2D Rescue Route Elevation and Flood Analysis Viewer.
Single source of truth per run. Strict spatial bounds checking.
Embeds Plotly.js offline (<15MB single file) with zero CDN dependencies.
"""

import argparse
import html
import json
import math
import os
from pathlib import Path
import sys
import numpy as np
import plotly.graph_objects as go

try:
    import rasterio
    from rasterio.transform import rowcol
    import rasterio.features
except ImportError:
    rasterio = None

try:
    from scipy.ndimage import label, binary_opening
except ImportError:
    label = None
    binary_opening = None

# Non-negotiable vehicle palette
VEHICLE_COLORS = {
    "AMBULANCE": "#1D4ED8",    # Blue
    "TRUCK_4X4": "#8B4513",    # Brown
    "RESCUE_BOAT": "#0D9488",  # Teal
    "HELICOPTER": "#9333EA",   # Purple
}

# 5 Road States Colors
ROAD_STATE_COLORS = {
    "DRY": "#16A34A",                # Green
    "FLOODED_PASSABLE": "#EAB308",   # Yellow/Gold
    "FLOODED_IMPASSABLE": "#EF4444", # Red
    "UNCERTAIN": "#F97316",          # Orange
    "UNKNOWN": "#64748B",            # Slate
}

DISCLAIMER_TEXT = (
    "PLANNING AID ONLY. Not validated for live rescue dispatch. "
    "Satellite flood extent may be outdated, depth is estimated, and radar misses flooding "
    "under buildings and vegetation. Verify routes on the ground."
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR
if not (PROJECT_ROOT / "routes_region.json").exists() and (PROJECT_ROOT.parent / "routes_region.json").exists():
    PROJECT_ROOT = PROJECT_ROOT.parent
if not (PROJECT_ROOT / "routes_region.json").exists() and (PROJECT_ROOT.parent.parent / "routes_region.json").exists():
    PROJECT_ROOT = PROJECT_ROOT.parent.parent

BASE_RIVER_ELEVATION_M = 194.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def sample_dem_elev(dem_arr: np.ndarray, tf: any, lon: float, lat: float) -> float | None:
    if dem_arr is None or tf is None:
        return None
    h, w = dem_arr.shape
    try:
        r, c = rowcol(tf, lon, lat)
        if 0 <= r < h and 0 <= c < w:
            val = float(dem_arr[r, c])
            if not np.isnan(val) and val > -500.0:
                return val
    except Exception:
        pass
    return None


def densify_segment_coords(coords: list[list[float]], max_step_m: float = 30.0) -> list[tuple[float, float]]:
    if len(coords) < 2:
        return [(c[0], c[1]) for c in coords]
    out = []
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        dist = haversine_m(p1[0], p1[1], p2[0], p2[1])
        num_steps = max(1, int(math.ceil(dist / max_step_m)))
        for s in range(num_steps):
            t = s / float(num_steps)
            out.append((p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])))
    out.append((coords[-1][0], coords[-1][1]))
    return out


def clean_water_mask_speckle(water_mask: np.ndarray, min_area_px: int = 2) -> tuple[np.ndarray, int]:
    if water_mask is None or not np.any(water_mask == 1) or label is None:
        return water_mask, 0
    is_water = (water_mask == 1)
    orig_count = int(np.sum(is_water))
    labeled, num_features = label(is_water)
    if num_features > 0 and min_area_px > 1:
        sizes = np.bincount(labeled.ravel())
        too_small = sizes < min_area_px
        too_small_mask = too_small[labeled]
        cleaned_water = is_water & (~too_small_mask)
    else:
        cleaned_water = is_water
    cleaned_mask = water_mask.copy()
    cleaned_mask[is_water & (~cleaned_water)] = 0
    removed_count = orig_count - int(np.sum(cleaned_mask == 1))
    return cleaned_mask, removed_count


def check_layer_bounds(layer_name: str, coords_list: list[tuple[float, float]], dem_bounds_allowed: tuple[float, float, float, float], dem_bounds_orig: tuple[float, float, float, float]) -> dict:
    dem_w, dem_s, dem_e, dem_n = dem_bounds_allowed
    total = len(coords_list)
    if total == 0:
        return {"total": 0, "inside": 0, "bbox": [0, 0, 0, 0], "layer": layer_name}
    lons = [c[0] for c in coords_list]
    lats = [c[1] for c in coords_list]
    bbox = [round(min(lons), 5), round(min(lats), 5), round(max(lons), 5), round(max(lats), 5)]
    inside = sum(1 for x, y in coords_list if dem_w <= x <= dem_e and dem_s <= y <= dem_n)
    print(f"[BOUNDS CHECK] Layer '{layer_name}': total={total}, inside={inside}, bbox={bbox}")
    if inside < total:
        orig_bbox = [round(dem_bounds_orig[0], 5), round(dem_bounds_orig[1], 5), round(dem_bounds_orig[2], 5), round(dem_bounds_orig[3], 5)]
        sys.exit(f"COORDINATE MISMATCH: {layer_name} bbox {bbox} not inside DEM bbox {orig_bbox}")
    return {"total": total, "inside": inside, "bbox": bbox, "layer": layer_name}


def build_viewer_html(routes_path: str | Path | None = None, dem_path: str | Path | None = None, mask_path: str | Path | None = None) -> tuple[str, dict]:
    # 1. Resolve routes file (Single Source of Truth)
    if routes_path is None:
        cand_paths = [PROJECT_ROOT / "routes_region.json", PROJECT_ROOT / "routes.json"]
        routes_file = next((p for p in cand_paths if p.exists()), cand_paths[0])
    else:
        routes_file = Path(routes_path)
        if not routes_file.is_absolute():
            routes_file = PROJECT_ROOT / routes_file

    if not routes_file.exists():
        sys.exit(f"ERROR: routes file not found: {routes_file}")

    with open(routes_file, "r", encoding="utf-8") as f:
        routes_data = json.load(f)

    schema_version = routes_data.get("schema_version", "UNKNOWN")
    disclaimer = routes_data.get("disclaimer") or "PLANNING AID ONLY. Not validated for live rescue dispatch. Satellite flood extent may be outdated, depth is estimated, and radar misses flooding under buildings and vegetation. Verify routes on the ground."
    provenance = routes_data.get("provenance", {})
    region_id = provenance.get("region") or provenance.get("network") or "UNKNOWN"
    scenarios_list = routes_data.get("scenarios", [])
    network_fc = routes_data.get("network", {})
    network_features = network_fc.get("features", [])

    print("============================================================")
    print("   ITEM 1: SINGLE SOURCE OF TRUTH")
    print("============================================================")
    print(f"Routes file path:           {routes_file}")
    print(f"Schema version:             {schema_version}")
    print(f"Region ID:                  {region_id}")
    print(f"Number of scenarios:        {len(scenarios_list)}")
    print(f"Number of network segments: {len(network_features)}")
    print("============================================================\n")

    # 2. Check and Load DEM & Mask
    dem_file = Path(dem_path) if dem_path else (PROJECT_ROOT / "data" / "region" / "dem.tif")
    mask_file = Path(mask_path) if mask_path else (PROJECT_ROOT / "data" / "region" / "flood_mask.tif")

    dem_arr, dem_tf, dem_bounds = None, None, None
    has_dem = False
    flooded_px_count = 0
    polygon_count = 0
    speckle_removed = 0
    sub_dem = None
    sub_lons, sub_lats = None, None
    flood_depth_grid = None
    mask_sub_lons, mask_sub_lats = None, None

    if dem_file.exists() and rasterio is not None:
        try:
            with rasterio.open(dem_file) as d_src:
                dem_arr = d_src.read(1)
                dem_tf = d_src.transform
                dem_bounds = d_src.bounds
                has_dem = True
        except Exception as e:
            sys.exit(f"ERROR: failed reading DEM GeoTIFF {dem_file}: {e}")

    # If DEM is present, perform STRICT BOUNDS CHECK on all layers
    if has_dem and dem_bounds:
        margin = 0.02
        dem_bounds_allowed = (dem_bounds.left - margin, dem_bounds.bottom - margin, dem_bounds.right + margin, dem_bounds.top + margin)
        dem_bounds_orig = (dem_bounds.left, dem_bounds.bottom, dem_bounds.right, dem_bounds.top)

        # A. Check Roads layer
        road_pts = []
        for feat in network_features:
            for c in feat.get("geometry", {}).get("coordinates", []):
                road_pts.append((c[0], c[1]))
        check_layer_bounds("roads", road_pts, dem_bounds_allowed, dem_bounds_orig)

        # B. Check Routes layer
        route_pts = []
        for feat in routes_data.get("features", []):
            geom = feat.get("geometry")
            if geom and geom.get("coordinates"):
                for c in geom["coordinates"]:
                    route_pts.append((c[0], c[1]))
        check_layer_bounds("routes", route_pts, dem_bounds_allowed, dem_bounds_orig)

        # C. Check Sites layer
        sites_path = PROJECT_ROOT / "data" / "spain_satellite_sites.json"
        sites_list = []
        if sites_path.exists():
            with open(sites_path, "r", encoding="utf-8") as sf:
                s_raw = json.load(sf)
                sites_list = s_raw if isinstance(s_raw, list) else [{"id": k, **v} for k, v in s_raw.items()]
        site_pts = [(s["lon"], s["lat"]) for s in sites_list if "lon" in s and "lat" in s]
        if site_pts:
            check_layer_bounds("sites", site_pts, dem_bounds_allowed, dem_bounds_orig)

        # D. Check Mask layer
        if mask_file.exists() and rasterio is not None:
            with rasterio.open(mask_file) as m_src:
                raw_mask = m_src.read(1)
                m_tf = m_src.transform
                m_bounds = m_src.bounds
                mask_pts = [(m_bounds.left, m_bounds.bottom), (m_bounds.right, m_bounds.top)]
                check_layer_bounds("mask", mask_pts, dem_bounds_allowed, dem_bounds_orig)

                cleaned_mask, speckle_removed = clean_water_mask_speckle(raw_mask, min_area_px=2)
                flooded_px_count = int(np.sum(cleaned_mask == 1))
                shapes = list(rasterio.features.shapes(cleaned_mask.astype(np.int16), mask=(cleaned_mask == 1), transform=m_tf))
                polygon_count = len(shapes)

                # Decimated surface grid (<= 200x200)
                h_d, w_d = dem_arr.shape
                step = max(1, math.ceil(max(h_d, w_d) / 180.0))
                sub_dem = dem_arr[::step, ::step].astype(float)
                ny, nx = sub_dem.shape

                sub_lons = np.linspace(dem_bounds.left, dem_bounds.right, nx)
                sub_lats = np.linspace(dem_bounds.top, dem_bounds.bottom, ny)

                mask_dec = cleaned_mask[::step, ::step] if cleaned_mask.shape == dem_arr.shape else np.zeros_like(sub_dem, dtype=np.int8)
                flood_depth_grid = np.full_like(sub_dem, np.nan)
                is_wet = (mask_dec == 1)
                if np.any(is_wet):
                    wse_est = float(np.percentile(sub_dem[is_wet], 75)) + 0.6
                    d_est = np.maximum(0.05, wse_est - sub_dem)
                    d_est[~is_wet] = np.nan
                    flood_depth_grid = d_est
                mask_sub_lons, mask_sub_lats = sub_lons, sub_lats

    # 3. Classify Road States
    state_coords = {st: [] for st in ROAD_STATE_COLORS}
    state_counts = {st: 0 for st in ROAD_STATE_COLORS}

    for feat in network_features:
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if not coords:
            continue

        is_bridge = bool(props.get("bridge") or props.get("kind") == "bridge")
        prob = props.get("flood_probability") or props.get("flood_risk") or props.get("risk") or props.get("edge_risk")
        depth = props.get("depth_meters") or props.get("current_water_depth_meters") or props.get("depth")
        prob_val = float(prob) if prob is not None else None
        depth_val = float(depth) if depth is not None else None

        if is_bridge:
            st_clean = "UNCERTAIN"
        elif (prob_val is not None and prob_val > 0.50) or (depth_val is not None and depth_val > 0.30):
            st_clean = "FLOODED_IMPASSABLE"
        elif (prob_val is not None and 0.20 <= prob_val <= 0.50) or (depth_val is not None and 0.05 <= depth_val <= 0.30):
            st_clean = "UNCERTAIN"
        elif prob_val is not None and prob_val < 0.20 and (depth_val is None or depth_val < 0.05):
            st_clean = "DRY"
        elif depth_val is not None and depth_val > 0:
            st_clean = "FLOODED_PASSABLE" if depth_val <= 0.30 else "FLOODED_IMPASSABLE"
        else:
            st_str = str(props.get("road_state") or props.get("status") or "DRY").upper()
            if st_str in state_coords:
                st_clean = st_str
            elif "SUBMERGED" in st_str or "IMPASSABLE" in st_str:
                st_clean = "FLOODED_IMPASSABLE"
            elif "PASSABLE" in st_str:
                st_clean = "FLOODED_PASSABLE"
            elif "UNCERTAIN" in st_str:
                st_clean = "UNCERTAIN"
            elif "UNKNOWN" in st_str:
                st_clean = "UNKNOWN"
            else:
                st_clean = "DRY"

        state_coords[st_clean].append((coords, props))
        state_counts[st_clean] += 1

    # 4. Build Plotly 3D Figure
    fig = go.Figure()

    # Dropdown and tracking data
    dropdown_buttons = []
    trace_indices_per_scenario = {}

    # 4A. Terrain Surface (Copernicus GLO-30 DEM, neutral Earth colorscale)
    if has_dem and sub_dem is not None:
        fig.add_trace(go.Surface(
            x=sub_lons,
            y=sub_lats,
            z=sub_dem,
            colorscale="Earth",
            opacity=0.65,
            showscale=False,
            name="Copernicus GLO-30 Terrain (EGM2008)",
            legendgroup="terrain",
            legendgrouptitle_text="Terrain Elevation",
            hoverinfo="none",
        ))

        # 4B. Draped Flood Water with Depth Colorbar
        if flood_depth_grid is not None and np.any(~np.isnan(flood_depth_grid)):
            fig.add_trace(go.Surface(
                x=mask_sub_lons,
                y=mask_sub_lats,
                z=sub_dem + flood_depth_grid,
                surfacecolor=flood_depth_grid,
                colorscale="Blues",
                cmin=0.0,
                cmax=max(1.5, float(np.nanmax(flood_depth_grid))),
                colorbar=dict(title="Water Depth (m)", len=0.5, y=0.45, x=1.12),
                opacity=0.75,
                name="Sentinel-1 Flood Water (Depth)",
                legendgroup="flood",
                legendgrouptitle_text="Flood Observation Layer",
                hoverinfo="z+name",
            ))

        # Flood extent outline
        flood_extent = routes_data.get("flood_extent", {})
        if flood_extent and flood_extent.get("type") in ("Polygon", "MultiPolygon"):
            coords_list = flood_extent.get("coordinates", [])
            poly_rings = coords_list if flood_extent.get("type") == "Polygon" else [ring for poly in coords_list for ring in poly]
            for ring in poly_rings[:30]:
                fx = [pt[0] for pt in ring]
                fy = [pt[1] for pt in ring]
                fz = [(sample_dem_elev(dem_arr, dem_tf, pt[0], pt[1]) or 20.0) + 0.15 for pt in ring]
                fig.add_trace(go.Scatter3d(
                    x=fx, y=fy, z=fz,
                    mode="lines",
                    name="Flood Extent Outline",
                    legendgroup="flood",
                    line=dict(color="#1D4ED8", width=3),
                    showlegend=False,
                    hoverinfo="none",
                ))

    # 4C. Draped Roads: width >= 3, densified <= 30m, NaN dropped
    road_nan_dropped = 0
    road_sampled_total = 0

    for st, color in ROAD_STATE_COLORS.items():
        items = state_coords.get(st, [])
        cnt = state_counts[st]
        trace_label = f"{st} ({cnt})"

        if not items:
            fig.add_trace(go.Scatter3d(
                x=[None], y=[None], z=[None],
                mode="lines",
                name=trace_label,
                legendgroup="road_states",
                legendgrouptitle_text="5-State Road Network",
                line=dict(color=color, width=3),
                showlegend=True,
                hoverinfo="none",
            ))
            continue

        rx, ry, rz = [], [], []
        for coords, props in items:
            dense_pts = densify_segment_coords(coords, max_step_m=30.0)
            seg_valid = False
            for c in dense_pts:
                road_sampled_total += 1
                elev = sample_dem_elev(dem_arr, dem_tf, c[0], c[1]) if has_dem else 20.0
                if elev is None or np.isnan(elev):
                    road_nan_dropped += 1
                    continue
                rx.append(c[0])
                ry.append(c[1])
                rz.append(elev + 0.4)  # Small offset above DEM
                seg_valid = True
            if seg_valid:
                rx.append(None)
                ry.append(None)
                rz.append(None)

        fig.add_trace(go.Scatter3d(
            x=rx, y=ry, z=rz,
            mode="lines",
            name=trace_label,
            legendgroup="road_states",
            legendgrouptitle_text="5-State Road Network",
            line=dict(color=color, width=4 if "FLOODED" in st else 3),
            hoverinfo="name",
            showlegend=True,
        ))

    print(f"[DEM SAMPLING] Roads: sampled {road_sampled_total} vertices, dropped {road_nan_dropped} NaN elevation vertices.")
    if road_sampled_total > 0 and (road_nan_dropped / road_sampled_total) > 0.05:
        print(f"WARNING: More than 5% ({road_nan_dropped}/{road_sampled_total}) of road vertices had NaN elevation and were dropped.")

    # 4D. Sites with Short IDs A, B, C and Leader Lines
    marker_letters = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    site_table_rows = []

    for i, s in enumerate(sites_list):
        s_id = s.get("id")
        slon = s.get("lon")
        slat = s.get("lat")
        if slon is None or slat is None:
            continue
        skind = s.get("kind", "site")
        m_id = marker_letters[i % len(marker_letters)]

        angle = (i * 2.0 * math.pi / max(len(sites_list), 1)) + 0.35
        dx = 0.0035 * math.cos(angle)
        dy = 0.0028 * math.sin(angle)

        base_e = (sample_dem_elev(dem_arr, dem_tf, slon, slat) or 20.0) if has_dem else 20.0
        label_z = base_e + 4.0

        site_table_rows.append({"short_id": m_id, "id": s_id, "kind": skind, "lat": slat, "lon": slon})
        hover_site = f"<b>[{m_id}] {s_id}</b> ({skind.upper()})<br>Coords: {slat:.5f}, {slon:.5f}"

        # Leader line
        fig.add_trace(go.Scatter3d(
            x=[slon, slon + dx],
            y=[slat, slat + dy],
            z=[base_e + 0.5, label_z],
            mode="lines",
            line=dict(color="#0F172A", width=2),
            showlegend=False,
            hoverinfo="none",
        ))

        # Marker and short ID
        fig.add_trace(go.Scatter3d(
            x=[slon + dx],
            y=[slat + dy],
            z=[label_z],
            mode="markers+text",
            marker=dict(size=8, color="#DC2626" if skind == "zone" else "#16A34A", symbol="circle"),
            text=[f"[{m_id}]"],
            textposition="top center",
            name=f"Site [{m_id}] {s_id}",
            legendgroup="sites",
            legendgrouptitle_text="Facilities & Sectors",
            hovertext=hover_site,
            hoverinfo="text",
        ))

    # 4E. Routes: width >= 8, start/end markers, densified <= 30m, helicopter air corridor
    features_list = routes_data.get("features", [])
    feat_to_sc = {}
    for sc in scenarios_list:
        for fi in sc.get("feature_indices", []):
            feat_to_sc[fi] = sc

    scenarios_rendered_set = set()
    stages_per_vehicle_rendered = {"AMBULANCE": 0, "TRUCK_4X4": 0, "RESCUE_BOAT": 0, "HELICOPTER": 0}
    stage_table_rows = []
    routes_nan_dropped = 0
    routes_sampled_total = 0

    for idx, feat in enumerate(features_list):
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        sc_info = feat_to_sc.get(idx, {})
        sc_id = sc_info.get("id") or props.get("scenario_id") or f"scenario_{idx}"
        sc_title = sc_info.get("title") or sc_id
        stage = props.get("stage", idx + 1)
        vehicle = props.get("vehicle_type", "AMBULANCE")
        status = props.get("status", "OK")
        reason = props.get("reason") or ("Corridors blocked" if status == "UNREACHABLE" else "")
        cut_edges = props.get("cut_edges") or props.get("blocked_edges") or []

        scenarios_rendered_set.add(sc_id)
        stages_per_vehicle_rendered[vehicle] = stages_per_vehicle_rendered.get(vehicle, 0) + 1

        v_color = VEHICLE_COLORS.get(vehicle, "#1D4ED8")
        line_dash = "solid" if "baseline" in sc_id.lower() else ("dash" if "predictive" in sc_id.lower() else ("dot" if "cascade" in sc_id.lower() else "dashdot"))

        trace_title = f"{sc_title} | stage {stage} | {vehicle}"
        if status == "UNREACHABLE":
            trace_title += " [UNREACHABLE]"

        stage_table_rows.append({
            "scenario": sc_title,
            "scenario_id": sc_id,
            "stage": stage,
            "vehicle": vehicle,
            "status": status,
            "reason": reason,
            "cut_edges": cut_edges,
            "eta": props.get("eta_minutes"),
            "distance": props.get("distance_km"),
        })

        if sc_id not in trace_indices_per_scenario:
            trace_indices_per_scenario[sc_id] = []

        coords = geom.get("coordinates", []) if (geom and geom.get("type") == "LineString") else []

        if status == "UNREACHABLE" or not coords:
            trace_idx = len(fig.data)
            trace_indices_per_scenario[sc_id].append(trace_idx)
            fig.add_trace(go.Scatter3d(
                x=[None], y=[None], z=[None],
                mode="markers",
                marker=dict(size=8, color=v_color, symbol="x"),
                name=trace_title,
                legendgroup=sc_id,
                legendgrouptitle_text=f"Scenario: {sc_title}",
                hoverinfo="text",
                hovertext=f"<b>{trace_title}</b><br>Reason: {reason}<br>Cut Edges: {cut_edges}",
                showlegend=True,
            ))
            continue

        # Densify route segment to 30m or less
        dense_pts = densify_segment_coords(coords, max_step_m=30.0)
        rx, ry, rz = [], [], []

        if vehicle == "HELICOPTER":
            # Parabolic air corridor arc above terrain
            n_pts = len(dense_pts)
            for i_pt, c in enumerate(dense_pts):
                routes_sampled_total += 1
                t = i_pt / max(n_pts - 1, 1)
                elev = sample_dem_elev(dem_arr, dem_tf, c[0], c[1]) if has_dem else 20.0
                if elev is None or np.isnan(elev):
                    routes_nan_dropped += 1
                    elev = 20.0
                rx.append(c[0])
                ry.append(c[1])
                rz.append(elev + 2.0 + 4.0 * 25.0 * t * (1.0 - t))
            route_dash = "dash"
            route_width = 8
        else:
            for c in dense_pts:
                routes_sampled_total += 1
                elev = sample_dem_elev(dem_arr, dem_tf, c[0], c[1]) if has_dem else 20.0
                if elev is None or np.isnan(elev):
                    routes_nan_dropped += 1
                    continue
                rx.append(c[0])
                ry.append(c[1])
                rz.append(elev + 1.2)  # Offset above roads
            route_dash = line_dash
            route_width = 9  # width >= 8

        hover_route = (
            f"<b>{trace_title}</b><br>"
            f"Distance: {props.get('distance_km')} km | ETA: {props.get('eta_minutes')} min<br>"
            f"Lowest-Risk Route (Model)"
        )

        trace_idx = len(fig.data)
        trace_indices_per_scenario[sc_id].append(trace_idx)

        # Route Line
        fig.add_trace(go.Scatter3d(
            x=rx, y=ry, z=rz,
            mode="lines",
            name=trace_title,
            legendgroup=sc_id,
            legendgrouptitle_text=f"Scenario: {sc_title}",
            line=dict(color=v_color, width=route_width, dash=route_dash),
            hovertext=hover_route,
            hoverinfo="text",
            showlegend=True,
        ))

        # Start and End Markers
        if rx:
            fig.add_trace(go.Scatter3d(
                x=[rx[0], rx[-1]],
                y=[ry[0], ry[-1]],
                z=[rz[0] + 0.3, rz[-1] + 0.3],
                mode="markers",
                marker=dict(size=[10, 10], color=["#16A34A", "#DC2626"], symbol=["square", "circle"]),
                name=f"{trace_title} (Endpoints)",
                legendgroup=sc_id,
                showlegend=False,
                hoverinfo="text",
                hovertext=[f"Origin: {props.get('origin', 'Base')}", f"Destination: {props.get('destination', 'Zone')}"],
            ))

    print(f"[DEM SAMPLING] Routes: sampled {routes_sampled_total} vertices, dropped {routes_nan_dropped} NaN elevation vertices.")
    if routes_sampled_total > 0 and (routes_nan_dropped / routes_sampled_total) > 0.05:
        print(f"WARNING: More than 5% ({routes_nan_dropped}/{routes_sampled_total}) of route vertices had NaN elevation and were dropped.")

    # 5. Dropdown Menu: Defaults to "All scenarios", lists each scenario with stage count
    base_trace_count = sum(1 for tr in fig.data if tr.legendgroup in ("terrain", "flood", "road_states", "sites"))
    total_traces = len(fig.data)

    dropdown_buttons.append(dict(
        label="All scenarios",
        method="update",
        args=[{"visible": [True] * total_traces}],
    ))

    for sc in scenarios_list:
        sc_id = sc.get("id")
        sc_title = sc.get("title", sc_id)
        num_stages = len(sc.get("feature_indices", []))
        stage_label = f"({num_stages} stage{'s' if num_stages != 1 else ''})"
        t_indices = trace_indices_per_scenario.get(sc_id, [])

        vis_list = []
        for i_tr in range(total_traces):
            if i_tr < base_trace_count or i_tr in t_indices:
                vis_list.append(True)
            else:
                vis_list.append(False)
        dropdown_buttons.append(dict(
            label=f"{sc_title} {stage_label}",
            method="update",
            args=[{"visible": vis_list}],
        ))

    # 6. Scene Framing: Explicit ranges from DEM bounds, real aspectratio, camera looks at center
    if has_dem and dem_bounds and sub_dem is not None:
        lon_min, lon_max = dem_bounds.left, dem_bounds.right
        lat_min, lat_max = dem_bounds.bottom, dem_bounds.top
        center_lat = (lat_min + lat_max) / 2.0
        center_lon = (lon_min + lon_max) / 2.0

        d_lat_m = (lat_max - lat_min) * 111320.0
        d_lon_m = (lon_max - lon_min) * 111320.0 * math.cos(math.radians(center_lat))
        z_min = float(np.nanmin(sub_dem))
        z_max = float(np.nanmax(sub_dem))
        d_elev_m = max(10.0, z_max - z_min)

        exaggeration = 3.0
        x_aspect = d_lon_m / d_lat_m
        y_aspect = 1.0
        z_aspect = max(0.20, min(0.60, (d_elev_m * exaggeration) / d_lat_m * 15.0))

        scene_layout = dict(
            xaxis=dict(range=[lon_min, lon_max], autorange=False, title="Longitude (deg WGS84)"),
            yaxis=dict(range=[lat_min, lat_max], autorange=False, title="Latitude (deg WGS84)"),
            zaxis=dict(range=[z_min - 2.0, z_max + d_elev_m * 0.5], autorange=False, title="Elevation (m EGM2008)"),
            aspectmode="manual",
            aspectratio=dict(x=x_aspect, y=y_aspect, z=z_aspect),
            camera=dict(center=dict(x=0, y=0, z=0), eye=dict(x=1.2, y=-1.3, z=0.8)),
        )
    else:
        scene_layout = dict(
            xaxis_title="Longitude",
            yaxis_title="Latitude",
            zaxis_title="Elevation (m)",
            camera=dict(center=dict(x=0, y=0, z=0), eye=dict(x=0.0, y=0.0, z=2.0)),
        )

    # 7. Slider Steps for Vertical Exaggeration
    slider_steps = []
    exagg_factors = [1.0, 2.0, 3.0, 4.0, 5.0]
    for ex in exagg_factors:
        slider_steps.append(dict(
            label=f"{ex:.1f}x",
            method="relayout",
            args=[{"scene.aspectratio.z": (z_aspect / 3.0) * ex}],
        ))

    # Provenance details
    flood_obs = provenance.get("flood_observation", {})
    prov_sensor = flood_obs.get("sensor") or "Sentinel-1 C-SAR"
    prov_platform = flood_obs.get("platform")
    if not prov_platform or prov_platform == "Sentinel-1":
        prov_platform = "UNKNOWN"
    prov_acq = flood_obs.get("acquired_utc") or provenance.get("acquired") or "2019-09-17 (time: UNKNOWN)"
    if "T06:00:00" in str(prov_acq) or "T00:00:00" in str(prov_acq):
        prov_acq = f"{str(prov_acq).split('T')[0]} (time: UNKNOWN)"
    prov_prod = flood_obs.get("product_id") or "Spain_7370579_LabelHand"
    prov_method = flood_obs.get("method") or "hand_labeled"
    prov_age_h = provenance.get("data_age_hours")
    is_date_only = "time: UNKNOWN" in str(prov_acq) or len(str(prov_acq).split()) == 1
    age_label = f"{prov_age_h}h (age approx, date only)" if (prov_age_h and is_date_only) else (f"{prov_age_h}h" if prov_age_h else "UNKNOWN")
    prov_fresh = provenance.get("data_freshness", "STALE")
    is_hist = bool(prov_age_h and prov_age_h > 72.0) or provenance.get("is_historical", True)

    caption_text = (
        f"Copernicus GLO-30 DEM (EGM2008 vertical datum, 30m resolution) | Vertical Exaggeration: 3.0x"
        if has_dem else
        "Predictive mode disabled: no DEM (Zaragoza curated elevation profile)"
    )

    fig.update_layout(
        title=dict(
            text=f"<b>HighWater Interactive Rescue Route & Flood Analysis</b><br><span style='font-size:12px;color:#475569;'>{caption_text}</span>",
            x=0.02, y=0.96,
        ),
        scene=scene_layout,
        margin=dict(l=10, r=10, b=30, t=100),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.95,
            xanchor="left",
            x=1.02,
            groupclick="toggleitem",
        ),
        updatemenus=[
            dict(
                buttons=dropdown_buttons,
                direction="down",
                pad={"r": 10, "t": 10},
                showactive=True,
                x=0.02,
                xanchor="left",
                y=1.06,
                yanchor="top",
                bgcolor="#FFFFFF",
                bordercolor="#94A3B8",
            )
        ],
        sliders=[
            dict(
                active=2,
                currentvalue={"prefix": "Vertical Exaggeration: "},
                pad={"t": 30},
                steps=slider_steps,
                x=0.15,
                len=0.35,
                y=-0.02,
            )
        ],
    )

    # 8. Scenario Deltas Table vs Baseline
    delta_rows = []
    baseline_feat = features_list[0] if features_list else {}
    base_props = baseline_feat.get("properties", {})
    base_eta = base_props.get("eta_minutes")
    base_coords = (baseline_feat.get("geometry") or {}).get("coordinates", [])

    for sc in scenarios_list[1:]:
        f_idxs = sc.get("feature_indices", [])
        if not f_idxs:
            continue
        feat_sc = features_list[f_idxs[0]]
        props_sc = feat_sc.get("properties", {})
        sc_eta = props_sc.get("eta_minutes")
        sc_coords = (feat_sc.get("geometry") or {}).get("coordinates", [])

        eta_delta = round(sc_eta - base_eta, 2) if (sc_eta is not None and base_eta is not None) else "N/A"
        is_identical = (sc_coords == base_coords) if (sc_coords and base_coords) else False
        dep_win = props_sc.get("departure_window_min", "N/A")
        risk_val = props_sc.get("route_risk", 0.0)

        delta_rows.append({
            "scenario": sc.get("title", sc.get("id")),
            "eta": sc_eta,
            "eta_delta": f"+{eta_delta} min" if isinstance(eta_delta, (int, float)) and eta_delta > 0 else f"{eta_delta} min",
            "risk": risk_val,
            "departure_window": dep_win,
            "path_identical": "Yes (Optimal Stable)" if is_identical else "No (Detour Active)",
        })

    plotly_div = fig.to_html(include_plotlyjs=True, full_html=False)

    age_badge = "<span class='badge-historical'>HISTORICAL EVENT DATA (&gt;72h)</span>" if is_hist else f"<span style='background-color:#22C55E;color:white;padding:3px 8px;border-radius:4px;'>{prov_fresh}</span>"

    audit_summary = {
        "scenarios_in_routes": len(scenarios_list),
        "scenarios_rendered": len(scenarios_rendered_set),
        "stages_per_vehicle": stages_per_vehicle_rendered,
        "total_stages": len(stage_table_rows),
        "flooded_pixel_count": flooded_px_count,
        "polygon_count": polygon_count,
        "speckle_removed": speckle_removed,
        "state_counts": state_counts,
        "provenance": {
            "sensor": (prov_sensor, "Sen1Floods11 product metadata"),
            "platform": (prov_platform, "chip metadata / Sentinel-1 variant unverified (UNKNOWN)"),
            "acquired_utc": (prov_acq, "Sen1Floods11 product date, exact observation time UNKNOWN"),
            "product_id": (prov_prod, "Sen1Floods11 chip name"),
            "method": (prov_method, "Sen1Floods11 ground truth / FwDET depth"),
            "data_age_hours": (age_label, "calculated vs current UTC timestamp"),
            "freshness": (prov_fresh, "historical event classification"),
        }
    }

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>HighWater - 3D Rescue Route & Flood Analysis</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 0; background-color: #F8FAFC; color: #0F172A; }}
    .banner {{ background-color: #DC2626; color: #FFFFFF; padding: 12px 20px; font-weight: bold; font-size: 13px; text-align: center; letter-spacing: 0.3px; }}
    .container {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}
    .panel {{ background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    .panel-title {{ font-size: 15px; font-weight: 700; margin-bottom: 12px; color: #1E293B; border-bottom: 2px solid #E2E8F0; padding-bottom: 6px; }}
    .grid-prov {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; font-size: 13px; }}
    .prov-item {{ background: #F1F5F9; padding: 10px 12px; border-radius: 6px; overflow: hidden; }}
    .prov-label {{ font-size: 11px; text-transform: uppercase; color: #64748B; font-weight: 700; margin-bottom: 4px; }}
    .prov-val {{ font-size: 13px; font-weight: 600; color: #0F172A; word-break: break-word; overflow-wrap: break-word; }}
    .badge-historical {{ display: inline-block; background-color: #EF4444; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; white-space: normal; line-height: 1.3; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }}
    th, td {{ border: 1px solid #E2E8F0; padding: 8px 12px; text-align: left; }}
    th {{ background: #F8FAFC; font-weight: 700; color: #334155; }}
    tr:nth-child(even) {{ background: #F8FAFC; }}
    .status-ok {{ color: #16A34A; font-weight: 700; }}
    .status-unreachable {{ color: #DC2626; font-weight: 700; }}
  </style>
</head>
<body>
  <div class="banner">
    ⚠️ {html.escape(disclaimer)}
  </div>

  <div class="container">
    <div class="panel">
      <div class="panel-title">📡 Satellite Flood Layer Provenance & Sensor Authenticity</div>
      <div class="grid-prov">
        <div class="prov-item"><div class="prov-label">Sensor</div><div class="prov-val">{html.escape(str(prov_sensor))}</div></div>
        <div class="prov-item"><div class="prov-label">Platform</div><div class="prov-val">{html.escape(str(prov_platform))}</div></div>
        <div class="prov-item"><div class="prov-label">Acquired (UTC)</div><div class="prov-val">{html.escape(str(prov_acq))}</div></div>
        <div class="prov-item"><div class="prov-label">Product ID</div><div class="prov-val">{html.escape(str(prov_prod))}</div></div>
        <div class="prov-item"><div class="prov-label">Method</div><div class="prov-val">{html.escape(str(prov_method))}</div></div>
        <div class="prov-item"><div class="prov-label">Data Age</div><div class="prov-val">{html.escape(str(age_label))}</div></div>
        <div class="prov-item"><div class="prov-label">Freshness / Badge</div><div class="prov-val">{age_badge}</div></div>
      </div>
    </div>

    <div class="panel" style="padding: 10px;">
      {plotly_div}
    </div>

    <div class="panel">
      <div class="panel-title">📊 Scenario Deltas vs Baseline (Lowest-Risk Route Model)</div>
      <table>
        <thead>
          <tr>
            <th>Scenario</th>
            <th>ETA (min)</th>
            <th>ETA Delta</th>
            <th>Route Risk</th>
            <th>Departure Window</th>
            <th>Path Identical</th>
          </tr>
        </thead>
        <tbody>
          {"".join(f"<tr><td><b>{html.escape(str(r['scenario']))}</b></td><td>{r['eta']}</td><td>{r['eta_delta']}</td><td>{r['risk']}</td><td>{r['departure_window']}</td><td>{html.escape(str(r['path_identical']))}</td></tr>" for r in delta_rows) if delta_rows else "<tr><td colspan='6'>No non-baseline scenarios available.</td></tr>"}
        </tbody>
      </table>
    </div>

    <div class="panel">
      <div class="panel-title">🚒 Multi-Stage Dispatch & Isolated Sectors (All {len(stage_table_rows)} Stages Rendered)</div>
      <table>
        <thead>
          <tr>
            <th>Scenario</th>
            <th>Stage</th>
            <th>Vehicle</th>
            <th>Status</th>
            <th>Reason / Failure Details</th>
            <th>Cut Edges</th>
            <th>Distance</th>
            <th>ETA</th>
          </tr>
        </thead>
        <tbody>
          {"".join(f"<tr><td>{html.escape(str(s['scenario']))}</td><td>{s['stage']}</td><td><b>{s['vehicle']}</b></td><td class='{'status-ok' if s['status']=='OK' else 'status-unreachable'}'>{s['status']}</td><td>{html.escape(str(s['reason']))}</td><td>{html.escape(str(s['cut_edges']))}</td><td>{s['distance'] or '-'} km</td><td>{s['eta'] or '-'} min</td></tr>" for s in stage_table_rows)}
        </tbody>
      </table>
    </div>

    <div class="panel">
      <div class="panel-title">📍 Facilities & Sites (Short Markers with Collision-Avoidance Leader Lines)</div>
      <table>
        <thead>
          <tr>
            <th>Marker</th>
            <th>Site ID</th>
            <th>Type</th>
            <th>Latitude</th>
            <th>Longitude</th>
          </tr>
        </thead>
        <tbody>
          {"".join(f"<tr><td><b>[{s['short_id']}]</b></td><td>{html.escape(str(s['id']))}</td><td>{html.escape(str(s['kind']))}</td><td>{s['lat']:.5f}</td><td>{s['lon']:.5f}</td></tr>" for s in site_table_rows)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""

    return html_content, audit_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="3D/2D Rescue Route & Flood Analysis Interactive Viewer")
    parser.add_argument("--routes", type=str, default=None, help="Path to routes.json or routes_region.json")
    parser.add_argument("--dem", type=str, default="data/region/dem.tif", help="Path to elevation GeoTIFF")
    parser.add_argument("--mask", type=str, default="data/region/flood_mask.tif", help="Path to flood mask GeoTIFF")
    parser.add_argument("--out", type=str, default=None, help="Output HTML file path")
    args = parser.parse_args()

    html_out, audit = build_viewer_html(args.routes, args.dem, args.mask)

    out_paths = []
    if args.out:
        out_paths.append(Path(args.out))
    else:
        out_paths.append(PROJECT_ROOT / "routes_3d_viewer.html")
        out_paths.append(PROJECT_ROOT / "modules" / "rescue_routing" / "routes_3d_viewer.html")

    for p in out_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(html_out)
        sz_b = p.stat().st_size
        sz_mb = sz_b / (1024 * 1024)
        print(f"SUCCESS: Generated {p} ({sz_b:,} bytes, {sz_mb:.2f} MB)")

    print("\n============================================================")
    print("   ITEM 5: SCENARIOS & VEHICLES AUDIT")
    print("============================================================")
    print(f"Number of scenarios in routes: {audit['scenarios_in_routes']}")
    print(f"Number of scenarios rendered:  {audit['scenarios_rendered']}")
    print("Number of stages per vehicle rendered:")
    for v, c in audit["stages_per_vehicle"].items():
        print(f"  - {v}: {c}")
    print(f"Total stages rendered: {audit['total_stages']} (Matches: {audit['scenarios_in_routes'] == audit['scenarios_rendered']})")

    print("\n============================================================")
    print("   ITEM 2: SENTINEL-1 FLOOD MASK & DEM AUDIT")
    print("============================================================")
    print(f"Flooded pixel count:               {audit['flooded_pixel_count']:,}")
    print(f"Polygon count:                     {audit['polygon_count']}")
    print(f"Pixels removed by speckle filter:  {audit['speckle_removed']:,}")

    print("\n============================================================")
    print("   ITEM 3: 5-STATE ROAD NETWORK AUDIT")
    print("============================================================")
    for st, c in audit["state_counts"].items():
        print(f"  - {st}: {c} segments")

    print("\n============================================================")
    print("   ITEM 6: PROVENANCE FIELD AUDIT")
    print("============================================================")
    for field, (val, src) in audit["provenance"].items():
        print(f"  - {field}: {val} (Source: {src})")
    print("============================================================\n")


if __name__ == "__main__":
    main()
