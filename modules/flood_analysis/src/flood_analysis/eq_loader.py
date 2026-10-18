"""Earthquake data loader: parses USGS ShakeMap grid and samples MMI for OSM features."""
import json
import os
import xml.etree.ElementTree as ET
from typing import Any, List, Optional, Tuple, Union

import numpy as np
from shapely.geometry import shape

from flood_analysis.processor import Feature


class ShakeMapGrid(tuple):
    """Container for ShakeMap grid data that unpacks as (lon, lat, mmi)."""

    def __new__(cls, lon: np.ndarray, lat: np.ndarray, mmi: np.ndarray):
        return super().__new__(cls, (lon, lat, mmi))

    @property
    def lon(self) -> np.ndarray:
        return self[0]

    @property
    def lat(self) -> np.ndarray:
        return self[1]

    @property
    def mmi(self) -> np.ndarray:
        return self[2]


_GRID_INTERP_CACHE: dict = {}


def parse_shakemap_grid(path: str) -> ShakeMapGrid:
    """Parse USGS ShakeMap grid.xml, returning numpy arrays (lon, lat, mmi).

    Reads the <grid_field> entries from grid.xml to find the MMI column index,
    handling the XML namespace.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0][1:]
    ns_prefix = f"{{{ns}}}" if ns else ""

    fields = root.findall(f"{ns_prefix}grid_field")
    if not fields:
        fields = [c for c in root.iter() if c.tag.endswith("grid_field")]

    col_map = {}
    for i, f in enumerate(fields):
        name = f.attrib.get("name", "").upper()
        idx = int(f.attrib.get("index", i + 1)) - 1
        col_map[name] = idx

    lon_col = col_map.get("LON", 0)
    lat_col = col_map.get("LAT", 1)
    mmi_col = col_map.get("MMI", 2)

    grid_data_el = root.find(f"{ns_prefix}grid_data")
    if grid_data_el is None:
        for c in root.iter():
            if c.tag.endswith("grid_data"):
                grid_data_el = c
                break

    if grid_data_el is None or not grid_data_el.text:
        raise ValueError(f"No grid_data found in {path}")

    ncols = len(fields) if fields else max(lon_col, lat_col, mmi_col) + 1
    arr = np.fromstring(grid_data_el.text.strip(), sep=" ").reshape(-1, ncols)

    lon_arr = arr[:, lon_col]
    lat_arr = arr[:, lat_col]
    mmi_arr = arr[:, mmi_col]

    return ShakeMapGrid(lon_arr, lat_arr, mmi_arr)


def _build_interpolator(lon_arr: np.ndarray, lat_arr: np.ndarray, mmi_arr: np.ndarray):
    """Build a fast bilinear or nearest-neighbor interpolation function."""
    u_lons = np.unique(lon_arr)
    u_lats = np.unique(lat_arr)
    n_lon = len(u_lons)
    n_lat = len(u_lats)

    is_regular = (n_lon * n_lat == len(mmi_arr)) and (n_lon >= 2) and (n_lat >= 2)

    if is_regular:
        lon_idx = np.searchsorted(u_lons, lon_arr)
        lat_idx = np.searchsorted(u_lats, lat_arr)
        mmi_2d = np.empty((n_lat, n_lon), dtype=float)
        mmi_2d[lat_idx, lon_idx] = mmi_arr

        def bilinear_sampler(q_lons: Any, q_lats: Any):
            q_lo = np.asarray(q_lons, dtype=float)
            q_la = np.asarray(q_lats, dtype=float)
            is_scalar = (q_lo.ndim == 0 and q_la.ndim == 0)
            q_lo = np.atleast_1d(q_lo)
            q_la = np.atleast_1d(q_la)

            lo_idx = np.searchsorted(u_lons, q_lo) - 1
            lo_idx = np.clip(lo_idx, 0, len(u_lons) - 2)
            la_idx = np.searchsorted(u_lats, q_la) - 1
            la_idx = np.clip(la_idx, 0, len(u_lats) - 2)

            lat0, lat1 = u_lats[la_idx], u_lats[la_idx + 1]
            lon0, lon1 = u_lons[lo_idx], u_lons[lo_idx + 1]

            d_lat = np.where(lat1 != lat0, lat1 - lat0, 1.0)
            d_lon = np.where(lon1 != lon0, lon1 - lon0, 1.0)

            t_lat = np.clip((q_la - lat0) / d_lat, 0.0, 1.0)
            t_lon = np.clip((q_lo - lon0) / d_lon, 0.0, 1.0)

            v00 = mmi_2d[la_idx, lo_idx]
            v01 = mmi_2d[la_idx, lo_idx + 1]
            v10 = mmi_2d[la_idx + 1, lo_idx]
            v11 = mmi_2d[la_idx + 1, lo_idx + 1]

            val = (
                (1.0 - t_lat) * (1.0 - t_lon) * v00
                + (1.0 - t_lat) * t_lon * v01
                + t_lat * (1.0 - t_lon) * v10
                + t_lat * t_lon * v11
            )
            return float(val[0]) if is_scalar else val

        return bilinear_sampler
    else:
        # Nearest neighbor interpolation for irregular grid
        try:
            from scipy.spatial import cKDTree

            tree = cKDTree(np.column_stack([lat_arr, lon_arr]))

            def nearest_sampler(q_lons: Any, q_lats: Any):
                q_lo = np.asarray(q_lons, dtype=float)
                q_la = np.asarray(q_lats, dtype=float)
                is_scalar = (q_lo.ndim == 0 and q_la.ndim == 0)
                pts = np.column_stack([np.atleast_1d(q_la), np.atleast_1d(q_lo)])
                _, idx = tree.query(pts)
                res = mmi_arr[idx]
                return float(res[0]) if is_scalar else res

            return nearest_sampler
        except ImportError:
            pts_grid = np.column_stack([lat_arr, lon_arr])

            def nearest_sampler_np(q_lons: Any, q_lats: Any):
                q_lo = np.asarray(q_lons, dtype=float)
                q_la = np.asarray(q_lats, dtype=float)
                is_scalar = (q_lo.ndim == 0 and q_la.ndim == 0)
                q_lo_1d = np.atleast_1d(q_lo)
                q_la_1d = np.atleast_1d(q_la)
                res = []
                for qy, qx in zip(q_la_1d, q_lo_1d):
                    dist2 = (pts_grid[:, 0] - qy) ** 2 + (pts_grid[:, 1] - qx) ** 2
                    res.append(mmi_arr[np.argmin(dist2)])
                arr_res = np.array(res, dtype=float)
                return float(arr_res[0]) if is_scalar else arr_res

            return nearest_sampler_np


def sample_mmi(grid: Any, lon: Any, lat: Any) -> Any:
    """Sample MMI at (lon, lat) via bilinear (or nearest if irregular) interpolation."""
    if isinstance(grid, (tuple, list)):
        lon_arr, lat_arr, mmi_arr = grid[0], grid[1], grid[2]
    elif isinstance(grid, dict):
        lon_arr, lat_arr, mmi_arr = grid["lon"], grid["lat"], grid["mmi"]
    else:
        lon_arr, lat_arr, mmi_arr = grid.lon, grid.lat, grid.mmi

    cache_key = (id(lon_arr), id(lat_arr), id(mmi_arr))
    sampler = _GRID_INTERP_CACHE.get(cache_key)
    if sampler is None:
        sampler = _build_interpolator(lon_arr, lat_arr, mmi_arr)
        _GRID_INTERP_CACHE[cache_key] = sampler

    return sampler(lon, lat)


def _print_percentiles(name: str, values: List[float]) -> None:
    if not values:
        print(f"{name} MMI: no features loaded")
        return
    vmin = float(np.min(values))
    p10 = float(np.percentile(values, 10))
    p50 = float(np.percentile(values, 50))
    p90 = float(np.percentile(values, 90))
    vmax = float(np.max(values))
    print(
        f"{name} MMI percentiles (n={len(values)}): "
        f"min={vmin:.2f}, p10={p10:.2f}, p50={p50:.2f}, p90={p90:.2f}, max={vmax:.2f}"
    )


def load_eq_features(
    input_dir: str,
    mmi_building: float = 7.0,
    mmi_road: float = 8.0,
) -> List[Feature]:
    """Load earthquake features, sample MMI, and return Feature objects.

    For each building use centroid MMI; for each road use max MMI sampled
    along vertices. flooded = (mmi >= threshold). Dedup by OSM id like
    load_tile_features does.
    """
    grid_path = os.path.join(input_dir, "grid.xml")
    buildings_path = os.path.join(input_dir, "buildings.geojson")
    roads_path = os.path.join(input_dir, "roads.geojson")

    grid = parse_shakemap_grid(grid_path)

    seen: dict = {}

    # 1. Buildings
    b_features_raw: List[Tuple[str, Any, float, float]] = []
    if os.path.exists(buildings_path):
        with open(buildings_path, "r", encoding="utf-8") as f:
            b_data = json.load(f)
        for item in b_data.get("features", []):
            if not item.get("geometry"):
                continue
            geom = shape(item["geometry"])
            if geom.is_empty:
                continue
            if geom.geom_type not in ("Polygon", "MultiPolygon"):
                continue

            fid = item.get("id")
            if not fid and item.get("properties"):
                fid = item["properties"].get("id") or item["properties"].get("@id")
            key = str(fid) if fid else f"building-{geom.wkb_hex[:16]}"
            if key in seen:
                continue
            seen[key] = True

            c = geom.centroid
            b_features_raw.append((key, geom, c.x, c.y))

    b_mmis: List[float] = []
    if b_features_raw:
        q_lons = [item[2] for item in b_features_raw]
        q_lats = [item[3] for item in b_features_raw]
        b_samples = sample_mmi(grid, q_lons, q_lats)
        b_mmis = [float(v) for v in np.atleast_1d(b_samples)]

    # 2. Roads
    r_features_raw: List[Tuple[str, Any, List[Tuple[float, float]]]] = []
    if os.path.exists(roads_path):
        with open(roads_path, "r", encoding="utf-8") as f:
            r_data = json.load(f)
        for item in r_data.get("features", []):
            if not item.get("geometry"):
                continue
            geom = shape(item["geometry"])
            if geom.is_empty:
                continue
            if geom.geom_type in ("Polygon", "MultiPolygon"):
                geom = geom.boundary
            if geom.geom_type not in ("LineString", "MultiLineString") or geom.is_empty:
                continue

            fid = item.get("id")
            if not fid and item.get("properties"):
                fid = item["properties"].get("id") or item["properties"].get("@id")
            key = str(fid) if fid else f"road-{geom.wkb_hex[:16]}"
            if key in seen:
                continue
            seen[key] = True

            if geom.geom_type == "LineString":
                coords = list(geom.coords)
            else:
                coords = [pt for line in geom.geoms for pt in line.coords]
            if not coords:
                continue
            r_features_raw.append((key, geom, coords))

    r_mmis: List[float] = []
    if r_features_raw:
        all_coords = []
        slices = []
        curr = 0
        for item in r_features_raw:
            coords = item[2]
            all_coords.extend(coords)
            slices.append((curr, curr + len(coords)))
            curr += len(coords)

        all_lons = [pt[0] for pt in all_coords]
        all_lats = [pt[1] for pt in all_coords]
        all_samples = np.atleast_1d(sample_mmi(grid, all_lons, all_lats))

        for start, end in slices:
            road_mmi = float(np.max(all_samples[start:end]))
            r_mmis.append(road_mmi)

    # Print percentiles before applying thresholds
    _print_percentiles("Building", b_mmis)
    _print_percentiles("Road", r_mmis)

    # Build Feature objects
    features: List[Feature] = []
    for (key, geom, _, _), mmi_val in zip(b_features_raw, b_mmis):
        flooded = bool(mmi_val >= mmi_building)
        features.append(
            Feature(
                id=key,
                kind="building",
                flooded=flooded,
                geometry=geom,
                hazard_value=mmi_val,
            )
        )

    for (key, geom, _), mmi_val in zip(r_features_raw, r_mmis):
        flooded = bool(mmi_val >= mmi_road)
        features.append(
            Feature(
                id=key,
                kind="road",
                flooded=flooded,
                geometry=geom,
                hazard_value=mmi_val,
            )
        )

    return features
