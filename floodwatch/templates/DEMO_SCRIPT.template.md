# FloodWatch 2-Minute Demo Presentation Script

This script provides an exact, factual, 2-minute walkthrough designed for live presentations and evaluators. All numbers are drawn directly from [`docs/MEASURED.json`](MEASURED.json).

---

## 2-Minute Spoken Walkthrough (Word Count: 171 Words)

### 0:00 – 0:15: Opening & Architecture
*(Show FloodWatch header and architecture badges)*
> *"FloodWatch runs 100% offline on a local RTX 3050 GPU. When disaster strikes, responders have no cloud access. FloodWatch serves prewarmed tiles in {{measured.benchmarks.prewarmed_click_to_render_30_tiles.median_ms}} ms, meaning cached at startup."*
*(3 numbers | 29 words)*

---

### 0:15 – 0:35: Step 1 – Severe Flood Hit (`0_41_58`)
*(Click tile `0_41_58` on the swath grid)*
> *"Tile 0_41_58 is our severe case. Up front: all {{measured.dataset.training_pool_tiles}} flooded Germany tiles were in the training pool. FloodWatch detects a +{{measured.dataset.demo_tiles.0.net_intrusion_pct:.2f}}% net surge, with {{measured.dataset.demo_tiles_agreement.0.fast_mode.recall_pct:.1f}}% recall across {{measured.dataset.demo_tiles_agreement.0.gt_features}} annotated features."*
*(5 numbers | 30 words)*

---

### 0:35 – 0:50: Step 2 – Re-run Live GPU Inference (`0_41_58`)
*(Click the '⚡ Re-run live' button on the inspector card)*
> *"Clicking 'Re-run live' bypasses the cache, executing full GPU inference in {{measured.benchmarks.warm_end_to_end_uncached_stage1.median_ms}} ms median roundtrip."*
*(1 number | 15 words)*

---

### 0:50 – 1:10: Step 3 – Moderate Flood Hit (`0_27_68`)
*(Click tile `0_27_68` on the demo quick-pick bar)*
> *"On tile 0_27_68, also in the training pool, the model detects +{{measured.dataset.demo_tiles.1.net_intrusion_pct:.2f}}% net intrusion with {{measured.dataset.demo_tiles_agreement.1.fast_mode.recall_pct:.1f}}% recall across {{measured.dataset.demo_tiles_agreement.1.gt_features}} annotated features."*
*(4 numbers | 21 words)*

---

### 1:10 – 1:30: Step 4 – Model Limitation & Accurate Mode (`0_23_62`)
*(Click tile `0_23_62`, then toggle Accurate Mode)*
> *"Tile 0_23_62 illustrates a limitation. Fast mode detects +{{measured.dataset.demo_tiles.6.net_intrusion_pct:.2f}}% net intrusion. Toggling Accurate Mode uses 512-pixel sliding crops, increasing building recall from {{measured.dataset.demo_tiles_agreement.6.fast_mode.bldg_recall_pct:.1f}}% to {{measured.dataset.demo_tiles_agreement.6.accurate_mode.bldg_recall_pct:.1f}}% and net intrusion to +{{measured.dataset.demo_tiles_agreement.6.accurate_mode.after_pct:.2f}}%."*
*(5 numbers | 30 words)*

---

### 1:30 – 1:45: Step 5 – False Alarm Check (`0_15_63` & `0_20_66`)
*(Click tile `0_15_63`, then `0_20_66` on the demo bar)*
> *"Tile 0_15_63 from the {{measured.dataset.non_training_tiles}} unflooded tiles yields 0.00% flooded area (class 1). On 0_20_66, pre-event false positives produce {{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.min_net}}% net, flagged by an explanatory banner."*
*(4 numbers | 24 words)*

---

### 1:45 – 2:00: Step 6 – Summary & Offline Resilience
*(Pan swath grid showing complete spatial coverage)*
> *"Across {{measured.dataset.non_training_tiles}} dry tiles, Fast mode had {{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_after_gt_0_1}} false alarms above 0.1% post-event; Accurate mode had {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_after_gt_0_1}}. FloodWatch provides robust offline disaster triage."*
*(4 numbers | 22 words)*

---

## 60-Second Fallback Version (Word Count: 103 Words)

> *"FloodWatch delivers 100% offline flood analysis on an RTX 3050 GPU in {{measured.benchmarks.warm_end_to_end_uncached_stage1.median_ms}} ms median client roundtrip and {{measured.benchmarks.prewarmed_click_to_render_30_tiles.median_ms}} ms prewarmed (meaning cached at startup).
> 
> Tile 0_41_58 shows severe inundation at +{{measured.dataset.demo_tiles.0.net_intrusion_pct:.2f}}% net intrusion with {{measured.dataset.demo_tiles_agreement.0.fast_mode.recall_pct:.1f}}% recall across {{measured.dataset.demo_tiles_agreement.0.gt_features}} features. All {{measured.dataset.training_pool_tiles}} flooded Germany tiles were in the training pool.
> 
> Tile 0_23_62 demonstrates a limitation: Fast mode achieves {{measured.dataset.demo_tiles_agreement.6.fast_mode.bldg_recall_pct:.1f}}% building recall, but Accurate mode's 512-pixel sliding crops raise building recall to {{measured.dataset.demo_tiles_agreement.6.accurate_mode.bldg_recall_pct:.1f}}% and net intrusion to +{{measured.dataset.demo_tiles_agreement.6.accurate_mode.after_pct:.2f}}%.
> 
> Across {{measured.dataset.non_training_tiles}} dry tiles, Fast mode produces {{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_after_gt_0_1}} post-event false alarms over 0.1%, confirming high specificity on unflooded terrain."*

---

## Known Quirks During Demo & What to Do

1. **Startup Prewarm Delay (~130 s):**
   * *Symptom:* Server takes ~130 seconds to launch with `FW_PREWARM=all`.
   * *What to do:* Run `start_demo.bat` 2–3 minutes before the presentation. Once "Application startup complete" appears in the terminal, the 256-entry cache is primed.
2. **Accurate Mode Latency (1.4 s – 2.8 s uncached):**
   * *Symptom:* Switching to Accurate Mode on an uncached tile takes 1.4 to 2.8 seconds.
   * *What to do:* Explain that Accurate Mode executes 25 overlapping 512x512 sliding window crops chunked to batches of $\le 8$ to safely fit 4 GB VRAM. When cached or prewarmed, it returns in ~{{measured.benchmarks.prewarmed_click_to_render_30_tiles.median_ms | int}} ms.
3. **Rapid Arrow Key Navigation:**
   * *Symptom:* Tapping arrow keys rapidly in the grid.
   * *What to do:* The UI implements trailing debounce (120 ms) and latest-wins request cancellation, cutting redundant network requests in half (5 vs 10 requests) so only the final destination tile finishes rendering without stalling the GPU.

---

## Presenter Reference Notes & Detailed Data

### Tile Agreement Metrics (from `MEASURED.json`):
* **`0_41_58` (Severe Hit):** Net +{{measured.dataset.demo_tiles.0.net_intrusion_pct}}0% (Before: {{measured.dataset.demo_tiles.0.before_pct}}% | After: {{measured.dataset.demo_tiles.0.after_pct}}%). {{measured.dataset.demo_tiles_agreement.0.gt_features}} GT features ({{measured.dataset.demo_tiles_agreement.0.gt_bldg_count}} buildings, {{measured.dataset.demo_tiles_agreement.0.gt_road_count}} roads). Fast Recall: {{measured.dataset.demo_tiles_agreement.0.fast_mode.recall_pct}}% (Bldg: {{measured.dataset.demo_tiles_agreement.0.fast_mode.bldg_recall_pct}}%, Road: {{measured.dataset.demo_tiles_agreement.0.fast_mode.road_recall_pct}}%), Fast precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): {{measured.dataset.demo_tiles_agreement.0.fast_mode.precision_pct}}%, IoU: {{measured.dataset.demo_tiles_agreement.0.fast_mode.iou_pct}}%. Accurate Recall: {{measured.dataset.demo_tiles_agreement.0.accurate_mode.recall_pct}}%, Accurate precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): {{measured.dataset.demo_tiles_agreement.0.accurate_mode.precision_pct}}%. Server inference core latency: {{measured.benchmarks.tile_0_41_58_timing_breakdown.server_inference_core_ms}} ms (excludes ~{{measured.benchmarks.tile_0_41_58_timing_breakdown.server_eager_mask_encoding_ms | int}} ms eager PNG mask encoding; total uncached response: ~{{measured.benchmarks.tile_0_41_58_timing_breakdown.total_uncached_response_ms | int}} ms).
* **`0_27_68` (Moderate Hit):** Net +{{measured.dataset.demo_tiles.1.net_intrusion_pct}}% (Before: {{measured.dataset.demo_tiles.1.before_pct}}% | After: {{measured.dataset.demo_tiles.1.after_pct}}%). {{measured.dataset.demo_tiles_agreement.1.gt_features}} GT features ({{measured.dataset.demo_tiles_agreement.1.gt_bldg_count}} buildings, {{measured.dataset.demo_tiles_agreement.1.gt_road_count}} roads). Fast Recall: {{measured.dataset.demo_tiles_agreement.1.fast_mode.recall_pct}}% (Bldg: {{measured.dataset.demo_tiles_agreement.1.fast_mode.bldg_recall_pct}}%, Road: {{measured.dataset.demo_tiles_agreement.1.fast_mode.road_recall_pct}}%), Fast precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): {{measured.dataset.demo_tiles_agreement.1.fast_mode.precision_pct}}%, IoU: {{measured.dataset.demo_tiles_agreement.1.fast_mode.iou_pct}}%. Accurate Recall: {{measured.dataset.demo_tiles_agreement.1.accurate_mode.recall_pct}}%, Accurate precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): {{measured.dataset.demo_tiles_agreement.1.accurate_mode.precision_pct}}%.
* **`0_23_62` (Model Miss):** Net +{{measured.dataset.demo_tiles.6.net_intrusion_pct}}% Fast vs +{{measured.dataset.flooded_tiles_66_all.7.accurate_net}}% Accurate. {{measured.dataset.demo_tiles_agreement.6.gt_features}} GT features ({{measured.dataset.demo_tiles_agreement.6.gt_bldg_count}} buildings, {{measured.dataset.demo_tiles_agreement.6.gt_road_count}} roads). Fast Building Recall: {{measured.dataset.demo_tiles_agreement.6.fast_mode.bldg_recall_pct}}% (Road: {{measured.dataset.demo_tiles_agreement.6.fast_mode.road_recall_pct}}%, Fast precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): {{measured.dataset.demo_tiles_agreement.6.fast_mode.precision_pct}}%). Accurate Building Recall: {{measured.dataset.demo_tiles_agreement.6.accurate_mode.bldg_recall_pct}}% (Road: {{measured.dataset.demo_tiles_agreement.6.accurate_mode.road_recall_pct}}%, Accurate precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): {{measured.dataset.demo_tiles_agreement.6.accurate_mode.precision_pct}}%).
* **`0_15_63` (True Negative):** Net 0.00% (Before: 0.00% | After: 0.00%). 0 GT features.
* **`0_20_66` (False Positive):** Net {{measured.dataset.demo_tiles.13.net_intrusion_pct}}% (Before: {{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_before}}% | After: 0.00%). 0 GT features. Inspection images viewed: `docs/inspection/0_20_66_pre.jpg`, `0_20_66_pre_fast_mask.jpg`, `0_20_66_pre_acc_mask.jpg`, `0_20_66_post.jpg`. Finding: Pre-event imagery displays false-positive cyan masks on settlement structures ({{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_before}}% Fast, {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_before}}% Accurate); post-event predicts 0.00% Fast, {{measured.dataset.demo_tiles_agreement.13.accurate_mode.after_pct}}% Accurate; ground-truth records 0 flooded features; specific root cause not determined.

---

## Likely Evaluator / Judge Questions & Factual Answers

### Q1: "Why is your IoU only {{measured.dataset.accuracy_modes_2m.fast_768.iou_pct}}% in Fast Mode and {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.iou_pct}}% in Accurate Mode?"
**Answer:**
> *"SpaceNet-8 ground truth includes narrow roads buffered by 2 meters, which at {{measured.dataset.resolution.ground_resolution_avg_m_per_px}} m/pixel average ground resolution corresponds to a {{measured.dataset.resolution.road_corridor_width_px}}-pixel corridor width. Roads constitute {{measured.dataset.gt_composition_2m.road_pct}}% of all ground-truth flooded pixels, yet the model achieves only {{measured.dataset.accuracy_modes_2m.fast_768.road_recall_pct}}% road recall in Fast Mode and {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.road_recall_pct}}% in Accurate Mode. In contrast, building recall is {{measured.dataset.accuracy_modes_2m.fast_768.building_recall_pct}}% in Fast Mode and jumps to {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.building_recall_pct}}% in Accurate Mode. Accurate Mode's 512px sliding window raises building recall from {{measured.dataset.accuracy_modes_2m.fast_768.building_recall_pct:.1f}}% to {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.building_recall_pct:.1f}}% and recovers missed building flooding (such as on tile 0_23_62 where building recall jumps from {{measured.dataset.demo_tiles_agreement.6.fast_mode.bldg_recall_pct}}% to {{measured.dataset.demo_tiles_agreement.6.accurate_mode.bldg_recall_pct}}% and net intrusion rises from +{{measured.dataset.demo_tiles.6.net_intrusion_pct}}% to +{{measured.dataset.flooded_tiles_66_all.7.accurate_net}}%), raising overall pixel recall from {{measured.dataset.accuracy_modes_2m.fast_768.combined_recall_pct}}% to {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.combined_recall_pct}}% and IoU from {{measured.dataset.accuracy_modes_2m.fast_768.iou_pct}}% to {{measured.dataset.accuracy_modes_2m.accurate_512_sliding.iou_pct}}%."*

### Q2: "Did you evaluate on genuinely unseen flood disasters?"
**Answer:**
> *"All {{measured.dataset.training_pool_tiles}} tiles containing annotated flooding in Germany were in the candidate training pool (`satellite_processed/images`), and no satellite validation set was held out during joint training. Therefore, our accuracy metrics reflect training pool fit, not held-out disaster performance. However, the remaining {{measured.dataset.non_training_tiles}} tiles in our dataset were not in the training pool and serve as a check for false alarms on unflooded terrain. Across those {{measured.dataset.non_training_tiles}} tiles, zero had post-event false alarms over 0.1% (the maximum detected was {{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_after}}% on 0_29_68), and {{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.count_net_eq_0}} of {{measured.dataset.non_training_tiles}} had net intrusion of exactly 0.00%. In Accurate Mode, false alarms on dry tiles increase to {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.count_after_gt_0_1}} tiles with post-event flooded area (class 1) over 0.1% (maximum: {{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_after}}% on 0_38_69)."*

### Q3: "Why did tile 0_20_66 produce a negative net intrusion ({{measured.dataset.demo_tiles.13.net_intrusion_pct}}%)?"
**Answer:**
> *"The net intrusion formula is `after_pct - before_pct`. On tile 0_20_66, the model predicted {{measured.dataset.dry_tiles_false_alarm_comparison_136.fast_mode.max_before}}% flooded area (class 1) in Fast Mode ({{measured.dataset.dry_tiles_false_alarm_comparison_136.accurate_mode.max_before}}% in Accurate Mode) on pre-event imagery and 0.00% Fast ({{measured.dataset.demo_tiles_agreement.13.accurate_mode.after_pct}}% Accurate) on post-event imagery, despite zero annotated flooding. We inspected all four pre- and post-event images and mask overlays (`docs/inspection/0_20_66_pre.jpg`, `0_20_66_pre_fast_mask.jpg`, `0_20_66_pre_acc_mask.jpg`, `0_20_66_post.jpg`). The pre-event imagery visibly displays false-positive cyan mask patches over settlement building roofs and driveway surfaces, whereas the post-event image is clean. The specific root cause for this spectral confusion is not determined. Rather than suppressing this anomaly, FloodWatch transparently reports it with an explanatory banner: 'No net increase: less flooded area detected post-event than pre-event.'"*

### Q4: "How does this run completely offline without an internet connection?"
**Answer:**
> *"The backend is a local FastAPI process holding the SegFormer-B0 FP16 weights resident in GPU VRAM (taking {{measured.system.peak_gpu_vram_mb}} MB peak VRAM). The frontend is pure HTML, CSS, and ES6 JavaScript with zero CDN or Google Font dependencies. In automated headless browser audits via Chrome DevTools Protocol, exactly 0 external network requests were made."*

### Q5: "What is the measured click-to-render latency?"
**Answer:**
> *"In automated headless Chrome benchmarks across 30 distinct uncached tiles, cold click-to-render had a median of {{measured.benchmarks.cold_click_to_render_30_tiles.requests_2_to_30_uncached.median_ms}} ms and P95 of {{measured.benchmarks.cold_click_to_render_30_tiles.requests_2_to_30_uncached.p95_ms}} ms (with Server-Timing I/O median of {{measured.benchmarks.cold_click_to_render_30_tiles.requests_2_to_30_uncached.server_timing_io_median_ms}} ms; OS file-system cache state was not controlled). Client-side warm end-to-end roundtrip across 50 tiles has a median of {{measured.benchmarks.warm_end_to_end_uncached_stage1.median_ms}} ms and P95 of {{measured.benchmarks.warm_end_to_end_uncached_stage1.p95_ms}} ms. When prewarmed (`FW_PREWARM=all`), 30 distinct clicks yielded a median of {{measured.benchmarks.prewarmed_click_to_render_30_tiles.median_ms}} ms and P95 of {{measured.benchmarks.prewarmed_click_to_render_30_tiles.p95_ms}} ms."*
