"""Risk-Ranking Sensitivity Analysis for HighWater Module 3 (Risk Engine).

Provides standalone, deterministic sensitivity analysis capabilities to evaluate
how robust zone priority rankings and risk scores are under reasonable, reproducible
alternative weight scenarios without modifying baseline results or rankings.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from risk_engine.config import (
    DEFAULT_WEIGHTS,
    ConfigError,
    RiskEngineConfig,
    ScoringWeights,
    load_config,
    validate_config,
    weights_fingerprint,
)
from risk_engine.scorer import (
    InputValidationError,
    ZoneRiskRecord,
    load_zones,
    score_zones,
)


# ---------------------------------------------------------------------------
# Kendall's Tau Rank Correlation Metric
# ---------------------------------------------------------------------------

def compute_kendall_tau(ranking_a: list[str], ranking_b: list[str]) -> float:
    """Compute Kendall's tau rank correlation between two permutations of zone_ids.

    Returns 1.0 if both rankings are identical or if n <= 1.
    Returns -1.0 if rankings are perfectly inverted.
    """
    if len(ranking_a) != len(ranking_b) or not ranking_a:
        return 1.0

    n = len(ranking_a)
    if n <= 1:
        return 1.0

    pos_b = {zid: idx for idx, zid in enumerate(ranking_b)}
    items = [pos_b[zid] for zid in ranking_a if zid in pos_b]
    if len(items) != n:
        # Mismatched zone sets
        return 0.0

    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if items[i] < items[j]:
                concordant += 1
            elif items[i] > items[j]:
                discordant += 1

    total_pairs = n * (n - 1) / 2
    if total_pairs == 0:
        return 1.0
    return (concordant - discordant) / total_pairs


# ---------------------------------------------------------------------------
# Sensitivity Scenario Definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SensitivityScenario:
    """Explicit, reproducible weight configuration scenario for sensitivity testing.

    Weights must satisfy all standard RiskEngineConfig validation constraints
    (finite, non-negative, and summing to 1.0).
    """
    name: str
    weights: dict[str, float]
    description: str = ""
    assumptions: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate scenario weights against the engine's ScoringWeights rules."""
        if not self.name or not isinstance(self.name, str):
            raise ConfigError("Scenario name must be a non-empty string")
        if not isinstance(self.weights, dict):
            raise ConfigError(f"Scenario '{self.name}' weights must be a dictionary; got {type(self.weights).__name__}")
        # Validates numeric, non-negative, required keys, and sum == 1.0
        ScoringWeights.from_dict(self.weights)

    def fingerprint(self) -> str:
        """Deterministic 16-hex fingerprint of scenario weights."""
        return weights_fingerprint(self.weights)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weights": {k: float(v) for k, v in self.weights.items()},
            "weights_fingerprint": self.fingerprint(),
            "description": self.description,
            "assumptions": self.assumptions,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SensitivityScenario:
        if not isinstance(d, dict):
            raise ConfigError("Scenario must be a dictionary")
        name = d.get("name")
        if not name:
            raise ConfigError("Scenario missing required 'name' field")
        weights = d.get("weights")
        if not weights or not isinstance(weights, dict):
            raise ConfigError(f"Scenario '{name}' missing valid 'weights' dictionary")
        return cls(
            name=str(name),
            weights=weights,
            description=str(d.get("description", "")),
            assumptions=str(d.get("assumptions", "")),
        )


# Standard curated exploratory scenarios with explicit assumptions
DEFAULT_SENSITIVITY_SCENARIOS: list[SensitivityScenario] = [
    SensitivityScenario(
        name="equal_weights",
        weights={
            "flood_percent": 0.25,
            "exposure": 0.25,
            "isolation": 0.25,
            "flood_area_density": 0.25,
            "exposure_fraction": 0.0,
        },
        description="Equal weight distribution across all four primary risk components.",
        assumptions="Exploratory neutral baseline assuming no single risk component has operational priority.",
    ),
    SensitivityScenario(
        name="exposure_heavy",
        weights={
            "flood_percent": 0.20,
            "exposure": 0.55,
            "isolation": 0.15,
            "flood_area_density": 0.10,
            "exposure_fraction": 0.0,
        },
        description="High building exposure weighting prioritizing structural vulnerability.",
        assumptions="Exploratory scenario simulating urban search-and-rescue where structural density dominates dispatch.",
    ),
    SensitivityScenario(
        name="flood_coverage_heavy",
        weights={
            "flood_percent": 0.55,
            "exposure": 0.20,
            "isolation": 0.15,
            "flood_area_density": 0.10,
            "exposure_fraction": 0.0,
        },
        description="High flood coverage weighting prioritizing relative inundated zone percentage.",
        assumptions="Exploratory scenario simulating wide-area flood monitoring where zone saturation drives emergency declarations.",
    ),
    SensitivityScenario(
        name="isolation_heavy",
        weights={
            "flood_percent": 0.25,
            "exposure": 0.20,
            "isolation": 0.45,
            "flood_area_density": 0.10,
            "exposure_fraction": 0.0,
        },
        description="High road isolation weighting prioritizing cut-off and inaccessible zones.",
        assumptions="Exploratory scenario simulating access-constrained operations where road blockages require specialized air or boat assets.",
    ),
    SensitivityScenario(
        name="areal_extent_heavy",
        weights={
            "flood_percent": 0.25,
            "exposure": 0.25,
            "isolation": 0.15,
            "flood_area_density": 0.35,
            "exposure_fraction": 0.0,
        },
        description="High flooded area density weighting prioritizing total absolute surface area inundated.",
        assumptions="Exploratory scenario simulating physical water volume response where expansive footprints dictate heavy drainage equipment.",
    ),
]


# ---------------------------------------------------------------------------
# Results Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ScenarioComparison:
    """Metrics comparing a single scenario's ranking against baseline."""
    scenario_name: str
    description: str
    assumptions: str
    weights: dict[str, float]
    weights_fingerprint: str
    kendall_tau: float
    max_rank_change: int
    mean_rank_change: float
    max_score_change: float
    mean_score_change: float
    priority_changes_count: int
    priority_changes_percent: float
    top_k_overlap_count: int
    top_k_overlap_percent: float
    high_priority_overlap_count: int
    high_priority_overlap_percent: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "description": self.description,
            "assumptions": self.assumptions,
            "weights": self.weights,
            "weights_fingerprint": self.weights_fingerprint,
            "kendall_tau": self.kendall_tau,
            "max_rank_change": self.max_rank_change,
            "mean_rank_change": self.mean_rank_change,
            "max_score_change": self.max_score_change,
            "mean_score_change": self.mean_score_change,
            "priority_changes_count": self.priority_changes_count,
            "priority_changes_percent": self.priority_changes_percent,
            "top_k_overlap_count": self.top_k_overlap_count,
            "top_k_overlap_percent": self.top_k_overlap_percent,
            "high_priority_overlap_count": self.high_priority_overlap_count,
            "high_priority_overlap_percent": self.high_priority_overlap_percent,
        }


@dataclass
class ZoneSensitivityRecord:
    """Zone-specific score and rank movement tracked across all scenarios."""
    zone_id: str
    baseline_rank: int
    baseline_score: float
    baseline_priority: str
    min_score: float
    max_score: float
    mean_score: float
    max_score_delta: float
    min_rank: int
    max_rank: int
    mean_rank: float
    max_rank_delta: int
    scores_by_scenario: dict[str, float]
    ranks_by_scenario: dict[str, int]
    priorities_by_scenario: dict[str, str]
    priority_shifts: list[dict[str, str]]
    is_robust_high_priority: bool
    is_robust_top_k: bool
    is_volatile: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "baseline_rank": self.baseline_rank,
            "baseline_score": self.baseline_score,
            "baseline_priority": self.baseline_priority,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "mean_score": self.mean_score,
            "max_score_delta": self.max_score_delta,
            "min_rank": self.min_rank,
            "max_rank": self.max_rank,
            "mean_rank": self.mean_rank,
            "max_rank_delta": self.max_rank_delta,
            "scores_by_scenario": self.scores_by_scenario,
            "ranks_by_scenario": self.ranks_by_scenario,
            "priorities_by_scenario": self.priorities_by_scenario,
            "priority_shifts": self.priority_shifts,
            "is_robust_high_priority": self.is_robust_high_priority,
            "is_robust_top_k": self.is_robust_top_k,
            "is_volatile": self.is_volatile,
        }


@dataclass
class SensitivityAnalysisResult:
    """Complete, self-contained sensitivity analysis report."""
    schema_version: str = "1.0"
    analysis_type: str = "risk_ranking_sensitivity"
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    disclaimer: str = (
        "EXPLORATORY SENSITIVITY SCENARIOS — Alternative weight configurations represent "
        "hypothetical operational priorities to test ranking stability. They are NOT "
        "scientifically validated, empirical, or predictive models of flood damage or casualty risk."
    )
    summary: dict[str, Any] = field(default_factory=dict)
    baseline: dict[str, Any] = field(default_factory=dict)
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    robust_high_priority_zones: list[dict[str, Any]] = field(default_factory=list)
    volatile_zones: list[dict[str, Any]] = field(default_factory=list)
    zone_sensitivity: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "analysis_type": self.analysis_type,
            "timestamp_utc": self.timestamp_utc,
            "disclaimer": self.disclaimer,
            "summary": self.summary,
            "baseline": self.baseline,
            "scenarios": self.scenarios,
            "robust_high_priority_zones": self.robust_high_priority_zones,
            "volatile_zones": self.volatile_zones,
            "zone_sensitivity": self.zone_sensitivity,
        }


# ---------------------------------------------------------------------------
# Core Analysis Engine
# ---------------------------------------------------------------------------

def _build_volatility_explanation(
    zone_id: str,
    base_rank: int,
    best_rank: int,
    best_scen: str,
    worst_rank: int,
    worst_scen: str,
    rec: ZoneRiskRecord,
) -> str:
    """Generate concise, factual explanation for why a zone experienced ranking shifts."""
    details = []
    if rec.exposed_buildings >= 20:
        details.append(f"high exposed building count ({rec.exposed_buildings})")
    elif rec.exposed_buildings == 0:
        details.append("zero building exposure")

    if rec.flooded_percent >= 40.0:
        details.append(f"high flood coverage ({rec.flooded_percent:.1f}%)")
    elif rec.flooded_percent <= 5.0:
        details.append(f"low flood coverage ({rec.flooded_percent:.1f}%)")

    if rec.accessibility == "BLOCKED":
        details.append("severe road blockage (BLOCKED)")
    elif rec.accessibility == "ACCESSIBLE":
        details.append("fully accessible roads")

    contrast_str = ", and ".join(details) if details else "differing relative factor balances"
    return (
        f"Zone {zone_id} shifts between rank #{best_rank} under '{best_scen}' and "
        f"rank #{worst_rank} under '{worst_scen}' (baseline rank #{base_rank}), "
        f"driven by {contrast_str}."
    )


def analyze_ranking_sensitivity(
    zones: dict[str, Any] | list[dict[str, Any]] | Path | str,
    config: dict[str, Any] | RiskEngineConfig | Path | str | None = None,
    scenarios: list[SensitivityScenario | dict[str, Any]] | dict[str, dict[str, float]] | None = None,
    top_k: int = 5,
    volatile_rank_threshold: int = 3,
) -> SensitivityAnalysisResult:
    """Perform standalone sensitivity analysis of risk scores and rankings under multiple weight scenarios.

    Requirements addressed:
        - Evaluates zones under multiple explicitly supplied, valid weight configurations.
        - Validates all scenarios using the same rules as the main scoring engine.
        - Compares score changes, priority-category changes, rank movement, and top-priority membership.
        - Identifies zones with substantial rank movement (volatile zones).
        - Identifies zones that remain high priority across all scenarios (robust high-priority zones).
        - Preserves baseline configuration, scores, and rankings completely unmodified.
        - Deterministic, reproducible, and includes explicit disclaimers without false validation claims.
    """
    # 1. Resolve and validate baseline configuration
    if config is None:
        base_config = load_config()
    elif isinstance(config, (Path, str)):
        base_config = load_config(Path(config))
    elif isinstance(config, RiskEngineConfig):
        base_config = config.to_dict()
    elif isinstance(config, dict):
        base_config = copy.deepcopy(config)
        validate_config(base_config)
    else:
        raise ConfigError(f"Unsupported config type: {type(config).__name__}")

    # 2. Resolve and load zones document
    if isinstance(zones, (Path, str)):
        zones_doc, warnings = load_zones(Path(zones), config=base_config)
    elif isinstance(zones, dict):
        zones_doc = copy.deepcopy(zones)
        if "zones" not in zones_doc:
            raise InputValidationError("zones document missing required 'zones' key")
        warnings = []
    elif isinstance(zones, list):
        zones_doc = {"zones": copy.deepcopy(zones)}
        warnings = []
    else:
        raise InputValidationError(f"Unsupported zones input type: {type(zones).__name__}")

    zone_items = zones_doc.get("zones", [])
    total_zones = len(zone_items)

    # 3. Score baseline zones (original ranking and scores remain untouched)
    baseline_records = score_zones(zones_doc, base_config, warnings)
    base_by_id: dict[str, ZoneRiskRecord] = {r.zone_id: r for r in baseline_records}
    base_order = [r.zone_id for r in baseline_records]
    base_top_k_set = set(base_order[:top_k])
    base_high_priority_set = {r.zone_id for r in baseline_records if r.priority in ("CRITICAL", "HIGH")}

    # 4. Resolve and validate scenarios
    resolved_scenarios: list[SensitivityScenario] = []
    if scenarios is None:
        resolved_scenarios = list(DEFAULT_SENSITIVITY_SCENARIOS)
    elif isinstance(scenarios, dict):
        for sname, sweights in scenarios.items():
            resolved_scenarios.append(SensitivityScenario(
                name=str(sname),
                weights=sweights,
                description=f"Custom scenario '{sname}'",
                assumptions="User-supplied weight scenario for sensitivity analysis.",
            ))
    elif isinstance(scenarios, list):
        for item in scenarios:
            if isinstance(item, SensitivityScenario):
                resolved_scenarios.append(item)
            elif isinstance(item, dict):
                resolved_scenarios.append(SensitivityScenario.from_dict(item))
            else:
                raise ConfigError(f"Invalid scenario item type: {type(item).__name__}")
    else:
        raise ConfigError(f"Unsupported scenarios input type: {type(scenarios).__name__}")

    if not resolved_scenarios:
        raise ConfigError("At least one sensitivity scenario must be provided")

    # Ensure all scenario weights are strictly validated
    for s in resolved_scenarios:
        s.validate()

    # 5. Evaluate each scenario
    scenario_comparisons: list[ScenarioComparison] = []
    scenario_records_map: dict[str, list[ZoneRiskRecord]] = {}

    for scen in resolved_scenarios:
        # Create a validated engine config for this scenario
        scen_cfg = RiskEngineConfig.from_dict(base_config).with_weights(scen.weights).to_dict()
        # Score zones with identical deterministic tie-breaking and data-quality rules
        scen_recs = score_zones(zones_doc, scen_cfg, warnings)
        scenario_records_map[scen.name] = scen_recs

        scen_order = [r.zone_id for r in scen_recs]
        scen_by_id = {r.zone_id: r for r in scen_recs}
        scen_top_k_set = set(scen_order[:top_k])
        scen_high_priority_set = {r.zone_id for r in scen_recs if r.priority in ("CRITICAL", "HIGH")}

        # Metric 1: Kendall's Tau Rank Correlation
        tau = compute_kendall_tau(base_order, scen_order)

        # Metric 2: Rank movements across all zones
        rank_changes = [
            abs(scen_by_id[zid].rank - base_by_id[zid].rank)
            for zid in base_order
        ]
        max_rank_change = max(rank_changes) if rank_changes else 0
        mean_rank_change = (sum(rank_changes) / total_zones) if total_zones > 0 else 0.0

        # Metric 3: Score changes across all zones
        score_changes = [
            abs(scen_by_id[zid].score - base_by_id[zid].score)
            for zid in base_order
        ]
        max_score_change = max(score_changes) if score_changes else 0.0
        mean_score_change = (sum(score_changes) / total_zones) if total_zones > 0 else 0.0

        # Metric 4: Priority category shifts
        priority_changes_count = sum(
            1 for zid in base_order
            if scen_by_id[zid].priority != base_by_id[zid].priority
        )
        priority_changes_pct = (
            round((priority_changes_count / total_zones) * 100.0, 1)
            if total_zones > 0
            else 0.0
        )

        # Metric 5: Top-K and High-Priority overlap
        top_k_overlap = len(base_top_k_set & scen_top_k_set)
        top_k_overlap_pct = (
            round((top_k_overlap / min(top_k, max(1, total_zones))) * 100.0, 1)
            if total_zones > 0
            else 100.0
        )

        hp_overlap = len(base_high_priority_set & scen_high_priority_set)
        hp_total = len(base_high_priority_set | scen_high_priority_set)
        hp_overlap_pct = (
            round((hp_overlap / hp_total) * 100.0, 1)
            if hp_total > 0
            else 100.0
        )

        scenario_comparisons.append(ScenarioComparison(
            scenario_name=scen.name,
            description=scen.description,
            assumptions=scen.assumptions,
            weights=scen.weights,
            weights_fingerprint=scen.fingerprint(),
            kendall_tau=round(tau, 4),
            max_rank_change=max_rank_change,
            mean_rank_change=round(mean_rank_change, 2),
            max_score_change=round(max_score_change, 1),
            mean_score_change=round(mean_score_change, 2),
            priority_changes_count=priority_changes_count,
            priority_changes_percent=priority_changes_pct,
            top_k_overlap_count=top_k_overlap,
            top_k_overlap_percent=top_k_overlap_pct,
            high_priority_overlap_count=hp_overlap,
            high_priority_overlap_percent=hp_overlap_pct,
        ))

    # 6. Aggregate multi-scenario metrics per zone
    zone_records: list[ZoneSensitivityRecord] = []
    robust_high_priority_zones: list[dict[str, Any]] = []
    volatile_zones: list[dict[str, Any]] = []

    for zid in base_order:
        base_r = base_by_id[zid]
        scores_by_scen: dict[str, float] = {}
        ranks_by_scen: dict[str, int] = {}
        prios_by_scen: dict[str, str] = {}
        priority_shifts: list[dict[str, str]] = []

        all_scores = [base_r.score]
        all_ranks = [base_r.rank]
        all_prios = [base_r.priority]

        for scen in resolved_scenarios:
            scen_r = next(r for r in scenario_records_map[scen.name] if r.zone_id == zid)
            scores_by_scen[scen.name] = scen_r.score
            ranks_by_scen[scen.name] = scen_r.rank
            prios_by_scen[scen.name] = scen_r.priority

            all_scores.append(scen_r.score)
            all_ranks.append(scen_r.rank)
            all_prios.append(scen_r.priority)

            if scen_r.priority != base_r.priority:
                priority_shifts.append({
                    "scenario": scen.name,
                    "from_priority": base_r.priority,
                    "to_priority": scen_r.priority,
                    "score_delta": round(scen_r.score - base_r.score, 1),
                })

        min_score = min(all_scores)
        max_score = max(all_scores)
        mean_score = round(sum(all_scores) / len(all_scores), 1)
        max_score_delta = round(max(abs(s - base_r.score) for s in all_scores), 1)

        min_rank = min(all_ranks)
        max_rank = max(all_ranks)
        mean_rank = round(sum(all_ranks) / len(all_ranks), 1)
        max_rank_delta = max(abs(rk - base_r.rank) for rk in all_ranks)

        # Robust High Priority criteria:
        # Zone is CRITICAL or HIGH in baseline AND in EVERY evaluated scenario
        is_robust_hp = all(p in ("CRITICAL", "HIGH") for p in all_prios)

        # Robust Top-K criteria:
        # Zone is in top-K in baseline AND in EVERY evaluated scenario
        is_robust_tk = all(rk <= top_k for rk in all_ranks)

        # Volatility criteria:
        # Substantial rank movement (max rank delta >= threshold) or priority changes
        is_volatile = (max_rank_delta >= volatile_rank_threshold) or (len(priority_shifts) > 0)

        record = ZoneSensitivityRecord(
            zone_id=zid,
            baseline_rank=base_r.rank,
            baseline_score=base_r.score,
            baseline_priority=base_r.priority,
            min_score=min_score,
            max_score=max_score,
            mean_score=mean_score,
            max_score_delta=max_score_delta,
            min_rank=min_rank,
            max_rank=max_rank,
            mean_rank=mean_rank,
            max_rank_delta=max_rank_delta,
            scores_by_scenario=scores_by_scen,
            ranks_by_scenario=ranks_by_scen,
            priorities_by_scenario=prios_by_scen,
            priority_shifts=priority_shifts,
            is_robust_high_priority=is_robust_hp,
            is_robust_top_k=is_robust_tk,
            is_volatile=is_volatile,
        )
        zone_records.append(record)

        # Populate robust high-priority zones list
        if is_robust_hp:
            robust_high_priority_zones.append({
                "zone_id": zid,
                "baseline_rank": base_r.rank,
                "baseline_score": base_r.score,
                "baseline_priority": base_r.priority,
                "min_score": min_score,
                "max_score": max_score,
                "min_rank": min_rank,
                "max_rank": max_rank,
                "priorities_observed": sorted(set(all_prios)),
                "stability_verdict": "Consistently high priority across all tested scenarios",
            })

        # Populate volatile zones list
        if max_rank_delta >= volatile_rank_threshold:
            # Find best and worst scenarios
            best_scen = min(ranks_by_scen.items(), key=lambda x: x[1])[0]
            worst_scen = max(ranks_by_scen.items(), key=lambda x: x[1])[0]

            explanation = _build_volatility_explanation(
                zid, base_r.rank, min_rank, best_scen, max_rank, worst_scen, base_r
            )
            volatile_zones.append({
                "zone_id": zid,
                "baseline_rank": base_r.rank,
                "baseline_score": base_r.score,
                "baseline_priority": base_r.priority,
                "max_rank_delta": max_rank_delta,
                "best_rank": min_rank,
                "best_scenario": best_scen,
                "worst_rank": max_rank,
                "worst_scenario": worst_scen,
                "score_range": [min_score, max_score],
                "priority_shifts": priority_shifts,
                "explanation": explanation,
            })

    # Sort volatile zones by largest rank movement descending, then baseline rank ascending
    volatile_zones.sort(key=lambda z: (-z["max_rank_delta"], z["baseline_rank"]))

    # Sort robust high-priority zones by baseline rank ascending
    robust_high_priority_zones.sort(key=lambda z: z["baseline_rank"])

    # 7. Identify summary extremes
    avg_tau = (
        round(sum(c.kendall_tau for c in scenario_comparisons) / len(scenario_comparisons), 4)
        if scenario_comparisons
        else 1.0
    )
    sorted_by_destabilization = sorted(scenario_comparisons, key=lambda c: (c.kendall_tau, -c.max_rank_change))
    most_destabilizing = sorted_by_destabilization[0].scenario_name if sorted_by_destabilization else None
    most_stable = sorted_by_destabilization[-1].scenario_name if sorted_by_destabilization else None

    base_weights_clean = {k: float(v) for k, v in base_config["scoring"]["weights"].items() if not k.startswith("_")}
    summary = {
        "total_zones": total_zones,
        "scenarios_tested_count": len(resolved_scenarios),
        "robust_high_priority_count": len(robust_high_priority_zones),
        "volatile_zones_count": len(volatile_zones),
        "average_kendall_tau": avg_tau,
        "most_destabilizing_scenario": most_destabilizing,
        "most_stable_scenario": most_stable,
        "volatile_rank_threshold": volatile_rank_threshold,
    }

    baseline_info = {
        "config_version": base_config.get("config_version", "1.0"),
        "weights": base_weights_clean,
        "weights_fingerprint": weights_fingerprint(base_weights_clean),
        "priority_thresholds": {k: float(v) for k, v in base_config["priority_thresholds"].items() if not k.startswith("_")},
    }

    return SensitivityAnalysisResult(
        schema_version="1.0",
        analysis_type="risk_ranking_sensitivity",
        disclaimer=(
            "EXPLORATORY SENSITIVITY SCENARIOS — Alternative weight configurations represent "
            "hypothetical operational priorities to test ranking stability. They are NOT "
            "scientifically validated, empirical, or predictive models of flood damage or casualty risk."
        ),
        summary=summary,
        baseline=baseline_info,
        scenarios=[sc.to_dict() for sc in scenario_comparisons],
        robust_high_priority_zones=robust_high_priority_zones,
        volatile_zones=volatile_zones,
        zone_sensitivity=[zr.to_dict() for zr in zone_records],
    )
