"""Risk scorer for HighWater Module 3.

Validation Policy:
    Input documents must strictly conform to expected types and schema:
    - Wrong TYPE (string, bool, list, NaN/inf): Raises `InputValidationError` identifying zone and field.
      Booleans are strictly rejected for every numeric field (since bool subclasses int in Python).
      Integral floats (e.g. 5.0) are accepted for `exposed_buildings` and coerced to integers;
      non-integral floats raise `InputValidationError`.
    - Negative exposure counts: Raises `InputValidationError` identifying zone and field by default.
      Configuring `data_quality.on_negative_exposure="warn_zero"` emits a warning and treats the value as 0.
    - Out-of-range numeric: Handled conservatively and transparently with warnings.
      Percentages outside [0, 100] are clamped to bounds.
    - Cross-field checks: Warnings are emitted when `flooded_road_length_m > road_length_m` (capped at 100%),
      when `exposed_buildings > total_buildings` (capped at 100%), and for negative road/building counts (clamped to 0).
    - Geometry: Centroid (2 finite numbers) and bbox (4 finite numbers) are validated. On failure,
      a warning is emitted and an empty array `[]` is output. CRS is passed through verbatim or marked as "unknown",
      never assuming EPSG:4326.

Missing Flood Area & Partial Scoring:
    `flooded_area_m2` null is scored as 0 ONLY when `flooded_percent == 0` (full scoring, no components dropped).
    If `flooded_area_m2` is null while `flooded_percent > 0` (inconsistent data), a warning is emitted and
    the `flood_area_density` component is omitted, renormalizing the remaining active weights for that zone.
    The zone output records `score_basis="partial"` and lists `omitted_components=["flood_area_density"]`.

Score Components & Shared Label Caveats:
    `flood_percent` and `flood_area_density` both measure flood extent (relative saturation vs. absolute area scale).
    All components derive from the same underlying flood and OSM labels. Scores are provisional decision-support
    heuristics, not validated predictions of life-safety risk. Road accessibility is an isolation proxy,
    not a claim that any route is safe.

Deterministic Ranking Policy:
    Zones are sorted by:
    1. Unrounded raw score descending
    2. Exposed buildings descending
    3. Flooded percentage descending
    4. Natural-sort zone ID ascending (e.g. zone-2 precedes zone-10)
    Tied zones receive distinct sequential integer ranks (1..N).
"""

from __future__ import annotations

import hashlib
import importlib.resources as pkg_resources
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data structures & Exceptions
# ---------------------------------------------------------------------------

from risk_engine.config import (
    ACCESSIBILITY_VALUES,
    ALLOWED_WEIGHT_KEYS,
    DEFAULT_CONFIG_VERSION,
    DEFAULT_ISOLATION_SCORES,
    DEFAULT_NORMALIZATION,
    DEFAULT_PRIORITY_THRESHOLDS,
    DEFAULT_WEIGHTS,
    REQUIRED_BASE_WEIGHT_KEYS,
    ConfigError,
    DataQualityConfig,
    IsolationScores,
    NormalizationCeilings,
    PriorityThresholds,
    RiskEngineConfig,
    ScoringConfig,
    ScoringWeights,
    _strip_comments,
    load_config,
    load_config_object,
    parse_weights_arg,
    validate_config,
    weights_fingerprint,
)

ACCESSIBILITY_DASHBOARD_MAP = {
    "ACCESSIBLE": "OPEN",
    "PARTIAL": "LIMITED",
    "BLOCKED": "BLOCKED",
    "UNKNOWN": "UNKNOWN",
}


class InputValidationError(ValueError):
    """Raised when zone input data fails structural or type validation."""
    pass


@dataclass
class DataQualityWarning:
    zone_id: str
    field: str
    issue: str


@dataclass
class ZoneDataQualityAssessment:
    zone_id: str
    confidence: str              # "HIGH" | "MEDIUM" | "LOW"
    needs_verification: bool     # True | False
    data_quality_status: str     # "VERIFIED" | "INCOMPLETE" | "CONTRADICTORY" | "DEGRADED"
    issues: list[str]            # Machine-readable issue tags
    warnings: list[str]          # All warning strings for this zone
    missing_fields: list[str]    # Fields omitted from input dictionary
    score_basis: str             # "full" | "partial"
    omitted_components: list[str]# Components dropped from scoring


@dataclass
class ZoneRiskRecord:
    zone_id: str
    rank: int
    score: float | None          # 0.0 – 100.0 (display rounded) or None for unassessed
    priority: str         # CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN
    raw_score: float      # Unrounded [0.0, 1.0] for deterministic ranking (-1.0 if unassessed)
    reasons: list[str]
    warnings: list[str]
    score_basis: str      # "full" | "partial" | "none"
    omitted_components: list[str]
    # Component contributions (each 0.0-1.0, before weighting)
    flood_percent_component: float
    exposure_component: float
    isolation_component: float
    flood_area_component: float
    exposure_fraction_component: float
    # Raw inputs
    flooded_percent: float | None
    exposed_buildings: int | None
    total_buildings: int
    accessibility: str
    road_length_m: float
    flooded_road_length_m: float
    flooded_area_m2: float | None
    centroid: list[float]
    bbox: list[float]
    # Data quality & confidence
    confidence: str = "HIGH"
    needs_verification: bool = False
    data_quality_status: str = "VERIFIED"
    data_quality_issues: list[str] = field(default_factory=list)
    score_breakdown: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Config validation & loading (centralized in risk_engine.config)
# ---------------------------------------------------------------------------
# Re-exported from risk_engine.config:
# ConfigError, ScoringWeights, NormalizationCeilings, IsolationScores,
# PriorityThresholds, DataQualityConfig, ScoringConfig, RiskEngineConfig,
# validate_config, load_config, load_config_object, parse_weights_arg,
# weights_fingerprint, _strip_comments.



# ---------------------------------------------------------------------------
# Zone input loading + validation
# ---------------------------------------------------------------------------

def _is_finite_num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _validate_geometry(
    zone_id: str,
    raw_geo: Any,
    expected_len: int,
    field_name: str,
    warnings: list[DataQualityWarning],
) -> list[float]:
    """Validate bbox or centroid coordinate list."""
    if not isinstance(raw_geo, (list, tuple)) or len(raw_geo) != expected_len:
        warnings.append(DataQualityWarning(
            zone_id=zone_id,
            field=field_name,
            issue=f"Invalid {field_name}: expected list of {expected_len} numbers; got {raw_geo!r}",
        ))
        return []

    for idx, c in enumerate(raw_geo):
        if not _is_finite_num(c):
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field=field_name,
                issue=f"Invalid {field_name}[{idx}]: expected finite coordinate number; got {c!r}",
            ))
            return []

    return [float(c) for c in raw_geo]


def load_zones(
    zones_json_path: Path,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[DataQualityWarning]]:
    """Load and validate a zones.json file produced by Module 2.

    Returns (zones_doc, warnings).
    Raises InputValidationError for structural and schema validation errors.
    """
    path = Path(zones_json_path)
    if not path.is_file():
        raise InputValidationError(f"zones.json not found: {path}")

    with open(path, encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except json.JSONDecodeError as exc:
            raise InputValidationError(f"zones.json is not valid JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise InputValidationError("zones.json top level must be a JSON object")

    if "zones" not in doc:
        raise InputValidationError("zones.json missing required 'zones' key")

    zones = doc["zones"]
    if not isinstance(zones, list):
        raise InputValidationError("'zones' must be a JSON array")

    warnings: list[DataQualityWarning] = []
    seen_ids: set[str] = set()
    coerced_zones: list[dict[str, Any]] = []

    cfg_dq = (config or {}).get("data_quality", {})
    on_neg_exposure = cfg_dq.get("on_negative_exposure", "error")
    on_missing_required = cfg_dq.get("on_missing_required", "error")

    for idx, zone in enumerate(zones):
        if not isinstance(zone, dict):
            raise InputValidationError(f"zones[{idx}] is not a JSON object")

        zone_id = zone.get("zone_id")
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise InputValidationError(f"zones[{idx}]: 'zone_id' must be a non-empty string; got {zone_id!r}")
        if zone_id in seen_ids:
            raise InputValidationError(f"Duplicate zone_id: '{zone_id}'")
        seen_ids.add(zone_id)

        # 1. Required field checks
        missing_req = [req for req in ("flooded_percent", "exposed_buildings", "accessibility") if req not in zone or zone[req] is None]
        if missing_req:
            if on_missing_required == "unknown":
                for req in missing_req:
                    warnings.append(DataQualityWarning(
                        zone_id=zone_id,
                        field=req,
                        issue=f"Zone '{zone_id}', field '{req}': missing required field; classified as UNKNOWN (INSUFFICIENT_DATA)",
                    ))
                coerced = dict(zone)
                coerced["zone_id"] = zone_id
                coerced["flooded_percent"] = None
                coerced["exposed_buildings"] = None
                coerced["accessibility"] = zone.get("accessibility") or "UNKNOWN"
                coerced["_is_insufficient_data"] = True
                coerced["_missing_fields"] = missing_req
                coerced_zones.append(coerced)
                continue
            else:
                raise InputValidationError(f"Zone '{zone_id}', field '{missing_req[0]}': missing required field")

        # 2. flooded_percent validation
        fp = zone["flooded_percent"]
        if not _is_finite_num(fp):
            raise InputValidationError(
                f"Zone '{zone_id}', field 'flooded_percent': expected finite number, got {fp!r}"
            )
        fp_float = float(fp)
        if fp_float < 0.0 or fp_float > 100.0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_percent",
                issue=f"flooded_percent {fp_float} is outside [0, 100]; clamped",
            ))
            fp_float = max(0.0, min(100.0, fp_float))

        # 3. exposed_buildings validation
        eb = zone["exposed_buildings"]
        if isinstance(eb, bool) or not isinstance(eb, (int, float)):
            raise InputValidationError(
                f"Zone '{zone_id}', field 'exposed_buildings': expected integer, got {type(eb).__name__} ({eb!r})"
            )
        if isinstance(eb, float):
            if not eb.is_integer():
                raise InputValidationError(
                    f"Zone '{zone_id}', field 'exposed_buildings': non-integral float count {eb!r}"
                )
            eb_int = int(eb)
        else:
            eb_int = eb

        if eb_int < 0:
            if on_neg_exposure == "warn_zero":
                warnings.append(DataQualityWarning(
                    zone_id=zone_id,
                    field="exposed_buildings",
                    issue=f"exposed_buildings {eb_int} is negative; treated as 0",
                ))
                eb_int = 0
            else:
                raise InputValidationError(
                    f"Zone '{zone_id}', field 'exposed_buildings': negative exposure count {eb_int}"
                )

        # 4. accessibility validation
        acc = zone["accessibility"]
        if not isinstance(acc, str):
            raise InputValidationError(
                f"Zone '{zone_id}', field 'accessibility': expected string, got {type(acc).__name__}"
            )
        if acc not in ACCESSIBILITY_VALUES:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="accessibility",
                issue=f"Unrecognised accessibility value '{acc}'; treating as UNKNOWN",
            ))
            acc = "UNKNOWN"

        # 5. flooded_area_m2 validation (nullable)
        fam = zone.get("flooded_area_m2")
        fam_val: float | None
        if fam is None:
            fam_val = None
        elif not _is_finite_num(fam):
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_area_m2",
                issue=f"flooded_area_m2 is non-numeric or non-finite ({fam!r}); treated as null",
            ))
            fam_val = None
        elif fam < 0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_area_m2",
                issue=f"flooded_area_m2 {fam} is negative; treated as null",
            ))
            fam_val = None
        else:
            fam_val = float(fam)

        # Track omitted fields (distinguishing missing data from legitimate 0 values)
        missing_fields: list[str] = []
        if "total_buildings" not in zone or zone["total_buildings"] is None:
            missing_fields.append("total_buildings")
        if "road_length_m" not in zone or zone["road_length_m"] is None:
            missing_fields.append("road_length_m")
        if "flooded_road_length_m" not in zone or zone["flooded_road_length_m"] is None:
            missing_fields.append("flooded_road_length_m")
        if "flooded_area_m2" not in zone or zone["flooded_area_m2"] is None:
            missing_fields.append("flooded_area_m2")
        if "centroid" not in zone or zone["centroid"] is None:
            missing_fields.append("centroid")
        if "bbox" not in zone or zone["bbox"] is None:
            missing_fields.append("bbox")

        # 6. Optional numeric fields validation
        tb_raw = zone.get("total_buildings", 0)
        if tb_raw is None:
            tb_raw = 0
        if not _is_finite_num(tb_raw):
            raise InputValidationError(
                f"Zone '{zone_id}', field 'total_buildings': expected finite number, got {tb_raw!r}"
            )
        tb_int = int(tb_raw)
        if tb_int < 0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="total_buildings",
                issue=f"total_buildings {tb_int} is negative; treated as 0",
            ))
            tb_int = 0

        rl_raw = zone.get("road_length_m", 0.0)
        if rl_raw is None:
            rl_raw = 0.0
        if not _is_finite_num(rl_raw):
            raise InputValidationError(
                f"Zone '{zone_id}', field 'road_length_m': expected finite number, got {rl_raw!r}"
            )
        rl_float = float(rl_raw)
        if rl_float < 0.0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="road_length_m",
                issue=f"road_length_m {rl_float} is negative; treated as 0.0",
            ))
            rl_float = 0.0

        frl_raw = zone.get("flooded_road_length_m", 0.0)
        if frl_raw is None:
            frl_raw = 0.0
        if not _is_finite_num(frl_raw):
            raise InputValidationError(
                f"Zone '{zone_id}', field 'flooded_road_length_m': expected finite number, got {frl_raw!r}"
            )
        frl_float = float(frl_raw)
        if frl_float < 0.0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_road_length_m",
                issue=f"flooded_road_length_m {frl_float} is negative; treated as 0.0",
            ))
            frl_float = 0.0

        # Cross-field checks & physical contradictions
        if frl_float > rl_float:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_road_length_m",
                issue=f"flooded_road_length_m ({frl_float}) exceeds total road_length_m ({rl_float}); clamped ratio to 100%",
            ))

        if eb_int > tb_int:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="exposed_buildings",
                issue=f"exposed_buildings ({eb_int}) exceeds total_buildings ({tb_int}); clamped ratio to 100%",
            ))

        # Contradictory flood measurement checks
        if fp_float == 0.0 and fam_val is not None and fam_val > 0.0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_area_m2",
                issue=f"flooded_percent is 0.0% but flooded_area_m2 is {fam_val:.1f} m²: contradictory flood extent measurements",
            ))

        if fp_float == 0.0 and eb_int > 0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="exposed_buildings",
                issue=f"flooded_percent is 0.0% but exposed_buildings={eb_int}: buildings marked flooded with zero zone flood coverage",
            ))

        if fp_float == 0.0 and frl_float > 0.0:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_road_length_m",
                issue=f"flooded_percent is 0.0% but flooded_road_length_m is {frl_float:.1f}m: roads marked flooded with zero zone flood coverage",
            ))

        if fp_float > 0.0 and fam_val == 0.0 and "flooded_area_m2" not in missing_fields:
            warnings.append(DataQualityWarning(
                zone_id=zone_id,
                field="flooded_area_m2",
                issue=f"flooded_percent is {fp_float:.1f}% but flooded_area_m2 is 0.0 m²: positive flood percent with zero flooded area",
            ))

        # Geometry validation
        centroid_clean = _validate_geometry(zone_id, zone.get("centroid", []), 2, "centroid", warnings)
        bbox_clean = _validate_geometry(zone_id, zone.get("bbox", []), 4, "bbox", warnings)

        coerced = dict(zone)
        coerced["zone_id"] = zone_id
        coerced["flooded_percent"] = fp_float
        coerced["exposed_buildings"] = eb_int
        coerced["accessibility"] = acc
        coerced["flooded_area_m2"] = fam_val
        coerced["total_buildings"] = tb_int
        coerced["road_length_m"] = rl_float
        coerced["flooded_road_length_m"] = frl_float
        coerced["centroid"] = centroid_clean
        coerced["bbox"] = bbox_clean
        coerced["_missing_fields"] = missing_fields
        coerced_zones.append(coerced)

    result_doc = dict(doc)
    result_doc["zones"] = coerced_zones
    return result_doc, warnings


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _natural_sort_key(s: str) -> list[int | str]:
    """Sort key for natural sort ordering (e.g. zone-2 before zone-10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def classify_risk_score(
    score: float | int | None,
    thresholds: dict[str, float] | PriorityThresholds | None = None,
) -> str:
    """Classify a numerical risk score (0.0 - 100.0) into a priority category.

    Centralized classification policy:
        CRITICAL: score >= thresholds['CRITICAL'] (default: 70.0)
        HIGH:     score >= thresholds['HIGH']     (default: 45.0)
        MEDIUM:   score >= thresholds['MEDIUM']   (default: 20.0)
        LOW:      score >= thresholds['LOW']      (default: 0.0)
        UNKNOWN:  missing, null, NaN, or non-finite score

    Returns:
        'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
    """
    if score is None or isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
        return "UNKNOWN"

    if thresholds is None:
        th = DEFAULT_PRIORITY_THRESHOLDS
    elif isinstance(thresholds, PriorityThresholds):
        th = thresholds.to_dict()
    elif isinstance(thresholds, dict):
        th = thresholds
    else:
        th = DEFAULT_PRIORITY_THRESHOLDS

    crit = th.get("CRITICAL", 70.0)
    high = th.get("HIGH", 45.0)
    med = th.get("MEDIUM", 20.0)
    low = th.get("LOW", 0.0)

    if score >= crit:
        return "CRITICAL"
    if score >= high:
        return "HIGH"
    if score >= med:
        return "MEDIUM"
    if score >= low:
        return "LOW"
    return "UNKNOWN"


def _priority_label(score: float, thresholds: dict[str, Any]) -> str:
    return classify_risk_score(score, thresholds)


def calculate_zone_risk(
    zone: dict[str, Any],
    config: dict[str, Any] | RiskEngineConfig | None = None,
) -> dict[str, Any]:
    """Calculate the numerical risk score and category for a single zone dictionary.

    Derives the score strictly from actual measurements and configured weights.
    Employs no special cases by zone ID.

    Returns:
        dict containing 'zone_id', 'score', 'raw_score', 'priority', 'status', 'confidence',
        'components', 'active_weights', 'needs_verification'.
    """
    cfg_obj: dict[str, Any]
    if config is None:
        cfg_obj = load_config()
    elif isinstance(config, RiskEngineConfig):
        cfg_obj = config.to_dict()
    else:
        cfg_obj = config

    weights_clean = _strip_comments(cfg_obj["scoring"]["weights"])
    norms = _strip_comments(cfg_obj["scoring"]["normalization"])
    iso_scores = _strip_comments(cfg_obj["scoring"]["isolation_score"])
    thresholds = _strip_comments(cfg_obj["priority_thresholds"])

    zid = str(zone.get("zone_id", "unknown"))
    fp_raw = zone.get("flooded_percent")
    eb_raw = zone.get("exposed_buildings")

    if fp_raw is None or eb_raw is None or not _is_finite_num(fp_raw) or not _is_finite_num(eb_raw):
        return {
            "zone_id": zid,
            "score": None,
            "raw_score": None,
            "priority": "UNKNOWN",
            "status": "INSUFFICIENT_DATA",
            "confidence": "LOW",
            "needs_verification": True,
            "components": {},
            "active_weights": weights_clean,
        }

    fp = max(0.0, min(100.0, float(fp_raw)))
    eb = max(0, int(eb_raw))
    tb = max(0, int(zone.get("total_buildings") or 0))
    acc_raw = zone.get("accessibility")
    acc = acc_raw if isinstance(acc_raw, str) and acc_raw in ACCESSIBILITY_VALUES else "UNKNOWN"
    fam_raw = zone.get("flooded_area_m2")
    fam = float(fam_raw) if fam_raw is not None and _is_finite_num(fam_raw) and fam_raw >= 0 else None

    flood_c = min(fp / norms["flood_percent_max"], 1.0)
    exposure_c = min(eb / norms["exposed_buildings_max"], 1.0)
    isolation_c = iso_scores.get(acc, iso_scores["UNKNOWN"])
    exp_frac_c = min(1.0, max(0.0, eb / tb)) if tb > 0 else 0.0

    if fam is not None and fam >= 0.0:
        flood_area_c = min(fam / norms["flood_area_m2_max"], 1.0)
        active_weights = dict(weights_clean)
        status = "VERIFIED"
    elif fp == 0.0:
        flood_area_c = 0.0
        active_weights = dict(weights_clean)
        status = "VERIFIED"
    else:
        flood_area_c = 0.0
        active_weights = {k: v for k, v in weights_clean.items() if k != "flood_area_density"}
        rem = sum(active_weights.values())
        if rem > 0:
            active_weights = {k: v / rem for k, v in active_weights.items()}
        status = "INCOMPLETE"

    raw = (
        active_weights.get("flood_percent", 0.0) * flood_c
        + active_weights.get("exposure", 0.0) * exposure_c
        + active_weights.get("isolation", 0.0) * isolation_c
        + active_weights.get("flood_area_density", 0.0) * flood_area_c
        + active_weights.get("exposure_fraction", 0.0) * exp_frac_c
    )
    raw = max(0.0, min(1.0, raw))
    score = round(raw * 100.0, 1)
    priority = classify_risk_score(score, thresholds)

    confidence = "HIGH" if (status == "VERIFIED" and acc != "UNKNOWN") else ("MEDIUM" if status == "INCOMPLETE" or acc == "UNKNOWN" else "LOW")
    needs_ver = priority == "LOW" and confidence != "HIGH"

    return {
        "zone_id": zid,
        "score": score,
        "raw_score": round(raw, 6),
        "priority": priority,
        "status": status,
        "confidence": confidence,
        "needs_verification": needs_ver,
        "components": {
            "flood_percent": round(flood_c, 4),
            "exposure": round(exposure_c, 4),
            "isolation": round(isolation_c, 4),
            "flood_area_density": round(flood_area_c, 4),
            "exposure_fraction": round(exp_frac_c, 4),
        },
        "active_weights": active_weights,
    }


def compute_score_breakdown(
    zone: dict[str, Any],
    active_weights: dict[str, float],
    raw_components: dict[str, float],
    raw_score: float,
    display_score: float,
    score_basis: str,
    omitted_components: list[str],
) -> dict[str, Any]:
    """Compute auditable, mathematically reconciled score breakdown and explanations."""
    fp = float(zone.get("flooded_percent", 0.0))
    eb = int(zone.get("exposed_buildings", 0))
    tb_raw = zone.get("total_buildings")
    tb = int(tb_raw) if tb_raw is not None else 0
    acc = str(zone.get("accessibility", "UNKNOWN"))
    fam = zone.get("flooded_area_m2")

    unit_map = {
        "flood_percent": "%",
        "exposure": "buildings",
        "isolation": "status",
        "flood_area_density": "m²",
        "exposure_fraction": "ratio",
    }

    fam_input = (
        float(fam)
        if (fam is not None and "flood_area_density" not in omitted_components)
        else None
    )
    exp_frac_input = round(eb / tb, 4) if tb > 0 else 0.0

    raw_input_map = {
        "flood_percent": fp,
        "exposure": eb,
        "isolation": acc,
        "flood_area_density": fam_input,
        "exposure_fraction": exp_frac_input,
    }

    components: dict[str, dict[str, Any]] = {}
    for key in ("flood_percent", "exposure", "isolation", "flood_area_density", "exposure_fraction"):
        is_omitted = key in omitted_components
        norm_val = raw_components.get(key, 0.0)
        weight = 0.0 if is_omitted else active_weights.get(key, 0.0)
        weighted_contrib = weight * norm_val
        points = round(weighted_contrib * 100.0, 2)
        pct_of_score = (
            round((weighted_contrib / raw_score * 100.0), 1)
            if raw_score > 0.0
            else 0.0
        )

        components[key] = {
            "raw_input": raw_input_map[key],
            "unit": unit_map[key],
            "normalized_value": round(norm_val, 4),
            "weight": round(weight, 4),
            "weighted_contribution": round(weighted_contrib, 6),
            "points": points,
            "percentage_of_score": pct_of_score,
            "omitted": is_omitted,
        }

    sum_weighted = sum(c["weighted_contribution"] for c in components.values())
    sum_points = round(sum(c["points"] for c in components.values()), 2)
    computed_score = raw_score * 100.0
    rounding_diff = round(display_score - sum_points, 2)

    weights_reconciled = abs(sum_weighted - raw_score) < 1e-5
    points_reconciled = abs(display_score - sum_points) <= 0.08
    reconciled = weights_reconciled and points_reconciled

    reconciliation = {
        "sum_weighted_contributions": round(sum_weighted, 6),
        "sum_points": sum_points,
        "computed_score": round(computed_score, 4),
        "final_score": display_score,
        "rounding_difference": rounding_diff,
        "reconciled": reconciled,
        "tolerance": 0.08,
    }

    contributing = [
        (k, components[k])
        for k in components
        if components[k]["weighted_contribution"] > 0.0
    ]
    priority_order = {
        "exposure": 1,
        "flood_percent": 2,
        "isolation": 3,
        "flood_area_density": 4,
        "exposure_fraction": 5,
    }
    sorted_contribs = sorted(
        contributing,
        key=lambda item: (-item[1]["weighted_contribution"], priority_order.get(item[0], 99)),
    )

    if not sorted_contribs:
        primary_driver = None
        primary_driver_summary = "No flood impact or isolation factors contributing to risk score"
        influential_factors: list[str] = []
        ranking_factors: list[str] = []
    else:
        primary_driver = sorted_contribs[0][0]
        friendly_names = {
            "exposure": "Building exposure",
            "flood_percent": "Flood coverage",
            "isolation": "Road isolation",
            "flood_area_density": "Flood extent area",
            "exposure_fraction": "Building exposure fraction",
        }
        top_name = friendly_names.get(primary_driver, primary_driver)
        top_pts = components[primary_driver]["points"]
        top_pct = components[primary_driver]["percentage_of_score"]
        primary_driver_summary = (
            f"{top_name} is the primary score driver ({top_pts:.1f} pts, {top_pct:.0f}% of score)"
        )

        influential_factors = []
        for k, c in sorted_contribs:
            pts = c["points"]
            pct = c["percentage_of_score"]
            if k == "exposure":
                influential_factors.append(
                    f"Building exposure: {eb} exposed buildings contribute {pts:.1f} pts ({pct:.0f}% of score)"
                )
            elif k == "flood_percent":
                influential_factors.append(
                    f"Flood coverage: {fp:.1f}% inundated area contributes {pts:.1f} pts ({pct:.0f}% of score)"
                )
            elif k == "isolation":
                influential_factors.append(
                    f"Road isolation: {acc} accessibility contributes {pts:.1f} pts ({pct:.0f}% of score)"
                )
            elif k == "flood_area_density":
                fam_val = float(fam) if fam is not None else 0.0
                influential_factors.append(
                    f"Flood extent area: {fam_val:,.0f} m² footprint contributes {pts:.1f} pts ({pct:.0f}% of score)"
                )
            elif k == "exposure_fraction":
                exp_f = raw_components.get("exposure_fraction", 0.0)
                influential_factors.append(
                    f"Building exposure fraction: {eb}/{tb} ({exp_f:.1%}) contributes {pts:.1f} pts ({pct:.0f}% of score)"
                )

        ranking_factors = []
        if acc == "BLOCKED" and components["isolation"]["weighted_contribution"] > 0.0:
            iso_pts = components["isolation"]["points"]
            ranking_factors.append(
                f"Blocked road access imposes maximum isolation penalty (+{iso_pts:.1f} pts), elevating zone priority"
            )
        elif acc == "PARTIAL" and components["isolation"]["weighted_contribution"] > 0.0:
            iso_pts = components["isolation"]["points"]
            ranking_factors.append(
                f"Partial road access imposes intermediate isolation penalty (+{iso_pts:.1f} pts), elevating zone priority"
            )
        elif acc == "UNKNOWN" and components["isolation"]["weighted_contribution"] > 0.0:
            iso_pts = components["isolation"]["points"]
            ranking_factors.append(
                f"Unknown road accessibility applies provisional intermediate isolation penalty (+{iso_pts:.1f} pts) pending field verification"
            )
        if (eb >= 15 or components["exposure"]["normalized_value"] >= 0.4) and components["exposure"]["weighted_contribution"] > 0.0:
            exp_pts = components["exposure"]["points"]
            ranking_factors.append(
                f"Substantial building exposure ({eb} exposed buildings, +{exp_pts:.1f} pts) strongly elevates priority and serves as primary tiebreaker"
            )
        if (fp >= 50.0 or components["flood_percent"]["normalized_value"] >= 0.5) and components["flood_percent"]["weighted_contribution"] > 0.0:
            fp_pts = components["flood_percent"]["points"]
            ranking_factors.append(
                f"High flood extent ({fp:.1f}% flooded, +{fp_pts:.1f} pts) strongly elevates priority and serves as secondary tiebreaker"
            )

    return {
        "score": display_score,
        "raw_score": round(raw_score, 6),
        "score_basis": score_basis,
        "omitted_components": list(omitted_components),
        "components": components,
        "reconciliation": reconciliation,
        "primary_driver": primary_driver,
        "primary_driver_summary": primary_driver_summary,
        "influential_factors": influential_factors,
        "ranking_factors": ranking_factors,
    }


def _build_reasons(
    zone: dict[str, Any],
    flood_c: float,
    has_flood_area: bool,
    cfg_dq: dict[str, Any],
    assessment: ZoneDataQualityAssessment | None = None,
    score: float | None = None,
    priority: str | None = None,
    breakdown: dict[str, Any] | None = None,
) -> list[str]:
    """Generate human-readable explanations for score components and data quality."""
    reasons: list[str] = []

    fp = zone["flooded_percent"]
    eb = zone["exposed_buildings"]
    tb_raw = zone.get("total_buildings")
    tb = int(tb_raw) if tb_raw is not None else 0
    acc_raw = zone.get("accessibility")
    acc = acc_raw if isinstance(acc_raw, str) and acc_raw in ACCESSIBILITY_VALUES else "UNKNOWN"
    fam = zone.get("flooded_area_m2")
    rl_raw = zone.get("road_length_m")
    rl = float(rl_raw) if rl_raw is not None else 0.0
    frl_raw = zone.get("flooded_road_length_m")
    frl = float(frl_raw) if frl_raw is not None else 0.0

    if flood_c > 0:
        reasons.append(
            f"{fp:.1f}% of zone area estimated as flooded "
            f"(derived from labelled building/road extents)"
        )
    else:
        reasons.append("No derived flood coverage in this zone")

    if tb > 0:
        reasons.append(
            f"{eb} of {tb} buildings have a human-labelled 'flooded' tag"
        )
    else:
        reasons.append("No buildings recorded in this zone")

    iso_w = 1.0
    if breakdown and "components" in breakdown and "isolation" in breakdown["components"]:
        iso_w = breakdown["components"]["isolation"]["weight"]

    if acc == "BLOCKED":
        if rl <= 0:
            if iso_w > 0:
                reasons.append(
                    "Zone roads are BLOCKED (No road length recorded; cannot compute % flooded) "
                    "— reaching this zone is severely restricted (road isolation penalty applied)"
                )
            else:
                reasons.append(
                    "Zone roads are BLOCKED (No road length recorded; cannot compute % flooded) "
                    "— reaching this zone is severely restricted (isolation weight is 0.0; no penalty applied to score)"
                )
        else:
            frl_pct = min(100.0, (frl / rl * 100))
            if iso_w > 0:
                reasons.append(
                    f"Zone roads are {frl_pct:.0f}% flooded — reaching this zone "
                    f"is severely restricted (road isolation penalty applied)"
                )
            else:
                reasons.append(
                    f"Zone roads are {frl_pct:.0f}% flooded — reaching this zone "
                    f"is severely restricted (isolation weight is 0.0; no penalty applied to score)"
                )
    elif acc == "PARTIAL":
        if rl <= 0:
            if iso_w > 0:
                reasons.append(
                    "Zone roads are PARTIAL (No road length recorded; cannot compute % flooded) "
                    "— partial road isolation penalty applied"
                )
            else:
                reasons.append(
                    "Zone roads are PARTIAL (No road length recorded; cannot compute % flooded) "
                    "— partial road isolation (isolation weight is 0.0; no penalty applied to score)"
                )
        else:
            frl_pct = min(100.0, (frl / rl * 100))
            if iso_w > 0:
                reasons.append(
                    f"Zone roads are {frl_pct:.0f}% flooded — partial road isolation penalty applied"
                )
            else:
                reasons.append(
                    f"Zone roads are {frl_pct:.0f}% flooded — partial road isolation (isolation weight is 0.0; no penalty applied to score)"
                )
    elif acc == "UNKNOWN":
        if acc_raw is None:
            road_note = "Accessibility data is missing for this zone"
        elif rl <= 0:
            road_note = "No road data for this zone"
        else:
            road_note = f"Road data unverified for this zone ({rl:.0f} m roads recorded)"

        if iso_w > 0:
            reasons.append(
                f"{road_note} — isolation status unknown (intermediate penalty applied)"
            )
        else:
            reasons.append(
                f"{road_note} — isolation status unknown (isolation weight is 0.0; no penalty applied to score)"
            )
    else:
        reasons.append("Roads in this zone are not significantly flooded")

    if has_flood_area and fam is not None and fam > 0:
        reasons.append(f"Derived flood-extent area: {fam:.0f} m²")

    warn_thresh = cfg_dq.get("warn_on_zero_exposure_with_high_flood_percent_threshold", 5.0)
    if eb == 0 and fp >= warn_thresh and tb > 0:
        reasons.append(
            f"NOTE: flooded_percent={fp:.1f}% but no buildings have a "
            f"'flooded' label — extent may not overlap recorded structures"
        )

    # Explain primary score driver concisely
    if breakdown and breakdown.get("primary_driver_summary") and score is not None and score > 0:
        reasons.append(f"Primary score driver: {breakdown['primary_driver_summary']}")

    # Explain ranking-relevant factors
    if breakdown and breakdown.get("ranking_factors"):
        for rf in breakdown["ranking_factors"]:
            reasons.append(f"Ranking factor: {rf}")

    # Explanation for low-risk zones with incomplete data requiring verification
    if assessment is not None and assessment.needs_verification and priority == "LOW":
        score_val = f"{score:.1f}" if score is not None else "LOW"
        reasons.append(
            f"VERIFICATION REQUIRED: Zone priority is LOW ({score_val}) but input data is "
            f"{assessment.data_quality_status.lower()} (confidence: {assessment.confidence}) — "
            f"insufficient data must be verified rather than assumed safe"
        )

    return reasons



def assess_zone_data_quality(
    zone: dict[str, Any],
    global_warnings: list[DataQualityWarning],
    cfg_dq: dict[str, Any],
    priority: str,
    score_basis: str,
    omitted_components: list[str],
) -> ZoneDataQualityAssessment:
    """Evaluate data completeness, physical consistency, and confidence deterministically.

    Categories:
        HIGH: All required and optional measurements present, valid, physically consistent,
              and accessibility confirmed (not UNKNOWN). No warnings or clamped values.
        MEDIUM: Data is usable for scoring but has single unverified/missing attributes:
              e.g. UNKNOWN accessibility, missing flood extent area requiring partial scoring,
              omitted building/road metadata, missing geometry coordinates, or heuristic extent mismatch.
        LOW: Severe data quality issues: direct physical contradictions in measurements,
              clamped out-of-range or coerced negative values, or multiple compounding incomplete fields.

    Safety Policy:
        A zone classified as LOW priority cannot be assumed safe if data is incomplete or unverified.
        Any such zone is flagged with needs_verification=True.
    """
    zid = zone["zone_id"]
    fp = float(zone["flooded_percent"])
    eb = int(zone["exposed_buildings"])
    tb_raw = zone.get("total_buildings")
    tb = int(tb_raw) if tb_raw is not None else 0
    acc_raw = zone.get("accessibility")
    acc = acc_raw if isinstance(acc_raw, str) and acc_raw in ACCESSIBILITY_VALUES else "UNKNOWN"
    fam = zone.get("flooded_area_m2")
    rl_raw = zone.get("road_length_m")
    rl = float(rl_raw) if rl_raw is not None else 0.0
    frl_raw = zone.get("flooded_road_length_m")
    frl = float(frl_raw) if frl_raw is not None else 0.0
    centroid = zone.get("centroid", [])
    bbox = zone.get("bbox", [])
    missing_fields = zone.get("_missing_fields", [])

    zone_warnings: list[str] = [w.issue for w in global_warnings if w.zone_id == zid]

    warn_thresh = cfg_dq.get("warn_on_zero_exposure_with_high_flood_percent_threshold", 5.0)

    # 1. Road accessibility warning (exactly once per zone)
    if acc_raw is None:
        msg = "accessibility is missing; cannot be assumed accessible (flagged for verification)"
        if msg not in zone_warnings:
            zone_warnings.append(msg)
    elif acc == "UNKNOWN" and cfg_dq.get("warn_on_unknown_accessibility", True):
        msg = "accessibility=UNKNOWN: no road data; isolation status cannot be determined"
        if msg not in zone_warnings:
            zone_warnings.append(msg)

    # 2. Heuristic zero exposure with high flood percentage
    if eb == 0 and fp >= warn_thresh:
        msg = (
            f"flooded_percent={fp:.1f}% but exposed_buildings=0: "
            f"flood extent may not coincide with recorded building footprints"
        )
        if msg not in zone_warnings:
            zone_warnings.append(msg)

    # 3. Partial scoring warning
    if score_basis == "partial" and cfg_dq.get("warn_on_null_flooded_area_m2", True):
        warn_msg = (
            "flooded_area_m2 is null while flooded_percent > 0; "
            "omitted flood_area_density component and renormalized remaining weights"
        )
        if warn_msg not in zone_warnings:
            zone_warnings.append(warn_msg)

    # 4. Identify specific issue categories
    contradictions: list[str] = []
    degradations: list[str] = []
    incompletes: list[str] = []

    # Check contradictions
    if fp == 0.0 and eb > 0:
        contradictions.append("contradictory_zero_flood_with_exposed_buildings")
    if fp == 0.0 and fam is not None and fam > 0.0:
        contradictions.append("contradictory_zero_flood_with_flooded_area")
    if fp == 0.0 and frl > 0.0:
        contradictions.append("contradictory_zero_flood_with_flooded_roads")
    if fp > 0.0 and fam == 0.0 and "flooded_area_m2" not in missing_fields:
        contradictions.append("contradictory_positive_flood_zero_area")
    if eb > tb:
        contradictions.append("exposed_buildings_exceeds_total")
    if frl > rl:
        contradictions.append("flooded_road_exceeds_total")
    if rl > 0.0 and (frl / rl) >= 0.60 and acc == "ACCESSIBLE":
        contradictions.append("contradictory_accessible_with_blocked_roads")
    if rl > 0.0 and frl == 0.0 and acc == "BLOCKED":
        contradictions.append("contradictory_blocked_with_zero_flooded_roads")

    # Check degradations from warnings
    for w in zone_warnings:
        w_lower = w.lower()
        if "clamped" in w_lower:
            degradations.append("clamped_value")
        if "negative" in w_lower:
            degradations.append("negative_value_coerced")
        if "non-numeric" in w_lower or "non-finite" in w_lower:
            degradations.append("non_finite_coerced")
        if "unrecognised accessibility" in w_lower:
            degradations.append("unrecognised_accessibility")
        if "invalid centroid" in w_lower or "invalid bbox" in w_lower:
            degradations.append("invalid_geometry")

    # Check incompleteness
    if acc_raw is None:
        incompletes.append("missing_accessibility")
    elif acc == "UNKNOWN":
        incompletes.append("unknown_accessibility")
    if score_basis == "partial":
        incompletes.append("missing_flood_area_partial_scoring")
    for mf in missing_fields:
        incompletes.append(f"missing_{mf}")
    if (not centroid or not bbox) and "invalid_geometry" not in degradations:
        incompletes.append("missing_geometry")
    if eb == 0 and fp >= warn_thresh:
        incompletes.append("zero_exposure_with_high_flood_percent")
    if rl <= 0.0 and acc in ("BLOCKED", "PARTIAL"):
        incompletes.append("unrecorded_road_network")

    # Combine unique issues in order
    all_issues: list[str] = []
    for issue in contradictions + degradations + incompletes:
        if issue not in all_issues:
            all_issues.append(issue)

    # 5. Determine status
    if contradictions:
        status = "CONTRADICTORY"
    elif degradations:
        status = "DEGRADED"
    elif incompletes:
        status = "INCOMPLETE"
    else:
        status = "VERIFIED"

    # 6. Determine confidence level
    # Count major missing/unknown attributes to detect compounding issues
    major_deficiencies = 0
    if acc == "UNKNOWN":
        major_deficiencies += 1
    if score_basis == "partial":
        major_deficiencies += 1
    if not centroid or not bbox or "invalid_geometry" in degradations:
        major_deficiencies += 1
    if "total_buildings" in missing_fields:
        major_deficiencies += 1
    if "road_length_m" in missing_fields:
        major_deficiencies += 1

    if status in ("CONTRADICTORY", "DEGRADED"):
        confidence = "LOW"
    elif major_deficiencies >= 2:
        confidence = "LOW"
    elif status == "INCOMPLETE":
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"

    # 7. Determine needs_verification flag
    needs_verification = False
    if confidence == "LOW":
        needs_verification = True
    elif score_basis == "partial":
        needs_verification = True
    elif acc == "UNKNOWN":
        needs_verification = True
    elif status in ("CONTRADICTORY", "DEGRADED"):
        needs_verification = True
    elif priority == "LOW" and confidence != "HIGH":
        # Cannot treat unknown or incomplete measurements as proof of safety
        needs_verification = True
    elif "zero_exposure_with_high_flood_percent" in all_issues and priority in ("LOW", "MEDIUM"):
        needs_verification = True

    return ZoneDataQualityAssessment(
        zone_id=zid,
        confidence=confidence,
        needs_verification=needs_verification,
        data_quality_status=status,
        issues=all_issues,
        warnings=zone_warnings,
        missing_fields=missing_fields,
        score_basis=score_basis,
        omitted_components=omitted_components,
    )


def _build_zone_warnings(
    zone: dict[str, Any],
    global_warnings: list[DataQualityWarning],
    cfg_dq: dict[str, Any],
    assessment: ZoneDataQualityAssessment | None = None,
) -> list[str]:
    """Collect per-zone warning strings from global warnings and heuristic flags."""
    if assessment is not None:
        return assessment.warnings

    zid = zone["zone_id"]
    msgs: list[str] = [w.issue for w in global_warnings if w.zone_id == zid]

    acc_raw = zone.get("accessibility")
    acc = acc_raw if isinstance(acc_raw, str) and acc_raw in ACCESSIBILITY_VALUES else "UNKNOWN"
    fp = float(zone.get("flooded_percent") or 0.0)
    eb = int(zone.get("exposed_buildings") or 0)
    warn_thresh = cfg_dq.get("warn_on_zero_exposure_with_high_flood_percent_threshold", 5.0)

    # Emit warning for missing or UNKNOWN accessibility
    if acc_raw is None:
        msg = "accessibility is missing; cannot be assumed accessible (flagged for verification)"
        if msg not in msgs:
            msgs.append(msg)
    elif acc == "UNKNOWN" and cfg_dq.get("warn_on_unknown_accessibility", True):
        msg = "accessibility=UNKNOWN: no road data; isolation status cannot be determined"
        if msg not in msgs:
            msgs.append(msg)

    if eb == 0 and fp >= warn_thresh:
        msg = (
            f"flooded_percent={fp:.1f}% but exposed_buildings=0: "
            f"flood extent may not coincide with recorded building footprints"
        )
        if msg not in msgs:
            msgs.append(msg)

    return msgs


def score_zones(
    zones_doc: dict[str, Any],
    config: dict[str, Any] | RiskEngineConfig,
    global_warnings: list[DataQualityWarning],
) -> list[ZoneRiskRecord]:
    """Compute risk scores for all zones and rank them deterministically.

    Ranking Order:
        1. Unrounded raw score descending
        2. Exposed buildings descending
        3. Flooded percentage descending
        4. Natural-sort zone_id ascending
    """
    if isinstance(config, RiskEngineConfig):
        config = config.to_dict()
    weights_clean = _strip_comments(config["scoring"]["weights"])
    norms = _strip_comments(config["scoring"]["normalization"])
    iso_scores = _strip_comments(config["scoring"]["isolation_score"])
    thresholds = _strip_comments(config["priority_thresholds"])
    cfg_dq = config.get("data_quality", {})

    records: list[ZoneRiskRecord] = []

    for zone in zones_doc["zones"]:
        zid = zone["zone_id"]
        fp_raw = zone.get("flooded_percent")
        eb_raw = zone.get("exposed_buildings")
        tb_raw = zone.get("total_buildings")
        tb = int(tb_raw) if tb_raw is not None else 0
        rl_raw = zone.get("road_length_m")
        rl = float(rl_raw) if rl_raw is not None else 0.0
        frl_raw = zone.get("flooded_road_length_m")
        frl = float(frl_raw) if frl_raw is not None else 0.0
        acc_raw = zone.get("accessibility")
        if acc_raw is None or not isinstance(acc_raw, str) or acc_raw not in ACCESSIBILITY_VALUES:
            acc = "UNKNOWN"
        else:
            acc = acc_raw
        fam = zone.get("flooded_area_m2")

        if zone.get("_is_insufficient_data") or fp_raw is None or eb_raw is None or not _is_finite_num(fp_raw) or not _is_finite_num(eb_raw):
            zone_warnings = [w.issue for w in global_warnings if w.zone_id == zid]
            if not zone_warnings:
                zone_warnings = ["insufficient_data: missing required flood or exposure measurements"]
            records.append(ZoneRiskRecord(
                zone_id=zid,
                rank=0,
                score=None,
                priority="UNKNOWN",
                raw_score=-1.0,
                reasons=["INSUFFICIENT DATA: Required flood coverage or building exposure data is missing or invalid; cannot reliably determine risk score (priority UNKNOWN)."],
                warnings=zone_warnings,
                score_basis="none",
                omitted_components=["all"],
                flood_percent_component=0.0,
                exposure_component=0.0,
                isolation_component=0.0,
                flood_area_component=0.0,
                exposure_fraction_component=0.0,
                flooded_percent=None,
                exposed_buildings=None,
                total_buildings=tb,
                accessibility=acc,
                road_length_m=rl,
                flooded_road_length_m=frl,
                flooded_area_m2=float(fam) if (fam is not None and _is_finite_num(fam)) else None,
                centroid=list(zone.get("centroid") or []),
                bbox=list(zone.get("bbox") or []),
                confidence="LOW",
                needs_verification=True,
                data_quality_status="INSUFFICIENT_DATA",
                data_quality_issues=["insufficient_data"],
                score_breakdown={},
            ))
            continue

        fp = float(fp_raw)
        eb = int(eb_raw)

        # 1. Component normalization [0.0, 1.0]
        flood_c = min(fp / norms["flood_percent_max"], 1.0)
        exposure_c = min(eb / norms["exposed_buildings_max"], 1.0)
        isolation_c = iso_scores.get(acc, iso_scores["UNKNOWN"])
        exp_frac_c = min(1.0, max(0.0, eb / tb)) if tb > 0 else 0.0

        # 2. Handling missing flooded_area_m2:
        # Score as 0 ONLY when flooded_percent == 0.
        # If null while flooded_percent > 0, drop component and renormalize remaining weights.
        if fam is not None and fam >= 0.0:
            flood_area_c = min(float(fam) / norms["flood_area_m2_max"], 1.0)
            score_basis = "full"
            omitted_components: list[str] = []
            active_weights = dict(weights_clean)
            has_flood_area = True
        elif fp == 0.0:
            # flooded_percent == 0 and flooded_area_m2 is null: score as 0 without dropping component
            flood_area_c = 0.0
            score_basis = "full"
            omitted_components = []
            active_weights = dict(weights_clean)
            has_flood_area = False
        else:
            # Inconsistent: flooded_area_m2 is null/invalid while flooded_percent > 0
            flood_area_c = 0.0
            score_basis = "partial"
            omitted_components = ["flood_area_density"]
            has_flood_area = False
            active_weights = {k: v for k, v in weights_clean.items() if k != "flood_area_density"}
            rem_sum = sum(active_weights.values())
            if rem_sum > 0:
                active_weights = {k: v / rem_sum for k, v in active_weights.items()}

        # 3. Compute raw score and priority
        raw = (
            active_weights.get("flood_percent", 0.0) * flood_c
            + active_weights.get("exposure", 0.0) * exposure_c
            + active_weights.get("isolation", 0.0) * isolation_c
            + active_weights.get("flood_area_density", 0.0) * flood_area_c
            + active_weights.get("exposure_fraction", 0.0) * exp_frac_c
        )
        raw = max(0.0, min(1.0, raw))
        score = round(raw * 100, 1)

        priority = _priority_label(score, thresholds)

        # 4. Compute transparent, auditable score breakdown
        breakdown = compute_score_breakdown(
            zone=zone,
            active_weights=active_weights,
            raw_components={
                "flood_percent": flood_c,
                "exposure": exposure_c,
                "isolation": isolation_c,
                "flood_area_density": flood_area_c,
                "exposure_fraction": exp_frac_c,
            },
            raw_score=raw,
            display_score=score,
            score_basis=score_basis,
            omitted_components=omitted_components,
        )

        # 5. Deterministic data quality and confidence assessment
        assessment = assess_zone_data_quality(
            zone=zone,
            global_warnings=global_warnings,
            cfg_dq=cfg_dq,
            priority=priority,
            score_basis=score_basis,
            omitted_components=omitted_components,
        )

        zone_warnings = assessment.warnings
        reasons = _build_reasons(
            zone, flood_c, has_flood_area, cfg_dq, assessment, score, priority, breakdown
        )

        records.append(ZoneRiskRecord(
            zone_id=zid,
            rank=0,
            score=score,
            priority=priority,
            raw_score=raw,
            reasons=reasons,
            warnings=zone_warnings,
            score_basis=score_basis,
            omitted_components=omitted_components,
            flood_percent_component=round(flood_c, 4),
            exposure_component=round(exposure_c, 4),
            isolation_component=round(isolation_c, 4),
            flood_area_component=round(flood_area_c, 4),
            exposure_fraction_component=round(exp_frac_c, 4),
            flooded_percent=fp,
            exposed_buildings=eb,
            total_buildings=tb,
            accessibility=acc,
            road_length_m=rl,
            flooded_road_length_m=frl,
            flooded_area_m2=float(fam) if fam is not None else 0.0,
            centroid=list(zone.get("centroid") or []),
            bbox=list(zone.get("bbox") or []),
            confidence=assessment.confidence,
            needs_verification=assessment.needs_verification,
            data_quality_status=assessment.data_quality_status,
            data_quality_issues=assessment.issues,
            score_breakdown=breakdown,
        ))

    # Deterministic Ranking
    records.sort(
        key=lambda r: (
            0 if (r.score is not None and r.raw_score is not None and r.raw_score >= 0) else 1,
            -r.raw_score if (r.raw_score is not None and r.raw_score >= 0) else 0.0,
            -(r.exposed_buildings if r.exposed_buildings is not None else -1),
            -(r.flooded_percent if r.flooded_percent is not None else -1.0),
            _natural_sort_key(r.zone_id),
        )
    )

    for i, rec in enumerate(records, start=1):
        rec.rank = i

    return records


# ---------------------------------------------------------------------------
# Output serialisation & Dashboard Exporter
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA_VERSION = "1.1"


def records_to_dict(
    records: list[ZoneRiskRecord],
    global_warnings: list[DataQualityWarning],
    source_doc: dict[str, Any],
    config: dict[str, Any] | RiskEngineConfig,
    input_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Serialise scored records to a dictionary matching the output contract."""
    if isinstance(config, RiskEngineConfig):
        config = config.to_dict()
    weights = _strip_comments(config["scoring"]["weights"])
    norms = _strip_comments(config["scoring"]["normalization"])
    thresholds = _strip_comments(config["priority_thresholds"])
    config_ver = config.get("config_version", "1.0")

    effective_config_clean = {
        "config_version": config_ver,
        "scoring": {
            "weights": weights,
            "normalization": norms,
            "isolation_score": _strip_comments(config["scoring"]["isolation_score"]),
        },
        "priority_thresholds": thresholds,
    }
    cfg_hash = hashlib.sha256(
        json.dumps(effective_config_clean, sort_keys=True).encode("utf-8")
    ).hexdigest()
    w_fingerprint = weights_fingerprint(weights)

    if input_file_sha256 is None:
        input_file_sha256 = hashlib.sha256(
            json.dumps(source_doc, sort_keys=True).encode("utf-8")
        ).hexdigest()

    now_utc = datetime.now(timezone.utc).isoformat()
    crs_val = source_doc.get("crs", "unknown")

    # Build disclaimer based on context hierarchy
    disclaimer_ctx = config.get("disclaimer_context")
    if not disclaimer_ctx:
        disclaimer_ctx = (
            source_doc.get("disclaimer_context")
            or source_doc.get("context")
            or source_doc.get("event")
            or source_doc.get("source")
        )

    if disclaimer_ctx:
        disclaimer = (
            f"PROVISIONAL DECISION-SUPPORT HEURISTIC — scores reflect configurable weightings "
            f"applied to flood analysis labels for {disclaimer_ctx}. They have NOT been validated against "
            f"historical flood casualties or response outcomes. Do not treat scores as predictions "
            f"of life-safety risk. Road accessibility data indicates zone isolation only — it makes "
            f"no claim about route safety."
        )
    else:
        disclaimer = (
            "PROVISIONAL DECISION-SUPPORT HEURISTIC — scores reflect configurable weightings "
            "applied to flood analysis labels. They have NOT been validated against historical flood "
            "casualties or response outcomes. Do not treat scores as predictions of life-safety risk. "
            "Road accessibility data indicates zone isolation only — it makes no claim about route safety."
        )

    scored_zones = []
    for r in records:
        iso_comp = r.score_breakdown.get("components", {}).get("isolation", {})
        iso_weight = iso_comp.get("weight", 0.15)
        iso_points = iso_comp.get("points", 0.0)
        iso_weighted = iso_comp.get("weighted_contribution", 0.0)
        iso_pct = iso_comp.get("percentage_of_score", 0.0)

        flooded_road_share = (
            round(r.flooded_road_length_m / r.road_length_m, 4)
            if r.road_length_m > 0
            else None
        )
        isolation_warnings = [
            w for w in r.warnings
            if any(term in w.lower() for term in ("accessibility", "road", "isolation"))
        ]

        isolation_dict = {
            "status": r.accessibility,
            "score": r.isolation_component,
            "weight": iso_weight,
            "weighted_contribution": iso_weighted,
            "points": iso_points,
            "percentage_of_score": iso_pct,
            "road_length_m": r.road_length_m,
            "flooded_road_length_m": r.flooded_road_length_m,
            "flooded_road_share": flooded_road_share,
            "warnings": isolation_warnings,
            "needs_verification": r.accessibility == "UNKNOWN",
        }

        scored_zones.append({
            "rank": r.rank,
            "zone_id": r.zone_id,
            "score": r.score,
            "priority": r.priority,
            "score_basis": r.score_basis,
            "omitted_components": r.omitted_components,
            "confidence": r.confidence,
            "needs_verification": r.needs_verification,
            "accessibility": r.accessibility,
            "isolation": isolation_dict,
            "data_quality": {
                "confidence": r.confidence,
                "status": r.data_quality_status,
                "needs_verification": r.needs_verification,
                "issues": r.data_quality_issues,
                "warnings": r.warnings,
            },
            "score_breakdown": r.score_breakdown,
            "reasons": r.reasons,
            "warnings": r.warnings,
            "score_components": {
                "flood_percent": r.flood_percent_component,
                "exposure": r.exposure_component,
                "isolation": r.isolation_component,
                "flood_area_density": r.flood_area_component,
                "exposure_fraction": r.exposure_fraction_component,
            },
            "inputs": {
                "flooded_percent": r.flooded_percent,
                "exposed_buildings": r.exposed_buildings,
                "total_buildings": r.total_buildings,
                "accessibility": r.accessibility,
                "road_length_m": r.road_length_m,
                "flooded_road_length_m": r.flooded_road_length_m,
                "flooded_area_m2": r.flooded_area_m2,
            },
            "geometry": {
                "centroid": r.centroid,
                "bbox": r.bbox,
                "crs": crs_val,
            },
        })

    priority_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    confidence_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    accessibility_counts = {"ACCESSIBLE": 0, "PARTIAL": 0, "BLOCKED": 0, "UNKNOWN": 0}
    verification_needed_count = 0
    for r in records:
        priority_counts[r.priority] = priority_counts.get(r.priority, 0) + 1
        confidence_counts[r.confidence] = confidence_counts.get(r.confidence, 0) + 1
        accessibility_counts[r.accessibility] = accessibility_counts.get(r.accessibility, 0) + 1
        if r.needs_verification:
            verification_needed_count += 1

    all_warnings = [
        {"zone_id": w.zone_id, "field": w.field, "issue": w.issue}
        for w in global_warnings
    ]

    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "module": "risk_engine",
        "module_version": "1.0",
        "generated_at": now_utc,
        "disclaimer": disclaimer,
        "source_metadata": {
            "input_schema_version": source_doc.get("schema_version", "unknown"),
            "input_source": source_doc.get("source", "unknown"),
            "input_crs": crs_val,
            "input_file_sha256": input_file_sha256,
            "config_hash_sha256": cfg_hash,
            "weights_fingerprint": w_fingerprint,
        },
        "scoring_config": {
            "config_version": config_ver,
            "config_hash_sha256": cfg_hash,
            "weights_fingerprint": w_fingerprint,
            "weights": weights,
            "normalization_ceilings": norms,
            "priority_thresholds": thresholds,
        },
        "summary": {
            "total_zones": len(records),
            "priority_counts": priority_counts,
            "confidence_counts": confidence_counts,
            "accessibility_counts": accessibility_counts,
            "verification_needed_count": verification_needed_count,
        },
        "data_quality_warnings": all_warnings,
        "ranked_zones": scored_zones,
    }


def export_dashboard(
    output_dict: dict[str, Any],
    source_doc: dict[str, Any],
    data_mode: str = "historical",
) -> dict[str, Any]:
    """Export scored zones matching dashboard architecture section 5.1."""
    study_area = (
        source_doc.get("study_area")
        or source_doc.get("source")
        or output_dict.get("source_metadata", {}).get("input_source")
        or "unknown"
    )

    dashboard_zones = []
    for z in output_dict["ranked_zones"]:
        inp = z["inputs"]
        bbox = z["geometry"]["bbox"]

        # Build closed GeoJSON Polygon ring from bbox [min_lng, min_lat, max_lng, max_lat]
        if isinstance(bbox, list) and len(bbox) == 4:
            min_lng, min_lat, max_lng, max_lat = bbox
            coordinates = [
                [
                    [min_lng, min_lat],
                    [max_lng, min_lat],
                    [max_lng, max_lat],
                    [min_lng, max_lat],
                    [min_lng, min_lat],
                ]
            ]
            geometry = {
                "type": "Polygon",
                "coordinates": coordinates,
            }
        else:
            geometry = {
                "type": "Polygon",
                "coordinates": [],
            }

        acc_raw = inp.get("accessibility", "UNKNOWN")
        acc_mapped = ACCESSIBILITY_DASHBOARD_MAP.get(acc_raw, "UNKNOWN")

        fam_m2 = inp.get("flooded_area_m2")
        fam_km2 = round(float(fam_m2) / 1e6, 6) if (fam_m2 is not None and _is_finite_num(fam_m2) and fam_m2 >= 0) else None

        zid = z["zone_id"]
        num_part = zid.replace("zone-", "") if zid.startswith("zone-") else zid
        zone_name = z.get("name") or f"Zone {num_part}"

        score_val = round(float(z["score"]), 1) if (z.get("score") is not None and _is_finite_num(z["score"])) else None
        fp_val = float(inp["flooded_percent"]) if (inp.get("flooded_percent") is not None and _is_finite_num(inp["flooded_percent"])) else None
        eb_val = int(inp["exposed_buildings"]) if (inp.get("exposed_buildings") is not None and _is_finite_num(inp["exposed_buildings"])) else None
        tb_val = int(inp["total_buildings"]) if (inp.get("total_buildings") is not None and _is_finite_num(inp["total_buildings"])) else None

        dashboard_zones.append({
            "zone_id": z["zone_id"],
            "name": zone_name,
            "risk_level": z["priority"],
            "risk_score": score_val,
            "confidence": z.get("confidence", "HIGH"),
            "needs_verification": z.get("needs_verification", False),
            "needs_survey": z.get("needs_verification", False),
            "flooded_percent": fp_val,
            "flooded_area_km2": fam_km2,
            "exposed_buildings": eb_val,
            "total_buildings": tb_val,
            "accessibility": acc_mapped,
            "isolation": z.get("isolation"),
            "reasons": z.get("reasons", []),
            "geometry": geometry,
            "score_breakdown": z.get("score_breakdown"),
        })

    thresh = (
        output_dict.get("scoring_config", {}).get("priority_thresholds")
        or DEFAULT_PRIORITY_THRESHOLDS
    )

    return {
        "schema_version": "1.1",
        "generated_at": output_dict.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "data_mode": data_mode,
        "study_area": study_area,
        "source": source_doc.get("source") or "SpaceNet 8 Germany (Dernau)",
        "crs": source_doc.get("crs", "EPSG:4326"),
        "score_scale": "0-100",
        "priority_thresholds": thresh,
        "scoring_config": output_dict.get("scoring_config"),
        "zones": dashboard_zones,
    }
