# FloodWatch System Limitations & Empirical Verification

This document provides a factual record of known failure modes, dataset constraints, and empirical calibration results for FloodWatch. All numbers are traced to measured data or an explicit allow-list (drawn directly from [`docs/MEASURED.json`](MEASURED.json)).

---

## 1. Operating Assumptions & Boundary Constraints

* **Hardware Target:** Designed for offline execution on an **NVIDIA GeForce RTX 3050 Laptop GPU** (4 GB VRAM).
* **Model Checkpoint:** `checkpoints_joint` (SegFormer-B0 architecture, {{measured.system.model_size_mb}} MB FP16 weights).
* **Label Taxonomy:** 3-class segmentation mapping (0: Background, 1: Flooded Water, 2: Natural Water). Analysis computes net flood intrusion based strictly on **Model Class 1**.
* **Offline Requirement:** 100% offline runtime operation with zero external CDN, font, or cloud API calls.
* **Latency Definitions:**
  * **Server-Timing Total:** Measures server inference core execution (disk I/O + PyTorch preprocessing + GPU inference + argmax postprocessing). It excludes eager PNG mask encoding and HTTP serialization.
  * **Uncached Response Time:** Total server HTTP transaction duration including eager PNG mask generation (~{{measured.benchmarks.tile_0_41_58_timing_breakdown.server_eager_mask_encoding_ms | int}} ms added on tile `0_41_58`, bringing total uncached response to ~{{measured.benchmarks.tile_0_41_58_timing_breakdown.total_uncached_response_ms | int}} ms).
  * **Client Roundtrip Wall Time:** Measured in browser from `fetch()` initiation to DOM update (includes network transfer, JSON parsing, and DOM rendering).

---

## 2. Empirical Benchmark & Ground-Truth Calibration

Evaluated across all {{measured.dataset.total_tiles}} SpaceNet-8 Germany satellite tiles against rasterized human-annotated GeoJSON vector boundaries:
* **Ground-Truth Geometry & Resolution:**
  * Coordinate latitude: $\approx {{measured.dataset.resolution.latitude_deg}}^\circ\text{N}$.
  * GeoTIFF transform scale: $dx = dy \approx 4.6\times 10^{-6}\text{ deg/px}$ (${{measured.dataset.resolution.geotiff_transform_deg_per_px}}\text{ deg/px}$).
  * Ground resolution: Longitude $dx = {{measured.dataset.resolution.ground_resolution_lon_m_per_px}}\text{ m/px}$, Latitude $dy = {{measured.dataset.resolution.ground_resolution_lat_m_per_px}}\text{ m/px}$ (average ground resolution: ${{measured.dataset.resolution.ground_resolution_avg_m_per_px}}\text{ m/px}$).
  * Road buffer assumption: {{measured.dataset.resolution.road_buffer_radius_m}}-meter buffer radius; full {{measured.dataset.resolution.road_corridor_width_m}}-meter road corridor width $= \mathbf{ {{measured.dataset.resolution.road_corridor_width_px}} \text{ pixels} }$ (our heuristic assumption for road surface width, not an official competition standard).
* **Ground-Truth Composition ({{measured.dataset.flooded_gt_tiles}} Flooded Germany Tiles at 2m Buffer):**
  * Flooded Buildings: ${{measured.dataset.gt_composition_2m.building_pixels}}\text{ px}$ (${{measured.dataset.gt_composition_2m.building_pct}}\%$)
  * Flooded Roads: ${{measured.dataset.gt_composition_2m.road_pixels}}\text{ px}$ (${{measured.dataset.gt_composition_2m.road_pct}}\%$)
  * Total Flooded Ground-Truth Pixels: ${{measured.dataset.gt_composition_2m.total_gt_pixels}}\text{ px}$
* **Training Pool Context:** All {{measured.dataset.training_pool_tiles}} flooded Germany tiles were in the training pool, the training script held out no satellite tiles, and checkpoint selection used drone validation mIoU only. So the pixel F1, recall, and AUC figures are computed on training tiles and are not a held-out estimate.

### Accuracy Breakdown: Fast vs. Accurate Modes (2m Buffer)

| Metric | Fast Mode (768px Whole Tile) | Accurate Mode (512px Overlapping Crops) |
| :--- | :---: | :---: |
| **Predicted Positive Pixels** | {{measured.dataset.accuracy_modes_2m.fast_768.predicted_positive_pixels}} px | {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.predicted_positive_pixels}} px |
| **Building Recall** | **{{measured.dataset.accuracy_modes_2m.fast_768.building_recall_pct}}%** | **{{measured.dataset.accuracy_modes_2m.accurate_512_sliding.building_recall_pct}}%** |
| **Road Recall** | **{{measured.dataset.accuracy_modes_2m.fast_768.road_recall_pct}}%** | **{{measured.dataset.accuracy_modes_2m.accurate_512_sliding.road_recall_pct}}%** |
| **Combined Pixel Recall** | **{{measured.dataset.accuracy_modes_2m.fast_768.combined_recall_pct}}%** | **{{measured.dataset.accuracy_modes_2m.accurate_512_sliding.combined_recall_pct}}%** |
| **Combined precision vs annotated buildings and roads (flooded land without annotations counts as a false positive)** | **{{measured.dataset.accuracy_modes_2m.fast_768.combined_precision_pct}}%** | **{{measured.dataset.accuracy_modes_2m.accurate_512_sliding.combined_precision_pct}}%** |
| **Precision vs. Buildings** | {{measured.dataset.accuracy_modes_2m.fast_768.precision_vs_bldg_pct}}% | {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.precision_vs_bldg_pct}}% |
| **Precision vs. Roads** | {{measured.dataset.accuracy_modes_2m.fast_768.precision_vs_road_pct}}% | {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.precision_vs_road_pct}}% |
| **Pixel F1 Score** | {{measured.dataset.accuracy_modes_2m.fast_768.f1_pct}}% | {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.f1_pct}}% |
| **Pixel IoU** | {{measured.dataset.accuracy_modes_2m.fast_768.iou_pct}}% | {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.iou_pct}}% |
| **Tile-Level Flood ROC-AUC** | {{measured.dataset.accuracy_modes_2m.fast_768.roc_auc}} | {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.roc_auc}} |
| **Client Wall Time (Stress Test Median)** | **{{measured.benchmarks.warm_end_to_end_uncached_stage1.median_ms}} ms median** (P95: {{measured.benchmarks.warm_end_to_end_uncached_stage1.p95_ms}} ms) | **{{measured.benchmarks.stage3_accurate_client_wall_time.median_ms}} ms median** (P95: {{measured.benchmarks.stage3_accurate_client_wall_time.p95_ms}} ms) |

*Calibration Re-measurement:* Accurate-mode false positive pixels decreased from 1,364,444 to {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.fp}} (raising F1 from 27.82% to {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.f1_pct:.2f}}%) due to calibration pipeline unification: replacing the separate benchmark sliding-window script with direct calls to production `analyze_tile` and unified metric UTM EPSG:32632 ground-truth rasterization.

*Key Empirical Insight:* Flooded roads constitute ${{measured.dataset.gt_composition_2m.road_pct}}\%$ of all ground-truth flooded pixels, yet the model achieves only ${{measured.dataset.accuracy_modes_2m.fast_768.road_recall_pct}}\%$ road recall in Fast Mode and ${{measured.dataset.accuracy_modes_2m.accurate_512_sliding.road_recall_pct}}\%$ in Accurate Mode. In contrast, building recall is substantially higher: Accurate Mode raises building recall from ${{measured.dataset.accuracy_modes_2m.fast_768.building_recall_pct:.1f}}\%$ to ${{measured.dataset.accuracy_modes_2m.accurate_512_sliding.building_recall_pct:.1f}}\%$. Consequently, the model functions primarily as a building and open inundation detector, largely missing narrow road flooding.

---

## 3. Road-Buffer Sensitivity Analysis

To verify whether low road recall was an artifact of our 2-meter road buffer assumption, ground-truth rasterization and accuracy evaluation were conducted at 1 m, 2 m, and 3 m road buffers:

| Buffer Parameter | 1m Buffer (2m Corridor) | 2m Buffer (4m Corridor) | 3m Buffer (6m Corridor) |
| :--- | :---: | :---: | :---: |
| **Corridor Width in Pixels** | {{measured.dataset.road_buffer_sensitivity.1m.corridor_width_px}} px | {{measured.dataset.road_buffer_sensitivity.2m.corridor_width_px}} px | {{measured.dataset.road_buffer_sensitivity.3m.corridor_width_px}} px |
| **GT Road Pixels (% of total GT)** | {{measured.dataset.road_buffer_sensitivity.1m.gt_road_pixels}} px ({{measured.dataset.road_buffer_sensitivity.1m.road_pct}}%) | {{measured.dataset.road_buffer_sensitivity.2m.gt_road_pixels}} px ({{measured.dataset.road_buffer_sensitivity.2m.road_pct}}%) | {{measured.dataset.road_buffer_sensitivity.3m.gt_road_pixels}} px ({{measured.dataset.road_buffer_sensitivity.3m.road_pct}}%) |
| **GT Building Pixels** | {{measured.dataset.road_buffer_sensitivity.1m.building_pixels}} px | {{measured.dataset.road_buffer_sensitivity.2m.building_pixels}} px | {{measured.dataset.road_buffer_sensitivity.3m.building_pixels}} px |
| **Fast Building Recall** | {{measured.dataset.road_buffer_sensitivity.1m.fast_building_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.2m.fast_building_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.3m.fast_building_recall_pct}}% |
| **Accurate Building Recall** | {{measured.dataset.road_buffer_sensitivity.1m.accurate_building_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.2m.accurate_building_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.3m.accurate_building_recall_pct}}% |
| **Fast Road Recall** | {{measured.dataset.road_buffer_sensitivity.1m.fast_road_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.2m.fast_road_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.3m.fast_road_recall_pct}}% |
| **Accurate Road Recall** | {{measured.dataset.road_buffer_sensitivity.1m.accurate_road_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.2m.accurate_road_recall_pct}}% | {{measured.dataset.road_buffer_sensitivity.3m.accurate_road_recall_pct}}% |
| **Fast Combined Recall / IoU** | {{measured.dataset.road_buffer_sensitivity.1m.fast_combined_recall_pct}}% / {{measured.dataset.road_buffer_sensitivity.1m.fast_iou_pct}}% | {{measured.dataset.road_buffer_sensitivity.2m.fast_combined_recall_pct}}% / {{measured.dataset.road_buffer_sensitivity.2m.fast_iou_pct}}% | {{measured.dataset.road_buffer_sensitivity.3m.fast_combined_recall_pct}}% / {{measured.dataset.road_buffer_sensitivity.3m.fast_iou_pct}}% |
| **Accurate Combined Recall / IoU** | {{measured.dataset.road_buffer_sensitivity.1m.accurate_combined_recall_pct}}% / {{measured.dataset.road_buffer_sensitivity.1m.accurate_iou_pct}}% | {{measured.dataset.road_buffer_sensitivity.2m.accurate_combined_recall_pct}}% / {{measured.dataset.road_buffer_sensitivity.2m.accurate_iou_pct}}% | {{measured.dataset.road_buffer_sensitivity.3m.accurate_combined_recall_pct}}% / {{measured.dataset.road_buffer_sensitivity.3m.accurate_iou_pct}}% |

*Key Finding on Buffer Sensitivity:*
1. **Building recall is completely invariant to road buffer width** (${{measured.dataset.road_buffer_sensitivity.2m.fast_building_recall_pct}}\%$ Fast, ${{measured.dataset.road_buffer_sensitivity.2m.accurate_building_recall_pct}}\%$ Accurate across all buffers).
2. **Road recall remains low across all buffer assumptions** (${{measured.dataset.road_buffer_sensitivity.1m.fast_road_recall_pct}}\%$ to ${{measured.dataset.road_buffer_sensitivity.3m.fast_road_recall_pct}}\%$ Fast; ${{measured.dataset.road_buffer_sensitivity.1m.accurate_road_recall_pct}}\%$ to ${{measured.dataset.road_buffer_sensitivity.3m.accurate_road_recall_pct}}\%$ Accurate).
3. **Resizing is not the primary cause of low road recall:** even when evaluating native overlapping 512px sliding crops (Accurate Mode) at a narrow 1m buffer, road recall reaches only ${{measured.dataset.road_buffer_sensitivity.1m.accurate_road_recall_pct}}\%$. The model struggles to detect narrow linear flood features regardless of scale or buffer width.

---

## 4. Accurate Mode Performance on Demo "Model Miss" Tiles

The impact of Accurate Mode was measured on four demo tiles with low or zero Fast Mode detections:

| Tile ID | Annotated GT Features | Fast Mode Net | Accurate Mode Net | Observed Effect |
| :--- | :--- | :---: | :---: | :--- |
| `0_23_62` | {{measured.dataset.demo_tiles_agreement.6.gt_bldg_count}} buildings, {{measured.dataset.demo_tiles_agreement.6.gt_road_count}} roads | $+{{measured.dataset.demo_tiles.6.net_intrusion_pct}}\%$ | **$+{{measured.dataset.flooded_tiles_66_all.7.accurate_net}}\%$** | Net increase from {{measured.dataset.demo_tiles.6.net_intrusion_pct}}% to {{measured.dataset.flooded_tiles_66_all.7.accurate_net}}%; building recall rises from {{measured.dataset.demo_tiles_agreement.6.fast_mode.bldg_recall_pct}}% to {{measured.dataset.demo_tiles_agreement.6.accurate_mode.bldg_recall_pct}}% (precision vs annotated buildings and roads: {{measured.dataset.demo_tiles_agreement.6.accurate_mode.precision_pct}}%). |
| `0_40_62` | {{measured.dataset.demo_tiles_agreement.8.gt_bldg_count}} buildings, {{measured.dataset.demo_tiles_agreement.8.gt_road_count}} roads | $+{{measured.dataset.demo_tiles.8.net_intrusion_pct}}\%$ | **$+{{measured.dataset.flooded_tiles_66_all.58.accurate_net}}\%$** | Net increase from {{measured.dataset.demo_tiles.8.net_intrusion_pct}}% to {{measured.dataset.flooded_tiles_66_all.58.accurate_net}}%; building recall rises from {{measured.dataset.demo_tiles_agreement.8.fast_mode.bldg_recall_pct}}% to {{measured.dataset.demo_tiles_agreement.8.accurate_mode.bldg_recall_pct}}% (precision vs annotated buildings and roads: {{measured.dataset.demo_tiles_agreement.8.accurate_mode.precision_pct}}%). |
| `0_29_66` | {{measured.dataset.demo_tiles_agreement.7.gt_bldg_count}} buildings, {{measured.dataset.demo_tiles_agreement.7.gt_road_count}} roads | $0.00\%$ | **${{measured.dataset.flooded_tiles_66_all.34.accurate_net}}\%$** | Remains near zero; low-contrast structures. |
| `0_39_62` | {{measured.dataset.demo_tiles_agreement.9.gt_bldg_count}} buildings, {{measured.dataset.demo_tiles_agreement.9.gt_road_count}} roads | $0.00\%$ | **$0.00\%$** | 0.00% in both modes; road-only flooding undetected without structures. |

*Takeaway:* Accurate Mode successfully recovers flooded structures that fall below resolution thresholds in Fast Mode (${{measured.dataset.demo_tiles.6.net_intrusion_pct}}\% \to {{measured.dataset.flooded_tiles_66_all.7.accurate_net}}\%$ on `0_23_62`, ${{measured.dataset.demo_tiles.8.net_intrusion_pct}}\% \to {{measured.dataset.flooded_tiles_66_all.58.accurate_net}}\%$ on `0_40_62`). However, when flooding is confined strictly to narrow roads without flooded buildings (e.g., `0_39_62`), neither mode detects the water.

---

## 5. Dry Tiles False-Alarm Evaluation ({{measured.dataset.non_training_tiles}} Not-in-Pool Tiles)

To evaluate false alarm behavior on unflooded terrain, all {{measured.dataset.non_training_tiles}} not-in-pool tiles were scanned in both Fast and Accurate modes side-by-side:

| False Alarm Metric | Fast Mode (768px Resize) | Accurate Mode (512px Sliding Window) |
| :--- | :---: | :---: |
| **Tiles with Pre-Event Flooded Area $> 0.1\%$** | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_before_gt_0_1}} tile** (`0_20_66` at ${{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_before}}\%$) | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_before_gt_0_1}} tiles** (max: ${{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_before}}\%$ on `0_20_66`) |
| **Tiles with Post-Event Flooded Area $> 0.1\%$** | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_after_gt_0_1}} tiles** (max: ${{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_after}}\%$ on `0_29_68`) | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_after_gt_0_1}} tiles** (max: ${{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_after}}\%$ on `0_38_69`) |
| **Tiles with Net Intrusion $== 0.00\%$** | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_net_eq_0}} tiles** (${{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.pct_net_eq_0}}\%$) | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_net_eq_0}} tiles** (${{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.pct_net_eq_0}}\%$) |
| **Tiles with Net Intrusion $> 0$** | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_net_gt_0}} tile** (`0_29_68` at $+{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_net}}\%$) | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_net_gt_0}} tiles** (max: $+{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_net}}\%$ on `0_31_69`) |
| **Tiles with Net Intrusion $< 0$** | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_net_lt_0}} tile** (`0_20_66` at ${{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.min_net}}\%$) | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_net_lt_0}} tiles** (min: ${{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.min_net}}\%$ on `0_20_66`) |
| **Max Post-Event Flooded Area Detected** | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_after}}%** (`0_29_68`) | **{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_after}}%** (`0_38_69`) |
| **Max Net Intrusion Detected** | **+{{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_net}}%** (`0_29_68`) | **+{{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_net}}%** (`0_31_69`) |
| **Flooded Tiles with Net $> 1.0\%$ ({{measured.dataset.flooded_gt_tiles}} Train Tiles)** | **{{measured.dataset.flooded_tiles_net_gt_1_comparison_66.fast_gt_1_count}} tiles** ({{measured.dataset.flooded_tiles_net_gt_1_comparison_66.fast_gt_1_pct:.2f}}%) | **{{measured.dataset.flooded_tiles_net_gt_1_comparison_66.accurate_gt_1_count}} tiles** ({{measured.dataset.flooded_tiles_net_gt_1_comparison_66.accurate_gt_1_pct:.2f}}%) |

*Trade-Off Reality:* Accurate Mode produces **more false alarms**, not fewer. While Accurate Mode increases the number of flooded tiles detected above $1.0\%$ net intrusion from {{measured.dataset.flooded_tiles_net_gt_1_comparison_66.fast_gt_1_count}} to {{measured.dataset.flooded_tiles_net_gt_1_comparison_66.accurate_gt_1_count}} ({{measured.dataset.flooded_tiles_net_gt_1_comparison_66.accurate_gt_1_pct:.2f}}\%) by recovering small flooded structures, its higher sensitivity comes at the cost of {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_after_gt_0_1}} false-alarm tiles with post-event flooded area $> 0.1\%$ (up to ${{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_after}}\%$) on completely dry, unflooded terrain.

---

## 6. Dataset Splitting & Candidate Pool Facts

* **Geographic Coverage:** Raw imagery in `data/raw` contains exclusively Germany tiles (prefix `0_`). Louisiana tiles (prefix `2_`) were present in training crops (`satellite_processed/images`), but do not exist in the raw GeoTIFF repository.
* **Candidate Training Pool:**
  * Exactly {{measured.dataset.training_pool_tiles}} Germany tiles overlap the candidate training pool (`satellite_processed/images`).
  * All {{measured.dataset.training_pool_tiles}} of these tiles contain positive human-annotated flooded ground truth (`gt_flooded_count > 0`).
* **Validation Split Reality:**
  * Examination of `train_joint_segformer.py` reveals that **no satellite validation set was held out during joint training**.
  * The validation dataset in `train_joint_segformer.py` consisted entirely of 100 Drone (FloodNet) images (`DroneValDataset`). Model checkpoint selection was driven strictly by validation mIoU on drone imagery.
* **Reconciled Not-in-Pool Anomalies ({{measured.dataset.non_training_tiles}} Tiles):**
  * `0_20_66`: `before: {{measured.dataset.not_in_pool_anomalies.0.before}}%`, `after: {{measured.dataset.not_in_pool_anomalies.0.after}}%`, `net: {{measured.dataset.not_in_pool_anomalies.0.net}}%`.
  * `0_29_68`: `before: {{measured.dataset.not_in_pool_anomalies.1.before}}%`, `after: {{measured.dataset.not_in_pool_anomalies.1.after}}%`, `net: {{measured.dataset.not_in_pool_anomalies.1.net}}%`.
  * All other 134 tiles have `before: 0.00%`, `after: 0.00%`, `net: 0.00%`. Note that `0_36_61` (`before: 0.15%`, `net: -0.15%`) has 15 ground-truth flooded features and is part of the 66 training pool tiles, not not-in-pool.

---

## 7. Known Failure Modes & Visual Inspections

1. **Model Misses on Narrow Roads:**
   * Example: Tile `0_39_62`. Contains 3 annotated flooded road corridors and 0 buildings. The model predicts $0.00\%$ flooded area (class 1) in both Fast and Accurate modes, reflecting the {{measured.dataset.accuracy_modes_2m.fast_768.road_recall_pct}}\% – {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.road_recall_pct}}\% road recall limit.
2. **Pre-Event False Positives (Negative Net):**
   * Example: Tile `0_20_66`. Contains 0 annotated flooded features. Pre-event imagery produces ${{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_before}}\%$ flooded area (class 1) prediction in Fast Mode (${{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_before}}\%$ in Accurate Mode), while post-event imagery produces $0.00\%$ Fast (${{measured.dataset.demo_tiles_agreement.13.accurate_mode.after_pct}}\%$ Accurate), resulting in net intrusion of ${{measured.dataset.demo_tiles.13.net_intrusion_pct}}\%$.
   * **Visual Inspection Verification:** The following inspection images were rendered and directly examined:
     1. `docs/inspection/0_20_66_pre.jpg`
     2. `docs/inspection/0_20_66_pre_fast_mask.jpg`
     3. `docs/inspection/0_20_66_pre_acc_mask.jpg`
     4. `docs/inspection/0_20_66_post.jpg`
   * Visual verification confirms that false-positive cyan masks cover roofs and small open areas between buildings in the pre-event image, while post-event is clean. The specific root cause is **cause not determined**. FloodWatch displays an explicit explanatory banner: *"No net increase: less flooded area detected post-event than pre-event."*
3. **Dry-Tile Post-Event False Alarms in Accurate Mode:**
   * In Accurate Mode, {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_after_gt_0_1}} dry tiles exceed $0.1\%$ post-event flooded area (class 1). The two worst cases were rendered and visually inspected:
     * **Tile `0_38_69`:** Accurate Mode predicts {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_after}}% post-event water (Fast Mode: 0.00%; 0 GT flooded features). Inspection images: `0_38_69_pre.jpg`, `0_38_69_post.jpg`, `0_38_69_post_acc_mask.jpg`. Finding: {{measured.inspections.tile_0_38_69.finding}}
     * **Tile `0_31_69`:** Accurate Mode predicts {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_net}}% post-event water (Fast Mode: 0.00%; 0 GT flooded features). Inspection images: `0_31_69_pre.jpg`, `0_31_69_post.jpg`, `0_31_69_post_acc_mask.jpg`. Finding: {{measured.inspections.tile_0_31_69.finding}}
4. **Resolution Sensitivity:**
   * While SegFormer's Mix Transformer encoder uses overlapped patch merging rather than fixed positional encodings, pixel recall varies with input scale: ${{measured.dataset.settings_benchmark.384.pixel_f1}}\%$ F1 at 384px, ${{measured.dataset.settings_benchmark.768.pixel_f1}}\%$ at 768px, and ${{measured.dataset.settings_benchmark.native_crops_512.pixel_f1}}\%$ at native 512px sliding crops.
