# FloodWatch 2-Minute Demo Presentation Script

This script provides an exact, factual, 2-minute walkthrough designed for live presentations and evaluators. All numbers are drawn directly from [`docs/MEASURED.json`](MEASURED.json).

---

## 2-Minute Spoken Walkthrough (Word Count: 171 Words)

### 0:00 – 0:15: Opening & Architecture
*(Show FloodWatch header and architecture badges)*
> *"FloodWatch runs 100% offline on a local RTX 3050 GPU. When disaster strikes, responders have no cloud access. FloodWatch serves prewarmed tiles in 61.3 ms, meaning cached at startup."*
*(3 numbers | 29 words)*

---

### 0:15 – 0:35: Step 1 – Severe Flood Hit (`0_41_58`)
*(Click tile `0_41_58` on the swath grid)*
> *"Tile 0_41_58 is our severe case. Up front: all 66 flooded Germany tiles were in the training pool. FloodWatch detects a +39.00% net surge, with 85.1% recall across 181 annotated features."*
*(5 numbers | 30 words)*

---

### 0:35 – 0:50: Step 2 – Re-run Live GPU Inference (`0_41_58`)
*(Click the '⚡ Re-run live' button on the inspector card)*
> *"Clicking 'Re-run live' bypasses the cache, executing full GPU inference in 498.1229000259191 ms median roundtrip."*
*(1 number | 15 words)*

---

### 0:50 – 1:10: Step 3 – Moderate Flood Hit (`0_27_68`)
*(Click tile `0_27_68` on the demo quick-pick bar)*
> *"On tile 0_27_68, also in the training pool, the model detects +6.96% net intrusion with 34.3% recall across 86 annotated features."*
*(4 numbers | 21 words)*

---

### 1:10 – 1:30: Step 4 – Model Limitation & Accurate Mode (`0_23_62`)
*(Click tile `0_23_62`, then toggle Accurate Mode)*
> *"Tile 0_23_62 illustrates a limitation. Fast mode detects +0.08% net intrusion. Toggling Accurate Mode uses 512-pixel sliding crops, increasing building recall from 1.0% to 5.3% and net intrusion to +0.66%."*
*(5 numbers | 30 words)*

---

### 1:30 – 1:45: Step 5 – False Alarm Check (`0_15_63` & `0_20_66`)
*(Click tile `0_15_63`, then `0_20_66` on the demo bar)*
> *"Tile 0_15_63 from the 136 unflooded tiles yields 0.00% flooded area (class 1). On 0_20_66, pre-event false positives produce -3.32% net, flagged by an explanatory banner."*
*(4 numbers | 24 words)*

---

### 1:45 – 2:00: Step 6 – Summary & Offline Resilience
*(Pan swath grid showing complete spatial coverage)*
> *"Across 136 dry tiles, Fast mode had 0 false alarms above 0.1% post-event; Accurate mode had 8. FloodWatch provides robust offline disaster triage."*
*(4 numbers | 22 words)*

---

## 60-Second Fallback Version (Word Count: 103 Words)

> *"FloodWatch delivers 100% offline flood analysis on an RTX 3050 GPU in 498.1229000259191 ms median client roundtrip and 61.3 ms prewarmed (meaning cached at startup).
> 
> Tile 0_41_58 shows severe inundation at +39.00% net intrusion with 85.1% recall across 181 features. All 66 flooded Germany tiles were in the training pool.
> 
> Tile 0_23_62 demonstrates a limitation: Fast mode achieves 1.0% building recall, but Accurate mode's 512-pixel sliding crops raise building recall to 5.3% and net intrusion to +0.66%.
> 
> Across 136 dry tiles, Fast mode produces 0 post-event false alarms over 0.1%, confirming high specificity on unflooded terrain."*

---

## Known Quirks During Demo & What to Do

1. **Startup Prewarm Delay (~130 s):**
   * *Symptom:* Server takes ~130 seconds to launch with `FW_PREWARM=all`.
   * *What to do:* Run `start_demo.bat` 2–3 minutes before the presentation. Once "Application startup complete" appears in the terminal, the 256-entry cache is primed.
2. **Accurate Mode Latency (1.4 s – 2.8 s uncached):**
   * *Symptom:* Switching to Accurate Mode on an uncached tile takes 1.4 to 2.8 seconds.
   * *What to do:* Explain that Accurate Mode executes 25 overlapping 512x512 sliding window crops chunked to batches of $\le 8$ to safely fit 4 GB VRAM. When cached or prewarmed, it returns in ~61 ms.
3. **Rapid Arrow Key Navigation:**
   * *Symptom:* Tapping arrow keys rapidly in the grid.
   * *What to do:* The UI implements trailing debounce (120 ms) and latest-wins request cancellation, cutting redundant network requests in half (5 vs 10 requests) so only the final destination tile finishes rendering without stalling the GPU.

---

## Presenter Reference Notes & Detailed Data

### Tile Agreement Metrics (from `MEASURED.json`):
* **`0_41_58` (Severe Hit):** Net +39.00% (Before: 0.54% | After: 39.54%). 181 GT features (169 buildings, 12 roads). Fast Recall: 85.14% (Bldg: 84.85%, Road: 86.37%), Fast precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 35.36%, IoU: 33.3%. Accurate Recall: 91.48%, Accurate precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 34.59%. Server inference core latency: 333 ms (excludes ~177 ms eager PNG mask encoding; total uncached response: ~510 ms).
* **`0_27_68` (Moderate Hit):** Net +6.96% (Before: 0.0% | After: 6.96%). 86 GT features (80 buildings, 6 roads). Fast Recall: 34.26% (Bldg: 41.42%, Road: 6.47%), Fast precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 55.85%, IoU: 26.96%. Accurate Recall: 50.2%, Accurate precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 56.46%.
* **`0_23_62` (Model Miss):** Net +0.08% Fast vs +0.58% Accurate. 101 GT features (94 buildings, 7 roads). Fast Building Recall: 0.99% (Road: 0.17%, Fast precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 31.32%). Accurate Building Recall: 5.31% (Road: 3.6%, Accurate precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 28.76%).
* **`0_15_63` (True Negative):** Net 0.00% (Before: 0.00% | After: 0.00%). 0 GT features.
* **`0_20_66` (False Positive):** Net -3.32% (Before: 3.32% | After: 0.00%). 0 GT features. Inspection images viewed: `docs/inspection/0_20_66_pre.jpg`, `0_20_66_pre_fast_mask.jpg`, `0_20_66_pre_acc_mask.jpg`, `0_20_66_post.jpg`. Finding: Pre-event imagery displays false-positive cyan masks on settlement structures (3.32% Fast, 4.77% Accurate); post-event predicts 0.00% Fast, 0.5% Accurate; ground-truth records 0 flooded features; specific root cause not determined.

---

## Likely Evaluator / Judge Questions & Factual Answers

### Q1: "Why is your IoU only 11.42% in Fast Mode and 16.55% in Accurate Mode?"
**Answer:**
> *"SpaceNet-8 ground truth includes narrow roads buffered by 2 meters, which at 0.419 m/pixel average ground resolution corresponds to a 9.55-pixel corridor width. Roads constitute 45.37% of all ground-truth flooded pixels, yet the model achieves only 4.69% road recall in Fast Mode and 8.88% in Accurate Mode. In contrast, building recall is 21.27% in Fast Mode and jumps to 35.57% in Accurate Mode. Accurate Mode's 512px sliding window raises building recall from 21.3% to 35.6% and recovers missed building flooding (such as on tile 0_23_62 where building recall jumps from 0.99% to 5.31% and net intrusion rises from +0.08% to +0.58%), raising overall pixel recall from 13.75% to 23.47% and IoU from 11.42% to 16.55%."*

### Q2: "Did you evaluate on genuinely unseen flood disasters?"
**Answer:**
> *"All 66 tiles containing annotated flooding in Germany were in the candidate training pool (`satellite_processed/images`), and no satellite validation set was held out during joint training. Therefore, our accuracy metrics reflect training pool fit, not held-out disaster performance. However, the remaining 136 tiles in our dataset were not in the training pool and serve as a check for false alarms on unflooded terrain. Across those 136 tiles, zero had post-event false alarms over 0.1% (the maximum detected was 0.02% on 0_29_68), and 134 of 136 had net intrusion of exactly 0.00%. In Accurate Mode, false alarms on dry tiles increase to 8 tiles with post-event flooded area (class 1) over 0.1% (maximum: 1.33% on 0_38_69)."*

### Q3: "Why did tile 0_20_66 produce a negative net intrusion (-3.32%)?"
**Answer:**
> *"The net intrusion formula is `after_pct - before_pct`. On tile 0_20_66, the model predicted 3.32% flooded area (class 1) in Fast Mode (4.77% in Accurate Mode) on pre-event imagery and 0.00% Fast (0.5% Accurate) on post-event imagery, despite zero annotated flooding. We inspected all four pre- and post-event images and mask overlays (`docs/inspection/0_20_66_pre.jpg`, `0_20_66_pre_fast_mask.jpg`, `0_20_66_pre_acc_mask.jpg`, `0_20_66_post.jpg`). The pre-event imagery visibly displays false-positive cyan mask patches over settlement building roofs and driveway surfaces, whereas the post-event image is clean. The specific root cause for this spectral confusion is not determined. Rather than suppressing this anomaly, FloodWatch transparently reports it with an explanatory banner: 'No net increase: less flooded area detected post-event than pre-event.'"*

### Q4: "How does this run completely offline without an internet connection?"
**Answer:**
> *"The backend is a local FastAPI process holding the SegFormer-B0 FP16 weights resident in GPU VRAM (taking 721.12 MB peak VRAM). The frontend is pure HTML, CSS, and ES6 JavaScript with zero CDN or Google Font dependencies. In automated headless browser audits via Chrome DevTools Protocol, exactly 0 external network requests were made."*

### Q5: "What is the measured click-to-render latency?"
**Answer:**
> *"In automated headless Chrome benchmarks across 30 distinct uncached tiles, cold click-to-render had a median of 713 ms and P95 of 1178.699999988079 ms (with Server-Timing I/O median of 380.6 ms; OS file-system cache state was not controlled). Client-side warm end-to-end roundtrip across 50 tiles has a median of 498.1229000259191 ms and P95 of 645.6424999632873 ms. When prewarmed (`FW_PREWARM=all`), 30 distinct clicks yielded a median of 61.3 ms and P95 of 90.2 ms."*
