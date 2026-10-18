# Dernau Demo Dataset (SpaceNet 8)

This directory contains a contract-perfect, fully deterministic demonstration dataset generated from real SpaceNet 8 annotations covering the Dernau area (Ahr valley, Germany) following the June 2021 Western Europe floods.

## Source & Licensing

- **Dataset Source:** SpaceNet 8 Flood Detection Challenge, Germany training set (Dernau area, June 2021 Western Europe floods).
- **Attribution & License:** This dataset contains vector annotations derived from SpaceNet 8 / Maxar Technologies under the Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) license.
- **Imagery:** Maxar Technologies imagery (CC BY-NC 4.0 in original SpaceNet 8 challenge) is **not** redistributed here. Only derived vector outputs are included.
- **Integration Samples:** The files in `integration-samples/` are unmodified source copies extracted directly from the SpaceNet 8 Dernau training data for reference and build reproducibility.

## Derivation Notes

- **Flood Extent (`flood_extent.geojson`):**
  There is no measured water boundary or flood raster in this dataset. The flood extent was derived by unioning and buffering (5.0m) ground-truth flooded building polygons and flooded road line segments. With an AOI boundary tolerance of 0.0005 deg, all 196 flood polygons are preserved.
- **Risk Scores & Levels (`zones.json`):**
  Risk scores and levels are **illustrative demo scores, not Member 3 (risk engine) outputs**.
  Derived using the documented demo formula:
  $$\text{score} = \left(0.40 \cdot \min\left(\frac{\text{flooded\_percent}}{20}, 1\right) + 0.35 \cdot \frac{\text{exposed\_buildings}}{\text{total\_buildings}} + 0.25 \cdot \frac{\text{flooded\_road\_length\_m}}{\text{road\_length\_m}}\right) \times 100$$
  Rounded to 1 decimal place.
  - `HIGH`: score $\ge 60$
  - `MEDIUM`: score $\ge 30$
  - `LOW`: score $< 30$
  - `UNKNOWN`: score is `null` when a zone has insufficient infrastructure data.
- **Facilities (`facilities.geojson`):**
  Three simulated points (hospital, shelter, depot) placed in non-flooded areas inside the AOI. Provenance: `simulated`.
- **Routes (`routes.json`):**
  Two `OK` routes with geometry reused from real non-flooded road segments in `roads_status.geojson` with Haversine distance, and one `UNREACHABLE` route with `geometry: null`. `eta_minutes` is `null` (no fabricated speeds). Provenance: `simulated`.
- **AOI Location:**
  Dernau (Ahr valley), Rhineland-Palatinate, Germany (approx bbox `[7.015, 50.511]` to `[7.044, 50.531]`). The dashboard map must fit its bounds dynamically from the dataset.

## Required Edge Cases

1. **Zone with `geometry: null`:**
   - `zone-009` has `geometry: null` (LOW risk, score 4.1, real bbox available in raw data) to verify that zones without spatial representation remain listed and selectable in the UI without crashing the Leaflet map. `zone-038` (HIGH risk, score 93.7) retains its real rectangle polygon geometry on the map.
2. **Zone with missing numeric field (`exposed_buildings: null`):**
   - `zone-005` has `exposed_buildings: null` (explicitly marked in reasons and documentation as "designated test cases, not measured data") to verify the UI displays "Not available" rather than falsely coercing missing data to 0. Real values for all other fields and zones remain untouched.
3. **Zone with `UNKNOWN` risk level:**
   - `zone-018` has `risk_level: "UNKNOWN"` and `risk_score: null` (explicitly marked in reasons and documentation as "designated test cases, not measured data"; in raw data it contains no road segments, `road_length_m === 0`, accessibility `UNKNOWN`). Real values for all other fields and zones remain untouched.
4. **Zone with survey flag and uncertainty bounds (`needs_survey: true`):**
   - `zone-005` (partial data zone) has `needs_survey: true`, `confidence: 0.35`, `rank_p10: 10`, `rank_p90: 30`, `provenance: "observed"`, and `source: "SpaceNet 8 / Maxar ground truth (test fixture)"`. These are designated test fixture values, not measured data, illustrating that a zone with withheld infrastructure data has low assessment confidence (0.35) and is flagged for aerial reconnaissance survey.

## Dataset Statistics

- **Total Zones:** 38
  - `HIGH`: 4
  - `MEDIUM`: 4
  - `LOW`: 28
  - `UNKNOWN`: 2
- **Blocked Roads:** 45
- **Flood Polygons (valid inside AOI with 0.0005 deg tolerance):** 196
- **Dropped Features:** 0
- **Facilities:** 3
- **Routes:** 3 (2 OK, 1 UNREACHABLE)
- **Exposed Buildings:** 759
