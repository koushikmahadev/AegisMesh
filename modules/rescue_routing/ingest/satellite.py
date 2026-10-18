"""Satellite flood mask and SAR ingestion with Otsu thresholding and georeferencing."""

import math
from pathlib import Path
import numpy as np


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters between two points."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def compute_otsu_threshold(values: np.ndarray, num_bins: int = 256) -> float:
    """Compute Otsu threshold on valid 1D values using numpy only."""
    if len(values) == 0:
        return 0.0
    hist, bin_edges = np.histogram(values, bins=num_bins)
    hist = hist.astype(float)
    total = hist.sum()
    if total == 0:
        return float(values[0])

    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    sum_total = float(np.dot(hist, bin_centers))

    current_max = 0.0
    threshold = float(bin_centers[0])
    weight_bg = 0.0
    sum_bg = 0.0

    for i in range(len(hist)):
        weight_bg += hist[i]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break

        sum_bg += hist[i] * bin_centers[i]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg

        between_variance = weight_bg * weight_fg * ((mean_bg - mean_fg) ** 2)
        if between_variance > current_max:
            current_max = between_variance
            threshold = float(bin_centers[i])

    return threshold


def load_satellite_mask(
    mask_path: str | Path | None = None,
    sar_path: str | Path | None = None,
    bounds: tuple[float, float, float, float] | list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, any, any, float, str]:
    """Read water mask or derive from SAR; return (water_mask, nodata_mask, transform, crs, pixel_size_m, mask_source)."""
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.crs import CRS

    if sar_path is not None:
        p = Path(sar_path)
        if not p.exists():
            raise FileNotFoundError(f"SAR file not found: {sar_path}")
        with rasterio.open(p) as src:
            arr = src.read(1).astype(float)
            transform = src.transform
            crs = src.crs or CRS.from_epsg(4326)
            nodata_val = src.nodata

        if bounds is not None:
            w, s, e, n = bounds
            transform = from_bounds(w, s, e, n, arr.shape[1], arr.shape[0])
            crs = CRS.from_epsg(4326)

        nodata_mask = np.isnan(arr) | np.isinf(arr)
        if nodata_val is not None:
            nodata_mask |= np.isclose(arr, nodata_val)

        valid_vals = arr[~nodata_mask]
        thresh = compute_otsu_threshold(valid_vals)
        water_mask = (arr < thresh) & (~nodata_mask)
        mask_source = "sar_otsu"

    elif mask_path is not None:
        p = Path(mask_path)
        if not p.exists():
            raise FileNotFoundError(f"Mask file not found: {mask_path}")
        with rasterio.open(p) as src:
            arr = src.read(1)
            transform = src.transform
            crs = src.crs
            nodata_val = src.nodata

        if bounds is not None:
            w, s, e, n = bounds
            transform = from_bounds(w, s, e, n, arr.shape[1], arr.shape[0])
            crs = CRS.from_epsg(4326)
        elif crs is None:
            crs = CRS.from_epsg(4326)

        nodata_mask = (arr == -1)
        if nodata_val is not None and not np.isnan(nodata_val):
            nodata_mask |= (arr == nodata_val)
        if np.issubdtype(arr.dtype, np.floating):
            nodata_mask |= np.isnan(arr)

        water_mask = (arr == 1) & (~nodata_mask)
        mask_source = "mask"
    else:
        raise ValueError("Either mask_path or sar_path must be provided")

    # calculate pixel size in meters
    is_proj = getattr(crs, "is_projected", False)
    if is_proj:
        pixel_size_m = float((abs(transform.a) + abs(transform.e)) / 2.0)
    else:
        h, w = arr.shape
        left, bottom, right, top = rasterio.transform.array_bounds(h, w, transform)
        center_lat = (bottom + top) / 2.0
        center_lon = (left + right) / 2.0
        dx_deg = abs(transform.a)
        dy_deg = abs(transform.e)
        dx_m = haversine_m(center_lon, center_lat, center_lon + dx_deg, center_lat)
        dy_m = haversine_m(center_lon, center_lat, center_lon, center_lat + dy_deg)
        pixel_size_m = float((dx_m + dy_m) / 2.0)

    return water_mask, nodata_mask, transform, crs, pixel_size_m, mask_source
