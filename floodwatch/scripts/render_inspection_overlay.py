"""
Render Static Inspection Overlay for Tile 0_41_58.

Draws:
1. POST-event RGB imagery (base)
2. Fast-mode predicted flood polygons from exports/flood_extent_predicted_fast.geojson (cyan)
3. Observed ground-truth buildings from exports/flood_extent_groundtruth.geojson (amber)
4. Observed ground-truth roads from exports/flood_extent_groundtruth.geojson (red linestrings)
5. Clear legend and provenance disclosures

Saved to: docs/inspection/0_41_58_overlay.png
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont
import torch.nn.functional as F

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

proj_dir = os.path.join(os.path.dirname(rasterio.__file__), "proj_data")
os.environ["PROJ_DATA"] = proj_dir
os.environ["PROJ_LIB"] = proj_dir

from src.flood_inference import find_tile_paths, load_rgb

TILE_ID = "0_41_58"
EXPORTS_DIR = os.path.join(REPO_ROOT, "exports")
INSPECTION_DIR = os.path.join(REPO_ROOT, "docs", "inspection")
OUT_PATH = os.path.join(INSPECTION_DIR, "0_41_58_overlay.png")


def geo_to_pixel(coords, inv_transform):
    """Convert (lon, lat) coordinates to pixel (col, row) coordinates."""
    pts = []
    for pt in coords:
        col, row = inv_transform * (pt[0], pt[1])
        pts.append((col, row))
    return pts


def render_overlay():
    os.makedirs(INSPECTION_DIR, exist_ok=True)

    # 1. Load POST image matched to PRE grid
    pre_p, post_p = find_tile_paths(TILE_ID)
    pre_t = load_rgb(pre_p)
    post_t = load_rgb(post_p)
    if pre_t.shape != post_t.shape:
        post_t = F.interpolate(post_t.unsqueeze(0), size=pre_t.shape[-2:], mode="bilinear", align_corners=False)[0]

    H, W = pre_t.shape[-2:]
    with rasterio.open(pre_p) as src:
        transform = src.transform
        inv_transform = ~transform

    post_np = (post_t.permute(1, 2, 0).numpy() * 255.0).clip(0, 255).astype(np.uint8)
    base_img = Image.fromarray(post_np).convert("RGBA")

    # 2. Create separate transparent layers for predictions and ground truth
    pred_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pred_draw = ImageDraw.Draw(pred_layer)

    gt_bldg_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gt_bldg_draw = ImageDraw.Draw(gt_bldg_layer)

    gt_road_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gt_road_draw = ImageDraw.Draw(gt_road_layer)

    # 3. Load Predicted Fast Polygons
    fast_path = os.path.join(EXPORTS_DIR, "flood_extent_predicted_fast.geojson")
    with open(fast_path, "r", encoding="utf-8") as f:
        fast_data = json.load(f)

    fast_feats = [f for f in fast_data.get("features", []) if f["properties"].get("tile_id") == TILE_ID]

    for feat in fast_feats:
        geom = feat["geometry"]
        g_type = geom["type"]
        coords = geom["coordinates"]
        if g_type == "Polygon":
            for ring in coords:
                pts = geo_to_pixel(ring, inv_transform)
                if len(pts) >= 3:
                    pred_draw.polygon(pts, fill=(6, 182, 212, 110), outline=(8, 145, 178, 230))
        elif g_type == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    pts = geo_to_pixel(ring, inv_transform)
                    if len(pts) >= 3:
                        pred_draw.polygon(pts, fill=(6, 182, 212, 110), outline=(8, 145, 178, 230))

    # 4. Load Ground-Truth Features
    gt_path = os.path.join(EXPORTS_DIR, "flood_extent_groundtruth.geojson")
    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    gt_feats = [f for f in gt_data.get("features", []) if f["properties"].get("tile_id") == TILE_ID]

    bldg_count = 0
    road_count = 0

    for feat in gt_feats:
        props = feat["properties"]
        geom = feat["geometry"]
        g_type = geom["type"]
        coords = geom["coordinates"]
        f_type = props.get("feature_type")

        if f_type == "building":
            bldg_count += 1
            if g_type == "Polygon":
                for ring in coords:
                    pts = geo_to_pixel(ring, inv_transform)
                    if len(pts) >= 3:
                        gt_bldg_draw.polygon(pts, fill=(245, 158, 11, 130), outline=(217, 119, 6, 240))
            elif g_type == "MultiPolygon":
                for poly in coords:
                    for ring in poly:
                        pts = geo_to_pixel(ring, inv_transform)
                        if len(pts) >= 3:
                            gt_bldg_draw.polygon(pts, fill=(245, 158, 11, 130), outline=(217, 119, 6, 240))
        elif f_type == "road":
            road_count += 1
            if g_type == "LineString":
                pts = geo_to_pixel(coords, inv_transform)
                if len(pts) >= 2:
                    gt_road_draw.line(pts, fill=(239, 68, 68, 240), width=4)
            elif g_type == "MultiLineString":
                for line in coords:
                    pts = geo_to_pixel(line, inv_transform)
                    if len(pts) >= 2:
                        gt_road_draw.line(pts, fill=(239, 68, 68, 240), width=4)

    # 5. Composite layers onto base image
    combined = Image.alpha_composite(base_img, pred_layer)
    combined = Image.alpha_composite(combined, gt_bldg_layer)
    combined = Image.alpha_composite(combined, gt_road_layer)

    # 6. Add Header & Legend Banner
    banner_height = 110
    banner = Image.new("RGBA", (W, banner_height), (15, 23, 42, 230))
    b_draw = ImageDraw.Draw(banner)

    # Load default or fallback font
    try:
        font_title = ImageFont.truetype("arial.ttf", 26)
        font_sub = ImageFont.truetype("arial.ttf", 16)
        font_legend = ImageFont.truetype("arial.ttf", 15)
    except IOError:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_legend = ImageFont.load_default()

    # Draw title
    b_draw.text((20, 10), f"FloodWatch v1.1 - Tile {TILE_ID} Post-Event Verification Overlay", fill=(248, 250, 252), font=font_title)
    b_draw.text((20, 42), "SpaceNet 8 Germany (Swath 0) | Native GeoTIFF Grid 1300x1300 | GSD: ~0.51 m/px", fill=(148, 163, 184), font=font_sub)

    # Draw Legend Items
    y_leg = 72
    # Item 1: Predicted Fast (Cyan)
    b_draw.rectangle([20, y_leg, 42, y_leg + 16], fill=(6, 182, 212, 180), outline=(8, 145, 178, 255), width=2)
    b_draw.text((48, y_leg), f"Predicted Fast Extent (Derived: {len(fast_feats)} polygons, 73,795 m²)", fill=(241, 245, 249), font=font_legend)

    # Item 2: Observed GT Buildings (Amber)
    b_draw.rectangle([450, y_leg, 472, y_leg + 16], fill=(245, 158, 11, 180), outline=(217, 119, 6, 255), width=2)
    b_draw.text((478, y_leg), f"Observed GT Buildings ({bldg_count} flooded polygons)", fill=(241, 245, 249), font=font_legend)

    # Item 3: Observed GT Roads (Red Line)
    b_draw.line([(800, y_leg + 8), (825, y_leg + 8)], fill=(239, 68, 68, 255), width=4)
    b_draw.text((833, y_leg), f"Observed GT Roads ({road_count} flooded lines)", fill=(241, 245, 249), font=font_legend)

    # Paste banner at top
    combined.paste(banner, (0, 0), banner)

    # Save output
    combined.convert("RGB").save(OUT_PATH, "PNG")
    print(f"Successfully generated inspection overlay: {OUT_PATH}")
    print(f"  Fast predicted polygons: {len(fast_feats)}")
    print(f"  GT flooded buildings: {bldg_count}")
    print(f"  GT flooded roads: {road_count}")


if __name__ == "__main__":
    render_overlay()
