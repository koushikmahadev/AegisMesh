"""Flood analysis processing: builds flood extent, zone grid, and per-feature
flood status layers from SN8 Germany vector annotations (already EPSG:4326).

No flood-extent raster exists in the SN8 Germany annotations (PRE/POST tifs are
plain RGB imagery). Flood extent is therefore derived from labelled flooded
buildings/roads, not a measured water boundary.
"""
import glob
import json
import math
from dataclasses import dataclass, field

import pyproj
from shapely.geometry import box, shape, mapping
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union
from shapely.validation import make_valid

GRID_CELL_SIZE_M = 300.0
ROAD_BUFFER_M = 5.0  # half-width used only to turn flooded road lines into polygons for the derived flood extent
ACCESSIBILITY_THRESHOLDS = {"ACCESSIBLE": 0.10, "PARTIAL": 0.60}  # flooded_road_share upper bounds


def utm_crs_for(lon, lat):
    zone = int(math.floor((lon + 180) / 6) % 60) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return f"EPSG:{epsg}"


@dataclass
class Feature:
    id: str
    kind: str  # "building" or "road"
    flooded: bool
    geometry: object  # shapely geometry in EPSG:4326


def load_tile_features(raw_dir, tile_ids):
    """Load and dedup features (by id) from the chosen annotation tiles."""
    import os

    seen = {}
    for tile_id in tile_ids:
        fp = f"{raw_dir}/annotations/{tile_id}.geojson"
        if not os.path.exists(fp):
            continue
        d = json.load(open(fp))
        for f in d["features"]:
            p = f["properties"]
            fid = p.get("id")
            if p.get("building") is not None:
                kind = "building"
            elif p.get("highway") is not None:
                kind = "road"
            else:
                continue
            geom = shape(f["geometry"])
            if geom.is_empty:
                continue
            flooded = p.get("flooded") == "yes"
            key = fid or f"{kind}-{geom.wkb_hex}"
            if key in seen:
                continue
            seen[key] = Feature(id=key, kind=kind, flooded=flooded, geometry=geom)
    return list(seen.values())


def build_aoi(features):
    return box(*unary_union([f.geometry for f in features]).bounds)


AOI_WINDOW_ROWS = 6
AOI_WINDOW_COLS = 4
AOI_MIN_TILES_PRESENT = 12  # out of window_rows*window_cols=24; below this a window is too sparse/rural


def _tile_stats(raw_dir):
    """Per-tile (prefix, row, col) -> counts, parsed once from every annotation file.

    Tile ids follow SN8's own naming, '{prefix}_{row}_{col}.geojson'; prefix groups
    tiles into separate spatial swaths (Germany only has one, Louisiana has several),
    so AOI search must stay within a single prefix group.
    """
    import os
    import re

    pattern = re.compile(r"^(\d+)_(\d+)_(\d+)\.geojson$")
    stats = {}
    ann_dir = os.path.join(raw_dir, "annotations")
    for fname in os.listdir(ann_dir):
        m = pattern.match(fname)
        if not m:
            continue
        prefix, row, col = m.group(1), int(m.group(2)), int(m.group(3))
        d = json.load(open(os.path.join(ann_dir, fname)))
        n_buildings = n_roads = n_flooded_buildings = n_flooded_roads = 0
        for f in d["features"]:
            p = f["properties"]
            flooded = p.get("flooded") == "yes"
            if p.get("building") is not None:
                n_buildings += 1
                n_flooded_buildings += flooded
            elif p.get("highway") is not None:
                n_roads += 1
                n_flooded_roads += flooded
        stats[(prefix, row, col)] = {
            "tile_id": f"{prefix}_{row}_{col}",
            "buildings": n_buildings,
            "roads": n_roads,
            "flooded_buildings": n_flooded_buildings,
            "flooded_roads": n_flooded_roads,
        }
    return stats


def build_tile_index(raw_dir):
    """Per-tile id -> {bbox, buildings, roads, flooded_buildings, flooded_roads},
    for every tile in the dataset. Used client-side (map.html draw-box mode) to
    compute live tile-count/flooded-mix previews without a backend — the map just
    fetches this precomputed JSON and does the box-overlap math itself.
    """
    import os
    import re

    pattern = re.compile(r"^(\d+)_(\d+)_(\d+)\.geojson$")
    index = {}
    ann_dir = os.path.join(raw_dir, "annotations")
    for fname in os.listdir(ann_dir):
        m = pattern.match(fname)
        if not m:
            continue
        tile_id = f"{m.group(1)}_{m.group(2)}_{m.group(3)}"
        d = json.load(open(os.path.join(ann_dir, fname)))
        n_buildings = n_roads = n_flooded_buildings = n_flooded_roads = 0
        geoms = []
        for f in d["features"]:
            p = f["properties"]
            flooded = p.get("flooded") == "yes"
            if p.get("building") is not None:
                n_buildings += 1
                n_flooded_buildings += flooded
            elif p.get("highway") is not None:
                n_roads += 1
                n_flooded_roads += flooded
            else:
                continue
            geoms.append(shape(f["geometry"]))
        bbox = list(unary_union(geoms).bounds) if geoms else None
        index[tile_id] = {
            "bbox": bbox,
            "buildings": n_buildings,
            "roads": n_roads,
            "flooded_buildings": n_flooded_buildings,
            "flooded_roads": n_flooded_roads,
        }
    return index


def select_aoi_tile_ids(
    raw_dir,
    window_rows=AOI_WINDOW_ROWS,
    window_cols=AOI_WINDOW_COLS,
    min_tiles_present=AOI_MIN_TILES_PRESENT,
):
    """Pick a compact, contiguous tile block with a real flooded/non-flooded mix.

    Works for any SN8-format dataset (no hardcoded tile numbers): scans every
    tile's per-feature counts once, then slides a window_rows x window_cols
    rectangle (within a single tile-id prefix group, since different prefixes
    are separate, non-contiguous swaths) and scores each candidate window by
    feature density, requiring both a flooded and a non-flooded example among
    its buildings/roads so the AOI isn't degenerate (all-flooded or all-dry).
    """
    stats = _tile_stats(raw_dir)
    if not stats:
        raise RuntimeError(f"No annotation tiles found under {raw_dir}/annotations")

    by_prefix = {}
    for (prefix, row, col), s in stats.items():
        by_prefix.setdefault(prefix, {})[(row, col)] = s

    best = None  # (score, tile_ids)
    for prefix, tiles in by_prefix.items():
        rows = sorted(set(r for r, c in tiles))
        cols = sorted(set(c for r, c in tiles))
        for r0 in range(min(rows), max(rows) + 1):
            for c0 in range(min(cols), max(cols) + 1):
                window = [
                    tiles[(r, c)]
                    for r in range(r0, r0 + window_rows)
                    for c in range(c0, c0 + window_cols)
                    if (r, c) in tiles
                ]
                if len(window) < min_tiles_present:
                    continue
                flooded_b = sum(w["flooded_buildings"] for w in window)
                flooded_r = sum(w["flooded_roads"] for w in window)
                dry_b = sum(w["buildings"] - w["flooded_buildings"] for w in window)
                dry_r = sum(w["roads"] - w["flooded_roads"] for w in window)
                has_mix = (flooded_b > 0 or flooded_r > 0) and (dry_b > 0 or dry_r > 0)
                if not has_mix:
                    continue
                density = sum(w["buildings"] + w["roads"] for w in window)
                compactness = len(window) / (window_rows * window_cols)
                # Score favors a genuine, balanced mix (not just >0 on each side) over
                # raw density — the minority class size (flooded or dry, whichever is
                # smaller) is the main driver, density/compactness only break ties.
                mix_quality = min(flooded_b + flooded_r, dry_b + dry_r)
                score = (mix_quality, density * compactness)
                if best is None or score > best[0]:
                    best = (score, [w["tile_id"] for w in window])

    if best is None:
        raise RuntimeError(
            f"No {window_rows}x{window_cols} tile window under {raw_dir}/annotations had both "
            f"flooded and non-flooded buildings/roads with >= {min_tiles_present} tiles present"
        )
    return best[1]


def to_utm_transformer(aoi):
    c = aoi.centroid
    utm_epsg = utm_crs_for(c.x, c.y)
    fwd = pyproj.Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True).transform
    inv = pyproj.Transformer.from_crs(utm_epsg, "EPSG:4326", always_xy=True).transform
    return utm_epsg, fwd, inv


def derive_flood_extent(features, fwd):
    """Union of flooded building polygons and buffered flooded road lines, in UTM."""
    polys = []
    for f in features:
        if not f.flooded:
            continue
        g_utm = shp_transform(fwd, f.geometry)
        if f.kind == "building":
            polys.append(g_utm if g_utm.geom_type in ("Polygon", "MultiPolygon") else g_utm.buffer(0))
        else:
            polys.append(g_utm.buffer(ROAD_BUFFER_M))
    if not polys:
        return None
    merged = unary_union(polys)
    if not merged.is_valid:
        merged = make_valid(merged)
    merged = merged.simplify(1.0, preserve_topology=True)
    return merged


def accessibility_for(flooded_share):
    if flooded_share is None:
        return "UNKNOWN"
    if flooded_share < ACCESSIBILITY_THRESHOLDS["ACCESSIBLE"]:
        return "ACCESSIBLE"
    if flooded_share < ACCESSIBILITY_THRESHOLDS["PARTIAL"]:
        return "PARTIAL"
    return "BLOCKED"


def build_zones(features, aoi, fwd, inv, flood_extent_utm, cell_size_m=GRID_CELL_SIZE_M):
    aoi_utm = shp_transform(fwd, aoi)
    minx, miny, maxx, maxy = aoi_utm.bounds
    ncols = max(1, math.ceil((maxx - minx) / cell_size_m))
    nrows = max(1, math.ceil((maxy - miny) / cell_size_m))

    buildings = [f for f in features if f.kind == "building"]
    roads = [f for f in features if f.kind == "road"]
    buildings_utm = [(f, shp_transform(fwd, f.geometry)) for f in buildings]
    roads_utm = [(f, shp_transform(fwd, f.geometry)) for f in roads]

    zones = []
    zi = 0
    for row in range(nrows):
        for col in range(ncols):
            cx0, cy0 = minx + col * cell_size_m, miny + row * cell_size_m
            cx1, cy1 = min(cx0 + cell_size_m, maxx), min(cy0 + cell_size_m, maxy)
            cell = box(cx0, cy0, cx1, cy1)

            cell_buildings = [(f, g) for f, g in buildings_utm if g.intersects(cell)]
            cell_roads = [(f, g) for f, g in roads_utm if g.intersects(cell)]
            if not cell_buildings and not cell_roads:
                continue

            total_buildings = len(cell_buildings)
            exposed_buildings = sum(1 for f, g in cell_buildings if f.flooded)

            road_length_m = sum(g.intersection(cell).length for f, g in cell_roads)
            flooded_road_length_m = sum(
                g.intersection(cell).length for f, g in cell_roads if f.flooded
            )

            if flood_extent_utm is not None and not flood_extent_utm.is_empty:
                flooded_area_m2 = flood_extent_utm.intersection(cell).area
                flooded_percent = round(100.0 * flooded_area_m2 / cell.area, 2)
            else:
                flooded_area_m2 = None
                flooded_percent = 0.0

            if cell_roads and road_length_m > 0:
                accessibility = accessibility_for(flooded_road_length_m / road_length_m)
            else:
                accessibility = "UNKNOWN"

            cell_lonlat = shp_transform(inv, cell)
            minlon, minlat, maxlon, maxlat = cell_lonlat.bounds
            centroid = cell_lonlat.centroid

            zi += 1
            zones.append(
                {
                    "zone_id": f"zone-{zi:03d}",
                    "bbox": [minlon, minlat, maxlon, maxlat],
                    "centroid": [centroid.x, centroid.y],
                    "flooded_percent": flooded_percent,
                    "flooded_area_m2": round(flooded_area_m2, 1) if flooded_area_m2 is not None else None,
                    "total_buildings": total_buildings,
                    "exposed_buildings": exposed_buildings,
                    "road_length_m": round(road_length_m, 1),
                    "flooded_road_length_m": round(flooded_road_length_m, 1),
                    "accessibility": accessibility,
                }
            )
    return zones


def features_to_geojson(features, kind, inv):
    feats = []
    for f in features:
        if f.kind != kind:
            continue
        feats.append(
            {
                "type": "Feature",
                "properties": {"id": f.id, "flooded": bool(f.flooded)},
                "geometry": mapping(f.geometry),
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def flood_extent_to_geojson(flood_extent_utm, inv):
    if flood_extent_utm is None or flood_extent_utm.is_empty:
        return {"type": "FeatureCollection", "features": []}
    geom_lonlat = shp_transform(inv, flood_extent_utm)
    geoms = [geom_lonlat] if geom_lonlat.geom_type == "Polygon" else list(geom_lonlat.geoms)
    feats = []
    for i, g in enumerate(geoms):
        if g.is_empty:
            continue
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "source": "derived_from_labelled_flooded_buildings_roads",
                    "label_class": "derived_flood_extent",
                },
                "geometry": mapping(g),
            }
        )
    return {"type": "FeatureCollection", "features": feats}
