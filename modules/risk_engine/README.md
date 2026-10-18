# Risk & Prioritization Engine (Module 3)

HighWater Mission 6 — Disaster Response Drones. Consumes the zone grid
produced by Module 2 (`modules/flood_analysis/output/zones.json`) and ranks
zones by a configurable, documented priority score to guide drone
reconnaissance and resource dispatch decisions.

> **Important**: Scores are **provisional decision-support heuristics** based
> on SpaceNet 8 ground-truth labels for a single flood event (Dernau, June
> 2021). They have not been validated against historical casualty or response
> data. Do not treat them as predictions of life-safety risk.

---

## Quick start

```bash
# From modules/risk_engine/:
PYTHONPATH=src python -m risk_engine.cli \
    --zones ../flood_analysis/output/zones.json \
    --out output/

# Export in dashboard format (writes output/zones.json):
PYTHONPATH=src python -m risk_engine.cli \
    --zones ../flood_analysis/output/zones.json \
    --out output/ \
    --format dashboard \
    --data-mode historical

# With a custom weights file:
PYTHONPATH=src python -m risk_engine.cli \
    --zones ../flood_analysis/output/zones.json \
    --out output/ \
    --config config/weights.json

# With inline custom weights (JSON or key=value):
PYTHONPATH=src python -m risk_engine.cli \
    --zones ../flood_analysis/output/zones.json \
    --out output/ \
    --weights '{"flood_percent": 0.40, "exposure": 0.35, "isolation": 0.15, "flood_area_density": 0.10}'

PYTHONPATH=src python -m risk_engine.cli \
    --zones ../flood_analysis/output/zones.json \
    --out output/ \
    --weights "flood_percent=0.40,exposure=0.35,isolation=0.15,flood_area_density=0.10"
```

Output is written to:
- `output/risk_scores.json` when `--format standard` (default)
- `output/zones.json` when `--format dashboard`

### CLI Exit Codes
- `0`: Success.
- `1`: Input validation failure (`InputValidationError`).
- `2`: Configuration or file not found error (`ConfigError` / `FileNotFoundError`).
- `3`: Unexpected internal runtime failure.
- `--weights`: Custom scoring weights as JSON string or key=val pairs.
- `--debug`: Pass to output full stack traces on error.

### Install / Run Tests
```bash
pip install -e .
python -m pytest tests/ -v
```

---

## Scoring Formula & Weights

```
raw_score = w_flood_pct     * min(flooded_percent  / FLOOD_PCT_MAX,  1.0)
          + w_exposure      * min(exposed_buildings / EXPOSED_MAX,    1.0)
          + w_isolation     * isolation_score[accessibility]
          + w_flood_area    * min(flooded_area_m2   / FLOOD_AREA_MAX, 1.0)
          + w_exp_frac      * min(exposed_buildings / total_buildings, 1.0)

score_0_100 = round(raw_score * 100, 1)
```

### Default Weights (`config/weights.json`)

| Component           | Weight | Description |
|---------------------|--------|-------------|
| `flood_percent`     | 0.35   | Estimated percentage of zone area flooded |
| `exposure`          | 0.40   | Number of buildings tagged as flooded |
| `isolation`         | 0.15   | Road accessibility status proxy |
| `flood_area_density`| 0.10   | Absolute flooded area in m² |
| `exposure_fraction` | 0.00   | Optional ratio of exposed to total buildings (defaults to 0.0) |

*Caveat*: `flood_percent` and `flood_area_density` both measure flood extent (relative saturation vs. absolute inundation scale). Both components derive from the same flood extent labels.

### Normalisation Ceilings (Default)

| Field               | Ceiling    |
|---------------------|------------|
| `flooded_percent`   | 30.0 %     |
| `exposed_buildings` | 75         |
| `flooded_area_m2`   | 15 000 m²  |

### Isolation Scores & Road Accessibility (Module 2 Source of Truth)

Road accessibility classifications derive from Module 2 (`modules/flood_analysis`) based on the proportion of road length within each zone cell that is inundated (`flooded_road_length_m / road_length_m`):

| `accessibility` | Module 2 Definition | Component Value | Default Points Contribution | Operational Interpretation |
|---|---|---|---|---|
| `ACCESSIBLE` | < 10% road length flooded | 0.0 | +0.0 pts | Local zone roads largely open; no isolation penalty applied |
| `PARTIAL` | 10%–60% road length flooded | 0.5 | +7.5 pts | Intermediate ground access restriction; elevates zone priority |
| `BLOCKED` | ≥ 60% road length flooded | 1.0 | +15.0 pts | Maximum intra-zone road flooding; imposes full isolation penalty |
| `UNKNOWN` | No road segments in zone cell | 0.5 | +7.5 pts | Isolation cannot be determined; provisional penalty; flagged for survey |

> **Physical Reachability Caveat**: Accessibility reflects intra-zone road inundation percentages from SpaceNet 8 ground-truth labels. It does **not** evaluate external road network connectivity, bridge status outside the bounding box, or total physical unreachability from external response centers. Scores must not be interpreted as definitive claims of physical isolation.

#### Missing & Unknown Accessibility Policy
- **Never interpreted as safe**: Missing or unrecognised accessibility is never assumed to be `ACCESSIBLE` (which would silently omit isolation points).
- **Verification required**: Zones with `UNKNOWN` or unavailable accessibility are automatically assigned `needs_verification: true`, confidence is degraded (`MEDIUM` or `LOW`), and an actionable warning is emitted.
- **Single isolation source**: Isolation risk is evaluated strictly through the `isolation` component. It is never double-counted through separate geospatial pipelines or secondary penalties.

### Priority Thresholds

| Priority   | Score Range |
|------------|-------------|
| `CRITICAL` | ≥ 70        |
| `HIGH`     | ≥ 45        |
| `MEDIUM`   | ≥ 20        |
| `LOW`      | < 20        |

---

## Configuration Object & Validation Rules

Module 3 scoring configuration is centralized in `risk_engine.config` via validated dataclasses (`RiskEngineConfig`, `ScoringWeights`, `PriorityThresholds`, `NormalizationCeilings`, `IsolationScores`):

1. **Scoring Weights** (`ScoringWeights`):
   - Centralized default weights: `flood_percent=0.35`, `exposure=0.40`, `isolation=0.15`, `flood_area_density=0.10`, `exposure_fraction=0.0`.
   - Must contain the 4 base keys (`flood_percent`, `exposure`, `isolation`, `flood_area_density`) with optional `exposure_fraction`.
   - All weights must be non-negative finite numbers and sum to 1.0 (within relative tolerance 1e-6).
   - Reject invalid configurations with clear, actionable error messages.
   - `ScoringWeights.from_unnormalized()` allows scaling arbitrary positive weights to 1.0.
2. **Priority Thresholds** (`PriorityThresholds`):
   - Fully decoupled from scoring weights.
   - Default thresholds: `CRITICAL=70.0`, `HIGH=45.0`, `MEDIUM=20.0`, `LOW=0.0`.
   - Enforces strict descending order: `CRITICAL > HIGH > MEDIUM > LOW >= 0`.
3. **Deterministic Fingerprinting**:
   - `weights_fingerprint`: 16-character SHA-256 hex digest computed over canonicalized scoring weights.
   - `config_hash_sha256`: Full 64-character SHA-256 hash covering the entire effective configuration.
   - Identical configurations produce identical fingerprints across invocations and environments.
4. **Isolation Scores & Normalization**:
   - Normalization ceilings must be positive finite numbers.
   - Isolation scores satisfy monotonic ordering: `ACCESSIBLE <= PARTIAL <= BLOCKED` and `UNKNOWN >= PARTIAL`.
   - Underscore-prefixed keys (`_comment`) are stripped from numeric scoring blocks and output.

---

## Deterministic Ranking & Tie-Breaking

Zones are ordered deterministically using a 4-level hierarchy:
1. Unrounded raw score descending
2. Exposed buildings descending
3. Flooded percentage descending
4. Natural-sort `zone_id` ascending (`zone-2` precedes `zone-10`)

Tied zones receive distinct sequential integer ranks (`1..N`).

---

## Output Contract & Dashboard Exporter

### Standard Output Schema 1.1 (`risk_scores.json`)
- `schema_version`: `"1.1"`
- `generated_at`: ISO UTC timestamp
- `source_metadata`: input schema version, input source, input CRS, `input_file_sha256`, `config_hash_sha256`, `weights_fingerprint`
- `scoring_config`: echoed `config_version: "1.0"`, `config_hash_sha256`, `weights_fingerprint`, weights, normalization ceilings, priority thresholds
- `summary`: `total_zones`, `priority_counts`, `confidence_counts` (`{"HIGH": N, "MEDIUM": N, "LOW": N}`), `accessibility_counts` (`{"ACCESSIBLE": N, "PARTIAL": N, "BLOCKED": N, "UNKNOWN": N}`), `verification_needed_count`
- `ranked_zones`: includes `rank`, `zone_id`, `score`, `priority`, `accessibility`, `isolation` (`status`, `score`, `weight`, `weighted_contribution`, `points`, `percentage_of_score`, `road_length_m`, `flooded_road_length_m`, `flooded_road_share`, `warnings`, `needs_verification`), `score_basis`, `omitted_components`, `confidence`, `needs_verification`, `data_quality`, `score_breakdown`, `reasons`, `warnings`, `score_components`, `inputs`, `geometry`

### Dashboard Export (`zones.json`)
When `--format dashboard` is specified, the CLI writes `zones.json` formatted per dashboard specifications:
- `schema_version`: `"1.1"`
- `data_mode`: from `--data-mode` (default `"historical"`)
- `study_area`: dynamically resolved from input metadata (never a hardcoded fallback)
- `score_scale`: `"0-100"`
- `zones`: includes `zone_id`, `name`, `risk_level`, `risk_score` (1 dp, preserving 0.5 and 0.1), `confidence` (`HIGH` | `MEDIUM` | `LOW`), `needs_verification` (boolean), `needs_survey` (boolean, consumable by dashboard `SurveyNeededList`), `flooded_percent`, `flooded_area_km2`, `exposed_buildings`, `total_buildings`, `accessibility` (mapped to `OPEN`, `LIMITED`, `BLOCKED`, `UNKNOWN`), `isolation`, `reasons`, `geometry` as a closed 5-point GeoJSON Polygon ring built from bbox in `[lng, lat]` order, and `score_breakdown`.

> **Note**: The dashboard adapter consumes `needs_survey` directly (`z.needs_survey === true`) and displays `confidence` in zone details.

---

## Risk-Score Explainability & Auditability

Every zone includes a transparent, auditable explanation of its risk score and priority ranking via the `score_breakdown` field and deterministic reason strings:

### Score Breakdown Schema (`score_breakdown`)
```json
{
  "score": 46.0,
  "raw_score": 0.46,
  "score_basis": "full",
  "omitted_components": [],
  "components": {
    "flood_percent": {
      "raw_input": 15.0,
      "unit": "%",
      "normalized_value": 0.5,
      "weight": 0.35,
      "weighted_contribution": 0.175,
      "points": 17.5,
      "percentage_of_score": 38.0,
      "omitted": false
    },
    "exposure": {
      "raw_input": 30,
      "unit": "buildings",
      "normalized_value": 0.4,
      "weight": 0.4,
      "weighted_contribution": 0.16,
      "points": 16.0,
      "percentage_of_score": 34.8,
      "omitted": false
    },
    "isolation": {
      "raw_input": "PARTIAL",
      "unit": "status",
      "normalized_value": 0.5,
      "weight": 0.15,
      "weighted_contribution": 0.075,
      "points": 7.5,
      "percentage_of_score": 16.3,
      "omitted": false
    },
    "flood_area_density": {
      "raw_input": 7500.0,
      "unit": "m²",
      "normalized_value": 0.5,
      "weight": 0.1,
      "weighted_contribution": 0.05,
      "points": 5.0,
      "percentage_of_score": 10.9,
      "omitted": false
    },
    "exposure_fraction": {
      "raw_input": 0.0,
      "unit": "ratio",
      "normalized_value": 0.0,
      "weight": 0.0,
      "weighted_contribution": 0.0,
      "points": 0.0,
      "percentage_of_score": 0.0,
      "omitted": false
    }
  },
  "reconciliation": {
    "sum_weighted_contributions": 0.46,
    "sum_points": 46.0,
    "computed_score": 46.0,
    "final_score": 46.0,
    "rounding_difference": 0.0,
    "reconciled": true,
    "tolerance": 0.08
  },
  "primary_driver": "flood_percent",
  "primary_driver_summary": "Flood coverage is the primary score driver (17.5 pts, 38% of score)",
  "influential_factors": [
    "Flood coverage: 15.0% inundated area contributes 17.5 pts (38% of score)",
    "Building exposure: 30 exposed buildings contribute 16.0 pts (35% of score)",
    "Road isolation: PARTIAL accessibility contributes 7.5 pts (16% of score)",
    "Flood extent area: 7,500 m² footprint contributes 5.0 pts (11% of score)"
  ],
  "ranking_factors": []
}
```

### Mathematical Reconciliation Guarantee
1. **Unrounded Raw Score**: $\sum_i w_i \cdot v_i = \text{raw\_score}$ within floating point precision ($< 10^{-5}$).
2. **Display Score**: $\sum_i \text{points}_i$ reconciles with $\text{final\_score}$ within display rounding tolerance ($\le 0.08$), accounting for 1-decimal display rounding ($\pm 0.05$) and up to 5 component 2-decimal roundings ($5 \times \pm 0.005 = \pm 0.025$).
3. **Audit Flag**: `reconciliation.reconciled` is verified as `true` for all evaluated zones.

### Deterministic Explanations & Integrity
- **No Hallucinated Claims**: Explanations never claim that a factor affected the score unless the scoring formula confirms non-zero weighted contribution (`points > 0.0`). Zero-weight components (e.g. default `exposure_fraction`), zero-exposed building zones, and fully accessible roads are strictly excluded from driving factor explanations.
- **Ranking-Relevant Factors**: Blocked accessibility (maximum isolation penalty), substantial building exposure, and high flood saturation are explicitly identified when supported by measurements and active weights.
- **Backward Compatibility**: `score_components` retains its original flat dictionary mapping to floats, ensuring zero breakage for existing consumers.


---

## Data Confidence, Quality Assessment & Missing Data Handling

The engine strictly separates **risk score** from **data confidence**:
- **Risk Score**: Reflects the mathematical combination of flood coverage, exposed building count, and isolation penalty. Scoring formulas, weights, and priority thresholds are never artificially distorted by data quality.
- **Data Confidence**: Evaluates the completeness, validity, and physical consistency of the input data using deterministic rules.
- **Safety Policy**: Incomplete or unknown data is never treated as proof of safety. A zone classified as `LOW` priority with incomplete data (confidence != `HIGH`, such as unknown road accessibility or missing census data) is explicitly flagged with `needs_verification: true` and documented in human-readable explanations.

### Deterministic Confidence Categories

| Confidence Level | Definition & Assignment Rules |
|------------------|-------------------------------|
| `HIGH`           | All required and optional fields are present, valid, non-negative, and un-clamped. Road accessibility is explicitly confirmed (`ACCESSIBLE`, `PARTIAL`, or `BLOCKED`). Geographic bbox and centroid coordinates are valid. No physical contradictions. `needs_verification: false`. |
| `MEDIUM`         | Data is usable for scoring but contains a single unverified attribute: e.g. `accessibility == "UNKNOWN"` (unrecorded road data), missing `flooded_area_m2` requiring partial scoring, omitted building/road metadata, missing geometry coordinates, or heuristic extent mismatch (`exposed_buildings == 0` while `flooded_percent >= 5.0%`). No direct contradictions. |
| `LOW`            | Severe data quality issues: direct physical contradictions in measurements (e.g. 0% flood with exposed buildings, exposed buildings exceeding total buildings, flooded roads exceeding total road length), clamped out-of-range numbers, negative measurements coerced to 0, or multiple compounding incomplete fields. `needs_verification: true` is always enforced. |

*Note: Confidence categories represent deterministic data completeness and consistency heuristics, not statistically calibrated probabilities.*

### Data Quality Statuses (`data_quality_status`)
- `VERIFIED`: Complete, uncompromised, and physically consistent input measurements.
- `INCOMPLETE`: Valid for scoring, but with omitted optional metadata or unrecorded road accessibility.
- `CONTRADICTORY`: Conflicting physical measurements detected between flood extent and infrastructure.
- `DEGRADED`: Recovered from clamped out-of-bounds or coerced negative values.

### Handling Missing Measurements vs. Valid Zeros
- **Legitimate Zeros**: Explicit values of `0.0` flooded percent, `0.0` flooded area, `0` exposed buildings, or `0` total buildings are legitimate data (e.g., uninhabited or unflooded areas) and are treated as verified.
- **Omitted Optional Fields**: Fields not present in the input JSON (or explicitly `null`) are tracked as missing data rather than assumed to be verified zeros.
- **Missing Required Fields**: Structural fields (`zone_id`, `flooded_percent`, `exposed_buildings`, `accessibility`) without valid values strictly fail fast with `InputValidationError`.
- **`flooded_area_m2` Null**:
  - Scored as 0.0 with full scoring ONLY when `flooded_percent == 0` (physically consistent absence of flood extent).
  - When `flooded_area_m2` is null while `flooded_percent > 0`, the engine omits `flood_area_density`, renormalizes remaining weights, flags `score_basis: "partial"`, sets `confidence: "MEDIUM"`, and flags `needs_verification: true`.
- **`accessibility == "UNKNOWN"`**:
  - Emits exactly one warning per zone, applies intermediate isolation penalty `0.5`, sets `confidence: "MEDIUM"` (or `LOW`), and flags `needs_verification: true`.
- **Contradictory Inputs**:
  - Checked during loading and centralized assessment: `fp == 0` with `eb > 0`, `fp == 0` with `fam > 0`, `fp == 0` with `frl > 0`, `eb > tb`, and `frl > rl`. Structured warnings are emitted, confidence is marked `LOW`, and `needs_verification: true` is set.

---

## Diagnostic & Sensitivity Analysis Tools

1. **Risk-Ranking Sensitivity Analysis** (`risk_engine.sensitivity` & `tools/sensitivity.py --mode scenarios`):
   - Standalone analytical evaluation of zone priority rankings across explicit, valid weight scenarios.
   - Evaluates baseline vs. exploratory scenarios (`equal_weights`, `exposure_heavy`, `flood_coverage_heavy`, `isolation_heavy`, `areal_extent_heavy`).
   - Compares score changes, priority-category changes, rank movement, and top-priority membership.
   - Identifies **robust high-priority zones** (consistently `CRITICAL`/`HIGH` across all tested scenarios).
   - Identifies **volatile zones** (substantial rank movements $\ge 3$ positions), with contextual explanations.
   - Reports scenario metrics: Kendall's tau rank correlation, max/mean rank shift, max/mean score shift, priority category change rate, top-$k$ overlap percentage.
   - Preserves baseline scores, rankings, and configuration 100% unmodified.
   - Uses identical deterministic tie-breaking (raw score desc, exposed buildings desc, flooded percent desc, natural-sort zone ID asc).
   - Rejects invalid scenario weights using standard `ScoringWeights` validation rules.
   - Disclaimer: Exploratory sensitivity scenarios test ranking stability under hypothetical operational assumptions; they are NOT empirical or scientifically validated ground truth.

2. **Parameter Perturbation Tool** (`tools/sensitivity.py --mode perturbation`):
   - Perturbs individual model weights by -20%, -10%, +10%, +20% (with weight renormalization).
   - Perturbs isolation scores and priority thresholds by ±10%.
   - Computes Kendall's tau rank correlation against baseline, top-5 overlap, and priority change counts.
   - Outputs table sorted from most destabilizing to least destabilizing parameter.

3. **Calibration Diagnostic** (`tools/calibrate.py`):
   - Computes distribution (min, median, p90, p95, max) for raw inputs and scores.
   - Evaluates ceiling utilization and warns if a ceiling is >25% above observed maximum or below p95.
   - Warns on empty priority classes (`CRITICAL=0` in real dataset).
   - Suggests empirical ceilings without modifying configuration files.

---

## Known Limitations

- **Exploratory Sensitivity Scenarios**: Alternative weight configurations represent hypothetical operational priorities for evaluating ranking robustness. They are not empirical ground truth, predictive casualties, or scientifically validated risk distributions.
- **Single Flood Event**: Derived and calibrated on SpaceNet 8 ground truth labels from Dernau (Ahr valley, June 2021). Not validated against other events.
- **Uncalibrated Thresholds**: Heuristic boundaries (70/45/20) have not been calibrated against operational disaster-response casualty or dispatch data.
- **Correlated Inputs**: `flooded_percent` and `flooded_area_density` both reflect flood extent and share common error modes from the underlying segmentation.
- **Absolute Exposure Counts**: Building counts do not account for building type, floor area, or population density.
- **Topological Reachability vs Local Road Flooding**: Road accessibility is an intra-zone heuristic (`flooded_road_length_m / road_length_m`), not a network graph routing analysis from external supply staging bases.

