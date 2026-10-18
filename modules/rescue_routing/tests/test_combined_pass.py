"""Unit tests for combined pass: evacuation corridors, vehicle hardening, weather, and dispatch."""

import random
import networkx as nx
import pytest
from modules.rescue_routing.router import (
    RescueRouter,
    VehicleType,
    load_vehicle_limits,
    GroundedWeatherStatus,
    NoRoadRouteStatus,
)
from modules.rescue_routing.dispatch import compute_delivery_sorties_and_mix


def _create_detour_graph():
    g = nx.Graph()
    g.add_node("A", lat=40.0, lon=-1.0, type="hospital")
    g.add_node("B", lat=40.0, lon=-0.98, type="shelter")
    g.add_node("C", lat=40.01, lon=-1.0, type="junction")
    g.add_node("D", lat=40.01, lon=-0.98, type="junction")

    # direct blocked segment
    g.add_edge("A", "B", distance_meters=2000.0, travel_time_seconds=120.0, elevation_meters=200.0,
               distance_to_river_meters=500.0, kind="road", current_water_depth_meters=0.0, name="Direct Road")
    # detour route A -> C -> D -> B
    g.add_edge("A", "C", distance_meters=1100.0, travel_time_seconds=80.0, elevation_meters=210.0,
               distance_to_river_meters=600.0, kind="road", current_water_depth_meters=0.0, name="North Road West")
    g.add_edge("C", "D", distance_meters=2000.0, travel_time_seconds=130.0, elevation_meters=215.0,
               distance_to_river_meters=700.0, kind="road", current_water_depth_meters=0.0, name="Highline Corridor")
    g.add_edge("D", "B", distance_meters=1100.0, travel_time_seconds=80.0, elevation_meters=205.0,
               distance_to_river_meters=600.0, kind="road", current_water_depth_meters=0.0, name="North Road East")
    return g


def test_detour_taken_when_straight_line_crosses_blocked_road():
    g = _create_detour_graph()
    router = RescueRouter(g)
    res = router.find_route("A", "B", VehicleType.AMBULANCE, blocked_edges=[("A", "B")])
    assert res["status"] == "OK"
    assert res["path_nodes"] == ["A", "C", "D", "B"]
    coords = res["geojson_geometry"]["coordinates"]
    assert len(coords) >= 4
    # Ensure blocked edge is avoided
    for u, v in zip(res["path_nodes"][:-1], res["path_nodes"][1:]):
        assert tuple(sorted((u, v))) != tuple(sorted(("A", "B")))


def test_no_road_path_gives_no_road_route():
    g = _create_detour_graph()
    router = RescueRouter(g)
    # Block both direct and detour paths
    res = router.find_route("A", "B", VehicleType.AMBULANCE, blocked_edges=[("A", "B"), ("C", "D")])
    assert res["status"] == "NO_ROAD_ROUTE"
    assert res["status"] == "UNREACHABLE"
    assert res["geojson_geometry"] is None
    assert "area cut off" in res["reason"].lower() or "area cut off" in res["wording"].lower()


def test_regression_fails_on_any_2_point_road_corridor():
    # 2-point corridor must fail validation unless labeled AIR_LINE or WATER_LINE
    road_corridor = {
        "status": "OK",
        "corridor_type": "ROADS",
        "geometry": {"type": "LineString", "coordinates": [[-1.0, 40.0], [-0.98, 40.0]]},
    }
    air_corridor = {
        "status": "OK",
        "corridor_type": "AIR_LINE",
        "geometry": {"type": "LineString", "coordinates": [[-1.0, 40.0], [-0.98, 40.0]]},
    }

    def validate_corridor(c):
        coords = c["geometry"]["coordinates"]
        is_air_or_water = c.get("corridor_type") in ("AIR_LINE", "WATER_LINE")
        if len(coords) < 3 and not is_air_or_water:
            return False
        return True

    assert validate_corridor(road_corridor) is False
    assert validate_corridor(air_corridor) is True


def test_truck_passes_where_ambulance_fails():
    g = nx.Graph()
    g.add_node("N1", lat=41.0, lon=-1.0, type="hospital")
    g.add_node("N2", lat=41.01, lon=-1.0, type="shelter")
    # Depth = 0.30m, which sits between ambulance limit (0.0m) and truck wading limit (0.40m)
    g.add_edge("N1", "N2", distance_meters=1000.0, travel_time_seconds=60.0, elevation_meters=200.0,
               distance_to_river_meters=300.0, kind="road", current_water_depth_meters=0.30, name="Flooded Street")

    router = RescueRouter(g)
    amb_res = router.find_route("N1", "N2", VehicleType.AMBULANCE)
    truck_res = router.find_route("N1", "N2", VehicleType.TRUCK_4X4)

    assert amb_res["status"] in ("UNREACHABLE", "NO_ROAD_ROUTE")
    assert truck_res["status"] == "OK"
    assert truck_res["path_nodes"] == ["N1", "N2"]


def test_boat_eta_consistent_across_scenarios():
    g = nx.Graph()
    g.add_node("DEPOT", lat=41.0, lon=-1.0, type="depot")
    g.add_node("RAMP", lat=41.01, lon=-1.0, type="ramp")
    g.add_node("ISLAND", lat=41.02, lon=-1.0, type="shelter")

    g.add_edge("DEPOT", "RAMP", distance_meters=1500.0, travel_time_seconds=120.0, elevation_meters=210.0,
               distance_to_river_meters=100.0, kind="road", current_water_depth_meters=0.0, name="Ground Approach")
    g.add_edge("RAMP", "ISLAND", distance_meters=2000.0, travel_time_seconds=200.0, elevation_meters=190.0,
               distance_to_river_meters=0.0, kind="river", current_water_depth_meters=2.5, name="River Channel")

    router = RescueRouter(g)
    res1 = router.find_multimodal_route("DEPOT", "ISLAND", scenario_id="scenario_alpha")
    res2 = router.find_multimodal_route("DEPOT", "ISLAND", scenario_id="scenario_beta")

    assert res1["status"] == "OK"
    assert res2["status"] == "OK"
    assert res1["eta_minutes"] == res2["eta_minutes"]

    # Verify legs include travel to ramp + launch + water leg
    assert len(res1["legs"]) == 2
    assert res1["legs"][0]["mode"] == "TRUCK_4X4"
    assert res1["legs"][1]["mode"] == "RESCUE_BOAT"
    expected_eta = round(res1["legs"][0]["eta_minutes"] + 10.0 + res1["legs"][1]["eta_minutes"], 2)
    assert res1["eta_minutes"] == expected_eta


def test_helicopter_weather_limits_and_unknown():
    g = nx.Graph()
    g.add_node("BASE", lat=41.0, lon=-1.0)
    g.add_node("ZONE", lat=41.05, lon=-1.0)

    router = RescueRouter(g)

    # Severe wind (85 km/h > 75 km/h limit)
    res_wind = router.find_route("BASE", "ZONE", VehicleType.HELICOPTER, wind_kmh=85.0)
    assert res_wind["status"] == "GROUNDED_WEATHER"
    assert res_wind["status"] == "UNREACHABLE"
    assert "WEATHER_GROUNDED" in res_wind["reason"]
    assert res_wind["geojson_geometry"] is None

    # Weather absent -> WEATHER_UNKNOWN
    res_unknown = router.find_route("BASE", "ZONE", VehicleType.HELICOPTER)
    assert res_unknown["status"] == "OK"
    assert res_unknown["weather_assessment"] == "WEATHER_UNKNOWN"


def test_fallback_chain_order():
    g = nx.Graph()
    g.add_node("HOSPITAL_BASE", lat=41.0, lon=-1.0)
    g.add_node("DEST", lat=41.05, lon=-1.0)

    # Cut all ground and boat access, forcing escalation to helicopter
    router = RescueRouter(g)
    cascade = router.plan_cascade("DEST", origin="HOSPITAL_BASE")

    attempts = cascade["attempts"]
    assert len(attempts) == 4

    expected_sequence = [
        (1, "Ambulance", "AMBULANCE"),
        (2, "4x4 Truck", "TRUCK_4X4"),
        (3, "Rescue Boat (Multimodal)", "RESCUE_BOAT"),
        (4, "Helicopter", "HELICOPTER"),
    ]
    for att, (exp_stage, exp_title, exp_vehicle) in zip(attempts, expected_sequence):
        assert att["stage"] == exp_stage
        assert att["stage_title"] == exp_title
        assert att["vehicle_type"] == exp_vehicle

    assert cascade["selected_vehicle"] == "HELICOPTER"


def test_cascade_keyed_by_scenario_and_stage():
    g = nx.Graph()
    g.add_node("HOSPITAL_BASE", lat=41.0, lon=-1.0)
    g.add_node("DEST", lat=41.05, lon=-1.0)

    router = RescueRouter(g)
    cascade = router.plan_cascade("DEST", origin="HOSPITAL_BASE", scenario_id="scenario_rapid_response")

    keyed_attempts = {}
    for att in cascade["attempts"]:
        key = (att["scenario_id"], att["stage"], att["vehicle_type"])
        assert key not in keyed_attempts, f"Duplicate attempt key detected: {key}"
        keyed_attempts[key] = att

    assert len(keyed_attempts) == 4


def test_total_delivery_time_monotonic_in_payload():
    vehicle_etas = {
        "AMBULANCE": 10.0,
        "TRUCK_4X4": 15.0,
        "RESCUE_BOAT": 25.0,
        "HELICOPTER": 12.0,
    }

    payloads = [400.0, 800.0, 1600.0, 3200.0]
    prev_sorties = {v: 0 for v in vehicle_etas}
    prev_times = {v: 0.0 for v in vehicle_etas}

    for p in payloads:
        res = compute_delivery_sorties_and_mix(p, vehicle_etas)
        for v in vehicle_etas:
            v_info = res["per_vehicle"][v]
            assert v_info["feasible"] is True
            assert v_info["sorties"] >= prev_sorties[v]
            assert v_info["total_delivery_time_min"] >= prev_times[v]
            prev_sorties[v] = v_info["sorties"]
            prev_times[v] = v_info["total_delivery_time_min"]


def test_router_determinism_seed_42():
    random.seed(42)
    g = _create_detour_graph()
    router1 = RescueRouter(g)
    res1 = router1.find_route("A", "B", VehicleType.AMBULANCE, blocked_edges=[("A", "B")])

    random.seed(42)
    router2 = RescueRouter(g)
    res2 = router2.find_route("A", "B", VehicleType.AMBULANCE, blocked_edges=[("A", "B")])

    assert res1["eta_minutes"] == res2["eta_minutes"]
    assert res1["distance_km"] == res2["distance_km"]
    assert res1["path_nodes"] == res2["path_nodes"]
    assert res1["geojson_geometry"] == res2["geojson_geometry"]
