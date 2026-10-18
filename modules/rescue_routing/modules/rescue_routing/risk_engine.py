"""Flood submersion risk calculation engine for rescue transit corridors."""

import math

ON_SCENE_DWELL_MIN = 15.0  # assumed on-scene emergency dwell duration before return transit

def _load_base_river_elevation_m() -> float:
    """Read baseline river elevation from Zaragoza network dataset."""
    try:
        from pathlib import Path
        import json
        p = Path("data/zaragoza_network.json")
        if not p.exists():
            p = Path(__file__).resolve().parent.parent.parent / "data" / "zaragoza_network.json"
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return float(json.load(f).get("meta", {}).get("base_river_elevation_m", 194.0))
    except Exception:
        pass
    return 194.0

BASE_RIVER_ELEVATION_M = _load_base_river_elevation_m()
RAINFALL_COEFFICIENT = 0.38  # tuned hydraulic head growth rate per mm/h of rainfall
ELEVATION_COEFFICIENT = 0.70  # tuned risk reduction rate per meter of elevation clearance
RIVER_DISTANCE_COEFFICIENT = 0.005  # flood attenuation factor per meter distance from river channel
RISK_THRESHOLD_BIAS = 10.40  # tuned empirical offset ensuring sub-1% risk at 15 mm/h baseline across all edges
RIVER_FLOW_COEFFICIENT = 0.09  # drag and debris hazard growth rate per mm/h rainfall
RIVER_FLOW_THRESHOLD_BIAS = 6.0  # baseline offset keeping river flow hazard under 1% at 15 mm/h
HAZARD_RISK_MIN = 0.25  # minimum flood submersion probability to qualify as an avoided hazard
RISK_TIME_PENALTY = 1500.0  # penalty scaling factor tuned for round-trip exposure flipping ambulance at 20-30 mm/h
RELIABILITY_MIN = 0.9  # minimum route reliability threshold for safe departure window
HELI_SPEED_KMH = 180.0  # cruising speed in km/h for emergency rescue helicopter
HELI_GROUND_MM_H = 60.0  # rainfall threshold grounding helicopter flight operations
LAUNCH_MINUTES = 10.0  # staging and slipway offload duration for boat trailer
HELI_LAUNCH_MINUTES = 10.0  # pre-flight briefing, spool-up and takeoff clearance duration for rescue helicopter
DISPATCH_MIN_RELIABILITY = 0.5  # minimum route reliability threshold for ground asset dispatch feasibility
ADVISORY_NONE = "NONE"  # nominal conditions meeting reliability standard
ADVISORY_LOW_RELIABILITY = "LOW_RELIABILITY"  # route reliability below minimum operating standard
ADVISORY_NO_SAFE_OPTION = "NO_SAFE_OPTION"  # aviation grounded and all surface options below reliability threshold
STABILITY_MIN = 0.9  # route should tolerate 20% parameter drift


def calculate_river_flow_hazard(
    rainfall_mmh: float,
    horizon_min: float = 30.0,
) -> float:
    """Calculate flow and debris hazard for navigable river corridors."""
    # models current velocity and debris accumulation rather than water depth
    effective_rain = rainfall_mmh * (horizon_min / 30.0)
    z = RIVER_FLOW_COEFFICIENT * effective_rain - RIVER_FLOW_THRESHOLD_BIAS
    z = max(-50.0, min(50.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def calculate_edge_risk(
    elevation_m: float | None,
    distance_to_river_m: float,
    rainfall_mmh: float,
    horizon_min: float = 30.0,
    kind: str = "road",
    base_river_elevation_m: float | None = None,
) -> float:
    """Calculate flood submersion or river flow hazard for an edge within the transit horizon."""
    if kind == "river":
        return calculate_river_flow_hazard(rainfall_mmh, horizon_min)
    effective_rain = rainfall_mmh * (horizon_min / 30.0)
    base_elev = base_river_elevation_m if base_river_elevation_m is not None else BASE_RIVER_ELEVATION_M
    if elevation_m is None:
        z = (
            RAINFALL_COEFFICIENT * effective_rain
            - RIVER_DISTANCE_COEFFICIENT * distance_to_river_m
            - RISK_THRESHOLD_BIAS
        )
    else:
        z = (
            RAINFALL_COEFFICIENT * effective_rain
            - ELEVATION_COEFFICIENT * (elevation_m - base_elev)
            - RIVER_DISTANCE_COEFFICIENT * distance_to_river_m
            - RISK_THRESHOLD_BIAS
        )
    # prevent float overflow outside typical logistic tail bounds
    z = max(-50.0, min(50.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def effective_cost(distance: float, flood_risk_prob: float) -> float:
    """Calculate routing cost penalized by flood submersion risk."""
    return distance * (1.0 + 10.0 * flood_risk_prob)
