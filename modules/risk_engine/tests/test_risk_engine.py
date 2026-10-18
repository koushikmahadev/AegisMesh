"""Pytest test suite for HighWater Module 3 — Risk & Prioritization Engine.

Preserves and strengthens existing tests, and covers all Stage 1, Stage 2, and Stage 3
requirements, including property-based tests via Hypothesis.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
from typing import Any

import pytest
from hypothesis import given, strategies as st, settings

from risk_engine.cli import main as cli_main, run as cli_run
from risk_engine.config import (
    DEFAULT_WEIGHTS,
    PriorityThresholds,
    RiskEngineConfig,
    ScoringWeights,
    load_config_object,
    parse_weights_arg,
    weights_fingerprint,
)
from risk_engine.scorer import (
    ACCESSIBILITY_VALUES,
    ACCESSIBILITY_DASHBOARD_MAP,
    ConfigError,
    DataQualityWarning,
    InputValidationError,
    ZoneDataQualityAssessment,
    ZoneRiskRecord,
    _natural_sort_key,
    _priority_label,
    assess_zone_data_quality,
    calculate_zone_risk,
    classify_risk_score,
    compute_score_breakdown,
    export_dashboard,
    load_config,
    load_zones,
    records_to_dict,
    score_zones,
    validate_config,
)
from risk_engine.sensitivity import (
    DEFAULT_SENSITIVITY_SCENARIOS,
    ScenarioComparison,
    SensitivityAnalysisResult,
    SensitivityScenario,
    ZoneSensitivityRecord,
    analyze_ranking_sensitivity,
    compute_kendall_tau as sens_compute_kendall_tau,
)
MODULE_ROOT = pathlib.Path(__file__).parent.parent
REAL_ZONES_PATH = MODULE_ROOT.parent / "flood_analysis" / "output" / "zones.json"
DEFAULT_CONFIG_PATH = MODULE_ROOT / "config" / "weights.json"

import importlib.util

def _load_tool_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_sens_path = MODULE_ROOT / "tools" / "sensitivity.py"
if not _sens_path.exists():
    _sens_path = MODULE_ROOT.parent.parent / "tools" / "sensitivity.py"
_sens_mod = _load_tool_module("sensitivity", _sens_path)
compute_kendall_tau = _sens_mod.compute_kendall_tau
run_sensitivity_analysis = _sens_mod.run_sensitivity_analysis

_calib_path = MODULE_ROOT / "tools" / "calibrate.py"
if not _calib_path.exists():
    _calib_path = MODULE_ROOT.parent.parent / "tools" / "calibrate.py"
_calib_mod = _load_tool_module("calibrate", _calib_path)
analyze_calibration = _calib_mod.analyze_calibration


@pytest.fixture()
def default_config() -> dict[str, Any]:
    return load_config(DEFAULT_CONFIG_PATH)


def _make_zone(**kwargs) -> dict[str, Any]:
    """Return a minimal valid zone dict; keyword args override defaults."""
    base = {
        "zone_id": "zone-001",
        "bbox": [7.0, 50.5, 7.01, 50.51],
        "centroid": [7.005, 50.505],
        "flooded_percent": 10.0,
        "flooded_area_m2": 5000.0,
        "total_buildings": 20,
        "exposed_buildings": 5,
        "road_length_m": 400.0,
        "flooded_road_length_m": 100.0,
        "accessibility": "PARTIAL",
    }
    base.update(kwargs)
    return base


def _make_zones_doc(*zones) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "source": "test",
        "crs": "EPSG:4326",
        "zones": list(zones),
    }


def _write_zones(tmp_path: pathlib.Path, *zones) -> pathlib.Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "zones.json"
    p.write_text(json.dumps(_make_zones_doc(*zones)), encoding="utf-8")
    return p


# ===========================================================================
# 1. Config loading & Configuration Validation Rules
# ===========================================================================

class TestConfigLoadingAndValidation:
    def test_default_config_loads(self, default_config):
        assert "scoring" in default_config
        assert "priority_thresholds" in default_config
        assert default_config.get("config_version") == "1.0"

    def test_weights_sum_to_one(self, default_config):
        weights = default_config["scoring"]["weights"]
        total = sum(v for k, v in weights.items() if not k.startswith("_"))
        assert math.isclose(total, 1.0, rel_tol=1e-6), f"Weights sum to {total}"

    def test_isolation_scores_in_range(self, default_config):
        for cat, val in default_config["scoring"]["isolation_score"].items():
            if cat.startswith("_"):
                continue
            assert 0.0 <= val <= 1.0, f"isolation_score[{cat!r}] = {val} out of [0,1]"

    def test_all_accessibility_values_covered(self, default_config):
        iso = default_config["scoring"]["isolation_score"]
        for cat in ACCESSIBILITY_VALUES:
            assert cat in iso, f"Missing isolation_score entry for '{cat}'"

    def test_normalization_ceilings_positive(self, default_config):
        norms = default_config["scoring"]["normalization"]
        for k, v in norms.items():
            if not k.startswith("_"):
                assert v > 0, f"Normalisation ceiling '{k}' must be > 0"

    def test_missing_config_file_raises(self, tmp_path):
        with pytest.raises((ConfigError, FileNotFoundError)):
            load_config(tmp_path / "nonexistent.json")

    def test_weight_sum_mismatch_raises(self, tmp_path, default_config):
        cfg = json.loads(json.dumps(default_config))
        cfg["scoring"]["weights"]["flood_percent"] += 0.5
        p = tmp_path / "bad_weights.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ConfigError, match="sum to 1.0"):
            load_config(p)

    def test_config_loading_independent_of_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert cfg.get("config_version") == "1.0"
        assert "weights" in cfg["scoring"]

    def test_config_missing_scoring_section_raises(self):
        with pytest.raises(ConfigError, match="missing 'scoring'"):
            validate_config({"priority_thresholds": {}})

    def test_config_missing_weights_section_raises(self):
        with pytest.raises(ConfigError, match="missing 'scoring.weights'"):
            validate_config({"scoring": {}})

    def test_config_missing_weight_key_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        del cfg["scoring"]["weights"]["flood_percent"]
        with pytest.raises(ConfigError, match="missing required keys"):
            validate_config(cfg)

    def test_config_optional_exposure_fraction_defaults(self, default_config):
        cfg = copy.deepcopy(default_config)
        del cfg["scoring"]["weights"]["exposure_fraction"]
        validated = validate_config(cfg)
        assert validated["scoring"]["weights"].get("exposure_fraction", 0.0) == 0.0

    def test_config_extra_weight_key_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["weights"]["extra_metric"] = 0.0
        with pytest.raises(ConfigError, match="unexpected extra"):
            validate_config(cfg)

    def test_config_negative_weight_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["weights"]["flood_percent"] = -0.1
        cfg["scoring"]["weights"]["exposure"] = 0.85
        with pytest.raises(ConfigError, match="non-negative"):
            validate_config(cfg)

    def test_config_non_numeric_weight_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["weights"]["flood_percent"] = True  # boolean check
        with pytest.raises(ConfigError, match="finite number"):
            validate_config(cfg)

    def test_config_missing_normalization_ceiling_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        del cfg["scoring"]["normalization"]["flood_percent_max"]
        with pytest.raises(ConfigError, match="missing required ceiling"):
            validate_config(cfg)

    def test_config_non_positive_normalization_ceiling_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["normalization"]["flood_percent_max"] = 0.0
        with pytest.raises(ConfigError, match="positive finite number"):
            validate_config(cfg)

    def test_config_missing_isolation_score_category_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        del cfg["scoring"]["isolation_score"]["BLOCKED"]
        with pytest.raises(ConfigError, match="missing required entry for 'BLOCKED'"):
            validate_config(cfg)

    def test_config_isolation_score_out_of_range_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["isolation_score"]["BLOCKED"] = 1.5
        with pytest.raises(ConfigError, match=r"\[0\.0, 1\.0\]"):
            validate_config(cfg)

    def test_config_isolation_ordering_accessible_partial_blocked_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["isolation_score"]["ACCESSIBLE"] = 0.8
        cfg["scoring"]["isolation_score"]["PARTIAL"] = 0.5
        with pytest.raises(ConfigError, match="Isolation ordering constraint violated"):
            validate_config(cfg)

    def test_config_isolation_ordering_unknown_partial_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["isolation_score"]["UNKNOWN"] = 0.2  # less than PARTIAL 0.5
        with pytest.raises(ConfigError, match="Isolation ordering constraint violated"):
            validate_config(cfg)

    def test_config_priority_thresholds_missing_key_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        del cfg["priority_thresholds"]["CRITICAL"]
        with pytest.raises(ConfigError, match="missing 'CRITICAL'"):
            validate_config(cfg)

    def test_config_priority_thresholds_ordering_raises(self, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["priority_thresholds"]["CRITICAL"] = 40
        cfg["priority_thresholds"]["HIGH"] = 50
        with pytest.raises(ConfigError, match="Priority thresholds ordering violated"):
            validate_config(cfg)

    def test_comment_inside_weights_does_not_crash(self, default_config, tmp_path):
        cfg = copy.deepcopy(default_config)
        cfg["scoring"]["weights"]["_comment"] = "Comment explaining weights"
        validated = validate_config(cfg)
        assert "_comment" not in validated["scoring"]["weights"]
        p = _write_zones(tmp_path, _make_zone())
        doc, warnings = load_zones(p)
        records = score_zones(doc, validated, warnings)
        output = records_to_dict(records, warnings, doc, validated)
        assert "_comment" not in output["scoring_config"]["weights"]


# ===========================================================================
# 2. Input Loading, Validation & Type Checks
# ===========================================================================

class TestInputLoadingAndValidation:
    def test_valid_zones_doc_loads(self, tmp_path, default_config):
        p = _write_zones(tmp_path, _make_zone())
        doc, warnings = load_zones(p)
        assert len(doc["zones"]) == 1
        assert warnings == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(InputValidationError):
            load_zones(tmp_path / "not_there.json")

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(InputValidationError):
            load_zones(p)

    def test_missing_zones_key_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
        with pytest.raises(InputValidationError):
            load_zones(p)

    def test_non_list_zones_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"zones": "not a list"}), encoding="utf-8")
        with pytest.raises(InputValidationError):
            load_zones(p)

    def test_empty_zones_list_is_valid(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"zones": []}), encoding="utf-8")
        doc, warnings = load_zones(p)
        assert doc["zones"] == []

    def test_duplicate_zone_id_raises(self, tmp_path):
        p = _write_zones(tmp_path, _make_zone(zone_id="zone-001"), _make_zone(zone_id="zone-001"))
        with pytest.raises(InputValidationError, match="Duplicate zone_id"):
            load_zones(p)

    def test_null_flooded_area_m2_becomes_none_with_partial_scoring(self, tmp_path, default_config):
        p = _write_zones(tmp_path, _make_zone(flooded_area_m2=None))
        doc, warnings = load_zones(p)
        assert doc["zones"][0]["flooded_area_m2"] is None
        records = score_zones(doc, default_config, warnings)
        assert records[0].score_basis == "partial"
        assert records[0].omitted_components == ["flood_area_density"]

    def test_unknown_accessibility_becomes_warning(self, tmp_path):
        p = _write_zones(tmp_path, _make_zone(accessibility="IMPASSABLE"))
        doc, warnings = load_zones(p)
        assert doc["zones"][0]["accessibility"] == "UNKNOWN"
        assert any(w.field == "accessibility" for w in warnings)

    def test_unknown_accessibility_produces_exactly_one_warning(self, tmp_path, default_config):
        p = _write_zones(tmp_path, _make_zone(accessibility="UNKNOWN"))
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        acc_warns = [w for w in records[0].warnings if "accessibility" in w.lower()]
        assert len(acc_warns) == 1

    def test_flooded_percent_out_of_range_clamped_with_warning(self, tmp_path):
        p = _write_zones(tmp_path, _make_zone(flooded_percent=150.0))
        doc, warnings = load_zones(p)
        assert doc["zones"][0]["flooded_percent"] == 100.0
        assert any(w.field == "flooded_percent" for w in warnings)

    def test_missing_required_field_raises(self, tmp_path):
        zone = _make_zone()
        del zone["exposed_buildings"]
        p = _write_zones(tmp_path, zone)
        with pytest.raises(InputValidationError, match="exposed_buildings"):
            load_zones(p)

    def test_non_object_in_zones_array_raises(self, tmp_path):
        p = tmp_path / "zones.json"
        p.write_text(json.dumps({"zones": ["a string"]}), encoding="utf-8")
        with pytest.raises(InputValidationError):
            load_zones(p)

    def test_integral_float_exposure_accepted(self, tmp_path):
        p = _write_zones(tmp_path, _make_zone(exposed_buildings=5.0))
        doc, warnings = load_zones(p)
        assert isinstance(doc["zones"][0]["exposed_buildings"], int)
        assert doc["zones"][0]["exposed_buildings"] == 5

    def test_non_integral_float_exposure_raises(self, tmp_path):
        p = _write_zones(tmp_path, _make_zone(exposed_buildings=5.3))
        with pytest.raises(InputValidationError, match="non-integral float"):
            load_zones(p)

    def test_booleans_in_numeric_fields_raise(self, tmp_path):
        # Python bool is subclass of int; must be strictly rejected
        for field, val in [
            ("flooded_percent", True),
            ("exposed_buildings", False),
            ("road_length_m", True),
            ("flooded_road_length_m", False),
            ("total_buildings", True),
        ]:
            zone = _make_zone(**{field: val})
            p = _write_zones(tmp_path, zone)
            with pytest.raises(InputValidationError, match=field):
                load_zones(p)

    def test_nan_inf_numeric_fields_raise(self, tmp_path):
        for bad_val in (float("nan"), float("inf"), float("-inf")):
            p = _write_zones(tmp_path, _make_zone(flooded_percent=bad_val))
            with pytest.raises(InputValidationError, match="flooded_percent"):
                load_zones(p)

    def test_invalid_centroid_and_bbox_handled_with_warnings(self, tmp_path):
        zone = _make_zone(
            centroid=[7.0],  # expected length 2
            bbox=[7.0, 50.0, True, 50.1],  # boolean inside coordinates
        )
        p = _write_zones(tmp_path, zone)
        doc, warnings = load_zones(p)
        assert doc["zones"][0]["centroid"] == []
        assert doc["zones"][0]["bbox"] == []
        warn_fields = {w.field for w in warnings}
        assert "centroid" in warn_fields
        assert "bbox" in warn_fields

    def test_negative_exposure_strict_vs_warn_zero(self, tmp_path):
        zone = _make_zone(exposed_buildings=-5)
        p = _write_zones(tmp_path, zone)
        # Default: strict failure
        with pytest.raises(InputValidationError, match="negative exposure"):
            load_zones(p)
        # Configured: on_negative_exposure="warn_zero"
        cfg = {"data_quality": {"on_negative_exposure": "warn_zero"}}
        doc, warnings = load_zones(p, config=cfg)
        assert doc["zones"][0]["exposed_buildings"] == 0
        assert any(w.field == "exposed_buildings" for w in warnings)

    def test_cross_field_road_and_building_overflows(self, tmp_path, default_config):
        zone = _make_zone(
            road_length_m=100.0,
            flooded_road_length_m=150.0,
            total_buildings=10,
            exposed_buildings=15,
        )
        p = _write_zones(tmp_path, zone)
        doc, warnings = load_zones(p)
        warn_issues = [w.issue for w in warnings]
        assert any("exceeds total road_length_m" in issue for issue in warn_issues)
        assert any("exceeds total_buildings" in issue for issue in warn_issues)

        # Ensure priority is not silently compromised and component clamped to 1.0
        records = score_zones(doc, default_config, warnings)
        assert records[0].exposure_fraction_component == 1.0

    def test_negative_road_and_building_lengths_warn_and_clamped(self, tmp_path):
        zone = _make_zone(
            road_length_m=-50.0,
            flooded_road_length_m=-10.0,
            total_buildings=-5,
        )
        p = _write_zones(tmp_path, zone)
        doc, warnings = load_zones(p)
        assert doc["zones"][0]["road_length_m"] == 0.0
        assert doc["zones"][0]["flooded_road_length_m"] == 0.0
        assert doc["zones"][0]["total_buildings"] == 0
        fields = {w.field for w in warnings}
        assert {"road_length_m", "flooded_road_length_m", "total_buildings"}.issubset(fields)


# ===========================================================================
# 3. Reasons & Explanations
# ===========================================================================

class TestReasonsAndExplanations:
    def test_zero_road_length_reasons_never_claim_100_percent(self, tmp_path, default_config):
        # BLOCKED with 0 road length
        zone_blocked = _make_zone(
            zone_id="zone-b",
            road_length_m=0.0,
            flooded_road_length_m=0.0,
            accessibility="BLOCKED",
        )
        # PARTIAL with 0 road length
        zone_partial = _make_zone(
            zone_id="zone-p",
            road_length_m=0.0,
            flooded_road_length_m=0.0,
            accessibility="PARTIAL",
        )
        p = _write_zones(tmp_path, zone_blocked, zone_partial)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)

        for r in records:
            all_reasons = " ".join(r.reasons)
            assert "No road length recorded; cannot compute % flooded" in all_reasons
            assert "100% flooded" not in all_reasons


# ===========================================================================
# 4. Scoring, Ranking & Determinism
# ===========================================================================

class TestScoringAndRanking:
    def test_score_in_bounds(self, tmp_path, default_config):
        p = _write_zones(tmp_path, _make_zone())
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        assert 0.0 <= records[0].score <= 100.0

    def test_score_is_deterministic(self, tmp_path, default_config):
        z1 = _make_zone(zone_id="z1", exposed_buildings=10, flooded_percent=5.0)
        z2 = _make_zone(zone_id="z2", exposed_buildings=40, flooded_percent=25.0)
        p1 = _write_zones(tmp_path / "run1", z1, z2)
        p2 = _write_zones(tmp_path / "run2", z2, z1)
        doc1, w1 = load_zones(p1)
        doc2, w2 = load_zones(p2)
        r1 = score_zones(doc1, default_config, w1)
        r2 = score_zones(doc2, default_config, w2)
        assert [r.zone_id for r in r1] == [r.zone_id for r in r2]
        assert [r.score for r in r1] == [r.score for r in r2]
        assert [r.reasons for r in r1] == [r.reasons for r in r2]

    def test_high_flood_percent_zero_exposure(self, tmp_path, default_config):
        z = _make_zone(flooded_percent=25.0, exposed_buildings=0)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        assert any("exposed_buildings=0" in w for w in records[0].warnings)

    def test_higher_exposure_raises_score(self, tmp_path, default_config):
        z_low = _make_zone(zone_id="z-low", exposed_buildings=2)
        z_high = _make_zone(zone_id="z-high", exposed_buildings=50)
        p = _write_zones(tmp_path, z_low, z_high)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        by_id = {r.zone_id: r for r in records}
        assert by_id["z-high"].score > by_id["z-low"].score

    def test_blocked_accessibility_raises_score_vs_accessible(self, tmp_path, default_config):
        z_acc = _make_zone(zone_id="z-acc", accessibility="ACCESSIBLE")
        z_blk = _make_zone(zone_id="z-blk", accessibility="BLOCKED")
        p = _write_zones(tmp_path, z_acc, z_blk)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        by_id = {r.zone_id: r for r in records}
        assert by_id["z-blk"].score > by_id["z-acc"].score

    def test_zero_exposure_zero_flood_gives_low_or_medium_score(self, tmp_path, default_config):
        z = _make_zone(flooded_percent=0.0, exposed_buildings=0, flooded_area_m2=0.0, accessibility="ACCESSIBLE")
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        record = score_zones(doc, default_config, warnings)[0]
        assert record.score == 0.0
        assert record.priority == "LOW"

    def test_max_exposure_max_flood_gives_high_score(self, tmp_path, default_config):
        z = _make_zone(
            flooded_percent=100.0,
            exposed_buildings=200,
            flooded_area_m2=50000.0,
            accessibility="BLOCKED",
            total_buildings=200,
        )
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        record = score_zones(doc, default_config, warnings)[0]
        assert record.score == 100.0
        assert record.priority == "CRITICAL"

    def test_score_capped_at_100(self, tmp_path, default_config):
        z = _make_zone(
            flooded_percent=100.0,
            exposed_buildings=500,
            flooded_area_m2=100000.0,
            accessibility="BLOCKED",
        )
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        record = score_zones(doc, default_config, warnings)[0]
        assert record.score == 100.0

    def test_ranking_is_descending(self, tmp_path, default_config):
        zones = [
            _make_zone(zone_id="z1", exposed_buildings=5),
            _make_zone(zone_id="z2", exposed_buildings=60),
            _make_zone(zone_id="z3", exposed_buildings=20),
        ]
        p = _write_zones(tmp_path, *zones)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        scores = [r.score for r in records]
        assert scores == sorted(scores, reverse=True)

    def test_rank_values_are_sequential(self, tmp_path, default_config):
        zones = [_make_zone(zone_id=f"z{i}", exposed_buildings=i * 5) for i in range(5)]
        p = _write_zones(tmp_path, *zones)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        assert [r.rank for r in records] == [1, 2, 3, 4, 5]

    def test_natural_sort_tie_ordering(self, tmp_path, default_config):
        # Two identical zones where zone-2 should precede zone-10
        z10 = _make_zone(zone_id="zone-10", exposed_buildings=10)
        z2 = _make_zone(zone_id="zone-2", exposed_buildings=10)
        p = _write_zones(tmp_path, z10, z2)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        assert records[0].zone_id == "zone-2"
        assert records[1].zone_id == "zone-10"
        assert records[0].rank == 1
        assert records[1].rank == 2

    def test_tie_breaking_raw_score_vs_exposed_vs_flood_percent(self, tmp_path, default_config):
        # Tied rounded score, but higher exposed buildings
        z_a = _make_zone(zone_id="zone-a", exposed_buildings=25, flooded_percent=5.0)
        z_b = _make_zone(zone_id="zone-b", exposed_buildings=10, flooded_percent=20.0)
        p = _write_zones(tmp_path, z_a, z_b)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        # All receive distinct sequential ranks
        assert len({r.rank for r in records}) == 2
        assert [r.rank for r in records] == [1, 2]

    def test_empty_input_returns_empty_list(self, tmp_path, default_config):
        p = tmp_path / "zones.json"
        p.write_text(json.dumps({"zones": []}), encoding="utf-8")
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        assert records == []


# ===========================================================================
# 5. Missing Flood Area & Partial Scoring
# ===========================================================================

class TestPartialScoring:
    def test_null_area_when_flooded_percent_zero_scores_full(self, tmp_path, default_config):
        """When flooded_percent == 0 and flooded_area_m2 is null, score as 0 without dropping component."""
        z = _make_zone(
            flooded_percent=0.0,
            exposed_buildings=10,
            accessibility="PARTIAL",
            total_buildings=20,
            flooded_area_m2=None,
        )
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        rec = records[0]
        assert rec.score_basis == "full"
        assert rec.omitted_components == []
        assert rec.flood_area_component == 0.0

    def test_null_area_partial_score_renormalization(self, tmp_path, default_config):
        """When flooded_percent > 0 and flooded_area_m2 is null, drop component and renormalize."""
        z = _make_zone(
            flooded_percent=15.0,
            exposed_buildings=30,
            accessibility="PARTIAL",
            total_buildings=50,
            flooded_area_m2=None,
        )
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        rec = records[0]

        assert rec.score_basis == "partial"
        assert rec.omitted_components == ["flood_area_density"]
        assert rec.flood_area_component == 0.0

        # Verify weights were renormalized
        weights = default_config["scoring"]["weights"]
        active_w = {k: v for k, v in weights.items() if not k.startswith("_") and k != "flood_area_density"}
        w_sum = sum(active_w.values())
        norm_w = {k: v / w_sum for k, v in active_w.items()}

        norms = default_config["scoring"]["normalization"]
        iso = default_config["scoring"]["isolation_score"]

        exp_raw = (
            norm_w["flood_percent"] * min(15.0 / norms["flood_percent_max"], 1.0)
            + norm_w["exposure"] * min(30 / norms["exposed_buildings_max"], 1.0)
            + norm_w["isolation"] * iso["PARTIAL"]
            + norm_w.get("exposure_fraction", 0.0) * (30 / 50)
        )
        assert math.isclose(rec.raw_score, exp_raw, rel_tol=1e-5)

    def test_null_area_warning_suppression(self, tmp_path, default_config):
        cfg = copy.deepcopy(default_config)
        cfg["data_quality"]["warn_on_null_flooded_area_m2"] = False
        z = _make_zone(flooded_percent=10.0, flooded_area_m2=None)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p, config=cfg)
        records = score_zones(doc, cfg, warnings)
        rec = records[0]
        assert rec.score_basis == "partial"
        assert not any("flooded_area_m2" in w for w in rec.warnings)


# ===========================================================================
# 6. Priority Labels & Thresholds
# ===========================================================================

class TestPriorityLabels:
    def test_critical_label(self, default_config):
        t = default_config["priority_thresholds"]
        assert _priority_label(t["CRITICAL"], t) == "CRITICAL"
        assert _priority_label(t["CRITICAL"] + 5, t) == "CRITICAL"

    def test_high_label(self, default_config):
        t = default_config["priority_thresholds"]
        assert _priority_label(t["HIGH"], t) == "HIGH"
        assert _priority_label(t["CRITICAL"] - 0.1, t) == "HIGH"

    def test_medium_label(self, default_config):
        t = default_config["priority_thresholds"]
        assert _priority_label(t["MEDIUM"], t) == "MEDIUM"
        assert _priority_label(t["HIGH"] - 0.1, t) == "MEDIUM"

    def test_low_label(self, default_config):
        t = default_config["priority_thresholds"]
        assert _priority_label(t["LOW"], t) == "LOW"
        assert _priority_label(t["MEDIUM"] - 0.1, t) == "LOW"


# ===========================================================================
# 7. Output Schema, Metadata & JSON Constraints
# ===========================================================================

class TestOutputSchemaAndContract:
    def test_output_has_required_top_level_keys(self, tmp_path, default_config):
        p = _write_zones(tmp_path, _make_zone())
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        output = records_to_dict(records, warnings, doc, default_config)

        required_keys = {
            "schema_version", "module", "module_version", "generated_at",
            "disclaimer", "source_metadata", "scoring_config", "summary",
            "data_quality_warnings", "ranked_zones",
        }
        assert required_keys.issubset(set(output.keys()))
        assert output["schema_version"] == "1.1"
        assert "config_version" in output["scoring_config"]
        assert "config_hash_sha256" in output["source_metadata"]
        assert "input_file_sha256" in output["source_metadata"]

    def test_ranked_zones_have_required_fields(self, tmp_path, default_config):
        p = _write_zones(tmp_path, _make_zone())
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        output = records_to_dict(records, warnings, doc, default_config)

        required_zone_keys = {
            "rank", "zone_id", "score", "priority", "score_basis",
            "omitted_components", "reasons", "warnings", "score_components",
            "inputs", "geometry",
        }
        for z in output["ranked_zones"]:
            assert required_zone_keys.issubset(set(z.keys()))

    def test_output_is_json_serialisable_and_rejects_constants(self, tmp_path, default_config):
        p = _write_zones(tmp_path, _make_zone())
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        output = records_to_dict(records, warnings, doc, default_config)
        serialised = json.dumps(output, allow_nan=False)

        def reject_constant(c):
            raise ValueError(f"Non-standard constant found: {c}")

        reloaded = json.loads(serialised, parse_constant=reject_constant)
        assert reloaded["ranked_zones"][0]["zone_id"] == "zone-001"

    def test_crs_passthrough_never_invents_epsg4326(self, tmp_path, default_config):
        # 1. Custom CRS
        p_custom = tmp_path / "custom.json"
        p_custom.write_text(json.dumps({"crs": "EPSG:32632", "zones": [_make_zone()]}), encoding="utf-8")
        doc, warnings = load_zones(p_custom)
        out = records_to_dict(score_zones(doc, default_config, warnings), warnings, doc, default_config)
        assert out["ranked_zones"][0]["geometry"]["crs"] == "EPSG:32632"

        # 2. Missing CRS -> 'unknown'
        p_nocrs = tmp_path / "nocrs.json"
        p_nocrs.write_text(json.dumps({"zones": [_make_zone()]}), encoding="utf-8")
        doc, warnings = load_zones(p_nocrs)
        out = records_to_dict(score_zones(doc, default_config, warnings), warnings, doc, default_config)
        assert out["ranked_zones"][0]["geometry"]["crs"] == "unknown"

    def test_disclaimer_hierarchy(self, tmp_path, default_config):
        # 1. Config disclaimer_context
        cfg = copy.deepcopy(default_config)
        cfg["disclaimer_context"] = "Custom Event 2026"
        p = _write_zones(tmp_path, _make_zone())
        doc, warnings = load_zones(p)
        out = records_to_dict(score_zones(doc, cfg, warnings), warnings, doc, cfg)
        assert "Custom Event 2026" in out["disclaimer"]

        # 2. Input document context
        doc["context"] = "Flood Inundation Exercise"
        out2 = records_to_dict(score_zones(doc, default_config, warnings), warnings, doc, default_config)
        assert "Flood Inundation Exercise" in out2["disclaimer"]

        # 3. Generic fallback
        doc_generic = {"zones": [_make_zone()]}
        out3 = records_to_dict(score_zones(doc_generic, default_config, warnings), warnings, doc_generic, default_config)
        assert "applied to flood analysis labels." in out3["disclaimer"]

    def test_custom_weights_change_score(self, tmp_path, default_config):
        z = _make_zone(flooded_percent=10.0, exposed_buildings=50)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec_default = score_zones(doc, default_config, warnings)[0]

        cfg_custom = copy.deepcopy(default_config)
        cfg_custom["scoring"]["weights"]["flood_percent"] = 0.05
        cfg_custom["scoring"]["weights"]["exposure"] = 0.70
        cfg_custom["scoring"]["weights"]["isolation"] = 0.15
        cfg_custom["scoring"]["weights"]["flood_area_density"] = 0.10
        cfg_custom["scoring"]["weights"]["exposure_fraction"] = 0.0
        rec_custom = score_zones(doc, cfg_custom, warnings)[0]

        assert rec_custom.score != rec_default.score


# ===========================================================================
# 8. Dashboard Export Tests
# ===========================================================================

class TestDashboardExport:
    def test_dashboard_export_ring_closed_and_lng_lat_order(self, default_config):
        z = _make_zone(bbox=[7.123, 50.456, 7.234, 50.567])
        doc = _make_zones_doc(z)
        records = score_zones(doc, default_config, [])
        out = records_to_dict(records, [], doc, default_config)
        dash = export_dashboard(out, doc)
        assert len(dash["zones"]) == 1
        zone = dash["zones"][0]
        coords = zone["geometry"]["coordinates"]
        assert len(coords) == 1
        ring = coords[0]
        assert len(ring) == 5
        assert ring[0] == ring[-1]
        assert ring[0] == [7.123, 50.456]
        assert ring[1] == [7.234, 50.456]
        assert ring[2] == [7.234, 50.567]
        assert ring[3] == [7.123, 50.567]
        assert ring[4] == [7.123, 50.456]

    def test_dashboard_export_mapping_table_complete(self):
        expected_mappings = {
            "ACCESSIBLE": "OPEN",
            "PARTIAL": "LIMITED",
            "BLOCKED": "BLOCKED",
            "UNKNOWN": "UNKNOWN",
        }
        for k, v in expected_mappings.items():
            assert ACCESSIBILITY_DASHBOARD_MAP[k] == v
        assert set(ACCESSIBILITY_VALUES).issubset(set(ACCESSIBILITY_DASHBOARD_MAP.keys()))

    def test_dashboard_export_real_data_scores_preserved(self, default_config):
        if not REAL_ZONES_PATH.exists():
            pytest.skip("Real zones.json not available")
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)
        out = records_to_dict(records, warnings, doc, default_config)
        dash = export_dashboard(out, doc)
        by_id = {z["zone_id"]: z for z in dash["zones"]}
        assert by_id["zone-004"]["risk_score"] == 0.5
        assert by_id["zone-026"]["risk_score"] == 0.1

    def test_dashboard_export_study_area_not_hardcoded(self, default_config):
        z = _make_zone()
        doc = _make_zones_doc(z)
        doc["study_area"] = "Ahr Valley Inundation Basin"
        records = score_zones(doc, default_config, [])
        out = records_to_dict(records, [], doc, default_config)
        dash = export_dashboard(out, doc)
        assert dash["study_area"] == "Ahr Valley Inundation Basin"

    def test_cli_format_dashboard(self, tmp_path):
        zones_path = _write_zones(tmp_path, _make_zone())
        out_dir = tmp_path / "dash_out"
        dash_out = cli_run(zones_path, out_dir, output_format="dashboard", data_mode="scenario_exercise")
        assert (out_dir / "zones.json").exists()
        assert not (out_dir / "risk_scores.json").exists()
        assert dash_out["data_mode"] == "scenario_exercise"
        assert dash_out["score_scale"] == "0-100"
        assert dash_out["schema_version"] == "1.1"



# ===========================================================================
# 8. Golden Hand-Computed Score Test
# ===========================================================================

class TestGoldenHandComputed:
    def test_golden_three_zones(self, default_config):
        """Hand-compute exact scores for 3 diverse zones.

        Default weights:
            flood_percent: 0.35, ceiling: 30.0
            exposure: 0.40, ceiling: 75.0
            isolation: 0.15, PARTIAL=0.5, BLOCKED=1.0, ACCESSIBLE=0.0
            flood_area_density: 0.10, ceiling: 15000.0
            exposure_fraction: 0.0

        Zone G1:
            flooded_percent = 15.0 -> component = 15.0 / 30.0 = 0.50
            exposed_buildings = 30 -> component = 30 / 75.0 = 0.40
            isolation = PARTIAL -> component = 0.50
            flood_area_m2 = 7500.0 -> component = 7500 / 15000 = 0.50
            raw_score = 0.35*0.5 + 0.40*0.4 + 0.15*0.5 + 0.10*0.5
                      = 0.175 + 0.160 + 0.075 + 0.050 = 0.460
            score = 46.0 -> priority = HIGH

        Zone G2:
            flooded_percent = 30.0 -> component = 1.00
            exposed_buildings = 75 -> component = 1.00
            isolation = BLOCKED -> component = 1.00
            flood_area_m2 = 15000.0 -> component = 1.00
            raw_score = 1.00 -> score = 100.0 -> priority = CRITICAL

        Zone G3 (Missing flood area -> partial scoring):
            flooded_percent = 0.0 -> component = 0.0
            exposed_buildings = 0 -> component = 0.0
            isolation = ACCESSIBLE -> component = 0.0
            flooded_area_m2 = None -> omitted, remaining weights renormalized
            raw_score = 0.0 -> score = 0.0 -> priority = LOW
        """
        zones = [
            _make_zone(
                zone_id="zone-g1",
                flooded_percent=15.0,
                exposed_buildings=30,
                accessibility="PARTIAL",
                flooded_area_m2=7500.0,
            ),
            _make_zone(
                zone_id="zone-g2",
                flooded_percent=30.0,
                exposed_buildings=75,
                accessibility="BLOCKED",
                flooded_area_m2=15000.0,
            ),
            _make_zone(
                zone_id="zone-g3",
                flooded_percent=0.0,
                exposed_buildings=0,
                accessibility="ACCESSIBLE",
                flooded_area_m2=None,
            ),
        ]
        doc = _make_zones_doc(*zones)
        records = score_zones(doc, default_config, [])
        by_id = {r.zone_id: r for r in records}

        # G2: Rank 1, CRITICAL, 100.0
        assert by_id["zone-g2"].rank == 1
        assert by_id["zone-g2"].score == 100.0
        assert by_id["zone-g2"].priority == "CRITICAL"

        # G1: Rank 2, HIGH, 46.0
        assert by_id["zone-g1"].rank == 2
        assert by_id["zone-g1"].score == 46.0
        assert by_id["zone-g1"].priority == "HIGH"

        # G3: Rank 3, LOW, 0.0, full scoring per Item 4 (flooded_percent == 0 scores 0.0)
        assert by_id["zone-g3"].rank == 3
        assert by_id["zone-g3"].score == 0.0
        assert by_id["zone-g3"].priority == "LOW"
        assert by_id["zone-g3"].score_basis == "full"
        assert by_id["zone-g3"].omitted_components == []


# ===========================================================================
# 9. CLI Tests & Exit Codes (0, 1, 2, 3)
# ===========================================================================

class TestCLI:
    def test_cli_run_writes_output_file(self, tmp_path, default_config):
        zones_path = _write_zones(tmp_path, _make_zone())
        out_dir = tmp_path / "out"
        output = cli_run(zones_path, out_dir)
        assert (out_dir / "risk_scores.json").exists()
        assert len(output["ranked_zones"]) == 1

    def test_cli_run_with_custom_config_changes_score(self, tmp_path, default_config):
        zones_path = _write_zones(tmp_path, _make_zone(flooded_percent=10.0, exposed_buildings=50))
        out_dir_def = tmp_path / "out_def"
        out_def = cli_run(zones_path, out_dir_def)
        score_def = out_def["ranked_zones"][0]["score"]

        custom_cfg = copy.deepcopy(default_config)
        custom_cfg["scoring"]["weights"] = {
            "flood_percent": 0.80,
            "exposure": 0.10,
            "isolation": 0.05,
            "flood_area_density": 0.05,
            "exposure_fraction": 0.0,
        }
        cfg_path = tmp_path / "custom_weights.json"
        cfg_path.write_text(json.dumps(custom_cfg), encoding="utf-8")

        out_dir_cust = tmp_path / "out_cust"
        out_cust = cli_run(zones_path, out_dir_cust, config_path=cfg_path)
        score_cust = out_cust["ranked_zones"][0]["score"]

        assert score_cust != score_def

    def test_cli_run_missing_zones_raises(self, tmp_path):
        with pytest.raises(InputValidationError):
            cli_run(tmp_path / "nowhere.json", tmp_path / "out")

    def test_cli_exit_code_0_success(self, tmp_path):
        zones_path = _write_zones(tmp_path, _make_zone())
        out_dir = tmp_path / "out"
        cmd = [sys.executable, "-m", "risk_engine.cli", "--zones", str(zones_path), "--out", str(out_dir)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert "Scored 1 zones" in res.stdout

    def test_cli_exit_code_1_validation_error(self, tmp_path):
        bad_zone = _make_zone(exposed_buildings="five")
        zones_path = _write_zones(tmp_path, bad_zone)
        out_dir = tmp_path / "out"
        cmd = [sys.executable, "-m", "risk_engine.cli", "--zones", str(zones_path), "--out", str(out_dir)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 1
        assert "Input validation failed" in res.stderr

    def test_cli_exit_code_2_config_or_file_error(self, tmp_path):
        zones_path = _write_zones(tmp_path, _make_zone())
        out_dir = tmp_path / "out"
        cmd = [
            sys.executable, "-m", "risk_engine.cli",
            "--zones", str(zones_path),
            "--out", str(out_dir),
            "--config", str(tmp_path / "no_cfg.json"),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 2
        assert "Configuration or file error" in res.stderr

    def test_cli_debug_flag_shows_traceback(self, tmp_path):
        zones_path = _write_zones(tmp_path, _make_zone(flooded_percent="nan"))
        out_dir = tmp_path / "out"
        cmd = [sys.executable, "-m", "risk_engine.cli", "--zones", str(zones_path), "--out", str(out_dir), "--debug"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 1
        assert "Traceback (most recent call last):" in res.stderr

    def test_cli_validates_before_creating_output_dir(self, tmp_path):
        bad_zone = _make_zone(exposed_buildings="five")
        zones_path = _write_zones(tmp_path, bad_zone)
        out_dir = tmp_path / "uncreated_dir"
        with pytest.raises(InputValidationError):
            cli_run(zones_path, out_dir)
        assert not out_dir.exists()

    def test_cli_exit_code_3_unexpected_error(self, tmp_path):
        zones_path = _write_zones(tmp_path, _make_zone())
        out_dir = tmp_path / "out"
        cmd = [
            sys.executable, "-c",
            "import sys, unittest.mock; "
            "from risk_engine import cli; "
            "sys.argv = ['risk_engine', '--zones', sys.argv[1], '--out', sys.argv[2]]; "
            "unittest.mock.patch('risk_engine.cli.run', side_effect=RuntimeError('Simulated unexpected failure')).start(); "
            "cli.main()",
            str(zones_path), str(out_dir)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 3
        assert "Unexpected failure" in res.stderr


# ===========================================================================
# 10. Hypothesis Property-Based Tests
# ===========================================================================

class TestHypothesisProperties:
    @given(
        fp=st.floats(min_value=0.0, max_value=100.0),
        eb=st.integers(min_value=0, max_value=500),
        acc=st.sampled_from(list(ACCESSIBILITY_VALUES)),
        fam=st.one_of(st.none(), st.floats(min_value=0.0, max_value=100000.0)),
        tb=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50)
    def test_hypothesis_score_bounds(self, fp, eb, acc, fam, tb):
        cfg = load_config(DEFAULT_CONFIG_PATH)
        z = _make_zone(
            flooded_percent=fp,
            exposed_buildings=eb,
            accessibility=acc,
            flooded_area_m2=fam,
            total_buildings=tb,
        )
        doc = _make_zones_doc(z)
        records = score_zones(doc, cfg, [])
        assert 0.0 <= records[0].score <= 100.0
        assert not math.isnan(records[0].score)

    @given(
        eb1=st.integers(min_value=0, max_value=50),
        eb2=st.integers(min_value=51, max_value=100),
    )
    @settings(max_examples=30)
    def test_hypothesis_exposure_monotonicity(self, eb1, eb2):
        cfg = load_config(DEFAULT_CONFIG_PATH)
        z1 = _make_zone(zone_id="z1", exposed_buildings=eb1)
        z2 = _make_zone(zone_id="z2", exposed_buildings=eb2)
        doc = _make_zones_doc(z1, z2)
        records = score_zones(doc, cfg, [])
        by_id = {r.zone_id: r for r in records}
        assert by_id["z2"].raw_score >= by_id["z1"].raw_score

    @given(
        fp1=st.floats(min_value=0.0, max_value=40.0),
        fp2=st.floats(min_value=41.0, max_value=100.0),
    )
    @settings(max_examples=30)
    def test_hypothesis_flood_percent_monotonicity(self, fp1, fp2):
        cfg = load_config(DEFAULT_CONFIG_PATH)
        z1 = _make_zone(zone_id="z1", flooded_percent=fp1)
        z2 = _make_zone(zone_id="z2", flooded_percent=fp2)
        doc = _make_zones_doc(z1, z2)
        records = score_zones(doc, cfg, [])
        by_id = {r.zone_id: r for r in records}
        assert by_id["z2"].raw_score >= by_id["z1"].raw_score

    @given(
        fam1=st.floats(min_value=0.0, max_value=5000.0),
        fam2=st.floats(min_value=5001.0, max_value=30000.0),
    )
    @settings(max_examples=30)
    def test_hypothesis_flood_area_monotonicity(self, fam1, fam2):
        cfg = load_config(DEFAULT_CONFIG_PATH)
        z1 = _make_zone(zone_id="z1", flooded_area_m2=fam1)
        z2 = _make_zone(zone_id="z2", flooded_area_m2=fam2)
        doc = _make_zones_doc(z1, z2)
        records = score_zones(doc, cfg, [])
        by_id = {r.zone_id: r for r in records}
        assert by_id["z2"].raw_score >= by_id["z1"].raw_score

    @given(perm=st.permutations(["z1", "z2", "z3", "z4"]))
    @settings(max_examples=24)
    def test_hypothesis_permutation_invariance(self, perm):
        cfg = load_config(DEFAULT_CONFIG_PATH)
        zone_defs = {
            "z1": _make_zone(zone_id="z1", exposed_buildings=5, flooded_percent=5.0),
            "z2": _make_zone(zone_id="z2", exposed_buildings=25, flooded_percent=15.0),
            "z3": _make_zone(zone_id="z3", exposed_buildings=50, flooded_percent=30.0),
            "z4": _make_zone(zone_id="z4", exposed_buildings=75, flooded_percent=40.0),
        }
        ordered = [zone_defs[zid] for zid in perm]
        doc = _make_zones_doc(*ordered)
        records = score_zones(doc, cfg, [])
        ranked_ids = [r.zone_id for r in records]
        # Must always rank in the exact same order regardless of input permutation
        assert ranked_ids == ["z4", "z3", "z2", "z1"]

    @given(
        fp=st.floats(min_value=0.0, max_value=50.0),
        eb=st.integers(min_value=0, max_value=100),
        fam=st.floats(min_value=0.0, max_value=20000.0),
    )
    @settings(max_examples=30)
    def test_hypothesis_isolation_monotonicity(self, fp, eb, fam):
        """Monotonicity invariant: ACCESSIBLE <= PARTIAL <= BLOCKED when other metrics are held constant."""
        cfg = load_config(DEFAULT_CONFIG_PATH)
        z_acc = _make_zone(zone_id="z_acc", flooded_percent=fp, exposed_buildings=eb, flooded_area_m2=fam, accessibility="ACCESSIBLE")
        z_part = _make_zone(zone_id="z_part", flooded_percent=fp, exposed_buildings=eb, flooded_area_m2=fam, accessibility="PARTIAL")
        z_blk = _make_zone(zone_id="z_blk", flooded_percent=fp, exposed_buildings=eb, flooded_area_m2=fam, accessibility="BLOCKED")
        doc = _make_zones_doc(z_acc, z_part, z_blk)
        records = score_zones(doc, cfg, [])
        by_id = {r.zone_id: r for r in records}
        assert by_id["z_acc"].raw_score <= by_id["z_part"].raw_score <= by_id["z_blk"].raw_score
        assert by_id["z_acc"].score <= by_id["z_part"].score <= by_id["z_blk"].score

    @given(
        fp=st.floats(min_value=0.0, max_value=100.0),
        eb=st.integers(min_value=0, max_value=200),
        acc=st.sampled_from(list(ACCESSIBILITY_VALUES)),
        fam=st.one_of(st.none(), st.floats(min_value=0.0, max_value=50000.0)),
    )
    @settings(max_examples=40)
    def test_hypothesis_score_reconciliation(self, fp, eb, acc, fam):
        """Mathematical invariant: displayed score components always reconcile with final score."""
        cfg = load_config(DEFAULT_CONFIG_PATH)
        z = _make_zone(flooded_percent=fp, exposed_buildings=eb, accessibility=acc, flooded_area_m2=fam)
        doc = _make_zones_doc(z)
        records = score_zones(doc, cfg, [])
        rec = records[0]
        sb = rec.score_breakdown
        assert sb["reconciliation"]["reconciled"] is True
        assert abs(sb["reconciliation"]["sum_weighted_contributions"] - rec.raw_score) < 1e-5
        assert abs(rec.score - sb["reconciliation"]["sum_points"]) <= 0.08

    @given(
        w1=st.floats(min_value=0.01, max_value=1000.0),
        w2=st.floats(min_value=0.01, max_value=1000.0),
        w3=st.floats(min_value=0.01, max_value=1000.0),
        w4=st.floats(min_value=0.01, max_value=1000.0),
    )
    @settings(max_examples=30)
    def test_hypothesis_unnormalized_weights_scaling(self, w1, w2, w3, w4):
        """Scaling invariant: from_unnormalized always scales arbitrary positive weights to sum to 1.0."""
        sw = ScoringWeights.from_unnormalized({
            "flood_percent": w1,
            "exposure": w2,
            "isolation": w3,
            "flood_area_density": w4,
        })
        sw.validate()
        total = sw.flood_percent + sw.exposure + sw.isolation + sw.flood_area_density
        assert math.isclose(total, 1.0, rel_tol=1e-6)

    @given(
        perm_a=st.permutations(["a", "b", "c", "d", "e"]),
        perm_b=st.permutations(["a", "b", "c", "d", "e"]),
    )
    @settings(max_examples=30)
    def test_hypothesis_kendall_tau_bounded(self, perm_a, perm_b):
        """Correlation invariant: Kendall's tau between any two permutations is strictly bounded in [-1.0, 1.0]."""
        tau = sens_compute_kendall_tau(list(perm_a), list(perm_b))
        assert -1.0 <= tau <= 1.0
        assert not math.isnan(tau)


# ===========================================================================
# 11. Sensitivity and Calibration Diagnostic Tool Tests
# ===========================================================================

class TestDiagnosticTools:
    def test_kendall_tau_identical_rankings(self):
        items = ["a", "b", "c", "d", "e"]
        assert compute_kendall_tau(items, items) == 1.0

    def test_kendall_tau_inverted_rankings(self):
        a = ["a", "b", "c", "d"]
        b = ["d", "c", "b", "a"]
        assert compute_kendall_tau(a, b) == -1.0

    def test_sensitivity_baseline_self_comparison(self, tmp_path):
        p = _write_zones(tmp_path, _make_zone(zone_id="z1"), _make_zone(zone_id="z2", exposed_buildings=20))
        self_metrics, results = run_sensitivity_analysis(p)
        assert self_metrics["kendall_tau"] == 1.0
        assert self_metrics["priority_changes"] == 0
        assert len(results) > 0

    def test_sensitivity_perturbs_parameters(self, tmp_path):
        z1 = _make_zone(zone_id="z1", flooded_percent=20.0, exposed_buildings=5, accessibility="ACCESSIBLE")
        z2 = _make_zone(zone_id="z2", flooded_percent=5.0, exposed_buildings=25, accessibility="PARTIAL")
        p = _write_zones(tmp_path, z1, z2)
        self_metrics, results = run_sensitivity_analysis(p)
        assert len(results) > 0
        categories = {r["category"] for r in results}
        assert {"Weight", "Isolation", "Threshold"}.issubset(categories)
        deltas = {r["perturbation"] for r in results if r["category"] == "Weight"}
        assert {"-20%", "-10%", "+10%", "+20%"}.issubset(deltas)
        # Verify sensitivity perturbations altered rankings or metrics
        taus = [r["kendall_tau"] for r in results]
        assert any(t < 1.0 for t in taus) or any(r["priority_changes"] > 0 for r in results)

    def test_calibrate_analysis_runs(self, tmp_path):
        p = _write_zones(tmp_path, _make_zone(zone_id="z1"), _make_zone(zone_id="z2", exposed_buildings=20))
        res = analyze_calibration(p)
        assert res["total_zones"] == 2
        assert "flooded_percent" in res["input_stats"]
        assert "score_stats" in res


# ===========================================================================
# 12. Real Module 2 Data Integration Tests
# ===========================================================================

class TestRealDataIntegration:
    @pytest.fixture(autouse=True)
    def check_real_data_requirement(self):
        if not REAL_ZONES_PATH.exists():
            if os.environ.get("REQUIRE_REAL_DATA") == "1":
                pytest.fail(f"REQUIRE_REAL_DATA=1 set but {REAL_ZONES_PATH} not found")
            pytest.skip(f"Module 2 zones.json not found at {REAL_ZONES_PATH}")

    def test_real_zones_score_all_zones_count_derived(self, default_config):
        doc, warnings = load_zones(REAL_ZONES_PATH)
        expected_count = len(doc["zones"])
        records = score_zones(doc, default_config, warnings)
        assert len(records) == expected_count

    def test_real_zones_all_scores_in_bounds(self, default_config):
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)
        for r in records:
            assert 0.0 <= r.score <= 100.0

    def test_real_zones_ranking_is_descending(self, default_config):
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)
        scores = [r.score for r in records]
        assert scores == sorted(scores, reverse=True)

    def test_real_zones_cli_run_derived_counts(self, tmp_path):
        doc, _ = load_zones(REAL_ZONES_PATH)
        expected_count = len(doc["zones"])
        out_dir = tmp_path / "out"
        output = cli_run(REAL_ZONES_PATH, out_dir)
        assert output["summary"]["total_zones"] == expected_count
        assert sum(output["summary"]["priority_counts"].values()) == expected_count

    def test_real_zones_zone_002_score_and_rank(self, default_config):
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)
        by_id = {r.zone_id: r for r in records}
        assert "zone-002" in by_id
        z2 = by_id["zone-002"]
        assert z2.score == 53.4
        assert z2.priority == "HIGH"
        assert z2.rank == 2

    def test_real_zones_zone_018_and_zone_033_tie_breaking(self, default_config):
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)
        by_id = {r.zone_id: r for r in records}
        z18 = by_id["zone-018"]
        z33 = by_id["zone-033"]
        assert z18.score == z33.score == 7.5
        assert z18.raw_score == z33.raw_score == 0.075
        assert z18.exposed_buildings == z33.exposed_buildings == 0
        assert z18.flooded_percent == z33.flooded_percent == 0.0
        # Natural sort breaks the tie: zone-018 precedes zone-033
        assert z18.rank == 17
        assert z33.rank == 18


# ===========================================================================
# 13. Data Quality, Confidence Assessment & Missing Data Handling
# ===========================================================================

class TestDataConfidenceAndMissingData:
    def test_complete_and_valid_data_has_high_confidence(self, tmp_path, default_config):
        z = _make_zone()
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        assert len(records) == 1
        rec = records[0]

        assert rec.confidence == "HIGH"
        assert rec.data_quality_status == "VERIFIED"
        assert rec.needs_verification is False
        assert rec.warnings == []
        assert rec.data_quality_issues == []

    def test_legitimate_zero_values_distinguished_from_omitted_data(self, tmp_path, default_config):
        # Case A: Explicit valid zero measurements
        z_valid_zero = _make_zone(
            zone_id="zone-zero",
            flooded_percent=0.0,
            flooded_area_m2=0.0,
            total_buildings=10,
            exposed_buildings=0,
            road_length_m=500.0,
            flooded_road_length_m=0.0,
            accessibility="ACCESSIBLE",
        )
        p_zero = _write_zones(tmp_path, z_valid_zero)
        doc_zero, warnings_zero = load_zones(p_zero)
        rec_zero = score_zones(doc_zero, default_config, warnings_zero)[0]

        assert rec_zero.score == 0.0
        assert rec_zero.priority == "LOW"
        assert rec_zero.confidence == "HIGH"
        assert rec_zero.data_quality_status == "VERIFIED"
        assert rec_zero.needs_verification is False
        assert rec_zero.warnings == []

        # Case B: Omitted optional fields
        z_omitted = {
            "zone_id": "zone-omitted",
            "flooded_percent": 0.0,
            "flooded_area_m2": 0.0,
            "exposed_buildings": 0,
            "accessibility": "ACCESSIBLE",
            "bbox": [7.0, 50.5, 7.01, 50.51],
            "centroid": [7.005, 50.505],
            # total_buildings, road_length_m, flooded_road_length_m omitted
        }
        p_omitted = _write_zones(tmp_path, z_omitted)
        doc_omitted, warnings_omitted = load_zones(p_omitted)
        rec_omitted = score_zones(doc_omitted, default_config, warnings_omitted)[0]

        assert rec_omitted.score == 0.0
        assert rec_omitted.priority == "LOW"
        assert rec_omitted.confidence in ("MEDIUM", "LOW")
        assert rec_omitted.data_quality_status == "INCOMPLETE"
        assert "missing_total_buildings" in rec_omitted.data_quality_issues
        assert "missing_road_length_m" in rec_omitted.data_quality_issues
        # Safety policy: Low risk with incomplete data cannot be assumed safe
        assert rec_omitted.needs_verification is True

    def test_unknown_accessibility_degrades_confidence_and_flags_verification(self, tmp_path, default_config):
        z = _make_zone(accessibility="UNKNOWN")
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.confidence == "MEDIUM"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "INCOMPLETE"
        assert "unknown_accessibility" in rec.data_quality_issues
        acc_warns = [w for w in rec.warnings if "accessibility=UNKNOWN" in w]
        assert len(acc_warns) == 1
        assert rec.isolation_component == default_config["scoring"]["isolation_score"]["UNKNOWN"]

    def test_low_risk_zone_with_unknown_accessibility_cannot_be_assumed_safe(self, tmp_path, default_config):
        z = _make_zone(
            flooded_percent=0.0,
            flooded_area_m2=0.0,
            exposed_buildings=0,
            total_buildings=5,
            road_length_m=0.0,
            flooded_road_length_m=0.0,
            accessibility="UNKNOWN",
        )
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.priority == "LOW"
        assert rec.confidence == "MEDIUM"
        assert rec.needs_verification is True
        assert any("VERIFICATION REQUIRED" in r for r in rec.reasons)

    def test_contradictory_zero_flood_with_exposed_buildings(self, tmp_path, default_config):
        z = _make_zone(flooded_percent=0.0, exposed_buildings=5, total_buildings=10)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.confidence == "LOW"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "CONTRADICTORY"
        assert "contradictory_zero_flood_with_exposed_buildings" in rec.data_quality_issues
        assert any("buildings marked flooded with zero zone flood coverage" in w for w in rec.warnings)

    def test_contradictory_zero_flood_with_flooded_area(self, tmp_path, default_config):
        z = _make_zone(flooded_percent=0.0, flooded_area_m2=2500.0, exposed_buildings=0)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.confidence == "LOW"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "CONTRADICTORY"
        assert "contradictory_zero_flood_with_flooded_area" in rec.data_quality_issues
        assert any("contradictory flood extent measurements" in w for w in rec.warnings)

    def test_contradictory_zero_flood_with_flooded_roads(self, tmp_path, default_config):
        z = _make_zone(
            flooded_percent=0.0,
            exposed_buildings=0,
            road_length_m=400.0,
            flooded_road_length_m=100.0,
        )
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.confidence == "LOW"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "CONTRADICTORY"
        assert "contradictory_zero_flood_with_flooded_roads" in rec.data_quality_issues

    def test_contradictory_positive_flood_with_zero_flooded_area(self, tmp_path, default_config):
        z = _make_zone(flooded_percent=20.0, flooded_area_m2=0.0)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.confidence == "LOW"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "CONTRADICTORY"
        assert "contradictory_positive_flood_zero_area" in rec.data_quality_issues

    def test_contradictory_exposed_buildings_exceed_total(self, tmp_path, default_config):
        z = _make_zone(total_buildings=5, exposed_buildings=15)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.confidence == "LOW"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "CONTRADICTORY"
        assert "exposed_buildings_exceeds_total" in rec.data_quality_issues

    def test_contradictory_flooded_road_exceeds_total_road(self, tmp_path, default_config):
        z = _make_zone(road_length_m=100.0, flooded_road_length_m=200.0)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.confidence == "LOW"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "CONTRADICTORY"
        assert "flooded_road_exceeds_total" in rec.data_quality_issues

    def test_missing_flood_area_partial_scoring_flags_verification(self, tmp_path, default_config):
        z = _make_zone(flooded_percent=15.0, flooded_area_m2=None)
        p = _write_zones(tmp_path, z)
        doc, warnings = load_zones(p)
        rec = score_zones(doc, default_config, warnings)[0]

        assert rec.score_basis == "partial"
        assert rec.confidence == "MEDIUM"
        assert rec.needs_verification is True
        assert rec.data_quality_status == "INCOMPLETE"
        assert "missing_flood_area_partial_scoring" in rec.data_quality_issues

    def test_degraded_clamped_values_assign_low_confidence(self, tmp_path, default_config):
        # 1. Out of range percentage
        z_clamped = _make_zone(flooded_percent=125.0)
        p_clamped = _write_zones(tmp_path, z_clamped)
        doc_c, warnings_c = load_zones(p_clamped)
        rec_c = score_zones(doc_c, default_config, warnings_c)[0]

        assert rec_c.confidence == "LOW"
        assert rec_c.needs_verification is True
        assert rec_c.data_quality_status == "DEGRADED"
        assert "clamped_value" in rec_c.data_quality_issues

        # 2. Negative exposure count under warn_zero
        cfg_warn_zero = copy.deepcopy(default_config)
        cfg_warn_zero["data_quality"]["on_negative_exposure"] = "warn_zero"
        z_neg = _make_zone(exposed_buildings=-3)
        p_neg = _write_zones(tmp_path, z_neg)
        doc_n, warnings_n = load_zones(p_neg, config=cfg_warn_zero)
        rec_n = score_zones(doc_n, cfg_warn_zero, warnings_n)[0]

        assert rec_n.confidence == "LOW"
        assert rec_n.needs_verification is True
        assert rec_n.data_quality_status == "DEGRADED"

    def test_missing_required_measurements_rejected_with_input_validation_error(self, tmp_path):
        # 1. Missing flooded_percent
        z1 = _make_zone()
        del z1["flooded_percent"]
        with pytest.raises(InputValidationError, match="flooded_percent"):
            load_zones(_write_zones(tmp_path / "z1", z1))

        # 2. Missing exposed_buildings
        z2 = _make_zone()
        del z2["exposed_buildings"]
        with pytest.raises(InputValidationError, match="exposed_buildings"):
            load_zones(_write_zones(tmp_path / "z2", z2))

        # 3. Missing accessibility
        z3 = _make_zone()
        del z3["accessibility"]
        with pytest.raises(InputValidationError, match="accessibility"):
            load_zones(_write_zones(tmp_path / "z3", z3))

        # 4. Missing zone_id
        z4 = _make_zone()
        del z4["zone_id"]
        with pytest.raises(InputValidationError, match="zone_id"):
            load_zones(_write_zones(tmp_path / "z4", z4))

        # 5. Non-finite values
        z5 = _make_zone(flooded_percent=float("nan"))
        with pytest.raises(InputValidationError, match="flooded_percent"):
            load_zones(_write_zones(tmp_path / "z5", z5))

    def test_deterministic_confidence_and_verification(self, default_config):
        zones = [
            _make_zone(zone_id="z1"),
            _make_zone(zone_id="z2", accessibility="UNKNOWN"),
            _make_zone(zone_id="z3", flooded_percent=0.0, exposed_buildings=5),
        ]
        doc = _make_zones_doc(*zones)
        recs1 = score_zones(doc, default_config, [])
        recs2 = score_zones(doc, default_config, [])

        for r1, r2 in zip(recs1, recs2):
            assert r1.confidence == r2.confidence
            assert r1.needs_verification == r2.needs_verification
            assert r1.data_quality_status == r2.data_quality_status
            assert r1.data_quality_issues == r2.data_quality_issues
            assert r1.warnings == r2.warnings
            assert r1.reasons == r2.reasons

    def test_score_and_rank_separated_from_confidence(self, default_config):
        # Two zones with identical scoring inputs, but one has missing geometry
        z_high = _make_zone(zone_id="z-high", centroid=[7.0, 50.0], bbox=[7.0, 50.0, 7.1, 50.1])
        z_med = _make_zone(zone_id="z-med", centroid=[], bbox=[])
        doc = _make_zones_doc(z_high, z_med)
        records = score_zones(doc, default_config, [])
        by_id = {r.zone_id: r for r in records}

        # Scoring formula must not be changed because confidence is different
        assert by_id["z-high"].score == by_id["z-med"].score
        assert by_id["z-high"].raw_score == by_id["z-med"].raw_score
        assert by_id["z-high"].priority == by_id["z-med"].priority
        assert by_id["z-high"].confidence == "HIGH"
        assert by_id["z-med"].confidence == "MEDIUM"

    def test_output_schema_and_json_serialization(self, tmp_path, default_config):
        z1 = _make_zone(zone_id="z1")
        z2 = _make_zone(zone_id="z2", accessibility="UNKNOWN")
        p = _write_zones(tmp_path, z1, z2)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        out = records_to_dict(records, warnings, doc, default_config)

        # Check summary confidence counts
        assert "confidence_counts" in out["summary"]
        assert out["summary"]["confidence_counts"]["HIGH"] == 1
        assert out["summary"]["confidence_counts"]["MEDIUM"] == 1
        assert out["summary"]["confidence_counts"]["LOW"] == 0
        assert "verification_needed_count" in out["summary"]
        assert out["summary"]["verification_needed_count"] == 1

        # Check zone fields
        for z in out["ranked_zones"]:
            assert "confidence" in z
            assert z["confidence"] in ("HIGH", "MEDIUM", "LOW")
            assert "needs_verification" in z
            assert isinstance(z["needs_verification"], bool)
            assert "data_quality" in z
            dq = z["data_quality"]
            assert dq["confidence"] == z["confidence"]
            assert dq["needs_verification"] == z["needs_verification"]
            assert "status" in dq
            assert "issues" in dq
            assert "warnings" in dq

        # JSON serializable without non-standard constants
        serialized = json.dumps(out, allow_nan=False)
        reloaded = json.loads(serialized)
        assert len(reloaded["ranked_zones"]) == 2

    def test_dashboard_export_includes_confidence_and_needs_survey(self, tmp_path, default_config):
        z_high = _make_zone(zone_id="z1")
        z_unknown = _make_zone(zone_id="z2", accessibility="UNKNOWN")
        p = _write_zones(tmp_path, z_high, z_unknown)
        doc, warnings = load_zones(p)
        records = score_zones(doc, default_config, warnings)
        out = records_to_dict(records, warnings, doc, default_config)
        dash = export_dashboard(out, doc)

        assert len(dash["zones"]) == 2
        by_id = {z["zone_id"]: z for z in dash["zones"]}

        # z1: HIGH confidence, needs_survey False
        assert by_id["z1"]["confidence"] == "HIGH"
        assert by_id["z1"]["needs_verification"] is False
        assert by_id["z1"]["needs_survey"] is False

        # z2: MEDIUM confidence, needs_survey True
        assert by_id["z2"]["confidence"] == "MEDIUM"
        assert by_id["z2"]["needs_verification"] is True
        assert by_id["z2"]["needs_survey"] is True

    def test_real_module_2_integration_confidence_evaluation(self, default_config):
        if not REAL_ZONES_PATH.exists():
            pytest.skip("Real zones.json not available")
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)
        by_id = {r.zone_id: r for r in records}

        # zone-002: fully complete, high risk
        z2 = by_id["zone-002"]
        assert z2.confidence == "HIGH"
        assert z2.needs_verification is False
        assert z2.data_quality_status == "VERIFIED"

        # zone-018: UNKNOWN accessibility, LOW risk -> requires verification
        z18 = by_id["zone-018"]
        assert z18.priority == "LOW"
        assert z18.confidence == "MEDIUM"
        assert z18.needs_verification is True
        assert "unknown_accessibility" in z18.data_quality_issues
        assert any("VERIFICATION REQUIRED" in r for r in z18.reasons)

        # zone-033: UNKNOWN accessibility, LOW risk -> requires verification
        z33 = by_id["zone-033"]
        assert z33.priority == "LOW"
        assert z33.confidence == "MEDIUM"
        assert z33.needs_verification is True
        assert "unknown_accessibility" in z33.data_quality_issues

        # zone-004: 0.0% flood percent with 1 exposed building -> requires verification
        z4 = by_id["zone-004"]
        assert z4.priority == "LOW"
        assert z4.needs_verification is True
        assert "contradictory_zero_flood_with_exposed_buildings" in z4.data_quality_issues


# ===========================================================================
# 17. Risk-Score Explainability & Auditability Tests (Module 3 Task 2)
# ===========================================================================

class TestRiskScoreExplainability:
    """Tests for score reconciliation, breakdown auditability, and deterministic factor explanations."""

    def test_real_zones_score_reconciliation(self, default_config):
        """Verify mathematical reconciliation across all zones in the real flood analysis dataset."""
        if not REAL_ZONES_PATH.exists():
            pytest.skip("Real zones.json not available")
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)

        assert len(records) > 0
        for r in records:
            b = r.score_breakdown
            assert b is not None, f"Zone {r.zone_id} missing score_breakdown"

            # 1. Structural schema validation
            assert "components" in b
            assert "reconciliation" in b
            assert "primary_driver" in b
            assert "influential_factors" in b
            assert "ranking_factors" in b

            # 2. Mathematical reconciliation checks
            recon = b["reconciliation"]
            assert recon["reconciled"] is True, f"Zone {r.zone_id} failed reconciliation: {recon}"
            assert abs(recon["sum_weighted_contributions"] - r.raw_score) < 1e-5
            assert abs(r.score - recon["sum_points"]) <= 0.08
            assert recon["rounding_difference"] == round(r.score - recon["sum_points"], 2)

            # 3. Component constraints
            for comp_name, comp in b["components"].items():
                assert 0.0 <= comp["normalized_value"] <= 1.0
                assert comp["weight"] >= 0.0
                assert comp["weighted_contribution"] >= 0.0
                assert comp["points"] >= 0.0
                assert 0.0 <= comp["percentage_of_score"] <= 100.0

            # 4. Active weights sum to 1.0
            total_active_weight = sum(c["weight"] for c in b["components"].values())
            assert total_active_weight == pytest.approx(1.0, abs=1e-5)

    def test_golden_zones_explainability_and_drivers(self, default_config):
        """Verify exact component contributions, primary drivers, and factor explanations for G1, G2, G3."""
        zones = [
            _make_zone(
                zone_id="zone-g1",
                flooded_percent=15.0,
                exposed_buildings=30,
                accessibility="PARTIAL",
                flooded_area_m2=7500.0,
            ),
            _make_zone(
                zone_id="zone-g2",
                flooded_percent=30.0,
                exposed_buildings=75,
                accessibility="BLOCKED",
                flooded_area_m2=15000.0,
            ),
            _make_zone(
                zone_id="zone-g3",
                flooded_percent=0.0,
                exposed_buildings=0,
                accessibility="ACCESSIBLE",
                flooded_area_m2=None,
            ),
        ]
        doc = _make_zones_doc(*zones)
        records = score_zones(doc, default_config, [])
        by_id = {r.zone_id: r for r in records}

        # --- Zone G1 ---
        g1 = by_id["zone-g1"]
        b1 = g1.score_breakdown
        assert b1["reconciliation"]["reconciled"] is True
        assert b1["components"]["flood_percent"]["points"] == 17.5
        assert b1["components"]["exposure"]["points"] == 16.0
        assert b1["components"]["isolation"]["points"] == 7.5
        assert b1["components"]["flood_area_density"]["points"] == 5.0
        assert b1["primary_driver"] == "flood_percent"
        assert "Flood coverage is the primary score driver (17.5 pts, 38% of score)" in b1["primary_driver_summary"]
        assert len(b1["influential_factors"]) == 4
        assert "Building exposure: 30 exposed buildings contribute 16.0 pts" in b1["influential_factors"][1]
        assert any("Primary score driver: Flood coverage" in r for r in g1.reasons)

        # --- Zone G2 (Critical maxed out) ---
        g2 = by_id["zone-g2"]
        b2 = g2.score_breakdown
        assert b2["reconciliation"]["reconciled"] is True
        assert b2["primary_driver"] == "exposure"
        assert b2["components"]["exposure"]["points"] == 40.0
        assert b2["components"]["flood_percent"]["points"] == 35.0
        assert b2["components"]["isolation"]["points"] == 15.0
        assert b2["components"]["flood_area_density"]["points"] == 10.0
        # Check ranking factors
        assert any("Blocked road access imposes maximum isolation penalty" in rf for rf in b2["ranking_factors"])
        assert any("Substantial building exposure (75 exposed buildings" in rf for rf in b2["ranking_factors"])
        assert any("Ranking factor: Blocked road access" in r for r in g2.reasons)
        assert any("Ranking factor: Substantial building exposure" in r for r in g2.reasons)

        # --- Zone G3 (Safe zero flood) ---
        g3 = by_id["zone-g3"]
        b3 = g3.score_breakdown
        assert b3["reconciliation"]["reconciled"] is True
        assert b3["primary_driver"] is None
        assert b3["influential_factors"] == []
        assert b3["ranking_factors"] == []
        assert not any("Primary score driver" in r for r in g3.reasons)

    def test_partial_scoring_weight_renormalization_reconciliation(self, default_config):
        """Verify that when flood_area_density is omitted, remaining weights renormalize and reconcile."""
        zone = _make_zone(
            zone_id="zone-part",
            flooded_percent=20.0,
            exposed_buildings=10,
            accessibility="PARTIAL",
            flooded_area_m2=None,
        )
        doc = _make_zones_doc(zone)
        records = score_zones(doc, default_config, [])
        rec = records[0]
        b = rec.score_breakdown

        assert b["score_basis"] == "partial"
        assert "flood_area_density" in b["omitted_components"]
        assert b["components"]["flood_area_density"]["omitted"] is True
        assert b["components"]["flood_area_density"]["weight"] == 0.0
        assert b["components"]["flood_area_density"]["points"] == 0.0

        # Renormalized weights must sum to 1.0
        active_sum = sum(c["weight"] for c in b["components"].values())
        assert active_sum == pytest.approx(1.0, abs=1e-5)

        # Reconciliation must pass
        assert b["reconciliation"]["reconciled"] is True
        assert abs(b["reconciliation"]["sum_weighted_contributions"] - rec.raw_score) < 1e-5

        # Omitted component must NOT appear in influential factors
        for f in b["influential_factors"]:
            assert "Flood extent area" not in f

    def test_formula_confirmation_and_no_false_causal_claims(self, default_config):
        """Verify that factors are NEVER cited as driving or contributing to the score unless points > 0."""
        # 1. ACCESSIBLE roads -> isolation score is 0.0 -> must not be cited as score driver
        z_acc = _make_zone(
            zone_id="zone-acc",
            flooded_percent=10.0,
            exposed_buildings=5,
            accessibility="ACCESSIBLE",
            flooded_area_m2=2000.0,
        )
        doc = _make_zones_doc(z_acc)
        rec = score_zones(doc, default_config, [])[0]
        b = rec.score_breakdown
        assert b["components"]["isolation"]["points"] == 0.0
        assert not any("Road isolation" in f for f in b["influential_factors"])
        assert not any("road isolation penalty applied" in r for r in rec.reasons)

        # 2. Zero exposed buildings -> exposure points 0.0 -> must not be cited as score driver
        z_no_eb = _make_zone(
            zone_id="zone-no-eb",
            flooded_percent=10.0,
            exposed_buildings=0,
            accessibility="BLOCKED",
            flooded_area_m2=2000.0,
        )
        doc = _make_zones_doc(z_no_eb)
        rec = score_zones(doc, default_config, [])[0]
        b = rec.score_breakdown
        assert b["components"]["exposure"]["points"] == 0.0
        assert not any("Building exposure" in f for f in b["influential_factors"])

        # 3. Default exposure_fraction weight = 0.0 -> points 0.0 -> must not be cited
        assert b["components"]["exposure_fraction"]["points"] == 0.0
        assert not any("exposure fraction" in f.lower() for f in b["influential_factors"])

        # 4. Isolation weight configured to 0.0 -> even BLOCKED road contributes 0.0 pts
        cfg_no_iso = copy.deepcopy(default_config)
        cfg_no_iso["scoring"]["weights"]["isolation"] = 0.0
        cfg_no_iso["scoring"]["weights"]["flood_percent"] = 0.40
        cfg_no_iso["scoring"]["weights"]["exposure"] = 0.45
        cfg_no_iso["scoring"]["weights"]["flood_area_density"] = 0.15

        z_blocked = _make_zone(
            zone_id="zone-blocked",
            flooded_percent=10.0,
            exposed_buildings=5,
            accessibility="BLOCKED",
            flooded_area_m2=2000.0,
        )
        doc = _make_zones_doc(z_blocked)
        rec = score_zones(doc, cfg_no_iso, [])[0]
        b = rec.score_breakdown
        assert b["components"]["isolation"]["weight"] == 0.0
        assert b["components"]["isolation"]["points"] == 0.0
        assert not any("Road isolation" in f for f in b["influential_factors"])
        assert not any("road isolation penalty applied" in r for r in rec.reasons)
        assert any("isolation weight is 0.0; no penalty applied" in r for r in rec.reasons)

    def test_ranking_invariance_with_explainability(self, default_config):
        """Verify that score breakdown computation does not alter ranking order or scores."""
        if not REAL_ZONES_PATH.exists():
            pytest.skip("Real zones.json not available")
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)

        # Ensure top zones retain exact deterministic ranks and scores
        assert records[0].zone_id == "zone-036"
        assert records[0].rank == 1
        assert records[1].zone_id == "zone-002"
        assert records[1].rank == 2
        assert records[1].priority == "HIGH"
        assert records[1].score == 53.4

        # Deterministic sequential ranking
        for i, r in enumerate(records, start=1):
            assert r.rank == i

    def test_json_serialization_and_contracts(self, default_config):
        """Verify that score_breakdown serialises cleanly to JSON and preserves output contract."""
        if not REAL_ZONES_PATH.exists():
            pytest.skip("Real zones.json not available")
        doc, warnings = load_zones(REAL_ZONES_PATH)
        records = score_zones(doc, default_config, warnings)
        out_dict = records_to_dict(records, warnings, doc, default_config)

        # JSON serialisation check without NaN/inf
        json_str = json.dumps(out_dict, allow_nan=False)
        parsed = json.loads(json_str)

        assert "ranked_zones" in parsed
        for z in parsed["ranked_zones"]:
            assert "score_breakdown" in z
            sb = z["score_breakdown"]
            assert sb["reconciliation"]["reconciled"] is True
            # Backward-compatibility: score_components still holds flat floats
            assert isinstance(z["score_components"]["flood_percent"], float)
            assert isinstance(z["score_components"]["exposure"], float)
            assert isinstance(z["score_components"]["isolation"], float)

        # Dashboard export check
        dash_dict = export_dashboard(out_dict, doc)
        dash_str = json.dumps(dash_dict, allow_nan=False)
        parsed_dash = json.loads(dash_str)

        assert "zones" in parsed_dash
        for dz in parsed_dash["zones"]:
            assert "score_breakdown" in dz
            assert dz["score_breakdown"]["reconciliation"]["reconciled"] is True
            assert isinstance(dz["reasons"], list)
            assert dz["geometry"]["type"] == "Polygon"


# ===========================================================================
# 11. Configurable Risk-Scoring Weights (Stage 3 Requirement)
# ===========================================================================

class TestConfigurableRiskScoringWeights:
    """Comprehensive test suite for configurable risk-scoring weights."""

    def test_default_weights_values_and_constants(self):
        """Verify DEFAULT_WEIGHTS match baseline model specifications."""
        assert DEFAULT_WEIGHTS["flood_percent"] == 0.35
        assert DEFAULT_WEIGHTS["exposure"] == 0.40
        assert DEFAULT_WEIGHTS["isolation"] == 0.15
        assert DEFAULT_WEIGHTS["flood_area_density"] == 0.10
        assert DEFAULT_WEIGHTS["exposure_fraction"] == 0.0

        sw = ScoringWeights()
        assert sw.to_dict() == DEFAULT_WEIGHTS
        sw.validate()

        fp = sw.fingerprint()
        assert isinstance(fp, str) and len(fp) == 16
        assert fp == weights_fingerprint(DEFAULT_WEIGHTS)

    def test_scoring_weights_validation_rejections(self):
        """Verify strict rejection of invalid weight values with actionable errors."""
        # Negative weight
        with pytest.raises(ConfigError, match="must be non-negative"):
            ScoringWeights(flood_percent=-0.1, exposure=0.85).validate()

        # Non-numeric
        with pytest.raises(ConfigError, match="must be a finite number"):
            ScoringWeights.from_dict({
                "flood_percent": "0.35",
                "exposure": 0.40,
                "isolation": 0.15,
                "flood_area_density": 0.10,
            })

        # Non-finite (inf or NaN)
        with pytest.raises(ConfigError, match="must be a finite number"):
            ScoringWeights(flood_percent=float("inf"), exposure=0.0).validate()
        with pytest.raises(ConfigError, match="must be a finite number"):
            ScoringWeights(flood_percent=float("nan"), exposure=0.0).validate()

        # Sum does not equal 1.0
        with pytest.raises(ConfigError, match="sum to 1.0"):
            ScoringWeights(flood_percent=0.5, exposure=0.4, isolation=0.15, flood_area_density=0.10).validate()

        # Missing required base keys
        with pytest.raises(ConfigError, match="missing required keys"):
            ScoringWeights.from_dict({"flood_percent": 0.5, "exposure": 0.5})

        # Extra unknown keys
        with pytest.raises(ConfigError, match="unexpected extra"):
            ScoringWeights.from_dict({
                "flood_percent": 0.35,
                "exposure": 0.40,
                "isolation": 0.15,
                "flood_area_density": 0.10,
                "custom_bonus": 0.0,
            })

    def test_from_unnormalized_scaling(self):
        """Verify that from_unnormalized scales positive numbers to sum to 1.0."""
        sw = ScoringWeights.from_unnormalized({
            "flood_percent": 35,
            "exposure": 40,
            "isolation": 15,
            "flood_area_density": 10,
        })
        sw.validate()
        assert math.isclose(sw.flood_percent, 0.35, rel_tol=1e-6)
        assert math.isclose(sw.exposure, 0.40, rel_tol=1e-6)
        assert math.isclose(sw.isolation, 0.15, rel_tol=1e-6)
        assert math.isclose(sw.flood_area_density, 0.10, rel_tol=1e-6)

        # Zero sum raises
        with pytest.raises(ConfigError, match="at least one weight must be positive"):
            ScoringWeights.from_unnormalized({
                "flood_percent": 0,
                "exposure": 0,
                "isolation": 0,
                "flood_area_density": 0,
            })

    def test_priority_thresholds_separation(self):
        """Priority thresholds must remain separate from scoring weights."""
        pt = PriorityThresholds()
        pt.validate()
        assert pt.CRITICAL == 70.0
        assert pt.HIGH == 45.0
        assert pt.MEDIUM == 20.0
        assert pt.LOW == 0.0

        # Invalid ordering raises
        with pytest.raises(ConfigError, match="ordering violated"):
            PriorityThresholds(CRITICAL=50.0, HIGH=60.0).validate()

    def test_risk_engine_config_object_and_methods(self):
        """Verify RiskEngineConfig methods, fingerprinting, and immutability."""
        cfg = load_config_object()
        assert isinstance(cfg, RiskEngineConfig)
        assert cfg.config_version == "1.0"
        assert cfg.scoring.weights.to_dict() == DEFAULT_WEIGHTS

        fp1 = cfg.fingerprint()
        wfp1 = cfg.weights_fingerprint()
        assert len(fp1) == 64
        assert len(wfp1) == 16

        # Modifying weights produces a new config with different fingerprints
        cfg_alt = cfg.with_weights({
            "flood_percent": 0.25,
            "exposure": 0.25,
            "isolation": 0.25,
            "flood_area_density": 0.25,
        })
        assert cfg_alt.scoring.weights.flood_percent == 0.25
        assert cfg.scoring.weights.flood_percent == 0.35  # original unmodified
        assert cfg_alt.weights_fingerprint() != wfp1
        assert cfg_alt.fingerprint() != fp1

    def test_score_zones_with_config_object_or_dict(self, default_config):
        """score_zones accepts either a config dict or RiskEngineConfig object identically."""
        z = _make_zone(zone_id="z-test", flooded_percent=25.0, exposed_buildings=10)
        doc = _make_zones_doc(z)

        cfg_dict = default_config
        cfg_obj = RiskEngineConfig.from_dict(default_config)

        rec_from_dict = score_zones(doc, cfg_dict, [])
        rec_from_obj = score_zones(doc, cfg_obj, [])

        assert rec_from_dict[0].score == rec_from_obj[0].score
        assert rec_from_dict[0].priority == rec_from_obj[0].priority
        assert rec_from_dict[0].isolation_component == rec_from_obj[0].isolation_component
        assert rec_from_dict[0].score_breakdown == rec_from_obj[0].score_breakdown

    def test_boundary_case_single_component_weight_one(self):
        """When weight is 1.0 on flood_percent, score must strictly match normalized flood percent."""
        weights = {
            "flood_percent": 1.0,
            "exposure": 0.0,
            "isolation": 0.0,
            "flood_area_density": 0.0,
            "exposure_fraction": 0.0,
        }
        cfg = load_config_object().with_weights(weights)

        # Flood percent 25% with max ceiling 30% -> norm = 25/30 = 0.8333 -> points = 83.3
        z = _make_zone(
            zone_id="z-flood-only",
            flooded_percent=25.0,
            exposed_buildings=100,  # Huge buildings should not affect score
            accessibility="BLOCKED",  # Isolation should not affect score
            flooded_area_m2=50000.0,
        )
        doc = _make_zones_doc(z)
        rec = score_zones(doc, cfg, [])[0]

        assert math.isclose(rec.score, 83.3, abs_tol=0.1)
        assert rec.score_breakdown["reconciliation"]["reconciled"] is True
        assert rec.score_breakdown["components"]["flood_percent"]["points"] == pytest.approx(83.3, 0.1)
        assert rec.score_breakdown["components"]["exposure"]["points"] == 0.0
        assert rec.score_breakdown["components"]["isolation"]["points"] == 0.0
        assert rec.score_breakdown["components"]["flood_area_density"]["points"] == 0.0

        # Influential factors should only list flood extent
        assert any("Flood extent" in f or "Flood coverage" in f for f in rec.score_breakdown["influential_factors"])
        assert not any("Building exposure" in f for f in rec.score_breakdown["influential_factors"])

    def test_boundary_case_zero_weight_isolation_and_flood_area(self):
        """Zero weight on isolation and flood area completely removes their penalty."""
        weights = {
            "flood_percent": 0.50,
            "exposure": 0.50,
            "isolation": 0.0,
            "flood_area_density": 0.0,
        }
        cfg = load_config_object().with_weights(weights)
        z = _make_zone(
            zone_id="z-no-iso",
            flooded_percent=20.0,
            exposed_buildings=10,
            accessibility="BLOCKED",
        )
        doc = _make_zones_doc(z)
        rec = score_zones(doc, cfg, [])[0]
        assert rec.score_breakdown["components"]["isolation"]["points"] == 0.0
        assert rec.score_breakdown["components"]["flood_area_density"]["points"] == 0.0
        assert any("isolation weight is 0.0; no penalty applied" in r for r in rec.reasons)

    def test_valid_alternative_weights_ranking_shift(self):
        """Changing weights predictably changes relative rankings and maintains reconciliation."""
        # Zone A: high exposure, low flood
        zone_a = _make_zone(
            zone_id="zone-A",
            flooded_percent=5.0,
            exposed_buildings=40,
            accessibility="ACCESSIBLE",
            flooded_area_m2=500.0,
        )
        # Zone B: high flood, zero exposure
        zone_b = _make_zone(
            zone_id="zone-B",
            flooded_percent=45.0,
            exposed_buildings=0,
            accessibility="ACCESSIBLE",
            flooded_area_m2=500.0,
        )
        doc = _make_zones_doc(zone_a, zone_b)

        # Config 1: Exposure-dominated (80% exposure, 10% flood)
        cfg_exp = load_config_object().with_weights({
            "flood_percent": 0.10,
            "exposure": 0.80,
            "isolation": 0.05,
            "flood_area_density": 0.05,
        })
        records_exp = score_zones(doc, cfg_exp, [])
        assert records_exp[0].zone_id == "zone-A"
        assert records_exp[1].zone_id == "zone-B"
        for r in records_exp:
            assert r.score_breakdown["reconciliation"]["reconciled"] is True

        # Config 2: Flood-dominated (80% flood, 10% exposure)
        cfg_flood = load_config_object().with_weights({
            "flood_percent": 0.80,
            "exposure": 0.10,
            "isolation": 0.05,
            "flood_area_density": 0.05,
        })
        records_flood = score_zones(doc, cfg_flood, [])
        assert records_flood[0].zone_id == "zone-B"
        assert records_flood[1].zone_id == "zone-A"
        for r in records_flood:
            assert r.score_breakdown["reconciliation"]["reconciled"] is True

    def test_deterministic_reproducible_fingerprinting(self):
        """Weights fingerprint is deterministic, canonical, and order-independent."""
        w1 = {"flood_percent": 0.35, "exposure": 0.40, "isolation": 0.15, "flood_area_density": 0.10}
        w2 = {"flood_area_density": 0.10, "exposure": 0.40, "flood_percent": 0.35, "isolation": 0.15}
        assert weights_fingerprint(w1) == weights_fingerprint(w2)

        # Output dictionary contains weights_fingerprint and config_hash_sha256
        z = _make_zone()
        doc = _make_zones_doc(z)
        cfg = load_config()
        recs = score_zones(doc, cfg, [])
        out = records_to_dict(recs, [], doc, cfg)

        assert "weights_fingerprint" in out["scoring_config"]
        assert out["scoring_config"]["weights_fingerprint"] == weights_fingerprint(w1)
        assert "config_hash_sha256" in out["scoring_config"]
        assert "weights_fingerprint" in out["source_metadata"]

    def test_parse_weights_arg(self):
        """Verify parse_weights_arg parses JSON string and key=value pairs."""
        # JSON string
        json_str = '{"flood_percent": 0.4, "exposure": 0.35, "isolation": 0.15, "flood_area_density": 0.1}'
        parsed_json = parse_weights_arg(json_str)
        assert parsed_json["flood_percent"] == 0.4

        # Key-value string
        kv_str = "flood_percent=0.4,exposure=0.35,isolation=0.15,flood_area_density=0.1"
        parsed_kv = parse_weights_arg(kv_str)
        assert parsed_kv["flood_percent"] == 0.4
        assert parsed_kv["exposure"] == 0.35

        # Dict input passthrough
        dict_in = {"flood_percent": 0.4, "exposure": 0.35, "isolation": 0.15, "flood_area_density": 0.1}
        assert parse_weights_arg(dict_in) == dict_in

        # Invalid formats raise ConfigError
        with pytest.raises(ConfigError, match=r"(?i)invalid.*format"):
            parse_weights_arg("not_a_valid_format")
        with pytest.raises(ConfigError, match="must be a dict or string"):
            parse_weights_arg(12345)

    def test_cli_run_with_custom_weights(self, tmp_path):
        """CLI run() accepts weights parameter and incorporates configured weights."""
        z = _make_zone(zone_id="z-cli", flooded_percent=20.0, exposed_buildings=5)
        p_zones = _write_zones(tmp_path, z)
        out_dir = tmp_path / "cli_out"

        custom_weights = {
            "flood_percent": 0.25,
            "exposure": 0.25,
            "isolation": 0.25,
            "flood_area_density": 0.25,
        }
        res = cli_run(p_zones, out_dir, weights=custom_weights)

        assert res["scoring_config"]["weights"]["flood_percent"] == 0.25
        assert res["scoring_config"]["weights"]["exposure"] == 0.25
        assert res["scoring_config"]["weights_fingerprint"] == weights_fingerprint(custom_weights)

        # Output file was written and can be loaded
        written = json.loads((out_dir / "risk_scores.json").read_text(encoding="utf-8"))
        assert written["scoring_config"]["weights_fingerprint"] == weights_fingerprint(custom_weights)

    def test_cli_subprocess_weights_flag(self, tmp_path):
        """CLI invocation via subprocess with --weights flag."""
        z = _make_zone(zone_id="z-sub", flooded_percent=20.0, exposed_buildings=5)
        p_zones = _write_zones(tmp_path, z)
        out_dir = tmp_path / "sub_out"

        # 1. Valid JSON weights string
        w_arg = '{"flood_percent": 0.5, "exposure": 0.3, "isolation": 0.1, "flood_area_density": 0.1}'
        cmd = [
            sys.executable,
            "-m",
            "risk_engine.cli",
            "--zones",
            str(p_zones),
            "--out",
            str(out_dir),
            "--weights",
            w_arg,
        ]
        sub_env = {**os.environ, "PYTHONPATH": str(MODULE_ROOT / "src")}
        ret = subprocess.run(cmd, capture_output=True, text=True, cwd=str(MODULE_ROOT.parent), env=sub_env)
        assert ret.returncode == 0, f"CLI stderr: {ret.stderr}"
        res = json.loads((out_dir / "risk_scores.json").read_text(encoding="utf-8"))
        assert res["scoring_config"]["weights"]["flood_percent"] == 0.5

        # 2. Key=value format
        out_dir_kv = tmp_path / "sub_out_kv"
        w_kv = "flood_percent=0.5,exposure=0.3,isolation=0.1,flood_area_density=0.1"
        cmd_kv = [
            sys.executable,
            "-m",
            "risk_engine.cli",
            "--zones",
            str(p_zones),
            "--out",
            str(out_dir_kv),
            "--weights",
            w_kv,
        ]
        ret_kv = subprocess.run(cmd_kv, capture_output=True, text=True, cwd=str(MODULE_ROOT.parent), env=sub_env)
        assert ret_kv.returncode == 0, f"CLI stderr: {ret_kv.stderr}"
        res_kv = json.loads((out_dir_kv / "risk_scores.json").read_text(encoding="utf-8"))
        assert res_kv["scoring_config"]["weights"]["flood_percent"] == 0.5

        # 3. Invalid weights flag exits with code 2
        bad_w = "flood_percent=0.9,exposure=0.9,isolation=0.1,flood_area_density=0.1"  # sum = 2.0 != 1.0
        cmd_bad = [
            sys.executable,
            "-m",
            "risk_engine.cli",
            "--zones",
            str(p_zones),
            "--out",
            str(tmp_path / "bad_out"),
            "--weights",
            bad_w,
        ]
        ret_bad = subprocess.run(cmd_bad, capture_output=True, text=True, cwd=str(MODULE_ROOT.parent), env=sub_env)
        assert ret_bad.returncode == 2
        assert "sum to 1.0" in ret_bad.stderr


# ===========================================================================
# 12. Isolation-Aware Prioritization (Stage 4 Requirement)
# ===========================================================================

class TestIsolationAwarePrioritization:
    """Comprehensive test suite for isolation-aware prioritization and road accessibility."""

    def test_accessible_zone_isolation_behavior(self, default_config):
        """ACCESSIBLE zones incur 0.0 isolation component, 0.0 pts penalty, and explain status."""
        z = _make_zone(
            zone_id="z-acc",
            flooded_percent=15.0,
            exposed_buildings=10,
            accessibility="ACCESSIBLE",
            road_length_m=500.0,
            flooded_road_length_m=20.0,  # 4% < 10% threshold
        )
        doc = _make_zones_doc(z)
        recs = score_zones(doc, default_config, [])
        r = recs[0]

        assert r.accessibility == "ACCESSIBLE"
        assert r.isolation_component == 0.0
        assert r.score_breakdown["components"]["isolation"]["points"] == 0.0
        assert r.score_breakdown["components"]["isolation"]["weighted_contribution"] == 0.0

        # Reasons state roads are not significantly flooded
        assert any("Roads in this zone are not significantly flooded" in reason for reason in r.reasons)

        # Output serialisation check
        out = records_to_dict(recs, [], doc, default_config)
        z_out = out["ranked_zones"][0]
        assert z_out["accessibility"] == "ACCESSIBLE"
        iso = z_out["isolation"]
        assert iso["status"] == "ACCESSIBLE"
        assert iso["score"] == 0.0
        assert iso["points"] == 0.0
        assert iso["needs_verification"] is False
        assert iso["flooded_road_share"] == 0.04

    def test_partially_accessible_zone_isolation_behavior(self, default_config):
        """PARTIAL zones incur 0.5 isolation component, +7.5 pts, and explain partial isolation."""
        z = _make_zone(
            zone_id="z-part",
            flooded_percent=15.0,
            exposed_buildings=10,
            accessibility="PARTIAL",
            road_length_m=500.0,
            flooded_road_length_m=150.0,  # 30% flooded (in [10%, 60%))
        )
        doc = _make_zones_doc(z)
        recs = score_zones(doc, default_config, [])
        r = recs[0]

        assert r.accessibility == "PARTIAL"
        assert r.isolation_component == 0.5
        # Default weight 0.15 * 0.5 * 100 = 7.5 pts
        assert r.score_breakdown["components"]["isolation"]["points"] == 7.5
        assert r.score_breakdown["components"]["isolation"]["weighted_contribution"] == pytest.approx(0.075)

        # Explanations explain partial road isolation
        assert any("partial road isolation penalty applied" in reason for reason in r.reasons)
        assert any("Partial road access imposes intermediate isolation penalty" in rf for rf in r.score_breakdown["ranking_factors"])

        # Output serialisation check
        out = records_to_dict(recs, [], doc, default_config)
        z_out = out["ranked_zones"][0]
        assert z_out["accessibility"] == "PARTIAL"
        iso = z_out["isolation"]
        assert iso["status"] == "PARTIAL"
        assert iso["score"] == 0.5
        assert iso["points"] == 7.5
        assert iso["flooded_road_share"] == 0.3
        assert iso["needs_verification"] is False

    def test_blocked_zone_isolation_behavior(self, default_config):
        """BLOCKED zones incur 1.0 isolation component, +15.0 pts, and explain maximum penalty."""
        z = _make_zone(
            zone_id="z-blk",
            flooded_percent=15.0,
            exposed_buildings=10,
            accessibility="BLOCKED",
            road_length_m=500.0,
            flooded_road_length_m=400.0,  # 80% >= 60% threshold
        )
        doc = _make_zones_doc(z)
        recs = score_zones(doc, default_config, [])
        r = recs[0]

        assert r.accessibility == "BLOCKED"
        assert r.isolation_component == 1.0
        # Default weight 0.15 * 1.0 * 100 = 15.0 pts
        assert r.score_breakdown["components"]["isolation"]["points"] == 15.0

        # Explanations explain blocked road access
        assert any("road isolation penalty applied" in reason for reason in r.reasons)
        assert any("Blocked road access imposes maximum isolation penalty" in rf for rf in r.score_breakdown["ranking_factors"])

        # Output serialisation check
        out = records_to_dict(recs, [], doc, default_config)
        z_out = out["ranked_zones"][0]
        assert z_out["accessibility"] == "BLOCKED"
        iso = z_out["isolation"]
        assert iso["status"] == "BLOCKED"
        assert iso["score"] == 1.0
        assert iso["points"] == 15.0
        assert iso["flooded_road_share"] == 0.8
        assert iso["needs_verification"] is False

    def test_unknown_zone_isolation_and_verification(self, default_config):
        """UNKNOWN zones incur 0.5 component, flag verification, and do not assume safety."""
        z = _make_zone(
            zone_id="z-unk",
            flooded_percent=0.0,
            exposed_buildings=0,
            accessibility="UNKNOWN",
            road_length_m=0.0,
            flooded_road_length_m=0.0,
        )
        doc = _make_zones_doc(z)
        recs = score_zones(doc, default_config, [])
        r = recs[0]

        assert r.accessibility == "UNKNOWN"
        assert r.isolation_component == 0.5
        assert r.score_breakdown["components"]["isolation"]["points"] == 7.5
        assert r.needs_verification is True
        assert r.confidence != "HIGH"
        assert "unknown_accessibility" in r.data_quality_issues
        assert any("accessibility=UNKNOWN" in w for w in r.warnings)

        # Output serialisation check
        out = records_to_dict(recs, [], doc, default_config)
        z_out = out["ranked_zones"][0]
        assert z_out["accessibility"] == "UNKNOWN"
        iso = z_out["isolation"]
        assert iso["status"] == "UNKNOWN"
        assert iso["score"] == 0.5
        assert iso["points"] == 7.5
        assert iso["needs_verification"] is True
        assert any("accessibility=UNKNOWN" in w for w in iso["warnings"])

    def test_missing_accessibility_not_interpreted_as_accessible(self, tmp_path, default_config):
        """Missing accessibility must never be interpreted as confirmed accessible."""
        # 1. File loading rejects missing accessibility
        z_missing = _make_zone(zone_id="z-miss")
        del z_missing["accessibility"]
        p = _write_zones(tmp_path / "missing_acc", z_missing)
        with pytest.raises(InputValidationError, match="accessibility"):
            load_zones(p)

        # 2. score_zones handles missing accessibility defensively without assuming accessible
        doc = _make_zones_doc(z_missing)
        recs = score_zones(doc, default_config, [])
        r = recs[0]

        # Must NOT be 0.0 (which would be ACCESSIBLE)
        assert r.isolation_component == 0.5
        assert r.accessibility == "UNKNOWN"
        assert r.needs_verification is True
        assert r.confidence != "HIGH"
        assert any("missing" in w.lower() or "unknown" in w.lower() for w in r.warnings)

    def test_ranking_ties_broken_by_isolation(self, default_config):
        """Zones with identical flood coverage and exposure are ranked by isolation penalty."""
        # 3 zones identical in all aspects except accessibility
        z_blocked = _make_zone(
            zone_id="zone-blk",
            flooded_percent=20.0,
            exposed_buildings=15,
            flooded_area_m2=3000.0,
            accessibility="BLOCKED",
        )
        z_partial = _make_zone(
            zone_id="zone-part",
            flooded_percent=20.0,
            exposed_buildings=15,
            flooded_area_m2=3000.0,
            accessibility="PARTIAL",
        )
        z_accessible = _make_zone(
            zone_id="zone-acc",
            flooded_percent=20.0,
            exposed_buildings=15,
            flooded_area_m2=3000.0,
            accessibility="ACCESSIBLE",
        )

        doc = _make_zones_doc(z_accessible, z_blocked, z_partial)
        recs = score_zones(doc, default_config, [])

        # Ranking must strictly be: BLOCKED (#1) > PARTIAL (#2) > ACCESSIBLE (#3)
        assert recs[0].zone_id == "zone-blk"
        assert recs[0].rank == 1
        assert recs[1].zone_id == "zone-part"
        assert recs[1].rank == 2
        assert recs[2].zone_id == "zone-acc"
        assert recs[2].rank == 3

        # Scores strictly reflect isolation points (15.0 > 7.5 > 0.0)
        assert recs[0].score > recs[1].score > recs[2].score
        assert math.isclose(recs[0].score - recs[1].score, 7.5, abs_tol=0.2)
        assert math.isclose(recs[1].score - recs[2].score, 7.5, abs_tol=0.2)

    def test_contradictory_road_flooding_detection(self, default_config):
        """Contradictions between recorded road length flooding and accessibility labels are flagged."""
        # Case 1: 80% flooded roads but labelled ACCESSIBLE
        z_contra1 = _make_zone(
            zone_id="z-c1",
            road_length_m=500.0,
            flooded_road_length_m=400.0,  # 80% flooded
            accessibility="ACCESSIBLE",
        )
        doc1 = _make_zones_doc(z_contra1)
        r1 = score_zones(doc1, default_config, [])[0]
        assert r1.data_quality_status == "CONTRADICTORY"
        assert r1.confidence == "LOW"
        assert r1.needs_verification is True
        assert "contradictory_accessible_with_blocked_roads" in r1.data_quality_issues

        # Case 2: 0% flooded roads but labelled BLOCKED
        z_contra2 = _make_zone(
            zone_id="z-c2",
            road_length_m=500.0,
            flooded_road_length_m=0.0,
            accessibility="BLOCKED",
        )
        doc2 = _make_zones_doc(z_contra2)
        r2 = score_zones(doc2, default_config, [])[0]
        assert r2.data_quality_status == "CONTRADICTORY"
        assert r2.confidence == "LOW"
        assert r2.needs_verification is True
        assert "contradictory_blocked_with_zero_flooded_roads" in r2.data_quality_issues

    def test_explicit_output_structure_and_summary_counts(self, default_config):
        """Output dictionary explicitly includes accessibility, isolation block, and summary counts."""
        z_acc = _make_zone(zone_id="z1", accessibility="ACCESSIBLE")
        z_part = _make_zone(zone_id="z2", accessibility="PARTIAL")
        z_blk = _make_zone(zone_id="z3", accessibility="BLOCKED")
        z_unk = _make_zone(zone_id="z4", accessibility="UNKNOWN")

        doc = _make_zones_doc(z_acc, z_part, z_blk, z_unk)
        recs = score_zones(doc, default_config, [])
        out = records_to_dict(recs, [], doc, default_config)

        # Check summary accessibility_counts
        counts = out["summary"]["accessibility_counts"]
        assert counts["ACCESSIBLE"] == 1
        assert counts["PARTIAL"] == 1
        assert counts["BLOCKED"] == 1
        assert counts["UNKNOWN"] == 1

        # Check zone-level explicit accessibility and isolation
        for z in out["ranked_zones"]:
            assert "accessibility" in z
            assert z["accessibility"] in ("ACCESSIBLE", "PARTIAL", "BLOCKED", "UNKNOWN")
            assert "isolation" in z
            iso = z["isolation"]
            for field in (
                "status", "score", "weight", "weighted_contribution",
                "points", "percentage_of_score", "road_length_m",
                "flooded_road_length_m", "flooded_road_share",
                "warnings", "needs_verification",
            ):
                assert field in iso

    def test_isolation_mathematical_reconciliation(self, default_config):
        """Isolation component reconciles mathematically across all accessibility categories."""
        for acc_val in ("ACCESSIBLE", "PARTIAL", "BLOCKED", "UNKNOWN"):
            z = _make_zone(zone_id=f"z-{acc_val}", accessibility=acc_val)
            doc = _make_zones_doc(z)
            rec = score_zones(doc, default_config, [])[0]
            sb = rec.score_breakdown
            iso_comp = sb["components"]["isolation"]

            assert sb["reconciliation"]["reconciled"] is True
            expected_contrib = iso_comp["weight"] * iso_comp["normalized_value"]
            assert math.isclose(iso_comp["weighted_contribution"], expected_contrib, rel_tol=1e-5)
            assert math.isclose(iso_comp["points"], expected_contrib * 100.0, abs_tol=0.05)

    def test_dashboard_export_isolation_preservation(self, default_config):
        """Dashboard export preserves mapped accessibility, isolation structure, and reasons."""
        z = _make_zone(
            zone_id="z-dash",
            accessibility="BLOCKED",
            road_length_m=400.0,
            flooded_road_length_m=350.0,
        )
        doc = _make_zones_doc(z)
        recs = score_zones(doc, default_config, [])
        out = records_to_dict(recs, [], doc, default_config)
        dash = export_dashboard(out, doc)

        dz = dash["zones"][0]
        # BLOCKED maps to BLOCKED in dashboard
        assert dz["accessibility"] == "BLOCKED"
        assert "isolation" in dz
        assert dz["isolation"]["points"] == 15.0
        assert isinstance(dz["reasons"], list)
        assert len(dz["reasons"]) > 0


# ===========================================================================
# 13. Risk-Ranking Sensitivity Analysis (Stage 5 Requirement)
# ===========================================================================

class TestRiskRankingSensitivityAnalysis:
    """Comprehensive test suite for standalone risk-ranking sensitivity analysis."""

    def test_baseline_results_remain_completely_unchanged(self, default_config):
        """Verify baseline scores, ranks, and records are identical before, during, and after sensitivity analysis."""
        z1 = _make_zone(zone_id="zone-1", flooded_percent=25.0, exposed_buildings=20, accessibility="BLOCKED")
        z2 = _make_zone(zone_id="zone-2", flooded_percent=10.0, exposed_buildings=5, accessibility="ACCESSIBLE")
        z3 = _make_zone(zone_id="zone-3", flooded_percent=5.0, exposed_buildings=40, accessibility="PARTIAL")
        doc = _make_zones_doc(z1, z2, z3)

        # 1. Baseline scoring before
        records_before = score_zones(doc, default_config, [])
        scores_before = {r.zone_id: r.score for r in records_before}
        ranks_before = {r.zone_id: r.rank for r in records_before}
        prios_before = {r.zone_id: r.priority for r in records_before}

        # 2. Run standalone sensitivity analysis
        result = analyze_ranking_sensitivity(doc, config=default_config)

        # 3. Baseline scoring after
        records_after = score_zones(doc, default_config, [])
        scores_after = {r.zone_id: r.score for r in records_after}
        ranks_after = {r.zone_id: r.rank for r in records_after}
        prios_after = {r.zone_id: r.priority for r in records_after}

        # Verify exact equality before and after
        assert scores_before == scores_after
        assert ranks_before == ranks_after
        assert prios_before == prios_after

        # Verify sensitivity analysis baseline section matches original
        assert result.baseline["weights"]["flood_percent"] == default_config["scoring"]["weights"]["flood_percent"]
        assert result.baseline["weights_fingerprint"] == weights_fingerprint(default_config["scoring"]["weights"])
        for z in result.zone_sensitivity:
            assert z["baseline_score"] == scores_before[z["zone_id"]]
            assert z["baseline_rank"] == ranks_before[z["zone_id"]]
            assert z["baseline_priority"] == prios_before[z["zone_id"]]

    def test_default_scenarios_validation_and_assumptions(self):
        """Verify all DEFAULT_SENSITIVITY_SCENARIOS are valid, sum to 1.0, and have assumptions."""
        assert len(DEFAULT_SENSITIVITY_SCENARIOS) >= 4
        names = set()
        fingerprints = set()

        for s in DEFAULT_SENSITIVITY_SCENARIOS:
            s.validate()
            assert isinstance(s.name, str) and len(s.name) > 0
            assert isinstance(s.description, str) and len(s.description) > 0
            assert isinstance(s.assumptions, str) and len(s.assumptions) > 0
            assert s.name not in names, f"Duplicate scenario name: {s.name}"
            names.add(s.name)

            total_w = sum(s.weights.values())
            assert math.isclose(total_w, 1.0, rel_tol=1e-6)

            fp = s.fingerprint()
            assert len(fp) == 16
            assert fp not in fingerprints, f"Duplicate scenario fingerprint: {fp}"
            fingerprints.add(fp)

    def test_custom_alternative_scenarios_evaluation(self, default_config):
        """Evaluate explicitly supplied custom scenarios via dict and SensitivityScenario objects."""
        z1 = _make_zone(zone_id="z-exp", flooded_percent=5.0, exposed_buildings=50, accessibility="ACCESSIBLE")
        z2 = _make_zone(zone_id="z-fld", flooded_percent=50.0, exposed_buildings=2, accessibility="ACCESSIBLE")
        doc = _make_zones_doc(z1, z2)

        custom_scenarios = [
            SensitivityScenario(
                name="extreme_exposure",
                weights={
                    "flood_percent": 0.05,
                    "exposure": 0.85,
                    "isolation": 0.05,
                    "flood_area_density": 0.05,
                    "exposure_fraction": 0.0,
                },
                description="Extreme 85% exposure test",
                assumptions="Testing pure exposure-driven prioritization",
            ),
            SensitivityScenario(
                name="extreme_flood",
                weights={
                    "flood_percent": 0.85,
                    "exposure": 0.05,
                    "isolation": 0.05,
                    "flood_area_density": 0.05,
                    "exposure_fraction": 0.0,
                },
                description="Extreme 85% flood test",
                assumptions="Testing pure flood-coverage-driven prioritization",
            ),
        ]

        res = analyze_ranking_sensitivity(doc, config=default_config, scenarios=custom_scenarios)
        assert res.summary["scenarios_tested_count"] == 2
        assert len(res.scenarios) == 2

        scen_map = {sc["scenario_name"]: sc for sc in res.scenarios}
        assert "extreme_exposure" in scen_map
        assert "extreme_flood" in scen_map

        # Under extreme_exposure, z-exp must rank #1
        z_exp_rec = next(z for z in res.zone_sensitivity if z["zone_id"] == "z-exp")
        assert z_exp_rec["ranks_by_scenario"]["extreme_exposure"] == 1

        # Under extreme_flood, z-fld must rank #1
        z_fld_rec = next(z for z in res.zone_sensitivity if z["zone_id"] == "z-fld")
        assert z_fld_rec["ranks_by_scenario"]["extreme_flood"] == 1

    def test_invalid_scenario_configurations_rejected(self, default_config):
        """Ensure scenario configurations are rejected when violating engine validation rules."""
        doc = _make_zones_doc(_make_zone())

        # 1. Weights sum != 1.0
        with pytest.raises(ConfigError, match="sum to 1.0"):
            SensitivityScenario(
                name="bad_sum",
                weights={"flood_percent": 0.5, "exposure": 0.8, "isolation": 0.1, "flood_area_density": 0.1},
            )
        with pytest.raises(ConfigError, match="sum to 1.0"):
            analyze_ranking_sensitivity(doc, scenarios=[
                {"name": "bad_sum", "weights": {"flood_percent": 0.5, "exposure": 0.8, "isolation": 0.1, "flood_area_density": 0.1}}
            ])

        # 2. Negative weight
        with pytest.raises(ConfigError, match="must be non-negative"):
            SensitivityScenario(
                name="bad_neg",
                weights={"flood_percent": -0.1, "exposure": 0.8, "isolation": 0.15, "flood_area_density": 0.15},
            )
        with pytest.raises(ConfigError, match="must be non-negative"):
            analyze_ranking_sensitivity(doc, scenarios=[
                {"name": "bad_neg", "weights": {"flood_percent": -0.1, "exposure": 0.8, "isolation": 0.15, "flood_area_density": 0.15}}
            ])

        # 3. Missing base weight key
        bad_missing = [
            {"name": "missing_keys", "weights": {"flood_percent": 0.5, "exposure": 0.5}}
        ]
        with pytest.raises(ConfigError, match="missing required keys"):
            analyze_ranking_sensitivity(doc, scenarios=bad_missing)

        # 4. Unexpected extra weight key
        bad_extra = [
            {
                "name": "extra_keys",
                "weights": {
                    "flood_percent": 0.35, "exposure": 0.40, "isolation": 0.15,
                    "flood_area_density": 0.10, "unknown_factor": 0.0
                }
            }
        ]
        with pytest.raises(ConfigError, match="unexpected extra keys"):
            analyze_ranking_sensitivity(doc, scenarios=bad_extra)

        # 5. Non-numeric weight
        bad_nan = [
            {"name": "nan_weight", "weights": {"flood_percent": float("nan"), "exposure": 0.4, "isolation": 0.3, "flood_area_density": 0.3}}
        ]
        with pytest.raises(ConfigError, match="must be a finite number"):
            analyze_ranking_sensitivity(doc, scenarios=bad_nan)

        # 6. Empty scenario list
        with pytest.raises(ConfigError, match="At least one"):
            analyze_ranking_sensitivity(doc, scenarios=[])

    def test_ranking_ties_handled_consistently_across_scenarios(self, default_config):
        """Tied zones are broken deterministically by natural sort zone ID across all scenarios."""
        # Two identical zones where only zone_id differs: zone-02 vs zone-10
        z1 = _make_zone(zone_id="zone-02", flooded_percent=20.0, exposed_buildings=10, accessibility="PARTIAL")
        z2 = _make_zone(zone_id="zone-10", flooded_percent=20.0, exposed_buildings=10, accessibility="PARTIAL")
        doc = _make_zones_doc(z2, z1)  # insert in reverse order

        result = analyze_ranking_sensitivity(doc, config=default_config)

        # zone-02 must precede zone-10 in baseline
        z02_rec = next(z for z in result.zone_sensitivity if z["zone_id"] == "zone-02")
        z10_rec = next(z for z in result.zone_sensitivity if z["zone_id"] == "zone-10")
        assert z02_rec["baseline_rank"] < z10_rec["baseline_rank"]

        # zone-02 must precede zone-10 in EVERY scenario evaluated
        for scen_name in z02_rec["ranks_by_scenario"]:
            r02 = z02_rec["ranks_by_scenario"][scen_name]
            r10 = z10_rec["ranks_by_scenario"][scen_name]
            assert r02 < r10, f"Tie broken inconsistently in scenario '{scen_name}': {r02} vs {r10}"

    def test_missing_inputs_and_data_quality_handling(self, default_config):
        """Sensitivity analysis handles missing fields, UNKNOWN accessibility, and empty zones without crashing."""
        # 1. Zone with missing/null fields and UNKNOWN accessibility
        z_incomplete = _make_zone(
            zone_id="z-inc",
            accessibility="UNKNOWN",
            flooded_area_m2=None,
            total_buildings=None,
            road_length_m=None,
        )
        doc = _make_zones_doc(z_incomplete)
        res = analyze_ranking_sensitivity(doc, config=default_config)
        assert res.summary["total_zones"] == 1
        assert len(res.zone_sensitivity) == 1
        assert res.zone_sensitivity[0]["baseline_rank"] == 1

        # 2. Empty zones document
        doc_empty = {"zones": []}
        res_empty = analyze_ranking_sensitivity(doc_empty, config=default_config)
        assert res_empty.summary["total_zones"] == 0
        assert res_empty.summary["robust_high_priority_count"] == 0
        assert res_empty.summary["volatile_zones_count"] == 0
        assert res_empty.robust_high_priority_zones == []
        assert res_empty.volatile_zones == []
        assert res_empty.zone_sensitivity == []

    def test_robust_high_priority_zones_identification(self, default_config):
        """Identify zones that remain HIGH or CRITICAL across baseline and all scenarios."""
        # Zone Max: 100 score in all scenarios -> CRITICAL in all scenarios
        z_max = _make_zone(
            zone_id="z-max",
            flooded_percent=35.0,
            exposed_buildings=80,
            accessibility="BLOCKED",
            flooded_area_m2=20000.0,
        )
        # Zone Border: HIGH in exposure-heavy, but drops to MEDIUM/LOW in flood-heavy
        z_border = _make_zone(
            zone_id="z-border",
            flooded_percent=1.0,
            exposed_buildings=40,
            accessibility="ACCESSIBLE",
            flooded_area_m2=100.0,
        )
        # Zone Safe: LOW in all scenarios
        z_safe = _make_zone(
            zone_id="z-safe",
            flooded_percent=0.0,
            exposed_buildings=0,
            accessibility="ACCESSIBLE",
            flooded_area_m2=0.0,
        )

        doc = _make_zones_doc(z_max, z_border, z_safe)
        res = analyze_ranking_sensitivity(doc, config=default_config)

        robust_ids = [z["zone_id"] for z in res.robust_high_priority_zones]
        assert "z-max" in robust_ids
        assert "z-border" not in robust_ids
        assert "z-safe" not in robust_ids

        # Check stability verdict and priority observation
        z_max_robust = next(z for z in res.robust_high_priority_zones if z["zone_id"] == "z-max")
        assert "Consistently high priority" in z_max_robust["stability_verdict"]
        assert all(p in ("CRITICAL", "HIGH") for p in z_max_robust["priorities_observed"])

    def test_volatile_zones_identification_and_explanations(self, default_config):
        """Identify zones with substantial rank movement (>= 3 positions) and generate explanations."""
        # Create 5 zones where z-swing has high exposure but low flood,
        # competing with zones having high flood but low exposure
        z_swing = _make_zone(zone_id="z-swing", flooded_percent=2.0, exposed_buildings=50, accessibility="ACCESSIBLE")
        z_flood1 = _make_zone(zone_id="z-fld1", flooded_percent=28.0, exposed_buildings=10, accessibility="PARTIAL")
        z_flood2 = _make_zone(zone_id="z-fld2", flooded_percent=26.0, exposed_buildings=8, accessibility="PARTIAL")
        z_flood3 = _make_zone(zone_id="z-fld3", flooded_percent=24.0, exposed_buildings=6, accessibility="PARTIAL")
        z_flood4 = _make_zone(zone_id="z-fld4", flooded_percent=22.0, exposed_buildings=4, accessibility="PARTIAL")

        doc = _make_zones_doc(z_swing, z_flood1, z_flood2, z_flood3, z_flood4)
        res = analyze_ranking_sensitivity(doc, config=default_config, volatile_rank_threshold=2)

        volatile_ids = [z["zone_id"] for z in res.volatile_zones]
        assert "z-swing" in volatile_ids

        z_v = next(z for z in res.volatile_zones if z["zone_id"] == "z-swing")
        assert z_v["max_rank_delta"] >= 2
        assert "best_scenario" in z_v
        assert "worst_scenario" in z_v
        assert len(z_v["explanation"]) > 0
        assert "z-swing" in z_v["explanation"]

    def test_deterministic_reproducible_output(self, default_config):
        """Multiple runs on the same zones document produce bit-for-bit identical results."""
        z1 = _make_zone(zone_id="z1", flooded_percent=15.0, exposed_buildings=10)
        z2 = _make_zone(zone_id="z2", flooded_percent=25.0, exposed_buildings=5)
        doc = _make_zones_doc(z1, z2)

        res1 = analyze_ranking_sensitivity(doc, config=default_config).to_dict()
        res2 = analyze_ranking_sensitivity(doc, config=default_config).to_dict()

        # Disregard dynamic timestamp_utc
        res1.pop("timestamp_utc")
        res2.pop("timestamp_utc")

        assert json.dumps(res1, sort_keys=True) == json.dumps(res2, sort_keys=True)

    def test_kendall_tau_mathematical_properties(self):
        """Verify Kendall's tau correlation function behavior on identity, inversion, and edge cases."""
        # Self-comparison is always 1.0
        assert sens_compute_kendall_tau(["a", "b", "c"], ["a", "b", "c"]) == 1.0

        # Completely inverted is -1.0
        assert sens_compute_kendall_tau(["a", "b", "c"], ["c", "b", "a"]) == -1.0

        # 1-element or empty is 1.0
        assert sens_compute_kendall_tau(["a"], ["a"]) == 1.0
        assert sens_compute_kendall_tau([], []) == 1.0

        # Partial swap: ["a", "b", "c", "d"] vs ["a", "c", "b", "d"]
        # Total pairs = 6, concordant = 5, discordant = 1 -> tau = (5 - 1) / 6 = 0.6667
        tau_partial = sens_compute_kendall_tau(["a", "b", "c", "d"], ["a", "c", "b", "d"])
        assert math.isclose(tau_partial, 4.0 / 6.0, rel_tol=1e-5)

    def test_disclaimer_and_no_scientific_validation_claims(self, default_config):
        """Results explicitly disclaim empirical predictive ground truth and document assumptions."""
        doc = _make_zones_doc(_make_zone())
        res = analyze_ranking_sensitivity(doc, config=default_config)

        assert "EXPLORATORY SENSITIVITY SCENARIOS" in res.disclaimer
        assert "NOT" in res.disclaimer
        assert "scientifically validated" in res.disclaimer

        for sc in res.scenarios:
            assert len(sc["assumptions"]) > 0
            assert "exploratory" in sc["assumptions"].lower() or "simulat" in sc["assumptions"].lower()

    def test_cli_run_sensitivity_export_and_tool_module(self, tmp_path):
        """Verify CLI run() with sensitivity=True exports sensitivity_analysis.json and tool function works."""
        z1 = _make_zone(zone_id="z-cli-1", flooded_percent=20.0, exposed_buildings=10)
        z2 = _make_zone(zone_id="z-cli-2", flooded_percent=5.0, exposed_buildings=20)
        p_zones = _write_zones(tmp_path, z1, z2)
        out_dir = tmp_path / "cli_sens_out"

        # 1. Test cli_run with sensitivity=True
        out = cli_run(p_zones, out_dir, sensitivity=True)
        assert "_sensitivity_analysis" in out
        sens_file = out_dir / "sensitivity_analysis.json"
        assert sens_file.exists()

        loaded_sens = json.loads(sens_file.read_text(encoding="utf-8"))
        assert loaded_sens["analysis_type"] == "risk_ranking_sensitivity"
        assert loaded_sens["summary"]["total_zones"] == 2
        assert loaded_sens["summary"]["scenarios_tested_count"] == len(DEFAULT_SENSITIVITY_SCENARIOS)

        # 2. Test tools/sensitivity.py run_scenario_sensitivity_analysis
        res_tool = _sens_mod.run_scenario_sensitivity_analysis(p_zones)
        assert res_tool.summary["total_zones"] == 2
        assert len(res_tool.scenarios) == len(DEFAULT_SENSITIVITY_SCENARIOS)


class TestDynamicDataDrivenScoringAndRegression:
    """Rigorous regression and property-based verification of dynamic data-driven scoring.

    Verifies:
    - Different inputs produce different scores/categories.
    - Monotonicity: increasing flood coverage/exposure never reduces risk.
    - Reprocessing updated data dynamically updates output scores and categories.
    - Idempotence: identical inputs yield identical outputs.
    - Boundary thresholds classify strictly and correctly.
    - Missing/invalid data cannot silently become LOW.
    - Leading zeros in zone IDs are preserved through the full pipeline.
    - Zones 024, 030, and 035 reflect their true inputs under documented scoring rules.
    """

    def test_different_inputs_produce_different_scores_and_categories(self, default_config):
        """Varying underlying measurements dynamically shifts risk score and priority category."""
        z_low = _make_zone(
            zone_id="zone-low",
            flooded_percent=1.0,
            flooded_area_m2=200.0,
            total_buildings=20,
            exposed_buildings=1,
            accessibility="ACCESSIBLE",
        )
        z_high = _make_zone(
            zone_id="zone-high",
            flooded_percent=25.0,
            flooded_area_m2=12000.0,
            total_buildings=20,
            exposed_buildings=18,
            accessibility="BLOCKED",
        )
        doc = _make_zones_doc(z_low, z_high)
        recs = score_zones(doc, default_config, [])

        rec_low = next(r for r in recs if r.zone_id == "zone-low")
        rec_high = next(r for r in recs if r.zone_id == "zone-high")

        assert rec_low.score < 20.0
        assert rec_low.priority == "LOW"
        assert rec_high.score >= 45.0
        assert rec_high.priority in ("HIGH", "CRITICAL")
        assert rec_high.score > rec_low.score

    @settings(max_examples=40, deadline=None)
    @given(
        fp1=st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
        fp2=st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    )
    def test_monotonicity_flood_percent_property(self, fp1, fp2):
        """Higher flood percentage strictly cannot result in a lower risk score."""
        cfg = load_config()
        low_fp, high_fp = sorted([fp1, fp2])
        z1 = _make_zone(zone_id="z1", flooded_percent=low_fp, exposed_buildings=5, flooded_area_m2=1000.0)
        z2 = _make_zone(zone_id="z2", flooded_percent=high_fp, exposed_buildings=5, flooded_area_m2=1000.0)

        res1 = calculate_zone_risk(z1, cfg)
        res2 = calculate_zone_risk(z2, cfg)

        assert res2["score"] >= res1["score"], f"Monotonicity violated: {high_fp}% got {res2['score']} < {low_fp}% got {res1['score']}"

    @settings(max_examples=40, deadline=None)
    @given(
        b1=st.integers(min_value=0, max_value=75),
        b2=st.integers(min_value=0, max_value=75),
    )
    def test_monotonicity_exposed_buildings_property(self, b1, b2):
        """More exposed buildings strictly cannot result in a lower risk score."""
        cfg = load_config()
        low_b, high_b = sorted([b1, b2])
        z1 = _make_zone(zone_id="z1", flooded_percent=5.0, exposed_buildings=low_b, flooded_area_m2=1000.0)
        z2 = _make_zone(zone_id="z2", flooded_percent=5.0, exposed_buildings=high_b, flooded_area_m2=1000.0)

        res1 = calculate_zone_risk(z1, cfg)
        res2 = calculate_zone_risk(z2, cfg)

        assert res2["score"] >= res1["score"], f"Monotonicity violated: {high_b} bldgs got {res2['score']} < {low_b} bldgs got {res1['score']}"

    def test_monotonicity_accessibility_penalty(self, default_config):
        """Moving from ACCESSIBLE to PARTIAL to BLOCKED strictly increases risk score."""
        z_acc = _make_zone(zone_id="z-acc", flooded_percent=10.0, exposed_buildings=5, accessibility="ACCESSIBLE")
        z_part = _make_zone(zone_id="z-part", flooded_percent=10.0, exposed_buildings=5, accessibility="PARTIAL")
        z_blk = _make_zone(zone_id="z-blk", flooded_percent=10.0, exposed_buildings=5, accessibility="BLOCKED")

        r_acc = calculate_zone_risk(z_acc, default_config)
        r_part = calculate_zone_risk(z_part, default_config)
        r_blk = calculate_zone_risk(z_blk, default_config)

        assert r_blk["score"] > r_part["score"] > r_acc["score"]
        assert math.isclose(r_part["score"] - r_acc["score"], 7.5, abs_tol=0.1)
        assert math.isclose(r_blk["score"] - r_part["score"], 7.5, abs_tol=0.1)

    def test_reprocessing_updated_dataset_updates_outputs_without_code_change(self, tmp_path, default_config):
        """Reprocessing an updated input dataset dynamically alters output scores and priorities."""
        out_dir = tmp_path / "dynamic_out"
        zones_file = tmp_path / "zones.json"

        # Pass 1: Zone 024 has low water
        z = _make_zone(zone_id="zone-024", flooded_percent=0.24, flooded_area_m2=211.9, exposed_buildings=2, accessibility="ACCESSIBLE")
        zones_file.write_text(json.dumps(_make_zones_doc(z)), encoding="utf-8")

        cli_run(zones_file, out_dir, output_format="dashboard")
        dash_out_1 = json.loads((out_dir / "zones.json").read_text(encoding="utf-8"))
        z_res1 = dash_out_1["zones"][0]
        assert z_res1["risk_score"] == 1.5
        assert z_res1["risk_level"] == "LOW"

        # Pass 2: Extreme flood arrives at zone 024 (e.g. 28% flooded, 30 exposed buildings, blocked roads)
        z_updated = _make_zone(zone_id="zone-024", flooded_percent=28.0, flooded_area_m2=14000.0, exposed_buildings=30, accessibility="BLOCKED")
        zones_file.write_text(json.dumps(_make_zones_doc(z_updated)), encoding="utf-8")

        cli_run(zones_file, out_dir, output_format="dashboard")
        dash_out_2 = json.loads((out_dir / "zones.json").read_text(encoding="utf-8"))
        z_res2 = dash_out_2["zones"][0]
        assert z_res2["risk_score"] > 60.0
        assert z_res2["risk_level"] in ("HIGH", "CRITICAL")
        assert z_res2["risk_level"] != "LOW"

    def test_identical_inputs_produce_identical_results(self, default_config):
        """Identical inputs and configuration are completely deterministic."""
        z = _make_zone(zone_id="zone-024", flooded_percent=12.5, flooded_area_m2=5400.0, exposed_buildings=7, accessibility="PARTIAL")
        res1 = calculate_zone_risk(z, default_config)
        res2 = calculate_zone_risk(z, default_config)

        assert res1 == res2
        assert res1["score"] == res2["score"]
        assert res1["priority"] == res2["priority"]

    def test_score_to_category_thresholds_boundaries(self, default_config):
        """Verify strict behavior at category threshold boundaries."""
        thresholds = default_config.get("priority_thresholds") or default_config.get("scoring", {}).get("priority_thresholds")

        # CRITICAL boundary: 70.0
        assert classify_risk_score(70.0, thresholds) == "CRITICAL"
        assert classify_risk_score(69.99, thresholds) == "HIGH"

        # HIGH boundary: 45.0
        assert classify_risk_score(45.0, thresholds) == "HIGH"
        assert classify_risk_score(44.99, thresholds) == "MEDIUM"

        # MEDIUM boundary: 20.0
        assert classify_risk_score(20.0, thresholds) == "MEDIUM"
        assert classify_risk_score(19.99, thresholds) == "LOW"

        # LOW boundary: 0.0
        assert classify_risk_score(0.0, thresholds) == "LOW"
        assert classify_risk_score(0.01, thresholds) == "LOW"

        # Invalid / Negative / Missing
        assert classify_risk_score(-0.01, thresholds) == "UNKNOWN"
        assert classify_risk_score(-10.0, thresholds) == "UNKNOWN"
        assert classify_risk_score(None, thresholds) == "UNKNOWN"
        assert classify_risk_score(float("nan"), thresholds) == "UNKNOWN"
        assert classify_risk_score(float("inf"), thresholds) == "UNKNOWN"

    def test_missing_and_invalid_data_cannot_silently_become_low(self, default_config):
        """Missing or corrupt input measurements cannot silently be scored as LOW risk."""
        # Zone missing exposed_buildings
        z_bad = _make_zone(zone_id="zone-bad")
        del z_bad["exposed_buildings"]

        doc = _make_zones_doc(z_bad)
        warnings = [DataQualityWarning(zone_id="zone-bad", field="exposed_buildings", issue="missing")]
        recs = score_zones(doc, default_config, warnings)

        assert len(recs) == 1
        r = recs[0]
        # Must be flagged as UNKNOWN and insufficient data
        assert r.priority == "UNKNOWN"
        assert r.score is None
        assert r.score_basis in ("none", "insufficient_data")

    def test_zone_ids_leading_zeros_preserved(self, default_config):
        """Leading zeros in zone IDs like zone-001, zone-024, 035 are preserved without string/int truncation."""
        z1 = _make_zone(zone_id="zone-001")
        z2 = _make_zone(zone_id="zone-024")
        z3 = _make_zone(zone_id="035")

        doc = _make_zones_doc(z1, z2, z3)
        recs = score_zones(doc, default_config, [])
        scored_ids = [r.zone_id for r in recs]

        assert "zone-001" in scored_ids
        assert "zone-024" in scored_ids
        assert "035" in scored_ids
        assert not any(sid in scored_ids for sid in ["zone-1", "zone-24", "35", 1, 24, 35])

    def test_zones_024_030_035_exact_scores_and_categories(self, default_config):
        """Zones 024, 030, and 035 strictly match their authentic measurements and documented model."""
        # Zone 024: 0.24% flooded, 211.9 m2, 2/2 buildings, ACCESSIBLE
        z024 = _make_zone(
            zone_id="zone-024",
            flooded_percent=0.24,
            flooded_area_m2=211.9,
            total_buildings=2,
            exposed_buildings=2,
            road_length_m=130.6,
            flooded_road_length_m=10.8,
            accessibility="ACCESSIBLE",
        )
        # Zone 030: 1.90% flooded, 1710.9 m2, 0/18 buildings, PARTIAL
        z030 = _make_zone(
            zone_id="zone-030",
            flooded_percent=1.90,
            flooded_area_m2=1710.9,
            total_buildings=18,
            exposed_buildings=0,
            road_length_m=749.1,
            flooded_road_length_m=168.1,
            accessibility="PARTIAL",
        )
        # Zone 035: 4.42% flooded, 3976.4 m2, 14/44 buildings, PARTIAL
        z035 = _make_zone(
            zone_id="zone-035",
            flooded_percent=4.42,
            flooded_area_m2=3976.4,
            total_buildings=44,
            exposed_buildings=14,
            road_length_m=1389.9,
            flooded_road_length_m=225.0,
            accessibility="PARTIAL",
        )

        r024 = calculate_zone_risk(z024, default_config)
        r030 = calculate_zone_risk(z030, default_config)
        r035 = calculate_zone_risk(z035, default_config)

        # 024: very minor flood -> LOW (score ~ 1.5)
        assert r024["score"] == 1.5
        assert r024["priority"] == "LOW"

        # 030: 0 exposed buildings, partial isolation gives 7.5 pts -> LOW (score ~ 10.9)
        assert r030["score"] == 10.9
        assert r030["priority"] == "LOW"

        # 035: 14 exposed buildings + 7.5 isolation -> MEDIUM (score ~ 22.8, crossing >= 20.0 threshold)
        assert r035["score"] == 22.8
        assert r035["priority"] == "MEDIUM"
