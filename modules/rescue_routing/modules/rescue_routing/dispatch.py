"""Fleet assignment module matching emergency assets to incident requests."""

import math
import numpy as np
from scipy.optimize import linear_sum_assignment

from .risk_engine import DISPATCH_MIN_RELIABILITY
from .router import RescueRouter, VehicleType
from .needs import VEHICLE_CAPACITY_KG


def assign_fleet(
    incidents: list[dict],
    fleet: list[dict],
    router: RescueRouter,
    rainfall_rate: float,
    blocked_edges: set | list | None = None,
    depth_map: dict | None = None,
    min_reliability: float = DISPATCH_MIN_RELIABILITY,
    capacity_mode: bool = True,
) -> dict:
    """Assign emergency fleet assets to incidents maximizing total prioritized value."""
    for inc in incidents:
        if inc["node"] not in router.graph:
            raise ValueError(f"Incident site '{inc['node']}' not in network graph")
    for a in fleet:
        if a["start_node"] not in router.graph:
            raise ValueError(f"Asset start_node '{a['start_node']}' not in network graph")

    routes = {}
    feasibility = {}

    for i, inc in enumerate(incidents):
        for j, a in enumerate(fleet):
            v_raw = a["vehicle_type"]
            v_type = VehicleType(v_raw) if not isinstance(v_raw, VehicleType) else v_raw
            if v_type == VehicleType.RESCUE_BOAT:
                res = router.find_multimodal_route(
                    a["start_node"],
                    inc["node"],
                    rainfall_rate=rainfall_rate,
                    blocked_edges=blocked_edges,
                    depth_map=depth_map,
                )
            else:
                res = router.find_route(
                    a["start_node"],
                    inc["node"],
                    v_type,
                    rainfall_rate=rainfall_rate,
                    blocked_edges=blocked_edges,
                    depth_map=depth_map,
                )
            routes[(i, j)] = res

            is_ok = res.get("status") == "OK"
            eta = res.get("eta_minutes", float("inf"))
            # helicopter has no edge risk model so reliability is treated as 1.0
            rel = 1.0 if v_type == VehicleType.HELICOPTER else res.get("route_reliability", 1.0)
            req_rel = 1.0 if v_type == VehicleType.HELICOPTER else min_reliability
            feasible = is_ok and (eta <= inc["deadline_min"]) and (rel is not None and rel >= req_rel)
            feasibility[(i, j)] = (feasible, eta, rel)

    n = len(incidents)
    m = len(fleet)
    if n == 0 or m == 0:
        unserved = []
        for inc in incidents:
            unserved.append({"incident": inc["id"], "reason": "NO_FEASIBLE_ASSET"})
        return {
            "policy": "One sortie per asset",
            "objective": "priority*reliability*people*delivered_share",
            "assignments": [],
            "unserved": unserved,
            "total_value": 0.0,
            "total_people_equivalents": 0.0,
            "total_eta_minutes": 0.0,
            "note": "Incident sites are existing graph nodes; a bridgehead node is used as a demo incident.",
        }

    k_weight = 1e8
    big_pen = 1e12
    cost_matrix = np.full((n + m, m + n), big_pen)

    for i, inc in enumerate(incidents):
        demanded_kg = float(inc.get("required_kg", inc.get("people", 10) * 15.5))
        people = float(inc.get("people", 10))
        for j, a in enumerate(fleet):
            feasible, eta, rel = feasibility[(i, j)]
            if feasible:
                vt_str = str(a.get("vehicle_type", "AMBULANCE"))
                cap = VEHICLE_CAPACITY_KG.get(vt_str, 1000.0)
                if capacity_mode:
                    delivered_kg_share = (min(cap, demanded_kg) / demanded_kg) if demanded_kg > 0 else 1.0
                    val = inc["priority"] * rel * people * delivered_kg_share
                else:
                    val = inc["priority"] * people * rel
                cost_matrix[i, j] = -k_weight * val + eta

    # incident i unserved dummy slot
    for i in range(n):
        cost_matrix[i, m + i] = 0.0

    # asset j idle dummy slot
    for j in range(m):
        cost_matrix[n + j, j] = 0.0

    # dummy-dummy assignments carry zero cost
    cost_matrix[n:, m:] = 0.0

    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    assigned_pairs = {}
    for r, c in zip(row_ind, col_ind):
        if r < n and c < m and cost_matrix[r, c] < 0:
            assigned_pairs[r] = c

    assignments = []
    assigned_incidents = set()
    raw_values = []
    partially_served = []
    for r in range(n):
        if r in assigned_pairs:
            c = assigned_pairs[r]
            inc = incidents[r]
            a = fleet[c]
            _, eta, rel = feasibility[(r, c)]
            vt_str = str(a.get("vehicle_type", "AMBULANCE"))
            cap = VEHICLE_CAPACITY_KG.get(vt_str, 1000.0)
            req_kg = float(inc.get("required_kg", inc.get("people", 10) * 15.5))
            people = float(inc.get("people", 10))
            if capacity_mode:
                delivered_kg_share = (min(cap, req_kg) / req_kg) if req_kg > 0 else 1.0
                val = inc["priority"] * rel * people * delivered_kg_share
            else:
                delivered_kg_share = 1.0
                val = inc["priority"] * people * rel
            raw_values.append(val)
            deliv_kg = min(cap, req_kg)
            unmet_kg = max(0.0, round(req_kg - cap, 1))
            sorties = math.ceil(req_kg / cap) if cap > 0 else 1
            people_equiv = round(people * delivered_kg_share, 2)

            assignments.append({
                "asset": a["id"],
                "incident": inc["id"],
                "vehicle_type": vt_str,
                "eta_minutes": eta,
                "reliability": round(rel, 4) if rel is not None else 1.0,
                "priority": inc["priority"],
                "value": round(val, 2),
                "people_equivalents_supplied": people_equiv,
                "objective": "priority*reliability*people*delivered_share",
                "payload_capacity_kg": cap,
                "demanded_kg": round(req_kg, 1),
                "delivered_kg": round(deliv_kg, 1),
                "unmet_kg": unmet_kg,
                "sorties_needed": sorties,
            })
            assigned_incidents.add(r)
            if req_kg > deliv_kg:
                unmet_share = round(unmet_kg / req_kg, 4) if req_kg > 0 else 0.0
                partially_served.append({
                    "incident": inc["id"],
                    "demanded_kg": round(req_kg, 1),
                    "delivered_kg": round(deliv_kg, 1),
                    "unmet_kg": unmet_kg,
                    "unmet_share": unmet_share,
                })

    unserved = []
    unserved_unmet_kg = 0.0
    for i, inc in enumerate(incidents):
        if i in assigned_incidents:
            continue
        req_kg = float(inc.get("required_kg", inc.get("people", 10) * 15.5))
        unserved_unmet_kg += req_kg
        any_feasible = any(feasibility[(i, j)][0] for j in range(m))
        if any_feasible:
            reason = "OUT_OF_ASSETS"
        else:
            all_unreachable = all(routes[(i, j)].get("status") != "OK" for j in range(m))
            if all_unreachable:
                reason = "UNREACHABLE"
            else:
                reached_routes = [routes[(i, j)] for j in range(m) if routes[(i, j)].get("status") == "OK"]
                if reached_routes and all(r.get("eta_minutes", float("inf")) > inc["deadline_min"] for r in reached_routes):
                    reason = "DEADLINE_MISSED"
                else:
                    reason = "NO_FEASIBLE_ASSET"
        unserved.append({"incident": inc["id"], "reason": reason})

    total_unmet_kg = round(sum(ps["unmet_kg"] for ps in partially_served) + unserved_unmet_kg, 1)
    tot_val = round(sum(raw_values), 2)
    tot_eta = round(sum(a["eta_minutes"] for a in assignments), 2)
    tot_people_equiv = round(sum(a["people_equivalents_supplied"] for a in assignments), 2)

    return {
        "policy": "One sortie per asset",
        "objective": "priority*reliability*people*delivered_share",
        "assignments": assignments,
        "unserved": unserved,
        "partially_served": partially_served,
        "total_unmet_kg": total_unmet_kg,
        "total_value": tot_val,
        "total_people_equivalents": tot_people_equiv,
        "total_eta_minutes": tot_eta,
        "note": "Incident sites are existing graph nodes; a bridgehead node is used as a demo incident.",
    }


def compute_delivery_sorties_and_mix(
    demanded_kg: float,
    vehicle_etas: dict,
    config: dict | None = None,
) -> dict:
    """Compute sorties, total delivery time per vehicle, earliest delivery time, and recommended mix."""
    from .router import load_vehicle_limits
    cfg = config or load_vehicle_limits()
    payload_cap = cfg.get("payload_capacity_kg", {
        "AMBULANCE": 400.0,
        "TRUCK_4X4": 1500.0,
        "RESCUE_BOAT": 800.0,
        "HELICOPTER": 1200.0,
    })
    concurrent_counts = cfg.get("concurrent_vehicles", {
        "AMBULANCE": 1,
        "TRUCK_4X4": 1,
        "RESCUE_BOAT": 1,
        "HELICOPTER": 1,
    })

    per_vehicle = {}
    earliest_time = float("inf")
    best_vehicle = None

    for v in ["AMBULANCE", "TRUCK_4X4", "RESCUE_BOAT", "HELICOPTER"]:
        eta = vehicle_etas.get(v)
        cap = float(payload_cap.get(v, 400.0))
        conc = max(1, int(concurrent_counts.get(v, 1)))

        if eta is None or eta == float("inf"):
            per_vehicle[v] = {
                "feasible": False,
                "sorties": None,
                "capacity_kg": cap,
                "round_trip_min": None,
                "total_delivery_time_min": None,
                "reason": "Unreachable or grounded",
            }
            continue

        sorties = math.ceil(demanded_kg / cap) if (demanded_kg > 0 and cap > 0) else 1
        round_trip_min = round(2.0 * eta, 2)
        total_time_min = round(math.ceil(sorties / float(conc)) * round_trip_min, 2)

        per_vehicle[v] = {
            "feasible": True,
            "sorties": sorties,
            "capacity_kg": cap,
            "concurrent_vehicles": conc,
            "one_way_eta_min": round(eta, 2),
            "round_trip_min": round_trip_min,
            "total_delivery_time_min": total_time_min,
        }

        if total_time_min < earliest_time:
            earliest_time = total_time_min
            best_vehicle = v

    if best_vehicle is None:
        rec_mix = {
            "recommended_vehicle": None,
            "reason": "No feasible vehicle routes found. Ground routes cut off and aerial/water assets unavailable.",
            "earliest_complete_delivery_min": None,
        }
    else:
        rec_mix = {
            "recommended_vehicle": best_vehicle,
            "reason": (
                f"{best_vehicle} achieves earliest complete cargo delivery of {demanded_kg} kg in "
                f"{earliest_time} min across {per_vehicle[best_vehicle]['sorties']} sorties with optimal operational stability."
            ),
            "earliest_complete_delivery_min": earliest_time,
        }

    return {
        "demanded_kg": demanded_kg,
        "per_vehicle": per_vehicle,
        "recommendation": rec_mix,
    }


