"""CLI entry point for the HighWater Risk & Prioritization Engine (Module 3).

Usage:
    python -m risk_engine.cli --zones <path/to/zones.json> --out <output_dir>
    python -m risk_engine.cli --zones <path/to/zones.json> --out <output_dir> --format dashboard
    python -m risk_engine.cli --zones <path/to/zones.json> --out <output_dir> --config <path/to/weights.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import traceback
import uuid
from pathlib import Path

from risk_engine.scorer import (
    ConfigError,
    InputValidationError,
    export_dashboard,
    load_config,
    load_zones,
    parse_weights_arg,
    records_to_dict,
    score_zones,
    validate_config,
)
from risk_engine.sensitivity import analyze_ranking_sensitivity

logger = logging.getLogger("risk_engine")


def run(
    zones_path: Path,
    out_dir: Path,
    config_path: Path | None = None,
    weights: dict[str, float] | str | None = None,
    output_format: str = "standard",
    data_mode: str = "historical",
    sensitivity: bool = False,
) -> dict:
    """Core pipeline execution without direct stdout prints.

    Validates inputs and configuration prior to directory creation.
    Writes JSON output atomically to out_dir / 'risk_scores.json' (standard)
    or out_dir / 'zones.json' (dashboard).
    """
    zones_p = Path(zones_path)
    out_p = Path(out_dir)
    cfg_p = Path(config_path) if config_path is not None else None

    # 1. Validate config and inputs before creating output directories
    config = load_config(cfg_p)
    if weights is not None:
        parsed_weights = parse_weights_arg(weights)
        config["scoring"]["weights"] = parsed_weights
        validate_config(config)

    zones_doc, warnings = load_zones(zones_p, config=config)

    for w in warnings:
        logger.warning("Zone %s [%s]: %s", w.zone_id, w.field, w.issue)

    if not zones_doc["zones"]:
        logger.warning("Input zones.json contains zero zones — output list will be empty")

    records = score_zones(zones_doc, config, warnings)

    # Calculate input file hash
    try:
        with open(zones_p, "rb") as fh:
            file_hash = hashlib.sha256(fh.read()).hexdigest()
    except Exception:
        file_hash = None

    output = records_to_dict(records, warnings, zones_doc, config, input_file_sha256=file_hash)

    # 2. Format selection
    if output_format == "dashboard":
        final_dict = export_dashboard(output, zones_doc, data_mode=data_mode)
        filename = "zones.json"
    else:
        final_dict = output
        filename = "risk_scores.json"

    # 3. Create output directory and atomically write output
    out_p.mkdir(parents=True, exist_ok=True)
    out_path = out_p / filename

    tmp_name = f".tmp_{os.getpid()}_{uuid.uuid4().hex}.json"
    tmp_path = out_p / tmp_name
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(final_dict, fh, indent=2, allow_nan=False)
        os.replace(tmp_path, out_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    # 4. Optional sensitivity analysis output
    if sensitivity:
        sens_res = analyze_ranking_sensitivity(zones_p, config=config)
        sens_path = out_p / "sensitivity_analysis.json"
        tmp_sens = out_p / f".tmp_{os.getpid()}_{uuid.uuid4().hex}_sens.json"
        try:
            with open(tmp_sens, "w", encoding="utf-8") as fh:
                json.dump(sens_res.to_dict(), fh, indent=2, allow_nan=False)
            os.replace(tmp_sens, sens_path)
        except Exception:
            if tmp_sens.exists():
                try:
                    tmp_sens.unlink()
                except OSError:
                    pass
            raise
        final_dict["_sensitivity_analysis"] = sens_res.to_dict()

    return final_dict


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HighWater Module 3 — Risk & Prioritization Engine"
    )
    parser.add_argument(
        "--zones",
        required=True,
        type=Path,
        help="Path to zones.json produced by Module 2 (flood_analysis)",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory where output JSON will be written",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to custom configuration file (defaults to bundled package config or config/weights.json)",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default=None,
        help="Optional custom scoring weights as JSON string or key=val pairs (e.g. '{\"flood_percent\": 0.4, ...}' or 'flood_percent=0.4,exposure=0.35,isolation=0.15,flood_area_density=0.1')",
    )
    parser.add_argument(
        "--format",
        choices=["standard", "dashboard"],
        default="standard",
        help="Output format: 'standard' writes risk_scores.json, 'dashboard' writes zones.json for dashboard",
    )
    parser.add_argument(
        "--data-mode",
        default="historical",
        help="Data mode tag for dashboard export (defaults to 'historical')",
    )
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="Run standalone sensitivity analysis across plausible scenarios and save sensitivity_analysis.json",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print detailed stack traces on errors",
    )
    args = parser.parse_args()

    # Configure logging to stderr
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)

    try:
        output = run(
            args.zones,
            args.out,
            args.config,
            weights=args.weights,
            output_format=args.format,
            data_mode=args.data_mode,
            sensitivity=args.sensitivity,
        )
    except InputValidationError as exc:
        print(f"ERROR: Input validation failed — {exc}", file=sys.stderr)
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except (ConfigError, FileNotFoundError) as exc:
        print(f"ERROR: Configuration or file error — {exc}", file=sys.stderr)
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Unexpected failure — {exc}", file=sys.stderr)
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        sys.exit(3)

    if args.format == "dashboard":
        zones = output.get("zones", [])
        print(f"Exported {len(zones)} zones for dashboard (format: dashboard, data_mode: {args.data_mode})")
        out_file = args.out / "zones.json"
        print(f"\nOutput written to: {out_file}")
    else:
        summary = output["summary"]
        counts = summary["priority_counts"]
        dq_count = len(output["data_quality_warnings"])
        top5 = output["ranked_zones"][:5]

        print(
            f"Scored {summary['total_zones']} zones -> "
            f"CRITICAL={counts['CRITICAL']} HIGH={counts['HIGH']} "
            f"MEDIUM={counts['MEDIUM']} LOW={counts['LOW']}"
        )
        acc_counts = summary.get("accessibility_counts")
        if acc_counts:
            print(
                f"Accessibility: ACCESSIBLE={acc_counts.get('ACCESSIBLE', 0)} "
                f"PARTIAL={acc_counts.get('PARTIAL', 0)} "
                f"BLOCKED={acc_counts.get('BLOCKED', 0)} "
                f"UNKNOWN={acc_counts.get('UNKNOWN', 0)}"
            )
        if dq_count:
            print(f"Data-quality warnings: {dq_count}")

        print("\nTop-5 priority zones:")
        for z in top5:
            warn_flag = " [WARNINGS]" if z["warnings"] else ""
            basis_flag = f" [{z['score_basis'].upper()}]" if z.get("score_basis") == "partial" else ""
            print(
                f"  #{z['rank']:2d}  {z['zone_id']}  score={z['score']:5.1f}"
                f"  {z['priority']}{warn_flag}{basis_flag}"
            )

        if args.sensitivity and "_sensitivity_analysis" in output:
            sens = output["_sensitivity_analysis"]
            print(f"\nSensitivity Analysis (Tested {sens['summary']['scenarios_tested_count']} scenarios):")
            print(f"  Average Kendall's Tau: {sens['summary']['average_kendall_tau']:.4f}")
            print(f"  Robust high-priority zones: {sens['summary']['robust_high_priority_count']}")
            print(f"  Volatile zones: {sens['summary']['volatile_zones_count']}")
            print(f"  Sensitivity report written to: {args.out / 'sensitivity_analysis.json'}")

        out_file = args.out / "risk_scores.json"
        print(f"\nOutput written to: {out_file}")


if __name__ == "__main__":
    main()
