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
  Before water : 0.54 %
  After water  : 39.54 %
  Net intrusion: +39.0 %
  Latency      : 333 ms (device: cuda)
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
| `GET` | `/api/tiles` | List of all 202 available tile IDs |
| `GET` | `/api/tiles/meta` | Metadata array (`tile_id`, `net`, `before`, `after`, `split`, `gt_flooded_count`) |
| `GET` | `/api/demo_tiles` | Curated list of 14 demo cases (Hits, Misses, True Negatives, False Positives) |
| `GET` | `/api/scan_stats` | Distribution percentiles and single-source `SEVERITY_BANDS` definition |
| `GET` | `/api/analyze/{tile_id}` | Main analysis endpoint (`?mode=fast\|accurate`, `?nocache=1`). Includes `Server-Timing` header |
| `GET` | `/api/mask/{tile_id}/{kind}.png` | RGBA PNG overlay (`kind`: `before` or `after`), eager-encoded on inference |
| `GET` | `/api/image/{tile_id}/{kind}.jpg` | 8-bit RGB JPEG rendered from the GeoTIFF (`kind`: `pre` or `post`) |
| `POST` | `/api/cache/clear` | Clear in-memory LRU tile cache |

---

## 4. Model Calibration & Ground Truth

* **Ground-Truth Vector Rasterization:** SpaceNet-8 GeoJSON vector annotations rasterized with flooded buildings as polygons and flooded roads as linestrings with a **2-meter metric buffer heuristic assumption** (our assumption for road surface width, not an official competition standard). At $50.53^\circ\text{N}$, this corresponds to a 9.55-pixel average road corridor width.
* **Architecture Details:** SegFormer uses an overlap patch-merging Mix Transformer (MiT) encoder without fixed positional encodings. While it supports arbitrary test resolutions, empirical testing on satellite tiles demonstrates resolution sensitivity ($20.5\%$ F1 at 768px vs $27.82\%$ at native 512px sliding crops).
* **Ground-Truth Composition:** Flooded roads comprise $45.37\%$ of ground-truth pixels ($1367621\text{ px}$), while flooded buildings comprise $54.85\%$ ($1653312\text{ px}$). Road recall is $4.69\%$ (Fast) and $8.88\%$ (Accurate), whereas Accurate Mode raises building recall from $21.3\%$ to $35.6\%$.
* **Data Provenance:** All documentation figures are traced to measured data or an explicit allow-list (verified via `scripts/check_docs_numbers.py`).
* **Dataset Splitting Reality:**
  * All 66 flooded Germany tiles were in the training pool, the training script held out no satellite tiles, and checkpoint selection used drone validation mIoU only. So the pixel F1, recall, and AUC figures are computed on training tiles and are not a held-out estimate.
  * Across all 136 not-in-pool tiles evaluated to check for false alarms on unflooded terrain: In Fast Mode, 0 tiles had post-event flooded area (class 1) $> 0.1\%$ (max after: $0.02\%$ on `0_29_68`), 1 tile had pre-event flooded area $> 0.1\%$ ($3.32\%$ on `0_20_66`; cause not determined), and 134 tiles had net exactly $0.00\%$ (max net: $+0.02\%$). In Accurate Mode, dry-tile false alarms increase to 8 tiles with post-event flooded area $> 0.1\%$ (max: $1.33\%$).

---

## 5. Measured Runtime Performance

From automated headless Chrome DevTools Protocol benchmarks on NVIDIA RTX 3050 (4 GB VRAM):

* **Cold Click-to-Render (30 distinct uncached tiles):** Request #1: $1164.1\text{ ms}$ (I/O: $500.6\text{ ms}$, GPU: $223.3\text{ ms}$, Encode: $211.6\text{ ms}$, Render: $118.5\text{ ms}$). Requests 2–30: Median 713\text{ ms}$, P95 1178.699999988079\text{ ms}$ (Server-Timing I/O median: 380.6\text{ ms}$; OS cache state not controlled).
* **Warm end-to-end (I/O + preprocess + GPU + postprocess):** Median 498.1229000259191\text{ ms}$, P95 645.6424999632873\text{ ms}$ (uncached fast inference).
* **Prewarmed Click-to-Render (30 distinct tiles, `FW_PREWARM=all`):** Median 61.3\text{ ms}$, P95 90.2\text{ ms}$.
* **Accurate Mode Click-to-Render (10 distinct uncached tiles):** Median 1696.3\text{ ms}$, P95 2816.7\text{ ms}$.
* **Peak GPU VRAM:** 721.12\text{ MB}$ (stable across all 80 stress test runs).
* **Cache Memory Usage:** 109.8\text{ MB}$ for 216 cached entries (508.0\text{ KB/entry}$).

---

## 6. Troubleshooting

### Wrong Class Index
* **Symptom:** Water percentage is reported as near 100% or 0% across all tiles.
* **Cause:** The checkpoint uses a custom class mapping (0: background, 1: flooded, 2: natural_water).
* **Fix:** Verify `model.config.id2label` and set `FW_WATER_CLASS=1`.

### CUDA Out of Memory (OOM)
* **Symptom:** PyTorch raises `torch.cuda.OutOfMemoryError` on 4 GB GPUs.
* **Fix:** Ensure FP16 is enabled (`USE_FP16=True`). In Accurate Mode, the engine automatically chunks sliding window execution to batches of $\le 8$ crops, capping peak VRAM at $\sim 721\text{ MB}$.

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
