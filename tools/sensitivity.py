"""Sensitivity analysis tool for HighWater Module 3 (Risk Engine).

Perturbs model weights, isolation scores, and priority thresholds.
Measures stability against baseline ranking using Kendall's tau,
top-5 overlap, and priority change counts.
"""

from __future__ import annotations

import argparse
import copy
import math
from pathlib import Path
from typing import Any

from risk_engine.scorer import (
    load_config,
    load_zones,
    score_zones,
)


def compute_kendall_tau(ranking_a: list[str], ranking_b: list[str]) -> float:
    """Compute Kendall's tau rank correlation between two permutations of zone_ids.

    For baseline compared with itself, returns 1.0.
    """
    if len(ranking_a) != len(ranking_b) or not ranking_a:
        return 1.0

    n = len(ranking_a)
    if n <= 1:
        return 1.0

    pos_b = {zid: idx for idx, zid in enumerate(ranking_b)}
    items = [pos_b[zid] for zid in ranking_a]

    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if items[i] < items[j]:
                concordant += 1
            elif items[i] > items[j]:
                discordant += 1

    total_pairs = n * (n - 1) / 2
    return (concordant - discordant) / total_pairs


def evaluate_perturbation(
    perturbed_config: dict[str, Any],
    zones_doc: dict[str, Any],
    warnings: list[Any],
    baseline_order: list[str],
    baseline_priorities: dict[str, str],
) -> dict[str, Any]:
    """Score zones with perturbed config and compute stability metrics against baseline."""
    records = score_zones(zones_doc, perturbed_config, warnings)
    perturbed_order = [r.zone_id for r in records]
    perturbed_priorities = {r.zone_id: r.priority for r in records}

    tau = compute_kendall_tau(baseline_order, perturbed_order)
    top5_overlap = len(set(baseline_order[:5]) & set(perturbed_order[:5]))

    priority_changes = sum(
        1 for zid, prio in baseline_priorities.items()
        if perturbed_priorities.get(zid) != prio
    )

    return {
        "kendall_tau": tau,
        "top5_overlap": top5_overlap,
        "priority_changes": priority_changes,
    }


def run_sensitivity_analysis(
    zones_path: Path,
    config_path: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Perform deterministic sensitivity analysis across weights, isolation scores, and thresholds."""
    config = load_config(config_path)
    zones_doc, warnings = load_zones(zones_path, config=config)

    baseline_records = score_zones(zones_doc, config, warnings)
    baseline_order = [r.zone_id for r in baseline_records]
    baseline_priorities = {r.zone_id: r.priority for r in baseline_records}

    # Baseline self-comparison check
    self_tau = compute_kendall_tau(baseline_order, baseline_order)
    self_changes = sum(
        1 for zid, p in baseline_priorities.items()
        if baseline_priorities[zid] != p
    )
    baseline_self_metrics = {
        "kendall_tau": self_tau,
        "top5_overlap": min(5, len(baseline_order)),
        "priority_changes": self_changes,
    }
    assert math.isclose(self_tau, 1.0, abs_tol=1e-9), "Baseline self-tau must be 1.0"
    assert self_changes == 0, "Baseline self priority changes must be 0"

    results: list[dict[str, Any]] = []

    # 1. Weight perturbations: -20%, -10%, +10%, +20%
    weight_keys = list(config["scoring"]["weights"].keys())
    perturb_factors = [-0.20, -0.10, 0.10, 0.20]

    for key in weight_keys:
        if key.startswith("_"):
            continue
        base_w = config["scoring"]["weights"][key]
        if base_w <= 0.0:
            continue

        for delta in perturb_factors:
            cfg = copy.deepcopy(config)
            weights = cfg["scoring"]["weights"]
            weights[key] = max(0.0, base_w * (1.0 + delta))
            total = sum(weights.values())
            if total > 0:
                for k in weights:
                    weights[k] /= total

            metrics = evaluate_perturbation(cfg, zones_doc, warnings, baseline_order, baseline_priorities)
            results.append({
                "category": "Weight",
                "parameter": key,
                "perturbation": f"{delta * 100:+.0f}%",
                "kendall_tau": metrics["kendall_tau"],
                "top5_overlap": metrics["top5_overlap"],
                "priority_changes": metrics["priority_changes"],
            })

    # 2. Isolation score perturbations: ±10%
    for cat, val in config["scoring"]["isolation_score"].items():
        if cat.startswith("_"):
            continue
        for delta in [-0.10, 0.10]:
            cfg = copy.deepcopy(config)
            new_val = max(0.0, min(1.0, val * (1.0 + delta)))
            cfg["scoring"]["isolation_score"][cat] = new_val

            metrics = evaluate_perturbation(cfg, zones_doc, warnings, baseline_order, baseline_priorities)
            results.append({
                "category": "Isolation",
                "parameter": cat,
                "perturbation": f"{delta * 100:+.0f}%",
                "kendall_tau": metrics["kendall_tau"],
                "top5_overlap": metrics["top5_overlap"],
                "priority_changes": metrics["priority_changes"],
            })

    # 3. Priority threshold perturbations: ±10%
    for thresh, val in config["priority_thresholds"].items():
        if thresh.startswith("_"):
            continue
        for delta in [-0.10, 0.10]:
            cfg = copy.deepcopy(config)
            new_val = max(0.0, val * (1.0 + delta))
            cfg["priority_thresholds"][thresh] = new_val

            metrics = evaluate_perturbation(cfg, zones_doc, warnings, baseline_order, baseline_priorities)
            results.append({
                "category": "Threshold",
                "parameter": thresh,
                "perturbation": f"{delta * 100:+.0f}%",
                "kendall_tau": metrics["kendall_tau"],
                "top5_overlap": metrics["top5_overlap"],
                "priority_changes": metrics["priority_changes"],
            })

    # Sort from most destabilizing to least:
    # Lowest Kendall tau, then highest priority changes, then lowest top5 overlap
    results.sort(
        key=lambda r: (
            r["kendall_tau"],
            -r["priority_changes"],
            r["top5_overlap"],
        )
    )

    return baseline_self_metrics, results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HighWater Module 3 Sensitivity Analysis"
    )
    parser.add_argument(
        "--zones",
        type=Path,
        default=Path("modules/flood_analysis/output/zones.json"),
        help="Path to input zones.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to custom configuration file",
    )
    args = parser.parse_args()

    zones_p = args.zones
    if not zones_p.exists():
        alt = Path("../flood_analysis/output/zones.json")
        if alt.exists():
            zones_p = alt

    self_metrics, results = run_sensitivity_analysis(zones_p, args.config)

    print("=== HighWater Module 3 Sensitivity Analysis ===")
    print(
        f"Baseline self-comparison: Tau={self_metrics['kendall_tau']:.4f}, "
        f"Top-5 overlap={self_metrics['top5_overlap']}/5, "
        f"Priority changes={self_metrics['priority_changes']}\n"
    )

    headers = (
        f"{'Category':<12} {'Parameter':<22} {'Delta':>8} "
        f"{'Kendall Tau':>12} {'Top-5 Overlap':>14} {'Priority Shifts':>16}"
    )
    print(headers)
    print("-" * len(headers))
    for r in results:
        print(
            f"{r['category']:<12} {r['parameter']:<22} {r['perturbation']:>8} "
            f"{r['kendall_tau']:12.4f} {r['top5_overlap']:>14d}/5 "
            f"{r['priority_changes']:>16d}"
        )


if __name__ == "__main__":
    main()
