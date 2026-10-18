# FloodWatch

Offline satellite flood-intrusion analysis web application powered by a local **SegFormer** model resident on GPU (zero cloud APIs, zero runtime network dependencies).

```
Net Flood Intrusion % = After water % − Before water %
```

All benchmark numbers, latencies, and ground-truth metrics are calibrated against real measurements documented in [`docs/MEASURED.json`](docs/MEASURED.json).

---

## 1. Quick Start

### Option A: One-Click Demo Launcher (Windows)
Double-click `start_demo.bat` or run in terminal:
```cmd
start_demo.bat
```
This initializes the virtual environment, launches the FastAPI server on `127.0.0.1:8000`, prewarms the LRU cache (`FW_PREWARM=all`), and opens the UI in your default browser.

### Option B: Manual Server Launch
```bash
# Windows
floodnet_data\.venv\Scripts\python.exe -m uvicorn src.api:app --host 127.0.0.1 --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

### Option C: CLI Single-Tile Analysis
```bash
python -m src.flood_inference --tile 0_41_58
```
Expected output:
```text
Tile 0_41_58
  Before water : {{measured.dataset.demo_tiles.0.before_pct}} %
  After water  : {{measured.dataset.demo_tiles.0.after_pct}} %
  Net intrusion: +{{measured.dataset.demo_tiles.0.net_intrusion_pct}} %
  Latency      : {{measured.benchmarks.tile_0_41_58_timing_breakdown.server_inference_core_ms | int}} ms (device: cuda)
```

---

## 2. Configuration

Set via environment variables or edit constants in `src/flood_inference.py` / `src/api.py`:

| Setting | Env Var | Default | Description |
|:---|:---|:---|:---|
| Model Directory | `FW_MODEL_DIR` | `models/segformer` | Directory containing Hugging Face model weights |
| Data Directory | `FW_DATA_DIR` | `data/raw` | Root directory containing `PRE-event` and `POST-event` GeoTIFFs |
| Water Class Index | `FW_WATER_CLASS` | `1` | Model class index corresponding to flooded roads/buildings |
| Fast Input Size | `FW_INPUT_SIZE` | `768` | Whole-tile resize dimension for Fast Mode |
| Startup Prewarm | `FW_PREWARM` | `all` | Cache prewarm mode at startup: `demo`, `all`, or `none` |
| Server URL | `FW_SERVER_URL` | `http://127.0.0.1:8000` | Target URL used by test and prewarm scripts |

---

## 3. API Routes

| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/` | Web application HTML interface (100% offline static mount) |
| `GET` | `/api/health` | Status, model state, cache capacity, `peak_vram_mb`, `process_ram_mb` |
| `GET` | `/api/tiles` | List of all {{measured.dataset.total_tiles}} available tile IDs |
| `GET` | `/api/tiles/meta` | Metadata array (`tile_id`, `net`, `before`, `after`, `split`, `gt_flooded_count`) |
| `GET` | `/api/demo_tiles` | Curated list of 14 demo cases (Hits, Misses, True Negatives, False Positives) |
| `GET` | `/api/scan_stats` | Distribution percentiles and single-source `SEVERITY_BANDS` definition |
| `GET` | `/api/analyze/{tile_id}` | Main analysis endpoint (`?mode=fast\|accurate`, `?nocache=1`). Includes `Server-Timing` header |
| `GET` | `/api/mask/{tile_id}/{kind}.png` | RGBA PNG overlay (`kind`: `before` or `after`), eager-encoded on inference |
| `GET` | `/api/image/{tile_id}/{kind}.jpg` | 8-bit RGB JPEG rendered from the GeoTIFF (`kind`: `pre` or `post`) |
| `POST` | `/api/cache/clear` | Clear in-memory LRU tile cache |

---

## 4. Model Calibration & Ground Truth

* **Ground-Truth Vector Rasterization:** SpaceNet-8 GeoJSON vector annotations rasterized with flooded buildings as polygons and flooded roads as linestrings with a **2-meter metric buffer heuristic assumption** (our assumption for road surface width, not an official competition standard). At ${{measured.dataset.resolution.latitude_deg}}^\circ\text{N}$, this corresponds to a {{measured.dataset.resolution.road_corridor_width_px}}-pixel average road corridor width.
* **Architecture Details:** SegFormer uses an overlap patch-merging Mix Transformer (MiT) encoder without fixed positional encodings. While it supports arbitrary test resolutions, empirical testing on satellite tiles demonstrates resolution sensitivity (${{measured.dataset.settings_benchmark.768.pixel_f1}}\%$ F1 at 768px vs ${{measured.dataset.settings_benchmark.native_crops_512.pixel_f1}}\%$ at native 512px sliding crops).
* **Ground-Truth Composition:** Flooded roads comprise ${{measured.dataset.gt_composition_2m.road_pct}}\%$ of ground-truth pixels (${{measured.dataset.gt_composition_2m.road_pixels}}\text{ px}$), while flooded buildings comprise ${{measured.dataset.gt_composition_2m.building_pct}}\%$ (${{measured.dataset.gt_composition_2m.building_pixels}}\text{ px}$). Road recall is ${{measured.dataset.accuracy_modes_2m.fast_768.road_recall_pct}}\%$ (Fast) and ${{measured.dataset.accuracy_modes_2m.accurate_512_sliding.road_recall_pct}}\%$ (Accurate), whereas Accurate Mode raises building recall from ${{measured.dataset.accuracy_modes_2m.fast_768.building_recall_pct:.1f}}\%$ to ${{measured.dataset.accuracy_modes_2m.accurate_512_sliding.building_recall_pct:.1f}}\%$.
* **Data Provenance:** All documentation figures are traced to measured data or an explicit allow-list (verified via `scripts/check_docs_numbers.py`).
* **Dataset Splitting Reality:**
  * All {{measured.dataset.training_pool_tiles}} flooded Germany tiles were in the training pool, the training script held out no satellite tiles, and checkpoint selection used drone validation mIoU only. So the pixel F1, recall, and AUC figures are computed on training tiles and are not a held-out estimate.
  * Across all {{measured.dataset.non_training_tiles}} not-in-pool tiles evaluated to check for false alarms on unflooded terrain: In Fast Mode, 0 tiles had post-event flooded area (class 1) $> 0.1\%$ (max after: ${{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_after}}\%$ on `0_29_68`), 1 tile had pre-event flooded area $> 0.1\%$ (${{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_before}}\%$ on `0_20_66`; cause not determined), and 134 tiles had net exactly $0.00\%$ (max net: $+{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_net}}\%$). In Accurate Mode, dry-tile false alarms increase to {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_after_gt_0_1}} tiles with post-event flooded area $> 0.1\%$ (max: ${{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_after}}\%$).

---

## 5. Measured Runtime Performance

From automated headless Chrome DevTools Protocol benchmarks on NVIDIA RTX 3050 (4 GB VRAM):

* **Cold Click-to-Render (30 distinct uncached tiles):** Request #1: ${{measured.benchmarks.cold_click_to_render_30_tiles.request_1_startup.click_to_render_ms}}\text{ ms}$ (I/O: ${{measured.benchmarks.cold_click_to_render_30_tiles.request_1_startup.io_ms}}\text{ ms}$, GPU: ${{measured.benchmarks.cold_click_to_render_30_tiles.request_1_startup.gpu_ms}}\text{ ms}$, Encode: ${{measured.benchmarks.cold_click_to_render_30_tiles.request_1_startup.encode_ms}}\text{ ms}$, Render: ${{measured.benchmarks.cold_click_to_render_30_tiles.request_1_startup.client_render_ms}}\text{ ms}$). Requests 2–30: Median {{measured.benchmarks.cold_click_to_render_30_tiles.requests_2_to_30_uncached.median_ms}}\text{ ms}$, P95 {{measured.benchmarks.cold_click_to_render_30_tiles.requests_2_to_30_uncached.p95_ms}}\text{ ms}$ (Server-Timing I/O median: {{measured.benchmarks.cold_click_to_render_30_tiles.requests_2_to_30_uncached.server_timing_io_median_ms}}\text{ ms}$; OS cache state not controlled).
* **Warm end-to-end (I/O + preprocess + GPU + postprocess):** Median {{measured.benchmarks.warm_end_to_end_uncached_stage1.median_ms}}\text{ ms}$, P95 {{measured.benchmarks.warm_end_to_end_uncached_stage1.p95_ms}}\text{ ms}$ (uncached fast inference).
* **Prewarmed Click-to-Render (30 distinct tiles, `FW_PREWARM=all`):** Median {{measured.benchmarks.prewarmed_click_to_render_30_tiles.median_ms}}\text{ ms}$, P95 {{measured.benchmarks.prewarmed_click_to_render_30_tiles.p95_ms}}\text{ ms}$.
* **Accurate Mode Click-to-Render (10 distinct uncached tiles):** Median {{measured.benchmarks.accurate_mode_click_to_render_10_tiles.median_ms}}\text{ ms}$, P95 {{measured.benchmarks.accurate_mode_click_to_render_10_tiles.p95_ms}}\text{ ms}$.
* **Peak GPU VRAM:** {{measured.system.peak_gpu_vram_mb}}\text{ MB}$ (stable across all 80 stress test runs).
* **Cache Memory Usage:** {{measured.benchmarks.cache_prewarm_all.cache_memory_mb}}\text{ MB}$ for {{measured.benchmarks.cache_prewarm_all.cached_entries}} cached entries ({{measured.benchmarks.cache_prewarm_all.kb_per_entry}}\text{ KB/entry}$).

---

## 6. Troubleshooting

### Wrong Class Index
* **Symptom:** Water percentage is reported as near 100% or 0% across all tiles.
* **Cause:** The checkpoint uses a custom class mapping (0: background, 1: flooded, 2: natural_water).
* **Fix:** Verify `model.config.id2label` and set `FW_WATER_CLASS=1`.

### CUDA Out of Memory (OOM)
* **Symptom:** PyTorch raises `torch.cuda.OutOfMemoryError` on 4 GB GPUs.
* **Fix:** Ensure FP16 is enabled (`USE_FP16=True`). In Accurate Mode, the engine automatically chunks sliding window execution to batches of $\le 8$ crops, capping peak VRAM at $\sim {{measured.system.peak_gpu_vram_mb | int}}\text{ MB}$.

### Missing Tile Images
* **Symptom:** `/api/analyze/{tile_id}` returns HTTP 404 with `{"error": "tile_not_found"}`.
* **Fix:** Ensure both `PRE-event/*_{tile_id}.tif` and `POST-event/*_{tile_id}.tif` exist in `data/raw`. Query `/api/tiles` to view available IDs.

### Port In Use (Address already in use: 8000)
* **Symptom:** Uvicorn fails to bind to port 8000 (`[WinError 10048]`).
* **Fix:** Find and terminate the existing process listening on port 8000:
  ```powershell
  Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force
  ```

---

## 7. Documentation
* [Architecture](docs/ARCHITECTURE.md) – Components, API contracts, caching, and performance budget.
* [Limitations](docs/LIMITATIONS.md) – Precision, recall, F1, IoU, and empirical failure modes.
* [Demo Script](docs/DEMO_SCRIPT.md) – 2-minute live presentation guide with evaluator Q&A.
* [Single Source of Truth Metrics](docs/MEASURED.json) – Machine-readable empirical test results.
* [PRD](docs/PRD.md) – Product requirements and design principles.
* [Design](docs/DESIGN.md) – Layout, visual language, and interaction specification.
