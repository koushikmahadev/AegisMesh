# Architecture

## 1. Overview
A single-machine, 100% offline system: a browser UI communicates with a local FastAPI server hosting a SegFormer model resident on the GPU.

```
 Browser (Vanilla ES6 HTML5 / CSS)
        │  HTTP (127.0.0.1:8000)
        ▼
 FastAPI server  ──►  LRU Cache (capacity 256: result, JPEGs, lazy PNGs)
        │
        ▼
 flood_inference.py
   ├─ tile resolver  (glob PRE/POST .tif by tile_id)
   ├─ loader         (rasterio → float32 RGB tensor)
   ├─ SegFormer      (fp16, CUDA, loaded once at startup)
   ├─ fast mode      (768px whole-tile resize, ~35ms GPU forward)
   ├─ accurate mode  (512px sliding window, stride 256, chunked <= 8)
   └─ postprocess    (argmax → water mask → delta calculation)
        │
        ▼
 data/raw/{PRE-event,POST-event}/*.tif      models/segformer/
```

## 2. Modules
| Module | Responsibility |
|--------|----------------|
| `src/flood_inference.py` | Model singleton, tile lookup, Fast & Accurate inference modes, stage timings. |
| `src/api.py` | FastAPI application, 256-entry LRU cache, lazy PNG mask encoding, Server-Timing headers. |
| `web/` | Static offline frontend (`index.html`, `style.css`, `app.js`). |
| `scripts/prewarm.py` | Fills LRU cache for demo or all tiles. |
| `scripts/stress_test.py` | Concurrency and memory stress verification suite. |
| `start_demo.bat` | One-click Windows demo launcher. |

## 3. Data Flow (One Click)
1. User clicks a tile on the swath grid; browser aborts any pending in-flight request via `AbortController`.
2. Browser sends `GET /api/analyze/{tile_id}?mode=fast|accurate`.
3. API checks `TileLRUCache(capacity=256)`. On a cache hit, returns in `< 1 ms` with `Server-Timing: cache;dur=0.0`.
4. On a cache miss:
   - Reads PRE and POST GeoTIFFs into memory (`load_rgb`).
   - Runs SegFormer inference (`segment_water_with_timings`).
   - Encodes source imagery directly to JPEG bytes (~q85) from in-memory tensors (no re-reading from disk).
   - Defers PNG mask encoding until requested (lazy mask encoding).
   - Caches result and returns JSON response with `Server-Timing` stage breakdown.
5. Browser displays headline Net % and loads PRE/POST JPEGs in parallel.

## 4. API Contract

### `GET /api/analyze/{tile_id}?mode=fast|accurate`
```json
{
  "tile_id": "0_41_58",
  "mode": "fast",
  "before_water_pct": 0.54,
  "after_water_pct": 39.54,
  "net_intrusion_pct": 39.0,
  "latency_ms": 328,
  "cached": false,
  "seen_in_training": true,
  "split": "train",
  "gt_flooded_count": 181,
  "timings": {
    "io": 248.6,
    "preprocess": 18.6,
    "gpu": 43.0,
    "postprocess": 3.0,
    "encode": 101.0,
    "total": 422.5
  },
  "masks": {
    "before": "/api/mask/0_41_58/before.png?mode=fast",
    "after": "/api/mask/0_41_58/after.png?mode=fast"
  },
  "images": {
    "pre": "/api/image/0_41_58/pre.jpg",
    "post": "/api/image/0_41_58/post.jpg"
  },
  "device": "cuda"
}
```
**Response Header:**
```http
Server-Timing: io;dur=248.6, preprocess;dur=18.6, gpu;dur=43.0, postprocess;dur=3.0, encode;dur=101.0, total;dur=422.5
```

### Other Endpoints:
* `GET /api/image/{tile_id}/{pre|post}.jpg`: Serves 8-bit RGB JPEG rendered from the GeoTIFF.
* `GET /api/mask/{tile_id}/{before|after}.png?mode=fast|accurate`: Serves cyan `rgba(0,160,255,140)` PNG mask, lazy-encoded on demand.
* `GET /api/tiles`: List of all 202 available tile IDs.
* `GET /api/tiles/meta`: Metadata array for all tiles (`tile_id`, `net`, `before`, `after`, `split`, `gt_flooded_count`).
* `GET /api/demo_tiles`: 14 curated demo tiles sorted by flood net percentage.
* `GET /api/scan_stats`: Distribution metrics (min, median, p90, max) and single-source `SEVERITY_BANDS`.
* `GET /api/health`: Health status, cache metrics, `peak_vram_mb`, and `process_ram_mb`.

## 5. Performance Budget (Measured vs Target)

| Stage | Fast Mode Target | Fast Mode Measured (Median) | Accurate Mode Measured (Median) |
|:---|:---:|:---:|:---:|
| Read 2 GeoTIFFs (`io`) | $\le 150\text{ ms}$ | 141.5 ms | 148.2 ms |
| Preprocess (`preprocess`) | $\le 25\text{ ms}$ | 15.6 ms | 82.4 ms |
| SegFormer Forward (`gpu`) | $\le 50\text{ ms}$ | 35.6 ms | 312.5 ms |
| Postprocess (`postprocess`) | $\le 10\text{ ms}$ | 3.0 ms | 68.2 ms |
| Image Encoding (`encode`) | $\le 60\text{ ms}$ | 45.0 ms | 48.0 ms |
| **Total Server Latency** | **$\le 350\text{ ms}$** | **240.7 ms** | **659.3 ms** |
| **Browser Cold Click-to-Render** | **$\le 1000\text{ ms}$** | **489.8 ms** | **1,144.2 ms** |
| **Browser Cached Click-to-Render**| **$\le 50\text{ ms}$** | **23.6 ms** | **28.4 ms** |

## 6. Key Decisions
* **Lazy Mask Encoding:** Masks are encoded into PNGs only when requested by the browser, reducing `/api/analyze` cold latency by over 200 ms.
* **In-Memory Tensor JPEG Generation:** JPEGs are converted directly from the `load_rgb` float tensor, preventing redundant disk re-reads.
* **Chunked Accurate Mode:** Sliding window crops are chunked into batches of $\le 8$ crops on GPU, capping peak VRAM at 713.5 MB on a 4 GB RTX 3050.
* **Server-Timing Header:** Standard W3C Server-Timing metrics expose backend stage latency directly to developer tools and test suites.
