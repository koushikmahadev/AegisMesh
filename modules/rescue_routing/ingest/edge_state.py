"""Populate edge flood state, FwDET depth, distance to water, and elevation."""

import math
from pathlib import Path
import numpy as np
import networkx as nx

MIN_FLOOD_RUN_M = 20.0  # sar speckle filter: runs shorter than 20m ignored
ASSUMED_FLOOD_DEPTH_M = 0.6  # binary mask depth proxy: blocks ambulance (0.3m) and truck (0.5m)
SAMPLE_SPACING_M = 10.0  # polyline sample interval in meters


def _sample_polyline(coords: list[list[float]]) -> tuple[np.ndarray, np.ndarray, float]:
    """Sample polyline coordinates approximately every 10 meters."""
    pts = np.array(coords, dtype=float)
    lons = pts[:, 0]
    lats = pts[:, 1]
    if len(pts) < 2:
        return lons, lats, SAMPLE_SPACING_M

    # calculate segment lengths using haversine
    dphi = np.radians(lats[1:] - lats[:-1])
    dlambda = np.radians(lons[1:] - lons[:-1])
    phi1 = np.radians(lats[:-1])
    phi2 = np.radians(lats[1:])
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    seg_dists = 2.0 * 6371000.0 * np.arctan2(np.sqrt(a), np.sqrt(np.maximum(0.0, 1.0 - a)))
    cum_dists = np.insert(np.cumsum(seg_dists), 0, 0.0)
    total_dist = float(cum_dists[-1])

    num_samples = max(2, int(round(total_dist / SAMPLE_SPACING_M)) + 1)
    target_dists = np.linspace(0.0, total_dist, num_samples)
    step_dist = float(total_dist / (num_samples - 1)) if num_samples > 1 else SAMPLE_SPACING_M
    sample_lons = np.interp(target_dists, cum_dists, lons)
    sample_lats = np.interp(target_dists, cum_dists, lats)
    return sample_lons, sample_lats, step_dist


def populate_edge_state(
    graph: nx.Graph,
    water_mask: np.ndarray,
    nodata_mask: np.ndarray,
    transform: any,
    crs: any,
    pixel_size_m: float,
    dem_path: str | Path | None = None,
    permanent_water_path: str | Path | None = None,
) -> tuple[str, str]:
    """Populate graph edge flood depths, coverage, river distances, and elevations. Returns (depth_method, risk_model)."""
    import rasterio
    from rasterio.warp import reproject, Resampling, transform as warp_coords
    from scipy.ndimage import distance_transform_edt, binary_dilation

    # 1. Permanent water / river distance precomputation
    if permanent_water_path is not None and Path(permanent_water_path).exists():
        with rasterio.open(permanent_water_path) as p_src:
            if p_src.shape != water_mask.shape or p_src.transform != transform:
                p_arr = np.zeros(water_mask.shape, dtype=np.int16)
                reproject(
                    source=rasterio.band(p_src, 1),
                    destination=p_arr,
                    src_transform=p_src.transform,
                    src_crs=p_src.crs,
                    dst_transform=transform,
                    dst_crs=crs,
                    resampling=Resampling.nearest,
                )
            else:
                p_arr = p_src.read(1)
        perm_water = (p_arr == 1)
    else:
        perm_water = water_mask

    river_dist_grid_m = distance_transform_edt(~perm_water) * pixel_size_m

    # 2. DEM and FwDET depth precomputation
    dem_aligned = None
    depth_grid = None
    if dem_path is not None and Path(dem_path).exists():
        with rasterio.open(dem_path) as d_src:
            if d_src.shape != water_mask.shape or d_src.transform != transform:
                dem_aligned = np.zeros(water_mask.shape, dtype=np.float32)
                reproject(
                    source=rasterio.band(d_src, 1),
                    destination=dem_aligned,
                    src_transform=d_src.transform,
                    src_crs=d_src.crs,
                    dst_transform=transform,
                    dst_crs=crs,
                    resampling=Resampling.bilinear,
                )
            else:
                dem_aligned = d_src.read(1).astype(float)

        boundary = water_mask & binary_dilation(~water_mask)
        if np.any(boundary):
            _, (near_r, near_c) = distance_transform_edt(~boundary, return_indices=True)
            water_surface = dem_aligned[near_r, near_c]
            depth_grid = np.maximum(0.0, water_surface - dem_aligned)
            depth_grid[~water_mask] = 0.0
        else:
            depth_grid = np.zeros_like(dem_aligned)
        depth_method = "satellite_mask_dem"
        risk_model = "heuristic_uncalibrated"
    else:
        depth_method = "satellite_mask_assumed"
        risk_model = "heuristic_uncalibrated_no_dem"

    # 3. Vectorized sampling and attribution for every edge
    h, w = water_mask.shape
    inv_tf = ~transform
    is_proj = getattr(crs, "is_projected", False)

    for u, v, data in graph.edges(data=True):
        coords = data.get("geometry")
        if not coords or len(coords) < 2:
            u_node = graph.nodes[u]
            v_node = graph.nodes[v]
            coords = [[u_node["lon"], u_node["lat"]], [v_node["lon"], v_node["lat"]]]

        sample_lons, sample_lats, step_dist = _sample_polyline(coords)

        if is_proj:
            xs, ys = warp_coords("EPSG:4326", crs, sample_lons.tolist(), sample_lats.tolist())
            xs, ys = np.array(xs), np.array(ys)
        else:
            xs, ys = sample_lons, sample_lats

        cols = np.floor(inv_tf.a * xs + inv_tf.b * ys + inv_tf.c).astype(int)
        rows = np.floor(inv_tf.d * xs + inv_tf.e * ys + inv_tf.f).astype(int)

        valid_bounds = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        r_idx = np.clip(rows, 0, h - 1)
        c_idx = np.clip(cols, 0, w - 1)

        nodata_pts = nodata_mask[r_idx, c_idx] | (~valid_bounds)
        nodata_fraction = float(np.mean(nodata_pts))
        coverage = "GAP" if nodata_fraction > 0.5 else "OK"

        flooded_pts = water_mask[r_idx, c_idx] & (~nodata_pts)
        retained_flooded = flooded_pts.copy()

        # filter runs < MIN_FLOOD_RUN_M (distance between first and last sample of run)
        if np.any(flooded_pts):
            padded = np.pad(flooded_pts.astype(np.int8), (1, 1), mode="constant")
            diffs = np.diff(padded)
            starts = np.where(diffs == 1)[0]
            ends = np.where(diffs == -1)[0]
            for s, e in zip(starts, ends):
                run_len_m = max(0.0, (e - s - 1) * step_dist)
                if run_len_m < MIN_FLOOD_RUN_M:
                    retained_flooded[s:e] = False

        if dem_aligned is not None:
            if np.any(retained_flooded):
                fl_depths = depth_grid[r_idx, c_idx][retained_flooded]
                edge_depth = float(np.percentile(fl_depths, 90))
            else:
                edge_depth = 0.0
            edge_elev = float(np.min(dem_aligned[r_idx, c_idx]))
            depth_src = "satellite_mask_dem"
        else:
            edge_depth = ASSUMED_FLOOD_DEPTH_M if np.any(retained_flooded) else 0.0
            edge_elev = None
            depth_src = "satellite_mask_assumed"

        edge_dist_river = float(np.min(river_dist_grid_m[r_idx, c_idx]))

        data["current_water_depth_meters"] = round(edge_depth, 3)
        data["depth_source"] = depth_src
        data["satellite_coverage"] = coverage
        data["nodata_fraction"] = round(nodata_fraction, 3)
        data["distance_to_river_meters"] = round(edge_dist_river, 1)
        data["elevation_meters"] = round(edge_elev, 1) if edge_elev is not None else None

    return depth_method, risk_model
