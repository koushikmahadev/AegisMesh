"""Demonstration of HighWater Rescue Routing Engine."""

import argparse
import copy
import hashlib
import json
import os
import sys

from modules.rescue_routing import (
    load_network,
    load_depth_map,
    RescueRouter,
    VehicleType,
    generate_tactical_briefing,
    assign_fleet,
    run_benchmark,
    estimate_needs,
)


def get_file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def get_colors():
    if os.environ.get("NO_COLOR"):
        return {
            "reset": "",
            "bold": "",
            "cyan": "",
            "green": "",
            "yellow": "",
            "red": "",
            "magenta": "",
        }
    return {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "cyan": "\033[36m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "magenta": "\033[35m",
    }


def wait_step(no_pause: bool):
    if not no_pause and sys.stdin.isatty():
        input("\nPress Enter to continue to next scenario...")


def main():
    parser = argparse.ArgumentParser(description="HighWater Rescue Routing Demo")
    parser.add_argument("--no-pause", action="store_true", help="Run without pausing")
    args = parser.parse_args()

    c = get_colors()
    g = load_network()
    router = RescueRouter(g)

    features = []
    scenarios = []

    def record_feature(payload: dict, scenario_id: str | None = None) -> int:
        if scenario_id is not None:
            payload["scenario_id"] = scenario_id
        idx = len(features)
        feat = {
            "type": "Feature",
            "geometry": payload.get("geojson_geometry"),
            "properties": {
                k: v for k, v in payload.items() if k != "geojson_geometry"
            },
        }
        features.append(feat)
        return idx

    print(f"{c['bold']}{c['cyan']}=================================================={c['reset']}")
    print(f"{c['bold']}{c['cyan']}   HIGHWATER RESCUE ROUTING ENGINE (ZARAGOZA)     {c['reset']}")
    print(f"{c['bold']}{c['cyan']}=================================================={c['reset']}\n")

    # Step 1: Baseline ambulance route
    print(f"{c['bold']}[SCENARIO 1] Baseline Route (15 mm/h nominal rain){c['reset']}")
    res1 = router.find_route(
        "HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0
    )
    b1, src1 = generate_tactical_briefing(res1)
    idx1 = record_feature(res1, "scenario_1_baseline")
    scenarios.append({
        "id": "scenario_1_baseline",
        "title": "Baseline Ambulance Route via Puente de Piedra",
        "feature_indices": [idx1],
        "briefing": b1,
        "briefing_source": src1,
    })

    print(f"Status: {c['green']}{res1['status']}{c['reset']}")
    print(f"Path: {' -> '.join(res1['path_nodes'])}")
    print(f"Distance: {res1['distance_km']} km | ETA: {res1['eta_minutes']} min")
    print(f"Predictive Detour: {res1['is_predictive_detour']}")
    print(f"Briefing [{c['bold']}{src1.upper()}{c['reset']}]: {b1}\n")

    wait_step(args.no_pause)

    # Step 2A: 45 mm/h predictive detour
    print(f"{c['bold']}[SCENARIO 2A] Heavy Rain (45 mm/h) - Predictive Detour{c['reset']}")
    res2a = router.find_route(
        "HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=45.0
    )
    eta_delta = round(res2a["eta_minutes"] - res1["eta_minutes"], 2)
    dist_delta = round(res2a["distance_km"] - res1["distance_km"], 3)
    res2a["eta_delta_min"] = eta_delta
    b2a, src2a = generate_tactical_briefing(res2a)
    idx2a = record_feature(res2a, "scenario_2a_predictive_detour")
    scenarios.append({
        "id": "scenario_2a_predictive_detour",
        "title": "Heavy Rain (45 mm/h) Predictive Detour via Puente de Santiago",
        "feature_indices": [idx2a],
        "briefing": b2a,
        "briefing_source": src2a,
    })
    print(f"Status: {c['green']}{res2a['status']}{c['reset']}")
    print(f"Path: {' -> '.join(res2a['path_nodes'])}")
    print(f"Distance: {res2a['distance_km']} km (+{dist_delta} km vs baseline)")
    print(f"ETA: {res2a['eta_minutes']} min ({'+' if eta_delta >= 0 else ''}{eta_delta} min vs baseline)")
    print(f"Predictive Detour: {c['yellow']}{res2a['is_predictive_detour']}{c['reset']}")
    print("Avoided Hazards:")
    for h in res2a["avoided_hazards"]:
        print(f"  - {h['name']}: {h['reason']} (depth: {h['depth_m']}m, flood risk: {h['risk']:.1%})")
    print(f"Briefing [{c['bold']}{src2a.upper()}{c['reset']}]: {b2a}\n")

    wait_step(args.no_pause)

    # Step 2B: Piedra bridge submerged at 15 mm/h
    print(f"{c['bold']}[SCENARIO 2B] Puente de Piedra Submerged (depth 0.8m, 15 mm/h){c['reset']}")
    piedra_flooded = {("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH"): 0.8}
    res2b = router.find_route(
        "HOSPITAL_BASE",
        "ZONE_NORTH_RESIDENTIAL",
        VehicleType.AMBULANCE,
        rainfall_rate=15.0,
        edge_depths=piedra_flooded,
    )
    b2b, src2b = generate_tactical_briefing(res2b)
    idx2b = record_feature(res2b, "scenario_2b_flooded_bridge")
    scenarios.append({
        "id": "scenario_2b_flooded_bridge",
        "title": "Physical Submersion Detour via Puente de Santiago",
        "feature_indices": [idx2b],
        "briefing": b2b,
        "briefing_source": src2b,
    })

    print(f"Status: {c['green']}{res2b['status']}{c['reset']}")
    print(f"Path: {' -> '.join(res2b['path_nodes'])}")
    print(f"Distance: {res2b['distance_km']} km | ETA: {res2b['eta_minutes']} min")
    print(f"Predictive Detour: {res2b['is_predictive_detour']}")
    print("Avoided Hazards:")
    for h in res2b["avoided_hazards"]:
        print(f"  - {h['name']}: {h['reason']} (depth: {h['depth_m']}m, flood risk: {h['risk']:.1%})")
    print(f"Briefing [{c['bold']}{src2b.upper()}{c['reset']}]: {b2b}\n")

    wait_step(args.no_pause)

    # Step 3: Island Cutoff
    print(f"{c['bold']}[SCENARIO 3] Island Community Cutoff (Causeway depth 0.9m){c['reset']}")
    causeway_flooded = {("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"): 0.9}
    standing_water_note = (
        "Scenario-imposed depth, not derived from rainfall."
    )

    # Ambulance attempt
    res3_amb = router.find_route(
        "HOSPITAL_BASE",
        "ZONE_ISLAND_COMMUNITY",
        VehicleType.AMBULANCE,
        edge_depths=causeway_flooded,
    )
    res3_amb["standing_water_note"] = standing_water_note
    res3_amb["stage"] = 1
    res3_amb["stage_title"] = "Ambulance"
    b3_amb, src3_amb = generate_tactical_briefing(res3_amb)
    idx3_amb = record_feature(res3_amb, "scenario_3a_island_cutoff_boat_success")
    print(f"Ambulance: {c['red']}{res3_amb['status']}{c['reset']} - {res3_amb['reason']}")
    print(f"Briefing [{c['bold']}{src3_amb.upper()}{c['reset']}]: {b3_amb}")

    # Truck attempt
    res3_trk = router.find_route(
        "HOSPITAL_BASE",
        "ZONE_ISLAND_COMMUNITY",
        VehicleType.TRUCK_4X4,
        edge_depths=causeway_flooded,
    )
    res3_trk["standing_water_note"] = standing_water_note
    res3_trk["stage"] = 2
    res3_trk["stage_title"] = "4x4 Truck"
    b3_trk, src3_trk = generate_tactical_briefing(res3_trk)
    idx3_trk = record_feature(res3_trk, "scenario_3a_island_cutoff_boat_success")
    print(f"4x4 Truck: {c['red']}{res3_trk['status']}{c['reset']} - {res3_trk['reason']}")
    print(f"Briefing [{c['bold']}{src3_trk.upper()}{c['reset']}]: {b3_trk}")

    # Boat attempt from BOAT_RAMP_SOUTH
    res3_boat = router.find_route(
        "BOAT_RAMP_SOUTH",
        "ZONE_ISLAND_COMMUNITY",
        VehicleType.RESCUE_BOAT,
        edge_depths=causeway_flooded,
    )
    res3_boat["standing_water_note"] = standing_water_note
    res3_boat["stage"] = 3
    res3_boat["stage_title"] = "Rescue Boat"
    b3_boat, src3_boat = generate_tactical_briefing(res3_boat)
    idx3_boat = record_feature(res3_boat, "scenario_3a_island_cutoff_boat_success")
    print(f"Rescue Boat: {c['green']}{res3_boat['status']}{c['reset']}")
    print(f"  Path: {' -> '.join(res3_boat['path_nodes'])}")
    print(f"  Distance: {res3_boat['distance_km']} km | ETA: {res3_boat['eta_minutes']} min")
    print(f"Briefing [{c['bold']}{src3_boat.upper()}{c['reset']}]: {b3_boat}\n")

    scenarios.append({
        "id": "scenario_3a_island_cutoff_boat_success",
        "title": "Island Cutoff - Land Vehicles Impassable, Boat Dispatch",
        "feature_indices": [idx3_amb, idx3_trk, idx3_boat],
        "briefing": b3_boat,
        "briefing_source": src3_boat,
        "standing_water_note": standing_water_note,
    })

    # Block river edge: all vehicles unreachable -> AIRDROP alert
    river_blocked = [("BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY")]
    res3_boat_blocked = router.find_route(
        "BOAT_RAMP_SOUTH",
        "ZONE_ISLAND_COMMUNITY",
        VehicleType.RESCUE_BOAT,
        blocked_edges=river_blocked,
        edge_depths=causeway_flooded,
    )
    res3_boat_blocked["standing_water_note"] = standing_water_note
    res3_boat_blocked["stage"] = 4
    res3_boat_blocked["stage_title"] = "Rescue Boat (River Blocked)"
    b3_airdrop, src3_airdrop = generate_tactical_briefing(res3_boat_blocked)
    idx3_airdrop = record_feature(res3_boat_blocked, "scenario_3b_total_isolation_airdrop")

    print(f"{c['bold']}{c['red']}*** AIRDROP ALERT: ALL TRANSIT CORRIDORS SEVERED ***{c['reset']}")
    print(f"Rescue Boat blocked on river: {c['red']}{res3_boat_blocked['status']}{c['reset']}")
    print(f"Isolated Nodes: {res3_boat_blocked['isolated_nodes']}")
    print(f"Bordering Cut Edges: {res3_boat_blocked['cut_edges']}")
    print(f"Briefing [{c['bold']}{src3_airdrop.upper()}{c['reset']}]: {b3_airdrop}\n")

    # Cascade dispatch: ground & river blocked, helicopter air sortie dispatched
    cascade_3b = router.plan_cascade(
        "ZONE_ISLAND_COMMUNITY",
        rainfall_rate=15.0,
        blocked_edges=river_blocked,
        depth_map=causeway_flooded,
    )
    res3_heli = cascade_3b["selected_route"]
    res3_heli["surface_access_severed"] = True
    res3_heli["standing_water_note"] = standing_water_note
    res3_heli["stage"] = 5
    res3_heli["stage_title"] = "Helicopter"
    b3_heli, src3_heli = generate_tactical_briefing(res3_heli)
    idx3_heli = record_feature(res3_heli, "scenario_3b_total_isolation_airdrop")

    print(f"Cascade Dispatch Escalation: {c['cyan']}{res3_heli['vehicle_type']}{c['reset']}")
    print(f"  Path: {' -> '.join(res3_heli['path_nodes'])}")
    print(f"  Distance: {res3_heli['distance_km']} km | ETA: {res3_heli['eta_minutes']} min")
    print(f"Briefing [{c['bold']}{src3_heli.upper()}{c['reset']}]: {b3_heli}\n")

    scenarios.append({
        "id": "scenario_3b_total_isolation_airdrop",
        "title": "Total Island Isolation - Critical Airdrop Alert",
        "feature_indices": [idx3_airdrop, idx3_heli],
        "briefing": b3_heli,
        "briefing_source": src3_heli,
        "standing_water_note": standing_water_note,
    })

    wait_step(args.no_pause)

    # Step 4: Synthetic Satellite Depth Map Scenario
    print(f"{c['bold']}{c['yellow']}=================================================={c['reset']}")
    print(f"{c['bold']}{c['yellow']}   SYNTHETIC SATELLITE DEPTH OBSERVATION DEMO     {c['reset']}")
    print(f"{c['bold']}{c['yellow']}=================================================={c['reset']}\n")

    synth_depths = load_depth_map("data/synthetic_depth_map.json")
    res4_synth = router.find_route(
        "HOSPITAL_BASE",
        "ZONE_NORTH_RESIDENTIAL",
        VehicleType.AMBULANCE,
        rainfall_rate=15.0,
        depth_map=synth_depths,
    )
    b4_synth, src4_synth = generate_tactical_briefing(res4_synth)
    idx4_synth = record_feature(res4_synth, "scenario_4_synthetic_depth_map")
    scenarios.append({
        "id": "scenario_4_synthetic_depth_map",
        "title": "Satellite Observation Detour via Santiago (Synthetic Depth Map)",
        "feature_indices": [idx4_synth],
        "briefing": b4_synth,
        "briefing_source": src4_synth,
    })

    print(f"Status: {c['green']}{res4_synth['status']}{c['reset']}")
    print(f"Path: {' -> '.join(res4_synth['path_nodes'])}")
    print(f"Distance: {res4_synth['distance_km']} km | ETA: {res4_synth['eta_minutes']} min")
    print(f"Depth Source: {res4_synth['depth_source']} | Data Freshness: {res4_synth['data_freshness']} (Age: {res4_synth.get('depth_age_min')} min)")
    print(f"Briefing [{c['bold']}{src4_synth.upper()}{c['reset']}]: {b4_synth}\n")

    wait_step(args.no_pause)

    # Step 5: Severe Rain (45 mm/h) Full Cascade Escalation
    print(f"{c['bold']}[SCENARIO 5] Severe Rain (45 mm/h) Full Cascade Escalation{c['reset']}")
    cascade_5 = router.plan_cascade(
        "ZONE_ISLAND_COMMUNITY",
        rainfall_rate=45.0,
        depth_map=causeway_flooded,
    )
    res5_boat = cascade_5["selected_route"]
    b5_boat, src5_boat = generate_tactical_briefing(res5_boat)

    print(f"Ambulance: {c['red']}{cascade_5['attempts'][0]['status']}{c['reset']} - {cascade_5['attempts'][0].get('reason')}")
    print(f"4x4 Truck: {c['red']}{cascade_5['attempts'][1]['status']}{c['reset']} - {cascade_5['attempts'][1].get('reason')}")
    print(f"Multimodal Boat: {c['green']}{res5_boat['status']}{c['reset']}")
    print(f"  Path: {' -> '.join(res5_boat['path_nodes'])}")
    print(f"  Distance: {res5_boat['distance_km']} km | ETA: {res5_boat['eta_minutes']} min | Legs: {len(res5_boat.get('legs', []))}")
    print(f"Briefing [{c['bold']}{src5_boat.upper()}{c['reset']}]: {b5_boat}\n")

    # Block river edge: multimodal boat cut off -> helicopter air insertion
    cascade_5_blocked = router.plan_cascade(
        "ZONE_ISLAND_COMMUNITY",
        rainfall_rate=45.0,
        blocked_edges=river_blocked,
        depth_map=causeway_flooded,
    )
    res5_heli = cascade_5_blocked["selected_route"]
    res5_heli["surface_access_severed"] = True
    b5_heli, src5_heli = generate_tactical_briefing(res5_heli)

    print(f"Rescue Boat blocked on river: {c['red']}{cascade_5_blocked['attempts'][2]['status']}{c['reset']} - {cascade_5_blocked['attempts'][2].get('reason')}")
    print(f"Cascade Dispatch Escalation: {c['cyan']}{res5_heli['vehicle_type']}{c['reset']}")
    print(f"  Path: {' -> '.join(res5_heli['path_nodes'])}")
    print(f"  Distance: {res5_heli['distance_km']} km | ETA: {res5_heli['eta_minutes']} min")
    print(f"Briefing [{c['bold']}{src5_heli.upper()}{c['reset']}]: {b5_heli}\n")

    # Record each cascade attempt as a feature in order (final features 9 to 13)
    att1 = copy.deepcopy(cascade_5["attempts"][0]["payload"])
    att1["rainfall_mmh"] = 45.0
    att1["blocked_edges"] = []
    att1["stage"] = 1
    att1["stage_title"] = "Ambulance"
    idx9 = record_feature(att1, "scenario_5_full_cascade")

    att2 = copy.deepcopy(cascade_5["attempts"][1]["payload"])
    att2["rainfall_mmh"] = 45.0
    att2["blocked_edges"] = []
    att2["stage"] = 2
    att2["stage_title"] = "4x4 Truck"
    idx10 = record_feature(att2, "scenario_5_full_cascade")

    att3 = copy.deepcopy(cascade_5["attempts"][2]["payload"])
    att3["rainfall_mmh"] = 45.0
    att3["blocked_edges"] = []
    att3["stage"] = 3
    att3["stage_title"] = "Rescue Boat"
    idx11 = record_feature(att3, "scenario_5_full_cascade")

    att4 = copy.deepcopy(cascade_5_blocked["attempts"][2]["payload"])
    att4["rainfall_mmh"] = 45.0
    att4["blocked_edges"] = [list(e) for e in river_blocked]
    att4["stage"] = 4
    att4["stage_title"] = "Rescue Boat (River Blocked)"
    idx12 = record_feature(att4, "scenario_5_full_cascade")

    att5 = copy.deepcopy(cascade_5_blocked["attempts"][3]["payload"])
    att5["rainfall_mmh"] = 45.0
    att5["blocked_edges"] = [list(e) for e in river_blocked]
    att5["surface_access_severed"] = True
    att5["stage"] = 5
    att5["stage_title"] = "Helicopter"
    idx13 = record_feature(att5, "scenario_5_full_cascade")

    scenarios.append({
        "id": "scenario_5_full_cascade",
        "title": "Severe Rain (45 mm/h) Full Cascade Escalation to Aerial Insertion",
        "feature_indices": [idx9, idx10, idx11, idx12, idx13],
        "selected_feature_index": idx13,
        "attempts": [
            {
                "vehicle_type": "AMBULANCE",
                "status": "UNREACHABLE",
                "reason": cascade_5["attempts"][0]["reason"],
                "feature_index": idx9,
                "stage": 1,
                "stage_title": "Ambulance",
                "blocked_edges": [],
            },
            {
                "vehicle_type": "TRUCK_4X4",
                "status": "UNREACHABLE",
                "reason": cascade_5["attempts"][1]["reason"],
                "feature_index": idx10,
                "stage": 2,
                "stage_title": "4x4 Truck",
                "blocked_edges": [],
            },
            {
                "vehicle_type": "RESCUE_BOAT",
                "status": "OK",
                "eta_minutes": res5_boat["eta_minutes"],
                "legs": len(res5_boat.get("legs", [])),
                "feature_index": idx11,
                "stage": 3,
                "stage_title": "Rescue Boat",
                "blocked_edges": [],
            },
            {
                "vehicle_type": "RESCUE_BOAT",
                "status": "UNREACHABLE",
                "reason": cascade_5_blocked["attempts"][2]["reason"],
                "feature_index": idx12,
                "stage": 4,
                "stage_title": "Rescue Boat (River Blocked)",
                "blocked_edges": [list(e) for e in river_blocked],
            },
            {
                "vehicle_type": "HELICOPTER",
                "status": "OK",
                "eta_minutes": res5_heli["eta_minutes"],
                "feature_index": idx13,
                "stage": 5,
                "stage_title": "Helicopter",
                "blocked_edges": [list(e) for e in river_blocked],
                "selected": True,
            },
        ],
        "briefing": b5_heli,
        "briefing_source": src5_heli,
    })



    wait_step(args.no_pause)

    # Population & Humanitarian Relief Needs Estimation (Sphere Standards)
    print(f"{c['bold']}[NEEDS] Sphere-Standard Humanitarian Commodity Requirements{c['reset']}")
    needs_data = {
        "ZONE_NORTH_RESIDENTIAL": estimate_needs("ZONE_NORTH_RESIDENTIAL", exposure_fraction=0.5, days=3.0, ground_reachable=True),
        "ZONE_ISLAND_COMMUNITY": estimate_needs("ZONE_ISLAND_COMMUNITY", exposure_fraction=1.0, days=3.0, ground_reachable=False),
        "PUENTE_SANTIAGO_NORTH": estimate_needs("PUENTE_SANTIAGO_NORTH", exposure_fraction=0.3, days=3.0, ground_reachable=True),
    }
    for z_id, z_needs in needs_data.items():
        c_sc = z_needs["scenarios"]["central"]
        print(f"  {z_id}: Residents {z_needs['demographics']['residents']}, In-Need {c_sc['in_need']} ({c_sc['stranded_share']:.0%}), Total Payload: {c_sc['total_payload_kg']} kg (Truck Sorties: {c_sc['sorties_needed']['TRUCK_4X4']}, Boat: {c_sc['sorties_needed']['RESCUE_BOAT']}, Heli: {c_sc['sorties_needed']['HELICOPTER']})")
    print()

    # Step 6: Multi-Asset Fleet Dispatch
    print(f"{c['bold']}[DISPATCH] Multi-Asset Optimal Fleet Assignment (45 mm/h rain){c['reset']}")
    demo_fleet = [
        {"id": "AMB_1", "vehicle_type": "AMBULANCE", "start_node": "HOSPITAL_BASE"},
        {"id": "TRUCK_1", "vehicle_type": "TRUCK_4X4", "start_node": "HOSPITAL_BASE"},
        {"id": "HELI_1", "vehicle_type": "HELICOPTER", "start_node": "HOSPITAL_BASE"},
        {"id": "BOAT_1", "vehicle_type": "RESCUE_BOAT", "start_node": "BOAT_RAMP_SOUTH"},
    ]
    demo_incidents = [
        {
            "id": "ZONE_ISLAND_COMMUNITY",
            "node": "ZONE_ISLAND_COMMUNITY",
            "priority": 5,
            "people": needs_data["ZONE_ISLAND_COMMUNITY"]["scenarios"]["central"]["in_need"],
            "required_kg": needs_data["ZONE_ISLAND_COMMUNITY"]["scenarios"]["central"]["total_payload_kg"],
            "deadline_min": 45,
        },
        {
            "id": "ZONE_NORTH_RESIDENTIAL",
            "node": "ZONE_NORTH_RESIDENTIAL",
            "priority": 4,
            "people": needs_data["ZONE_NORTH_RESIDENTIAL"]["scenarios"]["central"]["in_need"],
            "required_kg": needs_data["ZONE_NORTH_RESIDENTIAL"]["scenarios"]["central"]["total_payload_kg"],
            "deadline_min": 30,
        },
        {
            "id": "PUENTE_SANTIAGO_NORTH",
            "node": "PUENTE_SANTIAGO_NORTH",
            "priority": 3,
            "people": needs_data["PUENTE_SANTIAGO_NORTH"]["scenarios"]["central"]["in_need"],
            "required_kg": needs_data["PUENTE_SANTIAGO_NORTH"]["scenarios"]["central"]["total_payload_kg"],
            "deadline_min": 30,
        },
    ]
    dispatch_depths = {("ZONE_ISLAND_COMMUNITY", "ZONE_NORTH_RESIDENTIAL"): 0.9}

    dispatch_res = assign_fleet(
        demo_incidents,
        demo_fleet,
        router,
        rainfall_rate=45.0,
        depth_map=dispatch_depths,
    )
    print(f"Policy: {dispatch_res['policy']}")
    print(f"Total Value: {dispatch_res['total_value']} | Total ETA: {dispatch_res['total_eta_minutes']} min")
    for a in dispatch_res["assignments"]:
        print(f"  Assignment: {c['cyan']}{a['asset']}{c['reset']} -> {a['incident']} (ETA: {a['eta_minutes']}m, Rel: {a['reliability']:.2%}, Value: {a['value']}, Cap: {a['payload_capacity_kg']}kg, Demanded: {a['demanded_kg']}kg, Delivered: {a['delivered_kg']}kg, Unmet: {a['unmet_kg']}kg, Sorties: {a['sorties_needed']})")
    if dispatch_res["unserved"]:
        for u in dispatch_res["unserved"]:
            print(f"  Unserved: {u['incident']} ({u['reason']})")
    print()

    wait_step(args.no_pause)

    # Step 7: Predictive vs Reactive Benchmark
    print(f"{c['bold']}[BENCHMARK] Predictive vs Reactive Monte Carlo Evaluation{c['reset']}")
    benchmark_res = run_benchmark(router)
    print(f"{c['yellow']}{benchmark_res['disclaimer']}{c['reset']}")
    for v_name, m in benchmark_res["metrics"].items():
        print(f"  {v_name}: Stranded Predictive {m['predictive_stranded_rate']['mean']:.2%}, Reactive {m['reactive_stranded_rate']['mean']:.2%}, ETA Penalty: {m['mean_eta_penalty_minutes']['mean']}m")
    print(f"  Predictive Reduces Stranding (Perturbed): {benchmark_res.get('predictive_reduces_stranding')}")
    print(f"  Predictive Reduces Stranding (Misspecified): {benchmark_res.get('predictive_reduces_stranding_misspecified')}")
    print(f"  Sensitivity Robustness: {benchmark_res['sensitivity']['overall_pct_unchanged']}% headline choices unchanged\n")

    # Export benchmark results to benchmark_results.json
    with open("benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(benchmark_res, f, indent=2)

    # Build slider dataset
    slider_data = router.build_slider_dataset()

    # Write routes.json with top-level schema_version, provenance, network, slider, dispatch, benchmark, needs
    network_fc = router.export_network_geojson()
    with open("data/zaragoza_network.json", "r", encoding="utf-8") as f:
        zaragoza_raw = json.load(f)
    meta = zaragoza_raw.get("meta", {})
    if "bridge_order_unverified" not in meta:
        meta["bridge_order_unverified"] = True
        zaragoza_raw["meta"] = meta
        with open("data/zaragoza_network.json", "w", encoding="utf-8") as f:
            json.dump(zaragoza_raw, f, indent=2)
    coords_verified = bool(meta.get("coordinates_verified") is True and meta.get("verified_by"))
    bridge_order_unverified = bool(meta.get("bridge_order_unverified", True))

    provenance = {
        "generated_by": "HighWater Rescue Routing Engine Person 4",
        "code_version": "2.2.1",
        "network": "curated_osm_derived_approximate",
        "coordinates_verified": coords_verified,
        "bridge_order_unverified": bridge_order_unverified,
        "risk_model": "heuristic_uncalibrated",
        "geometry_quality": "schematic_straight_lines",
        "benchmark": "synthetic",
        "population": "synthetic_demo",
        "input_files": {
            "data/zaragoza_network.json": get_file_sha256("data/zaragoza_network.json"),
            "data/synthetic_depth_map.json": get_file_sha256("data/synthetic_depth_map.json"),
            "data/population_zones.json": get_file_sha256("data/population_zones.json"),
        },
        "deterministic_seed": 42,
    }
    out_payload = {
        "schema_version": "2.2",
        "verified": False,
        "provenance": provenance,
        "type": "FeatureCollection",
        "features": features,
        "scenarios": scenarios,
        "network": network_fc,
        "slider": slider_data,
        "dispatch": dispatch_res,
        "benchmark": benchmark_res,
        "needs": needs_data,
    }
    routes_path = "routes.json"
    with open(routes_path, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2)
        f.write("\n")

    print(f"{c['bold']}{c['green']}SUCCESS: Exported {len(features)} route features across {len(scenarios)} scenarios to {routes_path}{c['reset']}")


if __name__ == "__main__":
    main()
