"""HighWater — Module 3: Risk & Prioritization Engine.

Consumes Module 2 zone data (zones.json) and produces a ranked list of zones
with deterministic 0-100 priority scores, human-readable reasons, and
data-quality warnings. Output is versioned JSON suitable for downstream
consumption by the dashboard and rescue-routing modules.
"""

from risk_engine.config import (
    DEFAULT_WEIGHTS,
    DataQualityConfig,
    IsolationScores,
    NormalizationCeilings,
    PriorityThresholds,
    RiskEngineConfig,
    ScoringConfig,
    ScoringWeights,
    load_config as load_config_dict,
    load_config_object,
    parse_weights_arg,
    validate_config,
    weights_fingerprint,
)
from risk_engine.scorer import (
    ConfigError,
    DataQualityWarning,
    InputValidationError,
    ZoneDataQualityAssessment,
    ZoneRiskRecord,
    compute_score_breakdown,
    export_dashboard,
    load_config,
    load_zones,
    records_to_dict,
    score_zones,
)
from risk_engine.sensitivity import (
    DEFAULT_SENSITIVITY_SCENARIOS,
    ScenarioComparison,
    SensitivityAnalysisResult,
    SensitivityScenario,
    ZoneSensitivityRecord,
    analyze_ranking_sensitivity,
    compute_kendall_tau,
)

__all__ = [
    "DEFAULT_SENSITIVITY_SCENARIOS",
    "DEFAULT_WEIGHTS",
    "ConfigError",
    "DataQualityConfig",
    "DataQualityWarning",
    "InputValidationError",
    "IsolationScores",
    "NormalizationCeilings",
    "PriorityThresholds",
    "RiskEngineConfig",
    "ScenarioComparison",
    "ScoringConfig",
    "ScoringWeights",
    "SensitivityAnalysisResult",
    "SensitivityScenario",
    "ZoneDataQualityAssessment",
    "ZoneRiskRecord",
    "ZoneSensitivityRecord",
    "analyze_ranking_sensitivity",
    "compute_kendall_tau",
    "compute_score_breakdown",
    "export_dashboard",
    "load_config",
    "load_config_dict",
    "load_config_object",
    "load_zones",
    "parse_weights_arg",
    "records_to_dict",
    "score_zones",
    "validate_config",
    "weights_fingerprint",
]

