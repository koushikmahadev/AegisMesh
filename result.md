# HighWater — Model Validation Results

SegFormer-B0 detects water extent across diverse geographies. Same model, different environmental manifestations.

---

## Validation Summary

| Metric | Value |
|:---|:---|
| **Ground-Truth Accuracy** | 80.67% (evaluated against human pixel annotations, FloodNet benchmark) |
| **Processing Latency** | ~0.5s per image (fully offline) |
| **Total Images Validated** | 48 real flood images |
| **Average Model Confidence (all 48)** | 85.85% (weighted: 15 Kerala satellite + 33 Harvey drone) |
| **Visual Verification Pass Rate** | 48/48 (100%) — every image currently in the carousel was manually inspected and confirmed to show real, visually obvious flooding |

---

## Datasets

### Kerala 2018 (Sentinel-2 Satellite)
- **Source:** ESA Sentinel-2 MSI, Aug 22 2018 (post-flood), false-color bands 11-8-3; Kuttanad region. Verified against NASA Earth Observatory's published before/after Kerala flood comparison. Satellite tiles, not drone photography — the earlier 26-tile "kerala_fresh" set was dropped after visual inspection showed it was cropped from a pre-flood GeoTIFF and contained no real floodwater (0/26 visually passed).
- **Count:** 15 tiles
- **Coverage Range:** 98.45% → 18.76%
- **Average Confidence:** 88.61%
- **Visual Verification:** 15/15 (100%) — all cropped from a confirmed post-flood scene, cloud-filtered, selected for unambiguous submerged-field signatures
- **Ground-Truth Accuracy:** not separately benchmarked — no human-annotated pixel masks exist for this satellite scene; only the FloodNet-derived 80.67% figure above is annotation-backed

### Hurricane Harvey 2017 (FloodNet)
- **Count:** 33 images
- **Coverage Range:** 64.81% → 0.00%
- **Average Confidence:** 84.60%
- **Visual Verification:** 33/33 (100%) — genuine drone photography from the public FloodNet dataset
