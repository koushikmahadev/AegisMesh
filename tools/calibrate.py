"""Calibration tool for HighWater Module 3 (Risk Engine).

Reads input zones and scoring configuration without modifying either file.
Reports statistics, ceiling saturation/utilization warnings, and suggested ceilings.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from risk_engine.scorer import (
    load_config,
    load_zones,
    score_zones,
)


def percentile(data: list[float], p: float) -> float:
    """Compute p-th percentile (0.0 to 1.0) using linear interpolation."""
    if not data:
        return 0.0
    s = sorted(data)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    return float(s[f] * (c - k) + s[c] * (k - f))


def compute_distribution(vals: list[float]) -> dict[str, float]:
    """Compute min, median, p90, p95, and max for a list of numbers."""
    if not vals:
        return {"min": 0.0, "median": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "min": min(vals),
        "median": percentile(vals, 0.50),
        "p90": percentile(vals, 0.90),
        "p95": percentile(vals, 0.95),
        "max": max(vals),
    }


def analyze_calibration(
    zones_path: Path,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Analyze input distribution and calibration metrics without modifying files."""
    config = load_config(config_path)
    zones_doc, warnings = load_zones(zones_path, config=config)
    records = score_zones(zones_doc, config, warnings)

    zones = zones_doc["zones"]

    # Raw input distributions
    raw_inputs = {
        "flooded_percent": [float(z["flooded_percent"]) for z in zones],
        "exposed_buildings": [float(z["exposed_buildings"]) for z in zones],
        "flooded_area_m2": [float(z["flooded_area_m2"]) for z in zones if z.get("flooded_area_m2") is not None],
        "road_length_m": [float(z.get("road_length_m", 0.0)) for z in zones],
        "flooded_road_length_m": [float(z.get("flooded_road_length_m", 0.0)) for z in zones],
        "total_buildings": [float(z.get("total_buildings", 0.0)) for z in zones],
    }

    input_stats = {name: compute_distribution(vals) for name, vals in raw_inputs.items()}

    # Score distribution
    scores = [r.score for r in records]
    score_stats = compute_distribution(scores)

    # Priority counts
    priority_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in records:
        priority_counts[r.priority] += 1

    # Normalization ceiling checks
    norms = config["scoring"]["normalization"]
    ceiling_checks = []
    suggestions = {}

    mappings = [
        ("flooded_percent", "flood_percent_max"),
        ("exposed_buildings", "exposed_buildings_max"),
        ("flooded_area_m2", "flood_area_m2_max"),
    ]

    for input_name, ceiling_name in mappings:
        if ceiling_name not in norms:
            continue
        ceiling_val = float(norms[ceiling_name])
        dist = input_stats[input_name]
        obs_max = dist["max"]
        obs_p95 = dist["p95"]

        warn = None
        if obs_max > 0 and ceiling_val > obs_max * 1.25:
            warn = (
                f"Ceiling '{ceiling_name}' ({ceiling_val}) exceeds observed maximum "
                f"({obs_max:.1f}) by >25% (underutilized dynamic range)"
            )
        elif ceiling_val < obs_p95:
            warn = (
                f"Ceiling '{ceiling_name}' ({ceiling_val}) is below p95 "
                f"({obs_p95:.1f}) (saturation risk for top 5% of zones)"
            )

        # Suggest ceiling derived from p95 (e.g. rounded up)
        if obs_p95 > 0:
            if input_name == "exposed_buildings":
                sugg = math.ceil(obs_p95)
            else:
                sugg = round(obs_p95 * 1.1, 1)
        else:
            sugg = ceiling_val

        suggestions[ceiling_name] = sugg
        ceiling_checks.append({
            "ceiling": ceiling_name,
            "configured": ceiling_val,
            "obs_max": obs_max,
            "obs_p95": obs_p95,
            "suggested": sugg,
            "warning": warn,
        })

    # Priority class balance check
    empty_priority_warnings = []
    for prio, count in priority_counts.items():
        if count == 0:
            empty_priority_warnings.append(
                f"Priority class '{prio}' contains zero zones (unbalanced distribution)"
            )

    return {
        "total_zones": len(zones),
        "input_stats": input_stats,
        "score_stats": score_stats,
        "priority_counts": priority_counts,
        "ceiling_checks": ceiling_checks,
        "suggestions": suggestions,
        "empty_priority_warnings": empty_priority_warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HighWater Module 3 Calibration & Normalization Diagnostics"
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

    # Fallback path if running from within modules/risk_engine
    zones_p = args.zones
    if not zones_p.exists():
        alt = Path("../flood_analysis/output/zones.json")
        if alt.exists():
            zones_p = alt

    results = analyze_calibration(zones_p, args.config)

    print(f"=== HighWater Module 3 Calibration Report ({results['total_zones']} zones) ===\n")
    print("--- Raw Input Statistics ---")
    headers = f"{'Input Field':<24} {'Min':>8} {'Median':>8} {'P90':>8} {'P95':>8} {'Max':>8}"
    print(headers)
    print("-" * len(headers))
    for name, st in results["input_stats"].items():
        print(
            f"{name:<24} {st['min']:8.1f} {st['median']:8.1f} "
            f"{st['p90']:8.1f} {st['p95']:8.1f} {st['max']:8.1f}"
        )

    print("\n--- Score Distribution & Priority Counts ---")
    sc = results["score_stats"]
    print(
        f"Scores: Min={sc['min']:.1f}, Median={sc['median']:.1f}, "
        f"P90={sc['p90']:.1f}, P95={sc['p95']:.1f}, Max={sc['max']:.1f}"
    )
    pc = results["priority_counts"]
    print(f"Priorities: CRITICAL={pc['CRITICAL']} HIGH={pc['HIGH']} MEDIUM={pc['MEDIUM']} LOW={pc['LOW']}")

    print("\n--- Normalization Ceiling Diagnostics & Suggestions ---")
    for chk in results["ceiling_checks"]:
        print(
            f"  {chk['ceiling']}: configured={chk['configured']}, "
            f"obs_p95={chk['obs_p95']:.1f}, obs_max={chk['obs_max']:.1f} -> "
            f"Suggested p95 ceiling={chk['suggested']}"
        )
        if chk["warning"]:
            print(f"    [WARN] {chk['warning']}")

    if results["empty_priority_warnings"]:
        print("\n--- Priority Warnings ---")
        for w in results["empty_priority_warnings"]:
            print(f"  [WARN] {w}")

    print("\nNote: Suggestions are diagnostic only. No configuration files were modified.")


if __name__ == "__main__":
    main()
