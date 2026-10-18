"""Disaster humanitarian relief needs estimation engine adhering to Sphere Handbook standards."""

import json
import math
from pathlib import Path

WATER_L_PER_PERSON_DAY = 15.0  # Sphere-derived, verify against current handbook: survival water L/person/day
KCAL_PER_PERSON_DAY = 2100.0  # Sphere-derived, verify against current handbook: nutritional energy kcal/person/day
FOOD_KG_PER_PERSON_DAY = 0.5  # Sphere-derived, verify against current handbook: dry ration density kg/person/day
MEDICAL_KIT_PEOPLE = 50  # coverage per emergency medical trauma kit
MEDICAL_KIT_KG = 5.0  # weight of standard emergency medical kit in kg
INITIAL_WATER_L_PER_PERSON = 3.0  # immediate drinking water allocation per person in liters
ELDERLY_VULNERABILITY_MULTIPLIER = 1.2  # Sphere-derived, verify against current handbook: mobility assistance multiplier
INFANT_VULNERABILITY_MULTIPLIER = 1.3  # Sphere-derived, verify against current handbook: pediatric nutrition multiplier

VEHICLE_CAPACITY_KG = {
    "AMBULANCE": 400.0,  # medical cargo payload limit in kg
    "TRUCK_4X4": 1500.0,  # high-clearance truck cargo payload limit in kg
    "RESCUE_BOAT": 800.0,  # inflatable rescue boat cargo payload limit in kg
    "HELICOPTER": 1200.0,  # emergency helicopter external sling / cabin payload limit in kg
}

STRANDED_SHARE_SCENARIOS = {
    "low": 0.3,  # optimistic evacuation and self-rescue rate leaving 30% stranded
    "central": 0.5,  # baseline scenario leaving 50% of exposed population stranded
    "high": 0.8,  # severe inundation leaving 80% of exposed population stranded
}
IN_NEED_SHARE = 0.8  # assumed share of stranded population lacking private emergency reserves



def load_population_data(filepath: str | Path | None = None) -> dict:
    """Load demographic zone population counts from json."""
    if filepath is None:
        target = Path("data/population_zones.json")
        if not target.exists():
            target = Path(__file__).resolve().parent.parent.parent / "data" / "population_zones.json"
    else:
        target = Path(filepath)

    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def build_priority_loading_plan(in_need: int, days: float = 3.0) -> list[dict]:
    """Generate prioritized humanitarian cargo loading manifest."""
    water_total_kg = in_need * WATER_L_PER_PERSON_DAY * days
    food_total_kg = in_need * FOOD_KG_PER_PERSON_DAY * days
    med_kits = math.ceil(in_need / float(MEDICAL_KIT_PEOPLE)) if in_need > 0 else 0
    med_kg = med_kits * MEDICAL_KIT_KG
    survival_water_kg = min(water_total_kg, in_need * INITIAL_WATER_L_PER_PERSON)
    bulk_water_kg = max(0.0, water_total_kg - survival_water_kg)

    return [
        {
            "priority": 1,
            "category": "MEDICAL",
            "item": "Trauma & First Aid Kits",
            "quantity": med_kits,
            "unit": "kits",
            "weight_kg": round(med_kg, 1),
            "rationale": "Immediate lifesaving stabilization and triage",
        },
        {
            "priority": 2,
            "category": "SURVIVAL_WATER",
            "item": "Purified Drinking Water",
            "quantity": round(survival_water_kg, 1),
            "unit": "liters",
            "weight_kg": round(survival_water_kg, 1),
            "rationale": "Initial 3L/person critical rehydration",
        },
        {
            "priority": 3,
            "category": "SUSTENANCE_WATER",
            "item": "Sanitation & Cooking Water",
            "quantity": round(bulk_water_kg, 1),
            "unit": "liters",
            "weight_kg": round(bulk_water_kg, 1),
            "rationale": "Sphere 12L/person/day bulk hydration and sanitation",
        },
        {
            "priority": 4,
            "category": "FOOD_RATIONS",
            "item": "High-Energy Nutritional Biscuits",
            "quantity": round(food_total_kg, 1),
            "unit": "kg",
            "weight_kg": round(food_total_kg, 1),
            "rationale": "Sphere 2100 kcal / 0.5 kg/person/day survival food rations",
        },
    ]


def estimate_needs(
    zone_id: str,
    exposure_fraction: float,
    days: float = 3.0,
    ground_reachable: bool = True,
    custom_pop: dict | None = None,
) -> dict:
    """Calculate relief commodity requirements across demographic funnel and scenarios."""
    pop_data = custom_pop if custom_pop is not None else load_population_data()
    zone_info = pop_data.get(zone_id, {
        "residents": 1000,
        "catchment_note": f"Estimated catchment for {zone_id}",
        "share_elderly": 0.20,
        "share_infants": 0.08,
        "synthetic": True,
    })

    residents = int(zone_info["residents"])
    clamped_exp = max(0.0, min(1.0, float(exposure_fraction)))
    exposed = round(residents * clamped_exp)

    scenarios = {}
    for sc_name, share in STRANDED_SHARE_SCENARIOS.items():
        eff_share = 1.0 if not ground_reachable else share
        stranded = min(exposed, round(exposed * eff_share))
        in_need_factor = 1.0 if not ground_reachable else IN_NEED_SHARE
        in_need = min(stranded, round(stranded * in_need_factor))

        water_kg = round(in_need * WATER_L_PER_PERSON_DAY * days, 1)
        food_kg = round(in_need * FOOD_KG_PER_PERSON_DAY * days, 1)
        med_kits = math.ceil(in_need / float(MEDICAL_KIT_PEOPLE)) if in_need > 0 else 0
        med_kg = round(med_kits * MEDICAL_KIT_KG, 1)
        total_kg = round(water_kg + food_kg + med_kg, 1)

        sorties = {
            v_name: math.ceil(total_kg / cap) if cap > 0 else None
            for v_name, cap in VEHICLE_CAPACITY_KG.items()
        }

        # enforce monotone funnel invariant: residents >= exposed >= stranded >= in_need
        assert residents >= exposed >= stranded >= in_need >= 0

        scenarios[sc_name] = {
            "stranded_share": eff_share,
            "stranded": stranded,
            "in_need": in_need,
            "relief_water_kg": water_kg,
            "relief_food_kg": food_kg,
            "medical_kits": med_kits,
            "medical_kits_kg": med_kg,
            "total_payload_kg": total_kg,
            "sorties_needed": sorties,
        }

    central_in_need = scenarios["central"]["in_need"]
    priority_manifest = build_priority_loading_plan(central_in_need, days=days)

    return {
        "zone_id": zone_id,
        "catchment_note": zone_info.get("catchment_note", ""),
        "demographics": {
            "residents": residents,
            "exposed": exposed,
            "exposure_fraction": clamped_exp,
            "share_elderly": zone_info.get("share_elderly", 0.0),
            "share_infants": zone_info.get("share_infants", 0.0),
        },
        "funnel": {
            "residents": residents,
            "exposed": exposed,
            "scenarios": {
                sc_name: {"stranded": sc["stranded"], "in_need": sc["in_need"]}
                for sc_name, sc in scenarios.items()
            },
        },
        "planning_duration_days": days,
        "ground_reachable": ground_reachable,
        "sphere_standards": {
            "water_l_per_person_day": WATER_L_PER_PERSON_DAY,
            "kcal_per_person_day": KCAL_PER_PERSON_DAY,
            "food_kg_per_person_day": FOOD_KG_PER_PERSON_DAY,
        },
        "vulnerability_multipliers": {
            "elderly": ELDERLY_VULNERABILITY_MULTIPLIER,
            "infants": INFANT_VULNERABILITY_MULTIPLIER,
        },
        "scenarios": scenarios,
        "priority_loading_plan": priority_manifest,
        "synthetic": zone_info.get("synthetic", True),
    }
