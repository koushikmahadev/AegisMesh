"""
FloodWatch FastAPI Backend (Phase 3).

Provides high-performance offline flood-intrusion analysis endpoints
backed by local SegFormer inference, threadpool execution with inference lock,
Fast and Accurate inference modes, and an in-memory LRU cache storing compressed bytes.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

import anyio
import numpy as np
import psutil
import rasterio
import torch
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from src.flood_inference import (
    DEVICE,
    TileNotFound,
    TileResult,
    analyze_tile,
    find_tile_paths,
    get_model,
    list_tiles,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("floodwatch.api")

TILE_ID_REGEX = re.compile(r"^\d+(?:_\d+)+$")

# Severity band edges (Single config constant per user spec)
SEVERITY_BANDS = [
    {"max": 0.1, "label": "None detected", "class": "none", "color": "#71717a"},
    {"min": 0.1, "max": 2.0, "label": "Low", "class": "low", "color": "#38bdf8"},
    {"min": 2.0, "max": 10.0, "label": "Moderate", "class": "moderate", "color": "#f59e0b"},
    {"min": 10.0, "label": "Severe", "class": "severe", "color": "#ef4444"},
]

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


# ---------------------------------------------------------------- Metadata Loader
def load_tile_meta_lookup() -> dict[str, dict]:
    path = os.path.join(DATA_DIR, "tile_scan.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                scan = json.load(f)
            return {item["tile_id"]: item for item in scan}
        except Exception as e:
            logger.warning(f"Failed to load tile_scan.json: {e}")
    return {}


# ---------------------------------------------------------------- LRU Cache
@dataclass
class CachedTile:
    result_dict: dict
    mask_before_png: Optional[bytes]
    mask_after_png: Optional[bytes]
    image_pre_jpg: Optional[bytes]
    image_post_jpg: Optional[bytes]
    pre_mask_raw: Optional[torch.Tensor] = None
    post_mask_raw: Optional[torch.Tensor] = None
    timings: Optional[dict[str, float]] = None


class TileLRUCache:
    def __init__(self, capacity: int = 256):
        self.capacity = capacity
        self.cache: OrderedDict[str, CachedTile] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[CachedTile]:
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def put(self, key: str, item: CachedTile) -> None:
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = item
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def __len__(self) -> int:
        with self.lock:
            return len(self.cache)

    def clear(self) -> None:
        with self.lock:
            self.cache.clear()

    def memory_bytes(self) -> int:
        with self.lock:
            total = 0
            for item in self.cache.values():
                if item.mask_before_png:
                    total += len(item.mask_before_png)
                if item.mask_after_png:
                    total += len(item.mask_after_png)
                if item.image_pre_jpg:
                    total += len(item.image_pre_jpg)
                if item.image_post_jpg:
                    total += len(item.image_post_jpg)
            return total


CACHE = TileLRUCache(capacity=256)
INFERENCE_LOCK = threading.Lock()
ASYNC_INFERENCE_LOCK = anyio.Lock()


# ---------------------------------------------------------------- Image Helpers
def mask_to_rgba_png_bytes(mask: torch.Tensor) -> bytes:
    m = mask.cpu().numpy().astype(bool)
    h, w = m.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[m] = [0, 160, 255, 140]
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def tensor_to_jpeg_bytes(t: torch.Tensor, quality: int = 85) -> bytes:
    arr = np.clip(t.permute(1, 2, 0).numpy() * 255.0, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def geotiff_to_jpeg_bytes(path: str, quality: int = 85) -> bytes:
    with rasterio.open(path) as src:
        arr = src.read([1, 2, 3])
    if np.issubdtype(arr.dtype, np.integer):
        max_val = float(np.iinfo(arr.dtype).max)
        arr = np.clip(arr.astype(np.float32) / max_val * 255.0, 0, 255).astype(np.uint8)
    else:
        arr = np.clip(arr.astype(np.float32) * 255.0, 0, 255).astype(np.uint8)
    rgb = np.transpose(arr, (1, 2, 0))
    img = Image.fromarray(rgb, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def get_or_analyze(tile_id: str, mode: str = "fast", force_recompute: bool = False) -> CachedTile:
    """
    Retrieve cached tile result/assets or run inference under lock.
    Keyed by (tile_id, mode) to cleanly isolate fast and accurate modes.
    If force_recompute is True, bypasses cache read and overwrites cache entry.
    """
    cache_key = f"{tile_id}:{mode}"

    # 1. Quick check outside lock
    if not force_recompute:
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

    # 2. Acquire inference lock
    with INFERENCE_LOCK:
        # Check cache AGAIN inside lock
        if not force_recompute:
            cached = CACHE.get(cache_key)
            if cached is not None:
                return cached

        pre_path, post_path = find_tile_paths(tile_id)
        result, pre_mask, post_mask, (pre_t, post_t) = analyze_tile(
            tile_id, return_masks=True, return_tensors=True, mode=mode
        )

        t_enc_0 = time.perf_counter()
        image_pre_jpg = tensor_to_jpeg_bytes(pre_t, quality=85)
        image_post_jpg = tensor_to_jpeg_bytes(post_t, quality=85)
        mask_before_png = mask_to_rgba_png_bytes(pre_mask)
        mask_after_png = mask_to_rgba_png_bytes(post_mask)
        t_encode = (time.perf_counter() - t_enc_0) * 1000

        # Free raw PyTorch tensors immediately to prevent memory retention
        del pre_mask, post_mask, pre_t, post_t

        timings = dict(result.timings or {})
        timings["encode"] = round(t_encode, 1)
        timings["total"] = round(timings.get("total", 0.0) + t_encode, 1)

        meta = load_tile_meta_lookup().get(tile_id, {})
        seen_in_training = meta.get("seen_in_training", False)
        split = meta.get("split", "train" if seen_in_training else "not_in_pool")
        gt_flooded_count = meta.get("gt_flooded_count", 0)

        cached_entry = CachedTile(
            result_dict={
                "tile_id": result.tile_id,
                "mode": mode,
                "before_water_pct": result.before_water_pct,
                "after_water_pct": result.after_water_pct,
                "net_intrusion_pct": result.net_intrusion_pct,
                "latency_ms": result.latency_ms,
                "cached": False,
                "seen_in_training": seen_in_training,
                "split": split,
                "gt_flooded_count": gt_flooded_count,
                "timings": timings,
                "masks": {
                    "before": f"/api/mask/{result.tile_id}/before.png?mode={mode}",
                    "after": f"/api/mask/{result.tile_id}/after.png?mode={mode}",
                },
                "images": {
                    "pre": f"/api/image/{result.tile_id}/pre.jpg",
                    "post": f"/api/image/{result.tile_id}/post.jpg",
                },
                "device": result.device,
            },
            mask_before_png=mask_before_png,
            mask_after_png=mask_after_png,
            image_pre_jpg=image_pre_jpg,
            image_post_jpg=image_post_jpg,
            pre_mask_raw=None,
            post_mask_raw=None,
            timings=timings,
        )
        CACHE.put(cache_key, cached_entry)
        return cached_entry


def validate_tile_id(tile_id: str) -> Optional[JSONResponse]:
    if not TILE_ID_REGEX.match(tile_id):
        return JSONResponse(
            status_code=422,
            content={
                "error": "malformed_tile_id",
                "message": f"Malformed tile ID '{tile_id}'. Expected format like '0_39_62'.",
            },
        )
    return None


def validate_mode(mode: str) -> Optional[JSONResponse]:
    if mode not in ("fast", "accurate"):
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_mode",
                "message": f"Invalid mode '{mode}'. Expected 'fast' or 'accurate'.",
            },
        )
    return None


def run_prewarm_thread(mode: str):
    logger.info(f"Background prewarm thread started (mode={mode})...")
    tiles = list_tiles()
    if mode == "all":
        targets = [(t, "fast") for t in tiles]
    elif mode == "demo":
        path = os.path.join(DATA_DIR, "demo_tiles.json")
        targets = []
        if os.path.exists(path):
            with open(path, "r") as f:
                demos = json.load(f)
            targets = [(d["tile_id"], "fast") for d in demos]
            targets += [(d["tile_id"], "accurate") for d in demos]
        else:
            targets = [(t, "fast") for t in tiles[:14]]
    else:
        targets = []

    count = 0
    t0 = time.perf_counter()
    for tid, m in targets:
        try:
            get_or_analyze(tid, mode=m)
            count += 1
        except Exception as e:
            logger.warning(f"Prewarm failed on {tid} ({m}): {e}")
    dt = time.perf_counter() - t0
    logger.info(f"Background prewarm complete: {count} entries cached in {dt:.2f}s ({CACHE.memory_bytes() / (1024*1024):.2f} MB RAM).")


# ---------------------------------------------------------------- Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FloodWatch API starting up: loading SegFormer model...")
    model = get_model()
    logger.info(f"Model resident on {DEVICE.type}. Warming up inference pipeline...")
    tiles = list_tiles()
    if tiles:
        warmup_id = tiles[0]
        try:
            # 1. Warm up fast mode (GeoTIFF I/O, CUDA forward pass, JPEG encoding)
            cached_fast = await anyio.to_thread.run_sync(get_or_analyze, warmup_id, "fast")
            # 2. Warm up mask PNG encoding (loads Pillow PNG/zlib C libraries and allocators)
            if cached_fast.pre_mask_raw is not None:
                cached_fast.mask_before_png = mask_to_rgba_png_bytes(cached_fast.pre_mask_raw)
            if cached_fast.post_mask_raw is not None:
                cached_fast.mask_after_png = mask_to_rgba_png_bytes(cached_fast.post_mask_raw)

            # 3. Warm up accurate mode (sliding window crop batches, tensor operations)
            cached_acc = await anyio.to_thread.run_sync(get_or_analyze, warmup_id, "accurate")
            if cached_acc.pre_mask_raw is not None:
                cached_acc.mask_before_png = mask_to_rgba_png_bytes(cached_acc.pre_mask_raw)

            logger.info(f"Warm-up complete on tile {warmup_id} (fast + accurate + PNG/JPEG compressors warm).")
        except Exception as e:
            logger.warning(f"Warm-up failed: {e}")
    else:
        logger.warning("No tile imagery detected in data directory.")

    prewarm_mode = os.getenv("FW_PREWARM", "demo").lower()
    if prewarm_mode == "none":
        with CACHE.lock:
            CACHE.cache.clear()
        logger.info("FW_PREWARM=none: Cache cleared for clean benchmarking.")
    elif prewarm_mode in ("all", "demo"):
        threading.Thread(target=run_prewarm_thread, args=(prewarm_mode,), daemon=True).start()

    yield
    logger.info("FloodWatch API shutting down.")


# ---------------------------------------------------------------- FastAPI App
app = FastAPI(title="FloodWatch API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- Routes
@app.get("/api/health")
def health_endpoint():
    """Health check: model status, active compute device, cache metrics, and memory."""
    mem_bytes = CACHE.memory_bytes()
    peak_vram = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2) if torch.cuda.is_available() else 0.0
    process_ram = round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 2)
    return {
        "status": "ok",
        "model_loaded": True,
        "device": DEVICE.type,
        "cache_size": len(CACHE),
        "cache_capacity": CACHE.capacity,
        "cache_memory_bytes": mem_bytes,
        "cache_memory_mb": round(mem_bytes / (1024 * 1024), 2),
        "peak_vram_mb": peak_vram,
        "process_ram_mb": process_ram,
    }


@app.get("/api/tiles")
def tiles_endpoint():
    """List of tile IDs that have both pre and post images available."""
    return list_tiles()


@app.get("/api/tiles/meta")
def tiles_meta_endpoint():
    """Returns metadata for all tiles: tile_id, net, before, after, seen_in_training, split, gt_flooded_count."""
    path = os.path.join(DATA_DIR, "tile_scan.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.exception(f"Error reading tile_scan.json: {e}")
    # Fallback to basic tile list if scan not yet generated
    return [{"tile_id": tid, "net": 0.0, "before": 0.0, "after": 0.0, "seen_in_training": False, "split": "not_in_pool", "gt_flooded_count": 0} for tid in list_tiles()]


@app.get("/api/demo_tiles")
def demo_tiles_endpoint():
    """Curated list of demo tiles sorted by flood net intrusion percentage."""
    path = os.path.join(DATA_DIR, "demo_tiles.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.exception(f"Error reading demo_tiles.json: {e}")
    return []


@app.get("/api/scan_stats")
def scan_stats_endpoint():
    """Dataset distribution metrics from tile_scan.json plus severity bands."""
    path = os.path.join(DATA_DIR, "tile_scan.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                scan = json.load(f)
            nets = np.array([t.get("net", 0.0) for t in scan])
            return {
                "min": float(nets.min()) if len(nets) else 0.0,
                "median": float(np.median(nets)) if len(nets) else 0.0,
                "p90": float(np.percentile(nets, 90)) if len(nets) else 0.0,
                "max": float(nets.max()) if len(nets) else 0.0,
                "total_tiles": len(scan),
                "counts": {
                    "net_gt_0_1": int((nets > 0.1).sum()),
                    "net_gt_1": int((nets > 1.0).sum()),
                    "net_gt_5": int((nets > 5.0).sum()),
                    "net_gt_10": int((nets > 10.0).sum()),
                    "net_eq_0": int((nets == 0.0).sum()),
                    "net_lt_0": int((nets < 0.0).sum()),
                },
                "severity_bands": SEVERITY_BANDS,
            }
        except Exception as e:
            logger.exception(f"Error computing scan_stats: {e}")

    return {
        "min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0, "total_tiles": 0,
        "counts": {"net_gt_0_1": 0, "net_gt_1": 0, "net_gt_5": 0, "net_gt_10": 0, "net_eq_0": 0, "net_lt_0": 0},
        "severity_bands": SEVERITY_BANDS,
    }


@app.get("/api/analyze/{tile_id}")
async def analyze_endpoint(
    tile_id: str,
    request: Request,
    mode: str = Query("fast", description="Inference mode: 'fast' or 'accurate'"),
    nocache: bool = Query(False, description="Bypass cache read if true"),
):
    """
    Analyze flood intrusion for a specific tile under mode ('fast' or 'accurate').
    Returns JSON contract with before/after/net %, latency, metadata, and mask/image URLs.
    Includes Server-Timing header.
    Checks request.is_disconnected() to prevent queue buildup during rapid clicking.
    If nocache=True, bypasses cache read and forces live re-inference, overwriting the cache.
    """
    err = validate_tile_id(tile_id)
    if err:
        return err
    err_mode = validate_mode(mode)
    if err_mode:
        return err_mode

    cache_key = f"{tile_id}:{mode}"
    if not nocache:
        cached_pre = CACHE.get(cache_key)
        if cached_pre is not None:
            res = dict(cached_pre.result_dict)
            res["cached"] = True
            res["latency_ms"] = 0
            return JSONResponse(content=res, headers={"Server-Timing": "cache;dur=0.0, total;dur=0.0"})

    # If client already disconnected before acquiring lock, drop immediately
    if await request.is_disconnected():
        return Response(status_code=499)

    async with ASYNC_INFERENCE_LOCK:
        # Check disconnect again upon acquiring lock
        if await request.is_disconnected():
            return Response(status_code=499)

        # Re-check cache inside lock unless nocache is requested
        if not nocache:
            cached_locked = CACHE.get(cache_key)
            if cached_locked is not None:
                res = dict(cached_locked.result_dict)
                res["cached"] = True
                res["latency_ms"] = 0
                return JSONResponse(content=res, headers={"Server-Timing": "cache;dur=0.0, total;dur=0.0"})

        try:
            cached = await anyio.to_thread.run_sync(get_or_analyze, tile_id, mode, nocache)
            if await request.is_disconnected():
                return Response(status_code=499)

            res = dict(cached.result_dict)
            res["cached"] = False
            t = cached.timings or {}
            st = f"io;dur={t.get('io', 0.0)}, preprocess;dur={t.get('preprocess', 0.0)}, gpu;dur={t.get('gpu', 0.0)}, postprocess;dur={t.get('postprocess', 0.0)}, encode;dur={t.get('encode', 0.0)}, total;dur={t.get('total', 0.0)}"
            return JSONResponse(content=res, headers={"Server-Timing": st})
        except TileNotFound as e:
            return JSONResponse(
                status_code=404,
                content={"error": "tile_not_found", "message": str(e)},
            )
        except Exception as e:
            logger.exception(f"Inference error for tile {tile_id} (mode={mode}): {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "inference_error", "message": str(e)},
            )


@app.get("/api/mask/{tile_id}/{kind}.png")
def mask_endpoint(tile_id: str, kind: str, mode: str = Query("fast", description="Inference mode: 'fast' or 'accurate'")):
    """
    Serve RGBA PNG mask overlay for before or after event.
    Water is rendered in cyan rgba(0, 160, 255, 140), transparent elsewhere.
    Lazy-encodes mask on demand if not already in cache.
    """
    err = validate_tile_id(tile_id)
    if err:
        return err
    err_mode = validate_mode(mode)
    if err_mode:
        return err_mode

    if kind not in ("before", "after"):
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_kind", "message": "kind must be 'before' or 'after'"},
        )

    try:
        cached = get_or_analyze(tile_id, mode=mode)
        if kind == "before":
            if cached.mask_before_png is None and cached.pre_mask_raw is not None:
                cached.mask_before_png = mask_to_rgba_png_bytes(cached.pre_mask_raw)
            png_bytes = cached.mask_before_png or b""
        else:
            if cached.mask_after_png is None and cached.post_mask_raw is not None:
                cached.mask_after_png = mask_to_rgba_png_bytes(cached.post_mask_raw)
            png_bytes = cached.mask_after_png or b""

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except TileNotFound as e:
        return JSONResponse(
            status_code=404,
            content={"error": "tile_not_found", "message": str(e)},
        )
    except Exception as e:
        logger.exception(f"Error serving mask for tile {tile_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "mask_error", "message": str(e)},
        )


@app.get("/api/image/{tile_id}/{kind}.jpg")
@app.get("/api/image/{tile_id}/{kind}.png")
def image_endpoint(tile_id: str, kind: str, mode: str = Query("fast")):
    """
    Serve source GeoTIFF rendered as 8-bit RGB JPEG (~q85) for browser rendering.
    """
    err = validate_tile_id(tile_id)
    if err:
        return err

    if kind not in ("pre", "post"):
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_kind", "message": "kind must be 'pre' or 'post'"},
        )

    try:
        cached = get_or_analyze(tile_id, mode="fast")
        jpg_bytes = cached.image_pre_jpg if kind == "pre" else cached.image_post_jpg
        return Response(
            content=jpg_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except TileNotFound as e:
        return JSONResponse(
            status_code=404,
            content={"error": "tile_not_found", "message": str(e)},
        )
    except Exception as e:
        logger.exception(f"Error serving image for tile {tile_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "image_error", "message": str(e)},
        )


@app.post("/api/cache/clear")
@app.get("/api/cache/clear")
def clear_cache_endpoint():
    """Clear in-memory LRU tile cache."""
    CACHE.clear()
    return {"status": "ok", "message": "Cache cleared", "cache_size": len(CACHE)}


# ---------------------------------------------------------------- Frontend Mount
web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.isdir(web_dir):
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=False)
