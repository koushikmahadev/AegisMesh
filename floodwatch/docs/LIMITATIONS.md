# FloodWatch System Limitations & Empirical Verification

This document provides a factual record of known failure modes, dataset constraints, and empirical calibration results for FloodWatch. All numbers are traced to measured data or an explicit allow-list (drawn directly from [`docs/MEASURED.json`](MEASURED.json)).

---

## 1. Operating Assumptions & Boundary Constraints

* **Hardware Target:** Designed for offline execution on an **NVIDIA GeForce RTX 3050 Laptop GPU** (4 GB VRAM).
* **Model Checkpoint:** `checkpoints_joint` (SegFormer-B0 architecture, 14.6 MB FP16 weights).
* **Label Taxonomy:** 3-class segmentation mapping (0: Background, 1: Flooded Water, 2: Natural Water). Analysis computes net flood intrusion based strictly on **Model Class 1**.
* **Offline Requirement:** 100% offline runtime operation with zero external CDN, font, or cloud API calls.
* **Latency Definitions:**
  * **Server-Timing Total:** Measures server inference core execution (disk I/O + PyTorch preprocessing + GPU inference + argmax postprocessing). It excludes eager PNG mask encoding and HTTP serialization.
  * **Uncached Response Time:** Total server HTTP transaction duration including eager PNG mask generation (~177 ms added on tile `0_41_58`, bringing total uncached response to ~510 ms).
  * **Client Roundtrip Wall Time:** Measured in browser from `fetch()` initiation to DOM update (includes network transfer, JSON parsing, and DOM rendering).

---

## 2. Empirical Benchmark & Ground-Truth Calibration

Evaluated across all 202 SpaceNet-8 Germany satellite tiles against rasterized human-annotated GeoJSON vector boundaries:
* **Ground-Truth Geometry & Resolution:**
  * Coordinate latitude: $\approx 50.53^\circ\text{N}$.
  * GeoTIFF transform scale: $dx = dy \approx 4.6\times 10^{-6}\text{ deg/px}$ ($4.60082608e-06\text{ deg/px}$).
  * Ground resolution: Longitude $dx = 0.326\text{ m/px}$, Latitude $dy = 0.512\text{ m/px}$ (average ground resolution: $0.419\text{ m/px}$).
  * Road buffer assumption: 2.0-meter buffer radius; full 4.0-meter road corridor width $= \mathbf{ 9.55 \text{ pixels} }$ (our heuristic assumption for road surface width, not an official competition standard).
* **Ground-Truth Composition (66 Flooded Germany Tiles at 2m Buffer):**
  * Flooded Buildings: $1653312\text{ px}$ ($54.85\%$)
  * Flooded Roads: $1367621\text{ px}$ ($45.37\%$)
  * Total Flooded Ground-Truth Pixels: $3014085\text{ px}$
* **Training Pool Context:** All 66 flooded Germany tiles were in the training pool, the training script held out no satellite tiles, and checkpoint selection used drone validation mIoU only. So the pixel F1, recall, and AUC figures are computed on training tiles and are not a held-out estimate.

### Accuracy Breakdown: Fast vs. Accurate Modes (2m Buffer)

| Metric | Fast Mode (768px Whole Tile) | Accurate Mode (512px Overlapping Crops) |
| :--- | :---: | :---: |
| **Predicted Positive Pixels** | 1029016 px | 1966751 px |
| **Building Recall** | **21.27%** | **35.57%** |
| **Road Recall** | **4.69%** | **8.88%** |
| **Combined Pixel Recall** | **13.75%** | **23.47%** |
| **Combined precision vs annotated buildings and roads (flooded land without annotations counts as a false positive)** | **40.27%** | **35.96%** |
| **Precision vs. Buildings** | 34.17% | 29.9% |
| **Precision vs. Roads** | 6.23% | 6.18% |
| **Pixel F1 Score** | 20.5% | 28.4% |
| **Pixel IoU** | 11.42% | 16.55% |
| **Tile-Level Flood ROC-AUC** | 0.6028 | 0.6466 |
| **Client Wall Time (Stress Test Median)** | **498.1229000259191 ms median** (P95: 645.6424999632873 ms) | **884.6985999844037 ms median** (P95: 1103.4398999763653 ms) |

*Calibration Re-measurement:* Accurate-mode false positive pixels decreased from 1,364,444 to 1259418 (raising F1 from 27.82% to 28.40%) due to calibration pipeline unification: replacing the separate benchmark sliding-window script with direct calls to production `analyze_tile` and unified metric UTM EPSG:32632 ground-truth rasterization.

*Key Empirical Insight:* Flooded roads constitute $45.37\%$ of all ground-truth flooded pixels, yet the model achieves only $4.69\%$ road recall in Fast Mode and $8.88\%$ in Accurate Mode. In contrast, building recall is substantially higher: Accurate Mode raises building recall from $21.3\%$ to $35.6\%$. Consequently, the model functions primarily as a building and open inundation detector, largely missing narrow road flooding.

---

## 3. Road-Buffer Sensitivity Analysis

To verify whether low road recall was an artifact of our 2-meter road buffer assumption, ground-truth rasterization and accuracy evaluation were conducted at 1 m, 2 m, and 3 m road buffers:

| Buffer Parameter | 1m Buffer (2m Corridor) | 2m Buffer (4m Corridor) | 3m Buffer (6m Corridor) |
| :--- | :---: | :---: | :---: |
| **Corridor Width in Pixels** | 4.77 px | 9.55 px | 14.32 px |
| **GT Road Pixels (% of total GT)** | 749310 px (31.2%) | 1367621 px (45.37%) | 1984154 px (54.86%) |
| **GT Building Pixels** | 1653312 px | 1653312 px | 1653312 px |
| **Fast Building Recall** | 21.27% | 21.27% | 21.27% |
| **Accurate Building Recall** | 35.57% | 35.57% | 35.57% |
| **Fast Road Recall** | 4.66% | 4.69% | 4.7% |
| **Accurate Road Recall** | 8.91% | 8.88% | 8.88% |
| **Fast Combined Recall / IoU** | 16.09% / 12.7% | 13.75% / 11.42% | 12.16% / 10.46% |
| **Accurate Combined Recall / IoU** | 27.26% / 17.63% | 23.47% / 16.55% | 20.92% / 15.67% |

*Key Finding on Buffer Sensitivity:*
1. **Building recall is completely invariant to road buffer width** ($21.27\%$ Fast, $35.57\%$ Accurate across all buffers).
2. **Road recall remains low across all buffer assumptions** ($4.66\%$ to $4.7\%$ Fast; $8.91\%$ to $8.88\%$ Accurate).
3. **Resizing is not the primary cause of low road recall:** even when evaluating native overlapping 512px sliding crops (Accurate Mode) at a narrow 1m buffer, road recall reaches only $8.91\%$. The model struggles to detect narrow linear flood features regardless of scale or buffer width.

---

## 4. Accurate Mode Performance on Demo "Model Miss" Tiles

The impact of Accurate Mode was measured on four demo tiles with low or zero Fast Mode detections:

| Tile ID | Annotated GT Features | Fast Mode Net | Accurate Mode Net | Observed Effect |
| :--- | :--- | :---: | :---: | :--- |
| `0_23_62` | 94 buildings, 7 roads | $+0.08\%$ | **$+0.58\%$** | Net increase from 0.08% to 0.58%; building recall rises from 0.99% to 5.31% (precision vs annotated buildings and roads: 28.76%). |
| `0_40_62` | 72 buildings, 16 roads | $+0.02\%$ | **$+2.37\%$** | Net increase from 0.02% to 2.37%; building recall rises from 0.0% to 11.51% (precision vs annotated buildings and roads: 29.52%). |
| `0_29_66` | 90 buildings, 5 roads | $0.00\%$ | **$-0.11\%$** | Remains near zero; low-contrast structures. |
| `0_39_62` | 0 buildings, 3 roads | $0.00\%$ | **$0.00\%$** | 0.00% in both modes; road-only flooding undetected without structures. |

*Takeaway:* Accurate Mode successfully recovers flooded structures that fall below resolution thresholds in Fast Mode ($0.08\% \to 0.58\%$ on `0_23_62`, $0.02\% \to 2.37\%$ on `0_40_62`). However, when flooding is confined strictly to narrow roads without flooded buildings (e.g., `0_39_62`), neither mode detects the water.

---

## 5. Dry Tiles False-Alarm Evaluation (136 Not-in-Pool Tiles)

To evaluate false alarm behavior on unflooded terrain, all 136 not-in-pool tiles were scanned in both Fast and Accurate modes side-by-side:

| False Alarm Metric | Fast Mode (768px Resize) | Accurate Mode (512px Sliding Window) |
| :--- | :---: | :---: |
| **Tiles with Pre-Event Flooded Area $> 0.1\%$** | **1 tile** (`0_20_66` at $3.32\%$) | **5 tiles** (max: $4.77\%$ on `0_20_66`) |
| **Tiles with Post-Event Flooded Area $> 0.1\%$** | **0 tiles** (max: $0.02\%$ on `0_29_68`) | **8 tiles** (max: $1.33\%$ on `0_38_69`) |
| **Tiles with Net Intrusion $== 0.00\%$** | **134 tiles** ($98.53\%$) | **117 tiles** ($86.03\%$) |
| **Tiles with Net Intrusion $> 0$** | **1 tile** (`0_29_68` at $+0.02\%$) | **11 tiles** (max: $+1.14\%$ on `0_31_69`) |
| **Tiles with Net Intrusion $< 0$** | **1 tile** (`0_20_66` at $-3.32\%$) | **8 tiles** (min: $-4.27\%$ on `0_20_66`) |
| **Max Post-Event Flooded Area Detected** | **0.02%** (`0_29_68`) | **1.33%** (`0_38_69`) |
| **Max Net Intrusion Detected** | **+0.02%** (`0_29_68`) | **+1.14%** (`0_31_69`) |
| **Flooded Tiles with Net $> 1.0\%$ (66 Train Tiles)** | **6 tiles** (9.09%) | **14 tiles** (21.21%) |

*Trade-Off Reality:* Accurate Mode produces **more false alarms**, not fewer. While Accurate Mode increases the number of flooded tiles detected above $1.0\%$ net intrusion from 6 to 14 (21.21\%) by recovering small flooded structures, its higher sensitivity comes at the cost of 8 false-alarm tiles with post-event flooded area $> 0.1\%$ (up to $1.33\%$) on completely dry, unflooded terrain.

---

## 6. Dataset Splitting & Candidate Pool Facts

* **Geographic Coverage:** Raw imagery in `data/raw` contains exclusively Germany tiles (prefix `0_`). Louisiana tiles (prefix `2_`) were present in training crops (`satellite_processed/images`), but do not exist in the raw GeoTIFF repository.
* **Candidate Training Pool:**
  * Exactly 66 Germany tiles overlap the candidate training pool (`satellite_processed/images`).
  * All 66 of these tiles contain positive human-annotated flooded ground truth (`gt_flooded_count > 0`).
* **Validation Split Reality:**
  * Examination of `train_joint_segformer.py` reveals that **no satellite validation set was held out during joint training**.
  * The validation dataset in `train_joint_segformer.py` consisted entirely of 100 Drone (FloodNet) images (`DroneValDataset`). Model checkpoint selection was driven strictly by validation mIoU on drone imagery.
* **Reconciled Not-in-Pool Anomalies (136 Tiles):**
  * `0_20_66`: `before: 3.32%`, `after: 0.0%`, `net: -3.32%`.
  * `0_29_68`: `before: 0.0%`, `after: 0.02%`, `net: 0.02%`.
  * All other 134 tiles have `before: 0.00%`, `after: 0.00%`, `net: 0.00%`. Note that `0_36_61` (`before: 0.15%`, `net: -0.15%`) has 15 ground-truth flooded features and is part of the 66 training pool tiles, not not-in-pool.

---

## 7. Known Failure Modes & Visual Inspections

1. **Model Misses on Narrow Roads:**
   * Example: Tile `0_39_62`. Contains 3 annotated flooded road corridors and 0 buildings. The model predicts $0.00\%$ flooded area (class 1) in both Fast and Accurate modes, reflecting the 4.69\% – 8.88\% road recall limit.
2. **Pre-Event False Positives (Negative Net):**
   * Example: Tile `0_20_66`. Contains 0 annotated flooded features. Pre-event imagery produces $3.32\%$ flooded area (class 1) prediction in Fast Mode ($4.77\%$ in Accurate Mode), while post-event imagery produces $0.00\%$ Fast ($0.5\%$ Accurate), resulting in net intrusion of $-3.32\%$.
   * **Visual Inspection Verification:** The following inspection images were rendered and directly examined:
     1. `docs/inspection/0_20_66_pre.jpg`
     2. `docs/inspection/0_20_66_pre_fast_mask.jpg`
     3. `docs/inspection/0_20_66_pre_acc_mask.jpg`
     4. `docs/inspection/0_20_66_post.jpg`
   * Visual verification confirms that false-positive cyan masks cover roofs and small open areas between buildings in the pre-event image, while post-event is clean. The specific root cause is **cause not determined**. FloodWatch displays an explicit explanatory banner: *"No net increase: less flooded area detected post-event than pre-event."*
3. **Dry-Tile Post-Event False Alarms in Accurate Mode:**
   * In Accurate Mode, 8 dry tiles exceed $0.1\%$ post-event flooded area (class 1). The two worst cases were rendered and visually inspected:
     * **Tile `0_38_69`:** Accurate Mode predicts 1.33% post-event water (Fast Mode: 0.00%; 0 GT flooded features). Inspection images: `0_38_69_pre.jpg`, `0_38_69_post.jpg`, `0_38_69_post_acc_mask.jpg`. Finding: Upper-left settlement has dark residential rooftops and asphalt driveways flagged as class 1 in Accurate Mode (1.33% post vs 0.29% pre, net +1.04%); Fast Mode predicts 0.00% on both; 0 annotated flooded features.
     * **Tile `0_31_69`:** Accurate Mode predicts 1.14% post-event water (Fast Mode: 0.00%; 0 GT flooded features). Inspection images: `0_31_69_pre.jpg`, `0_31_69_post.jpg`, `0_31_69_post_acc_mask.jpg`. Finding: Upper hillside residential strip has dark rooftops and paved road segments flagged as class 1 in Accurate Mode (1.14% post vs 0.00% pre, net +1.14%); Fast Mode predicts 0.00% on both; steep forested slopes and fog are unflagged; 0 annotated flooded features.
4. **Resolution Sensitivity:**
   * While SegFormer's Mix Transformer encoder uses overlapped patch merging rather than fixed positional encodings, pixel recall varies with input scale: $2.65\%$ F1 at 384px, $20.5\%$ at 768px, and $27.82\%$ at native 512px sliding crops.
