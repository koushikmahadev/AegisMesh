"""Unit tests for the rescue routing engine."""

import json
import pytest
from modules.rescue_routing import (
    load_network,
    calculate_edge_risk,
    RescueRouter,
    VehicleType,
    generate_tactical_briefing,
    ON_SCENE_DWELL_MIN,
    RISK_TIME_PENALTY,
)


@pytest.fixture
def graph():
    return load_network()


def test_ambulance_baseline_via_piedra(graph):
    router = RescueRouter(graph)
    res = router.find_route(
        "HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0
    )
    assert res["status"] == "OK"
    assert "PUENTE_PIEDRA_SOUTH" in res["path_nodes"]
    assert "PUENTE_PIEDRA_NORTH" in res["path_nodes"]
    assert "PUENTE_SANTIAGO_SOUTH" not in res["path_nodes"]

    nodes = res["path_nodes"]
    edges = list(zip(nodes[:-1], nodes[1:]))
    exp_dist = round(sum(graph[u][v]["distance_meters"] for u, v in edges) / 1000.0, 3)
    exp_eta = round(sum(graph[u][v]["travel_time_seconds"] for u, v in edges) * 1.0 / 60.0, 2)
    assert res["distance_km"] == exp_dist
    assert res["eta_minutes"] == exp_eta
    assert res["is_predictive_detour"] is False
    assert len(res["avoided_hazards"]) == 0


def test_piedra_blocked_santiago_detour(graph):
    router = RescueRouter(graph)
    res = router.find_route(
        "HOSPITAL_BASE",
        "ZONE_NORTH_RESIDENTIAL",
        VehicleType.AMBULANCE,
        blocked_edges=[("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH")],
        rainfall_rate=15.0,
    )
    assert res["status"] == "OK"
    assert "PUENTE_SANTIAGO_SOUTH" in res["path_nodes"]
    assert "PUENTE_SANTIAGO_NORTH" in res["path_nodes"]
    assert "PUENTE_PIEDRA_SOUTH" not in res["path_nodes"]
    assert res["is_predictive_detour"] is False

    avoided = {h["reason"] for h in res["avoided_hazards"]}
    assert "BLOCKED" in avoided


def test_predictive_detour_at_45mmh(graph):
    router = RescueRouter(graph)
    res = router.find_route(
        "HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=45.0
    )
    assert res["status"] == "OK"
    assert "PUENTE_SANTIAGO_SOUTH" in res["path_nodes"]
    assert "PUENTE_SANTIAGO_NORTH" in res["path_nodes"]
    assert "PUENTE_PIEDRA_SOUTH" not in res["path_nodes"]
    assert res["is_predictive_detour"] is True

    hazards = {h["reason"] for h in res["avoided_hazards"]}
    assert "PREDICTED_SUBMERSION" in hazards


def test_depth_boundaries(graph):
    router = RescueRouter(graph)
    edge = ("HOSPITAL_BASE", "JUNCTION_PARAISO")
    res_pass = router.find_route(
        "HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.TRUCK_4X4, edge_depths={edge: 0.40}
    )
    assert res_pass["status"] == "OK"

    res_fail = router.find_route(
        "HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.TRUCK_4X4, edge_depths={edge: 0.41}
    )
    assert res_fail["status"] == "UNREACHABLE"


def test_truck_passes_0_3m_ambulance_fails(graph):
    router = RescueRouter(graph)
    edge = ("HOSPITAL_BASE", "JUNCTION_PARAISO")
    res_amb = router.find_route(
        "HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.AMBULANCE, edge_depths={edge: 0.30}
    )
    assert res_amb["status"] == "UNREACHABLE"

    res_truck = router.find_route(
        "HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.TRUCK_4X4, edge_depths={edge: 0.30}
    )
    assert res_truck["status"] == "OK"


def test_boat_uses_river_edges(graph):
    router = RescueRouter(graph)
    res_boat = router.find_route(
        "BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY", VehicleType.RESCUE_BOAT
    )
    assert res_boat["status"] == "OK"
    assert res_boat["path_nodes"] == ["BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY"]

    res_dry = router.find_route(
        "HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.RESCUE_BOAT
    )
    assert res_dry["status"] == "UNREACHABLE"


def test_island_unreachable_ambulance_truck(graph):
    router = RescueRouter(graph)
    causeway = ("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY")
    depths = {causeway: 0.9}

    res_amb = router.find_route(
        "HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.AMBULANCE, edge_depths=depths
    )
    assert res_amb["status"] == "UNREACHABLE"
    assert res_amb["isolated_nodes"] == ["ZONE_ISLAND_COMMUNITY"]

    exp_cuts = sorted([
        sorted([u, v])
        for u, v in graph.edges
        if (u == "ZONE_ISLAND_COMMUNITY") != (v == "ZONE_ISLAND_COMMUNITY")
    ])
    assert res_amb["cut_edges"] == exp_cuts

    res_trk = router.find_route(
        "HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.TRUCK_4X4, edge_depths=depths
    )
    assert res_trk["status"] == "UNREACHABLE"
    assert res_trk["isolated_nodes"] == ["ZONE_ISLAND_COMMUNITY"]
    assert res_trk["cut_edges"] == exp_cuts


def test_all_vehicles_unreachable_river_blocked(graph):
    router = RescueRouter(graph)
    causeway = ("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY")
    river = ("BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY")
    depths = {causeway: 0.9}
    blocks = [river]

    for veh in [VehicleType.AMBULANCE, VehicleType.TRUCK_4X4, VehicleType.RESCUE_BOAT]:
        res = router.find_route(
            "BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY", veh, blocked_edges=blocks, edge_depths=depths
        )
        assert res["status"] == "UNREACHABLE"


def test_base_graph_unchanged_after_routing(graph):
    edges_before = {
        (u, v): dict(data) for u, v, data in graph.edges(data=True)
    }
    nodes_before = {
        n: dict(data) for n, data in graph.nodes(data=True)
    }

    router = RescueRouter(graph)
    router.find_route(
        "HOSPITAL_BASE",
        "ZONE_NORTH_RESIDENTIAL",
        VehicleType.AMBULANCE,
        blocked_edges=[("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH")],
        rainfall_rate=45.0,
        edge_depths={("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"): 0.9},
    )

    edges_after = {
        (u, v): dict(data) for u, v, data in graph.edges(data=True)
    }
    nodes_after = {
        n: dict(data) for n, data in graph.nodes(data=True)
    }

    assert edges_before == edges_after
    assert nodes_before == nodes_after


def test_risk_acceptance_values(graph):
    for u, v, d in graph.edges(data=True):
        r15 = calculate_edge_risk(d["elevation_meters"], d["distance_to_river_meters"], 15.0)
        assert r15 < 0.01

    piedra = graph["PUENTE_PIEDRA_SOUTH"]["PUENTE_PIEDRA_NORTH"]
    assert calculate_edge_risk(piedra["elevation_meters"], piedra["distance_to_river_meters"], 45.0) > 0.8

    santiago = graph["PUENTE_SANTIAGO_SOUTH"]["PUENTE_SANTIAGO_NORTH"]
    assert calculate_edge_risk(santiago["elevation_meters"], santiago["distance_to_river_meters"], 45.0) < 0.05

    app_s = graph["JUNCTION_PARAISO"]["PUENTE_SANTIAGO_SOUTH"]
    assert calculate_edge_risk(app_s["elevation_meters"], app_s["distance_to_river_meters"], 45.0) < 0.05

    app_n = graph["PUENTE_SANTIAGO_NORTH"]["ZONE_NORTH_RESIDENTIAL"]
    assert calculate_edge_risk(app_n["elevation_meters"], app_n["distance_to_river_meters"], 45.0) < 0.05

    causeway = graph["ZONE_NORTH_RESIDENTIAL"]["ZONE_ISLAND_COMMUNITY"]
    assert calculate_edge_risk(causeway["elevation_meters"], causeway["distance_to_river_meters"], 45.0) > 0.9


def test_coordinate_sanity(graph):
    for n, d in graph.nodes(data=True):
        assert 41.62 <= d["lat"] <= 41.68
        assert -0.92 <= d["lon"] <= -0.85

    for u, v, d in graph.edges(data=True):
        if d["kind"] == "bridge":
            assert 100.0 <= d["distance_meters"] <= 600.0


def test_geojson_coords_lon_lat(graph):
    router = RescueRouter(graph)
    res = router.find_route("HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.AMBULANCE)
    coords = res["geojson_geometry"]["coordinates"]
    for lon, lat in coords:
        assert -0.92 <= lon <= -0.85
        assert 41.62 <= lat <= 41.68


def test_fallback_briefing_offline(monkeypatch, graph):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    router = RescueRouter(graph)
    res = router.find_route("HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.AMBULANCE)
    text, source = generate_tactical_briefing(res)
    assert source == "offline"
    import re
    sentences = [s.strip() for s in re.split(r"\.\s+", text.rstrip(".")) if s.strip()]
    assert len(sentences) == 2

    res_unreach = router.find_route(
        "HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.AMBULANCE,
        edge_depths={("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"): 0.9}
    )
    text_unreach, src_unreach = generate_tactical_briefing(res_unreach)
    assert src_unreach == "offline"
    sentences_unreach = [s.strip() for s in re.split(r"\.\s+", text_unreach.rstrip(".")) if s.strip()]
    assert len(sentences_unreach) == 2
    assert "airdrop" in text_unreach.lower()


def test_routes_json_schema(tmp_path, graph):
    router = RescueRouter(graph)
    res = router.find_route("HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.AMBULANCE)
    briefing, src = generate_tactical_briefing(res)

    feature = {
        "type": "Feature",
        "geometry": res["geojson_geometry"],
        "properties": {k: v for k, v in res.items() if k != "geojson_geometry"},
    }
    payload = {
        "type": "FeatureCollection",
        "features": [feature],
        "scenarios": [
            {
                "id": "scenario_test",
                "title": "Test Route",
                "feature_indices": [0],
                "briefing": briefing,
                "briefing_source": src,
            }
        ],
    }

    out_file = tmp_path / "routes.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    with open(out_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded["type"] == "FeatureCollection"
    assert len(loaded["features"]) == 1
    assert loaded["features"][0]["geometry"]["type"] == "LineString"
    assert len(loaded["scenarios"]) == 1
    assert loaded["scenarios"][0]["briefing_source"] in {"offline", "groq"}

    from pathlib import Path
    root_routes = Path("routes.json")
    if root_routes.exists():
        with open(root_routes, "r", encoding="utf-8") as f:
            r_data = json.load(f)
        assert r_data["type"] == "FeatureCollection"
        assert len(r_data["features"]) > 0
        assert len(r_data["scenarios"]) > 0
        for s in r_data["scenarios"]:
            assert {"id", "title", "feature_indices", "briefing", "briefing_source"}.issubset(s.keys())


def test_river_channel_mid_node_and_edges(graph):
    assert "RIVER_CHANNEL_MID" in graph.nodes
    mid = graph.nodes["RIVER_CHANNEL_MID"]
    assert mid.get("derived") is True
    assert mid["elev_m"] == 194.0

    exp_lat = (graph.nodes["ZONE_NORTH_RESIDENTIAL"]["lat"] + graph.nodes["ZONE_ISLAND_COMMUNITY"]["lat"]) / 2.0
    exp_lon = (graph.nodes["ZONE_NORTH_RESIDENTIAL"]["lon"] + graph.nodes["ZONE_ISLAND_COMMUNITY"]["lon"]) / 2.0
    assert mid["lat"] == pytest.approx(exp_lat)
    assert mid["lon"] == pytest.approx(exp_lon)

    assert graph.has_edge("ZONE_ISLAND_COMMUNITY", "RIVER_CHANNEL_MID")
    assert graph.has_edge("RIVER_CHANNEL_MID", "ZONE_NORTH_RESIDENTIAL")
    assert graph["ZONE_ISLAND_COMMUNITY"]["RIVER_CHANNEL_MID"]["kind"] == "river"
    assert graph["RIVER_CHANNEL_MID"]["ZONE_NORTH_RESIDENTIAL"]["kind"] == "river"
    assert graph["ZONE_ISLAND_COMMUNITY"]["RIVER_CHANNEL_MID"]["current_water_depth_meters"] == 2.0
    assert graph["RIVER_CHANNEL_MID"]["ZONE_NORTH_RESIDENTIAL"]["current_water_depth_meters"] == 2.0

    assert graph.has_edge("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY")
    assert graph["ZONE_NORTH_RESIDENTIAL"]["ZONE_ISLAND_COMMUNITY"]["kind"] == "causeway"


def test_duplicate_edge_raises_value_error(tmp_path):
    dup_network = {
        "nodes": {
            "A": {"lat": 41.6, "lon": -0.8, "elev_m": 200.0, "type": "base"},
            "B": {"lat": 41.7, "lon": -0.8, "elev_m": 200.0, "type": "zone"},
        },
        "edges": [
            {"u": "A", "v": "B", "name": "Edge 1", "kind": "road", "elevation_meters": 200.0, "distance_to_river_meters": 100.0},
            {"u": "B", "v": "A", "name": "Edge 2", "kind": "road", "elevation_meters": 200.0, "distance_to_river_meters": 100.0},
        ],
    }
    net_file = tmp_path / "dup.json"
    with open(net_file, "w", encoding="utf-8") as f:
        json.dump(dup_network, f)
    with pytest.raises(ValueError, match="Duplicate edge"):
        load_network(net_file)


def test_avoided_hazards_qualification_and_precedence(graph):
    router = RescueRouter(graph)
    res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=45.0)
    for h in res["avoided_hazards"]:
        assert h["reason"] in {"BLOCKED", "SUBMERGED", "PREDICTED_SUBMERSION"}
        if h["reason"] == "PREDICTED_SUBMERSION":
            assert h["risk"] >= 0.25


def test_unreachable_component_scope(graph):
    router = RescueRouter(graph)
    causeway = ("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY")
    res = router.find_route("HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.AMBULANCE, edge_depths={causeway: 0.9})
    assert res["status"] == "UNREACHABLE"
    assert res["component_scope"] == "vehicle_passable_subgraph"


def test_edge_cases(graph):
    router = RescueRouter(graph)

    # origin == destination
    res_same = router.find_route("HOSPITAL_BASE", "HOSPITAL_BASE", VehicleType.AMBULANCE)
    assert res_same["status"] == "OK"
    assert res_same["eta_minutes"] == 0.0
    assert res_same["geojson_geometry"] is None
    assert res_same["note"] == "ORIGIN_EQUALS_DESTINATION"

    # unknown node
    res_un = router.find_route("UNKNOWN_NODE", "HOSPITAL_BASE", VehicleType.AMBULANCE)
    assert res_un["status"] == "INVALID_REQUEST"
    assert "Unknown origin" in res_un["reason"]

    # nan / negative rainfall
    res_nan = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=float("nan"))
    assert res_nan["status"] == "INVALID_REQUEST"
    res_neg = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=-1.0)
    assert res_neg["status"] == "INVALID_REQUEST"

    # blocked edges in either order
    r1 = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, blocked_edges=[("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH")])
    r2 = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, blocked_edges=[("PUENTE_PIEDRA_NORTH", "PUENTE_PIEDRA_SOUTH")])
    assert r1["path_nodes"] == r2["path_nodes"]

    # non-existent edge raises ValueError
    with pytest.raises(ValueError):
        router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, blocked_edges=[("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL")])
    with pytest.raises(ValueError):
        router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, edge_depths={("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL"): 0.5})


def test_time_dependent_dijkstra_equals_brute_force(graph):
    router = RescueRouter(graph)
    demo_cases = [
        (VehicleType.AMBULANCE, "HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", {}, set()),
        (VehicleType.AMBULANCE, "HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", {tuple(sorted(("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH"))): 0.8}, set()),
        (VehicleType.RESCUE_BOAT, "BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY", {tuple(sorted(("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"))): 0.9}, set()),
        (VehicleType.AMBULANCE, "HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", {tuple(sorted(("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"))): 0.9}, set()),
        (VehicleType.TRUCK_4X4, "HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", {tuple(sorted(("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"))): 0.9}, set()),
        (VehicleType.RESCUE_BOAT, "BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY", {tuple(sorted(("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"))): 0.9}, {tuple(sorted(("BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY")))}),
    ]

    import networkx as nx
    for v_type, orig, dest, d_map, b_set in demo_cases:
        for rain in [0.0, 15.0, 30.0, 45.0, 60.0]:
            res = router.find_route(orig, dest, v_type, blocked_edges=list(b_set), rainfall_rate=rain, depth_map=d_map)
            # compare against brute force
            def passable(u, v):
                pair = tuple(sorted((u, v)))
                if pair in b_set:
                    return False
                d = d_map.get(pair, graph[u][v].get("current_water_depth_meters", 0.0))
                return router._is_passable(v_type, d)

            view = nx.subgraph_view(graph, filter_edge=passable)
            if not (orig in view and dest in view and nx.has_path(view, orig, dest)):
                assert res["status"] == "UNREACHABLE"
            else:
                assert res["status"] == "OK"
                def obj(p):
                    times = [router._travel_time_s(v_type, graph[u][v], d_map.get(tuple(sorted((u, v))), graph[u][v].get("current_water_depth_meters", 0.0))) for u, v in zip(p[:-1], p[1:])]
                    tot_min = sum(times) / 60.0
                    cost = 0.0
                    el = 0.0
                    for idx, (u, v) in enumerate(zip(p[:-1], p[1:])):
                        ed = graph[u][v]
                        t_s = times[idx]
                        h = 2.0 * tot_min + ON_SCENE_DWELL_MIN - (el / 60.0)
                        kind = ed.get("kind", "road")
                        r = calculate_edge_risk(ed["elevation_meters"], ed["distance_to_river_meters"], rain, horizon_min=h, kind=kind)
                        cost += t_s * (1.0 + RISK_TIME_PENALTY * r)
                        el += t_s
                    return cost

                all_paths = list(nx.all_simple_paths(view, orig, dest))
                best_bf = min(all_paths, key=obj)
                assert res["path_nodes"] == best_bf


def test_risk_non_decreasing_in_horizon_min(graph):
    for u, v, d in graph.edges(data=True):
        elev = d["elevation_meters"]
        dist = d["distance_to_river_meters"]
        for rain in [0.0, 15.0, 30.0, 45.0, 60.0]:
            r_prev = -1.0
            for h in [0.0, 5.0, 15.0, 30.0, 60.0, 120.0]:
                r = calculate_edge_risk(elev, dist, rain, horizon_min=h)
                assert r >= r_prev - 1e-9
                r_prev = r


def test_depth_aware_speed_truck(graph):
    router = RescueRouter(graph)
    edge = ("HOSPITAL_BASE", "JUNCTION_PARAISO")
    res_dry = router.find_route("HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.TRUCK_4X4, depth_map={edge: 0.0})
    res_half = router.find_route("HOSPITAL_BASE", "JUNCTION_PARAISO", VehicleType.TRUCK_4X4, depth_map={edge: 0.4})
    # at 0.4m depth, speed factor is 0.5, so eta doubles
    assert res_half["eta_minutes"] == pytest.approx(round(res_dry["eta_minutes"] * 2.0, 2), abs=0.02)


def test_route_reliability_and_edge_risks(graph):
    import math
    router = RescueRouter(graph)
    res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0)
    assert "route_reliability" in res
    assert "edge_risks" in res
    assert len(res["edge_risks"]) == len(res["path_nodes"]) - 1
    exp_rel = round(math.prod(1.0 - r for r in res["edge_risks"]), 4)
    assert res["route_reliability"] == pytest.approx(exp_rel, abs=1e-4)


def test_counterfactual_structure(graph):
    router = RescueRouter(graph)
    res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=45.0)
    assert "counterfactual" in res
    cf = res["counterfactual"]
    expected_keys = {"reactive_path_nodes", "reactive_eta_min", "reactive_reliability", "eta_delta_min", "reliability_gain"}
    assert expected_keys.issubset(cf.keys())
    assert cf["eta_delta_min"] >= 0.0
    assert cf["reliability_gain"] >= 0.0


def test_departure_window_and_reliability_monotonic_in_delay(graph):
    router = RescueRouter(graph)
    res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0)
    assert "departure_window_min" in res
    assert "window_capped" in res
    assert res["departure_window_min"] in range(0, 125, 5)

    # test reliability is non-increasing in delay d
    nodes = res["path_nodes"]
    r_prev = 2.0
    for d in range(0, 125, 5):
        _, _, _, rel = router._compute_path_metrics(nodes, VehicleType.AMBULANCE, 15.0, float(d), {})
        assert rel <= r_prev + 1e-9
        r_prev = rel

    # null if it fails at d = 0 (reliability < RELIABILITY_MIN)
    res_high_rain = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=60.0)
    if res_high_rain["status"] == "OK" and (res_high_rain["route_reliability"] or 0.0) < 0.90:
        assert res_high_rain["departure_window_min"] is None
        assert res_high_rain["window_capped"] is False


def test_helicopter_flight_and_grounding(graph):
    from modules.rescue_routing.osm_loader import haversine_distance
    from modules.rescue_routing import HELI_LAUNCH_MINUTES
    router = RescueRouter(graph)
    res_ok = router.find_route("HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.HELICOPTER, rainfall_rate=15.0)
    assert res_ok["status"] == "OK"
    assert res_ok["path_nodes"] == ["HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY"]
    assert res_ok["route_reliability"] is None

    u_n = graph.nodes["HOSPITAL_BASE"]
    v_n = graph.nodes["ZONE_ISLAND_COMMUNITY"]
    exp_dist = round(haversine_distance(u_n["lon"], u_n["lat"], v_n["lon"], v_n["lat"]) / 1000.0, 3)
    exp_eta = round(HELI_LAUNCH_MINUTES + (exp_dist / 180.0) * 60.0, 2)
    assert res_ok["distance_km"] == exp_dist
    assert res_ok["eta_minutes"] == exp_eta
    assert res_ok["launch_minutes"] == HELI_LAUNCH_MINUTES
    assert res_ok["geometry_length_km"] == exp_dist
    assert len(res_ok["geojson_geometry"]["coordinates"]) == 2

    # grounded at 60 mm/h
    res_grounded = router.find_route("HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.HELICOPTER, rainfall_rate=60.0)
    assert res_grounded["status"] == "UNREACHABLE"
    assert res_grounded["reason"] == "WEATHER_GROUNDED"


def test_multimodal_boat_route(graph):
    router = RescueRouter(graph)
    # HOSPITAL_BASE is not a ramp, so it uses TRUCK_4X4 to BOAT_RAMP_SOUTH then RESCUE_BOAT
    res = router.find_multimodal_route("HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.RESCUE_BOAT)
    assert res["status"] == "OK"
    assert "legs" in res
    assert len(res["legs"]) == 2
    assert res["legs"][0]["mode"] == "TRUCK_4X4"
    assert res["legs"][1]["mode"] == "RESCUE_BOAT"
    assert res["legs"][0]["path_nodes"][-1] == "BOAT_RAMP_SOUTH"
    assert res["legs"][1]["path_nodes"][0] == "BOAT_RAMP_SOUTH"

    # top-level geometry should drop duplicate junction coordinate
    coords = res["geojson_geometry"]["coordinates"]
    expected_len = len(res["legs"][0]["geometry"]["coordinates"]) + len(res["legs"][1]["geometry"]["coordinates"]) - 1
    assert len(coords) == expected_len

    # eta includes 10 min launch
    exp_eta = round(res["legs"][0]["eta_minutes"] + 10.0 + res["legs"][1]["eta_minutes"], 2)
    assert res["eta_minutes"] == exp_eta


def test_plan_cascade(graph):
    router = RescueRouter(graph)
    causeway = ("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY")
    river = ("BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY")

    cascade = router.plan_cascade(
        "ZONE_ISLAND_COMMUNITY",
        rainfall_rate=15.0,
        blocked_edges=[river],
        depth_map={causeway: 0.9},
    )
    assert len(cascade["attempts"]) == 4
    # AMBULANCE fails, TRUCK fails, BOAT fails (river blocked), HELICOPTER succeeds
    assert cascade["attempts"][0]["status"] == "UNREACHABLE"
    assert cascade["attempts"][1]["status"] == "UNREACHABLE"
    assert cascade["attempts"][2]["status"] == "UNREACHABLE"
    assert cascade["attempts"][3]["status"] == "OK"
    assert cascade["selected_vehicle"] == "HELICOPTER"
    assert cascade["selected_route"]["geojson_geometry"] is not None


def test_network_geojson_export(graph):
    router = RescueRouter(graph)
    net_fc = router.export_network_geojson()
    assert net_fc["type"] == "FeatureCollection"
    assert len(net_fc["features"]) == len(graph.edges)
    for feat in net_fc["features"]:
        assert feat["geometry"]["type"] == "LineString"
        props = feat["properties"]
        assert {"name", "kind", "depth", "elevation", "distance_to_river_m", "geometry_quality"}.issubset(props.keys())


def test_load_depth_map_and_override(graph):
    from modules.rescue_routing import load_depth_map
    depth_map = load_depth_map("data/synthetic_depth_map.json")
    assert isinstance(depth_map, dict)
    pair = tuple(sorted(("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH")))
    assert pair in depth_map
    assert depth_map[pair] == 0.85

    router = RescueRouter(graph)
    # 0.85m depth on Piedra forces ambulance onto Santiago
    res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, depth_map=depth_map)
    assert res["status"] == "OK"
    assert "PUENTE_SANTIAGO_SOUTH" in res["path_nodes"]
    assert "PUENTE_PIEDRA_SOUTH" not in res["path_nodes"]
    assert res["depth_source"] == "depth_map"
    assert res["data_freshness"] == "FRESH"
    assert res["depth_age_min"] == 45


def test_depth_from_mask_fraction():
    from modules.rescue_routing import depth_from_mask_fraction, ASSUMED_FLOOD_DEPTH_M
    assert ASSUMED_FLOOD_DEPTH_M == 1.0

    fractions = {
        ("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH"): 0.75,
        "JUNCTION_PARAISO|JUNCTION_CENTRO": 0.20,
    }
    d_map = depth_from_mask_fraction(fractions)
    pair1 = tuple(sorted(("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH")))
    pair2 = tuple(sorted(("JUNCTION_PARAISO", "JUNCTION_CENTRO")))
    assert d_map[pair1] == 0.75
    assert d_map[pair2] == 0.20


def test_depth_source_and_freshness(graph):
    router = RescueRouter(graph)
    # scenario default
    r_scen = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE)
    assert r_scen["depth_source"] == "scenario"
    assert r_scen["data_freshness"] == "UNKNOWN"

    # stale depth map (> 180 min)
    r_stale = router.find_route(
        "HOSPITAL_BASE",
        "ZONE_NORTH_RESIDENTIAL",
        VehicleType.AMBULANCE,
        depth_map={tuple(sorted(("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH"))): 0.1},
        depth_age_min=200,
    )
    assert r_stale["data_freshness"] == "STALE"
    assert r_stale["depth_age_min"] == 200


def test_slider_dataset_structure(graph):
    router = RescueRouter(graph)
    slider = router.build_slider_dataset()
    assert slider["rainfall_steps_mm_h"] == [0, 15, 30, 45, 60]
    assert len(slider["queries"]) == 3
    assert len(slider["steps"]) == 5
    assert "route_flip_points" in slider
    for step in slider["steps"]:
        assert "rainfall_mm_h" in step
        assert "edge_risks" in step
        assert "advisory" in step
        assert len(step["edge_risks"]) == len(graph.edges)
        if step["rainfall_mm_h"] >= 60:
            assert len(step["results"]) == 4
            assert any(r.get("advisory") == "NO_SAFE_OPTION" for r in step["results"])
        else:
            assert len(step["results"]) == 3


def test_slider_decision_stability(graph):
    import json
    import jsonschema
    from modules.rescue_routing import STABILITY_MIN

    router = RescueRouter(graph)
    slider = router.build_slider_dataset()

    # (a) decision_stability.label matches share_unchanged >= STABILITY_MIN
    for step in slider["steps"]:
        for res in step["results"]:
            assert "decision_stability" in res
            stab = res["decision_stability"]
            assert "share_unchanged" in stab
            assert "label" in stab
            expected_label = "STABLE" if stab["share_unchanged"] >= STABILITY_MIN else "SENSITIVE"
            assert stab["label"] == expected_label

    # (b) at 0 mm/h and 60 mm/h for the ambulance, decision_stability is STABLE
    step_0 = next(s for s in slider["steps"] if s["rainfall_mm_h"] == 0)
    amb_0 = next(r for r in step_0["results"] if r.get("vehicle_type") == "AMBULANCE")
    assert amb_0["decision_stability"]["label"] == "STABLE"

    step_60 = next(s for s in slider["steps"] if s["rainfall_mm_h"] == 60)
    amb_60 = next(r for r in step_60["results"] if r.get("vehicle_type") == "AMBULANCE")
    assert amb_60["decision_stability"]["label"] == "STABLE"

    # (c) slider results validate against schema.json
    with open("schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    slider_schema = schema["properties"]["slider"]
    jsonschema.validate(instance=slider, schema=slider_schema)


def test_assign_fleet_demo_instance(graph):
    import itertools
    from modules.rescue_routing import assign_fleet, run_benchmark

    router = RescueRouter(graph)
    fleet = [
        {"id": "AMB_1", "vehicle_type": "AMBULANCE", "start_node": "HOSPITAL_BASE"},
        {"id": "TRUCK_1", "vehicle_type": "TRUCK_4X4", "start_node": "HOSPITAL_BASE"},
        {"id": "HELI_1", "vehicle_type": "HELICOPTER", "start_node": "HOSPITAL_BASE"},
        {"id": "BOAT_1", "vehicle_type": "RESCUE_BOAT", "start_node": "BOAT_RAMP_SOUTH"},
    ]
    incidents = [
        {"id": "ZONE_ISLAND_COMMUNITY", "node": "ZONE_ISLAND_COMMUNITY", "priority": 5, "people": 40, "deadline_min": 45},
        {"id": "ZONE_NORTH_RESIDENTIAL", "node": "ZONE_NORTH_RESIDENTIAL", "priority": 4, "people": 120, "deadline_min": 30},
        {"id": "PUENTE_SANTIAGO_NORTH", "node": "PUENTE_SANTIAGO_NORTH", "priority": 3, "people": 15, "deadline_min": 30},
    ]
    depth_map = {("ZONE_ISLAND_COMMUNITY", "ZONE_NORTH_RESIDENTIAL"): 0.9}

    res = assign_fleet(incidents, fleet, router, rainfall_rate=45.0, depth_map=depth_map)

    # 1. Output structure and policy
    assert res["policy"] == "One sortie per asset"
    assert "assignments" in res
    assert "unserved" in res

    # 2. Every asset serves at most one incident and vice versa
    assigned_assets = [a["asset"] for a in res["assignments"]]
    assigned_incidents = [a["incident"] for a in res["assignments"]]
    assert len(assigned_assets) == len(set(assigned_assets))
    assert len(assigned_incidents) == len(set(assigned_incidents))
    assert len(assigned_assets) <= len(fleet)
    assert len(assigned_incidents) <= len(incidents)

    # 3. Every assigned pair is feasible
    inc_map = {inc["id"]: inc for inc in incidents}
    fleet_map = {a["id"]: a for a in fleet}
    for ass in res["assignments"]:
        inc = inc_map[ass["incident"]]
        a = fleet_map[ass["asset"]]
        vt = a["vehicle_type"]
        if vt == "RESCUE_BOAT":
            r_check = router.find_multimodal_route(a["start_node"], inc["node"], rainfall_rate=45.0, depth_map=depth_map)
        else:
            r_check = router.find_route(a["start_node"], inc["node"], vt, rainfall_rate=45.0, depth_map=depth_map)
        assert r_check["status"] == "OK"
        assert ass["eta_minutes"] <= inc["deadline_min"]
        req_rel = 1.0 if vt == "HELICOPTER" else 0.5
        assert ass["reliability"] >= req_rel

    # 4. Brute-force verification on all 24 permutations
    best_bf_val = -1.0
    best_bf_eta = float("inf")

    routes_cache = {}
    for a in fleet:
        for inc in incidents:
            vt = a["vehicle_type"]
            if vt == "RESCUE_BOAT":
                r_cache = router.find_multimodal_route(a["start_node"], inc["node"], rainfall_rate=45.0, depth_map=depth_map)
            else:
                r_cache = router.find_route(a["start_node"], inc["node"], vt, rainfall_rate=45.0, depth_map=depth_map)
            routes_cache[(inc["id"], a["id"])] = r_cache

    for perm in itertools.permutations(fleet, len(incidents)):
        cur_val = 0.0
        cur_eta = 0.0
        feasible_count = 0
        for inc, a in zip(incidents, perm):
            r_pair = routes_cache[(inc["id"], a["id"])]
            if r_pair.get("status") == "OK":
                eta = r_pair["eta_minutes"]
                vt = a["vehicle_type"]
                rel = 1.0 if vt == "HELICOPTER" else r_pair.get("route_reliability", 1.0)
                req_rel = 1.0 if vt == "HELICOPTER" else 0.5
                if eta <= inc["deadline_min"] and rel >= req_rel:
                    from modules.rescue_routing import VEHICLE_CAPACITY_KG
                    vt_str = str(a.get("vehicle_type", "AMBULANCE"))
                    cap = VEHICLE_CAPACITY_KG.get(vt_str, 1000.0)
                    req_kg = float(inc.get("required_kg", inc.get("people", 10) * 15.5))
                    people = float(inc.get("people", 10))
                    delivered_kg_share = (min(cap, req_kg) / req_kg) if req_kg > 0 else 1.0
                    cur_val += inc["priority"] * rel * people * delivered_kg_share
                    cur_eta += eta
                    feasible_count += 1
        if feasible_count == len(incidents):
            if cur_val > best_bf_val or (abs(cur_val - best_bf_val) < 1e-6 and cur_eta < best_bf_eta):
                best_bf_val = cur_val
                best_bf_eta = cur_eta

    # (a) Total value equals brute-force optimum
    assert round(res["total_value"], 2) == round(best_bf_val, 2)
    assert round(res["total_eta_minutes"], 2) == round(best_bf_eta, 2)
    assert res["objective"] == "priority*reliability*people*delivered_share"
    for ass in res["assignments"]:
        assert ass["objective"] == "priority*reliability*people*delivered_share"
        assert "people_equivalents_supplied" in ass

    # (d) Determinism
    res2 = assign_fleet(incidents, fleet, router, rainfall_rate=45.0, depth_map=depth_map)
    assert res == res2

    # (e) Demo instance (45 mm/h, causeway depth 0.9) assigns HELI_1 to ZONE_ISLAND_COMMUNITY
    demo_incidents = [
        {"id": "ZONE_ISLAND_COMMUNITY", "node": "ZONE_ISLAND_COMMUNITY", "priority": 5, "people": 450, "required_kg": 20970.0, "deadline_min": 45},
        {"id": "ZONE_NORTH_RESIDENTIAL", "node": "ZONE_NORTH_RESIDENTIAL", "priority": 4, "people": 480, "required_kg": 22370.0, "deadline_min": 30},
        {"id": "PUENTE_SANTIAGO_NORTH", "node": "PUENTE_SANTIAGO_NORTH", "priority": 3, "people": 18, "required_kg": 842.0, "deadline_min": 30},
    ]
    res_demo = assign_fleet(demo_incidents, fleet, router, rainfall_rate=45.0, depth_map=depth_map)
    heli_ass = next((a for a in res_demo["assignments"] if a["asset"] == "HELI_1"), None)
    assert heli_ass is not None
    assert heli_ass["incident"] == "ZONE_ISLAND_COMMUNITY"

    # (f) Scaling people on one incident never lowers that incident's chance of being served
    # Island is served; doubling people preserves its served status
    demo_inc_scaled = [
        {"id": "ZONE_ISLAND_COMMUNITY", "node": "ZONE_ISLAND_COMMUNITY", "priority": 5, "people": 900, "required_kg": 41940.0, "deadline_min": 45},
        {"id": "ZONE_NORTH_RESIDENTIAL", "node": "ZONE_NORTH_RESIDENTIAL", "priority": 4, "people": 480, "required_kg": 22370.0, "deadline_min": 30},
        {"id": "PUENTE_SANTIAGO_NORTH", "node": "PUENTE_SANTIAGO_NORTH", "priority": 3, "people": 18, "required_kg": 842.0, "deadline_min": 30},
    ]
    res_scaled = assign_fleet(demo_inc_scaled, fleet, router, rainfall_rate=45.0, depth_map=depth_map)
    served_incidents_scaled = {a["incident"] for a in res_scaled["assignments"]}
    assert "ZONE_ISLAND_COMMUNITY" in served_incidents_scaled


def test_assign_fleet_unserved_reasons(graph):
    from modules.rescue_routing import assign_fleet

    router = RescueRouter(graph)

    # 1. Invalid node raises ValueError
    bad_inc = [{"id": "BAD", "node": "NONEXISTENT", "priority": 1, "people": 5, "deadline_min": 30}]
    good_fleet = [{"id": "AMB", "vehicle_type": "AMBULANCE", "start_node": "HOSPITAL_BASE"}]
    try:
        assign_fleet(bad_inc, good_fleet, router, rainfall_rate=15.0)
        assert False, "Expected ValueError on unknown incident node"
    except ValueError:
        pass

    # 2. DEADLINE_MISSED
    # Ambulance to North takes ~6.5 min, set deadline to 2 min
    inc_tight = [{"id": "NORTH", "node": "ZONE_NORTH_RESIDENTIAL", "priority": 1, "people": 10, "deadline_min": 2.0}]
    res_tight = assign_fleet(inc_tight, good_fleet, router, rainfall_rate=15.0)
    assert len(res_tight["assignments"]) == 0
    assert len(res_tight["unserved"]) == 1
    assert res_tight["unserved"][0]["reason"] == "DEADLINE_MISSED"

    # 3. UNREACHABLE
    # Island with causeway blocked at 1.0m, ambulance only
    inc_island = [{"id": "ISLAND", "node": "ZONE_ISLAND_COMMUNITY", "priority": 1, "people": 10, "deadline_min": 60.0}]
    depth_block = {("ZONE_ISLAND_COMMUNITY", "ZONE_NORTH_RESIDENTIAL"): 1.0}
    res_unreach = assign_fleet(inc_island, good_fleet, router, rainfall_rate=15.0, depth_map=depth_block)
    assert len(res_unreach["assignments"]) == 0
    assert len(res_unreach["unserved"]) == 1
    assert res_unreach["unserved"][0]["reason"] == "UNREACHABLE"

    # 4. OUT_OF_ASSETS
    # Two incidents feasible for 1 ambulance
    inc_two = [
        {"id": "NORTH_1", "node": "ZONE_NORTH_RESIDENTIAL", "priority": 5, "people": 100, "deadline_min": 30.0},
        {"id": "NORTH_2", "node": "ZONE_NORTH_RESIDENTIAL", "priority": 1, "people": 10, "deadline_min": 30.0},
    ]
    res_comp = assign_fleet(inc_two, good_fleet, router, rainfall_rate=15.0)
    assert len(res_comp["assignments"]) == 1
    assert res_comp["assignments"][0]["incident"] == "NORTH_1"
    assert len(res_comp["unserved"]) == 1
    assert res_comp["unserved"][0]["incident"] == "NORTH_2"
    assert res_comp["unserved"][0]["reason"] == "OUT_OF_ASSETS"


def test_benchmark_execution(graph):
    from modules.rescue_routing import run_benchmark

    router = RescueRouter(graph)
    bench = run_benchmark(router, output_path=None)

    assert "Synthetic benchmark on a 2-route network; demonstrates mechanism, not real-world performance." in bench["disclaimer"]
    assert bench["scenarios_count"] == 1000
    assert bench["seed"] == 42

    for v in ["AMBULANCE", "TRUCK_4X4"]:
        m = bench["metrics"][v]
        for key in ["predictive_stranded_rate", "reactive_stranded_rate", "mean_eta_penalty_minutes"]:
            stat = m[key]
            assert "mean" in stat
            assert "ci_95" in stat
            assert len(stat["ci_95"]) == 2
            assert stat["ci_95"][0] <= stat["ci_95"][1]
        assert "bands" in m
        assert set(m["bands"].keys()) == {"15-30", "30-45", "45-60"}
        assert "predictive_reduces_stranding" in m
        if v == "AMBULANCE":
            assert m["predictive_reduces_stranding"] is True

    assert "sensitivity" in bench
    assert "overall_pct_unchanged" in bench["sensitivity"]
    assert "constants" in bench["sensitivity"]
    assert len(bench["sensitivity"]["constants"]) == 6


def test_benchmark_robustness_variants(graph):
    import json
    import jsonschema
    from modules.rescue_routing import run_benchmark

    router = RescueRouter(graph)
    bench = run_benchmark(router, output_path=None)

    # (a) Confidence intervals have lower <= point_estimate <= upper
    def check_ci(stat):
        ci = stat["ci_95"]
        mean = stat["mean"]
        # Allow tiny rounding bound slack (1e-4) for float rounding
        assert ci[0] <= mean + 1e-4, f"CI lower bound {ci[0]} > mean {mean}"
        assert mean <= ci[1] + 1e-4, f"Mean {mean} > CI upper bound {ci[1]}"

    for variant_obj in bench["ground_truth_variants"]:
        for v in ["AMBULANCE", "TRUCK_4X4"]:
            for key in ["predictive_stranded_rate", "reactive_stranded_rate", "mean_eta_penalty_minutes"]:
                check_ci(variant_obj["overall"][v][key])
            for b in ["15-30", "30-45", "45-60"]:
                for key in ["predictive_stranded_rate", "reactive_stranded_rate", "mean_eta_penalty_minutes"]:
                    check_ci(variant_obj["by_rainfall_band"][b][v][key])

    # (b) Misspecified model produces non-zero stranded rates for both policies at 45-60 mm/h
    misspec = next(v for v in bench["ground_truth_variants"] if v["variant"] == "misspecified_water_level")
    b45_amb = misspec["by_rainfall_band"]["45-60"]["AMBULANCE"]
    assert b45_amb["predictive_stranded_rate"]["mean"] > 0.0, "Predictive stranded rate should be > 0 at 45-60 mm/h"
    assert b45_amb["reactive_stranded_rate"]["mean"] > 0.0, "Reactive stranded rate should be > 0 at 45-60 mm/h"

    # (c) Benchmark output validates against schema.json
    with open("schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    benchmark_schema = schema["properties"]["benchmark"]
    jsonschema.validate(instance=bench, schema=benchmark_schema)

    # (d) Deterministic under seed 42
    bench2 = run_benchmark(router, output_path=None)
    assert bench == bench2, "run_benchmark must produce deterministic output under seed 42"


def test_coordinate_verification_aid(graph):
    import csv
    import json
    from pathlib import Path
    from tools.coordinate_check import generate_coordinate_check_csv

    csv_path = Path("data/coordinate_check.csv")
    if not csv_path.exists():
        generate_coordinate_check_csv()

    # (a) coordinate_check.csv exists and has a row for every node in the graph
    assert csv_path.exists()
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    graph_nodes = set(graph.nodes)
    csv_nodes = {r["id"] for r in rows}
    assert graph_nodes == csv_nodes

    # (b) all latitudes are in [41.6, 41.7] and longitudes in [-0.95, -0.85] (Zaragoza bounding box)
    for r in rows:
        lat = float(r["lat"])
        lon = float(r["lon"])
        assert 41.6 <= lat <= 41.7, f"Latitude {lat} out of Zaragoza bbox [41.6, 41.7]"
        assert -0.95 <= lon <= -0.85, f"Longitude {lon} out of Zaragoza bbox [-0.95, -0.85]"

    # (c) Puente de Piedra y-coordinate is downstream of Puente de Santiago
    node_map = {r["id"]: float(r["lat"]) for r in rows}
    piedra_lat = (node_map["PUENTE_PIEDRA_SOUTH"] + node_map["PUENTE_PIEDRA_NORTH"]) / 2.0
    santiago_lat = (node_map["PUENTE_SANTIAGO_SOUTH"] + node_map["PUENTE_SANTIAGO_NORTH"]) / 2.0
    assert piedra_lat < santiago_lat, f"Puente de Piedra lat {piedra_lat} must be downstream (<) of Santiago lat {santiago_lat}"

    # (d) provenance coordinates_verified is false on the current repo
    with open("data/zaragoza_network.json", "r", encoding="utf-8") as f:
        net_raw = json.load(f)
    meta = net_raw.get("meta", {})
    verified = bool(meta.get("coordinates_verified") is True and meta.get("verified_by"))
    assert verified is False

    with open("routes.json", "r", encoding="utf-8") as f:
        routes_data = json.load(f)
    assert routes_data["provenance"]["coordinates_verified"] is False


def test_routes_json_schema_validation():
    import json
    import jsonschema

    with open("schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open("routes.json", "r", encoding="utf-8") as f:
        routes_data = json.load(f)

    # Validate routes.json against schema.json using jsonschema
    jsonschema.validate(instance=routes_data, schema=schema)


def test_replan_route(graph):
    router = RescueRouter(graph)
    base_res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0)
    assert base_res["status"] == "OK"
    assert "PUENTE_PIEDRA_SOUTH" in base_res["path_nodes"]

    # 1. Unchanged conditions
    rep_same = router.replan(base_res, {"rainfall_rate": 15.0})
    assert not rep_same["changed"]
    assert rep_same["reason"] == "ROUTE_UNCHANGED"
    assert rep_same["eta_delta_min"] == 0.0

    # 2. Heavy rain causes predictive detour to Santiago
    rep_rain = router.replan(base_res, {"rainfall_rate": 45.0})
    assert rep_rain["changed"]
    assert rep_rain["reason"] == "PREDICTIVE_RISK_DETOUR"
    assert rep_rain["eta_delta_min"] > 0
    assert "PUENTE_SANTIAGO_SOUTH" in rep_rain["new_payload"]["path_nodes"]

    # 3. Sudden blockage renders route unreachable
    rep_blocked = router.replan(base_res, {
        "blocked_edges": [
            ["PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH"],
            ["PUENTE_SANTIAGO_SOUTH", "PUENTE_SANTIAGO_NORTH"],
        ]
    })
    assert rep_blocked["changed"]
    assert rep_blocked["new_payload"]["status"] == "UNREACHABLE"


def test_display_geometry_osm_polyline(graph):
    router = RescueRouter(graph)
    # Inject display_geometry onto an edge
    pair = ("PUENTE_PIEDRA_SOUTH", "PUENTE_PIEDRA_NORTH")
    u, v = pair
    poly = [[-0.876, 41.656], [-0.8755, 41.657], [-0.875, 41.658]]
    graph[u][v]["display_geometry"] = {"type": "LineString", "coordinates": poly}

    res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0)
    assert res["status"] == "OK"
    assert res["geometry_quality"] == "osm_polyline"
    assert len(res["geojson_geometry"]["coordinates"]) > len(res["path_nodes"])

    # Network export also carries osm_polyline quality
    net_fc = router.export_network_geojson()
    feat = [f for f in net_fc["features"] if f["properties"]["name"] == graph[u][v]["name"]][0]
    assert feat["properties"]["geometry_quality"] == "osm_polyline"
    assert feat["geometry"]["coordinates"] == poly

    # Clean up graph fixture
    del graph[u][v]["display_geometry"]


def test_fastapi_endpoints():
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from modules.rescue_routing.api import app

    client = TestClient(app)
    net_resp = client.get("/network")
    assert net_resp.status_code == 200
    assert net_resp.json()["type"] == "FeatureCollection"

    route_resp = client.post("/route", json={
        "origin": "HOSPITAL_BASE",
        "destination": "ZONE_NORTH_RESIDENTIAL",
        "vehicle_type": "AMBULANCE",
        "rainfall_rate": 15.0
    })
    assert route_resp.status_code == 200
    assert route_resp.json()["status"] == "OK"


def test_phase1_risk_model_and_acceptance(graph):
    import math
    from modules.rescue_routing.risk_engine import calculate_river_flow_hazard
    router = RescueRouter(graph)

    # 1. 15 mm/h planning risks all < 0.01
    for u, v, d in graph.edges(data=True):
        r15 = calculate_edge_risk(d["elevation_meters"], d["distance_to_river_meters"], 15.0, horizon_min=30.0, kind=d.get("kind", "road"))
        assert r15 < 0.01
    res15 = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0)
    assert res15["status"] == "OK"
    assert "PUENTE_PIEDRA_SOUTH" in res15["path_nodes"]
    assert res15["eta_minutes"] == pytest.approx(5.89, abs=0.1)

    # 2. 45 mm/h planning risks
    piedra = graph["PUENTE_PIEDRA_SOUTH"]["PUENTE_PIEDRA_NORTH"]
    assert calculate_edge_risk(piedra["elevation_meters"], piedra["distance_to_river_meters"], 45.0, horizon_min=30.0) > 0.8
    santiago = graph["PUENTE_SANTIAGO_SOUTH"]["PUENTE_SANTIAGO_NORTH"]
    assert calculate_edge_risk(santiago["elevation_meters"], santiago["distance_to_river_meters"], 45.0, horizon_min=30.0) < 0.05
    app_s = graph["JUNCTION_PARAISO"]["PUENTE_SANTIAGO_SOUTH"]
    assert calculate_edge_risk(app_s["elevation_meters"], app_s["distance_to_river_meters"], 45.0, horizon_min=30.0) < 0.05
    app_n = graph["PUENTE_SANTIAGO_NORTH"]["ZONE_NORTH_RESIDENTIAL"]
    assert calculate_edge_risk(app_n["elevation_meters"], app_n["distance_to_river_meters"], 45.0, horizon_min=30.0) < 0.05
    causeway = graph["ZONE_NORTH_RESIDENTIAL"]["ZONE_ISLAND_COMMUNITY"]
    assert calculate_edge_risk(causeway["elevation_meters"], causeway["distance_to_river_meters"], 45.0, horizon_min=30.0) > 0.9

    # 3. 45 mm/h round-trip router behavior and counterfactual
    res45 = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=45.0)
    assert res45["status"] == "OK"
    assert "PUENTE_SANTIAGO_SOUTH" in res45["path_nodes"]
    assert res45["route_reliability"] >= 0.9
    cf = res45["counterfactual"]
    assert "PUENTE_PIEDRA_SOUTH" in cf["reactive_path_nodes"]
    assert cf["reactive_reliability"] < 0.6
    assert cf["reliability_gain"] > 0.3
    assert res45["route_reliability"] == round(math.prod(1.0 - r for r in res45["edge_risks"]), 4)

    # 4. 60 mm/h truck and high risk path reliability
    res60_truck = router.find_route("HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.TRUCK_4X4, rainfall_rate=60.0)
    if res60_truck["status"] == "OK":
        assert res60_truck["route_reliability"] < 0.05

    # 5. river flow hazard monotonicity
    prev_h = -1.0
    for h in [0.0, 15.0, 30.0, 60.0]:
        val = calculate_river_flow_hazard(30.0, horizon_min=h)
        assert val >= prev_h - 1e-9
        prev_h = val


def test_needs_engine():
    import math
    from modules.rescue_routing import (
        estimate_needs,
        build_priority_loading_plan,
        WATER_L_PER_PERSON_DAY,
        KCAL_PER_PERSON_DAY,
        FOOD_KG_PER_PERSON_DAY,
        VEHICLE_CAPACITY_KG,
    )

    # 1. Sphere constants
    assert WATER_L_PER_PERSON_DAY == 15.0
    assert KCAL_PER_PERSON_DAY == 2100.0
    assert FOOD_KG_PER_PERSON_DAY == 0.5

    # 2. Funnel monotonicity & low <= central <= high
    res_needs = estimate_needs("ZONE_NORTH_RESIDENTIAL", exposure_fraction=0.6, days=3.0, ground_reachable=True)
    assert res_needs["synthetic"] is True
    demo = res_needs["demographics"]
    assert demo["residents"] >= demo["exposed"] >= 0

    sc = res_needs["scenarios"]
    for sc_name in ["low", "central", "high"]:
        s = sc[sc_name]
        assert demo["residents"] >= demo["exposed"] >= s["stranded"] >= s["in_need"] >= 0
        for vt, cap in VEHICLE_CAPACITY_KG.items():
            assert s["sorties_needed"][vt] == math.ceil(s["total_payload_kg"] / cap)

    assert sc["low"]["stranded"] <= sc["central"]["stranded"] <= sc["high"]["stranded"]
    assert sc["low"]["total_payload_kg"] <= sc["central"]["total_payload_kg"] <= sc["high"]["total_payload_kg"]

    # 3. Linear scaling in days and exposure
    needs_3d = estimate_needs("ZONE_ISLAND_COMMUNITY", exposure_fraction=0.5, days=3.0, ground_reachable=True)
    needs_6d = estimate_needs("ZONE_ISLAND_COMMUNITY", exposure_fraction=0.5, days=6.0, ground_reachable=True)
    assert needs_6d["scenarios"]["central"]["relief_water_kg"] == pytest.approx(
        2 * needs_3d["scenarios"]["central"]["relief_water_kg"], abs=1e-1
    )
    assert needs_6d["scenarios"]["central"]["relief_food_kg"] == pytest.approx(
        2 * needs_3d["scenarios"]["central"]["relief_food_kg"], abs=1e-1
    )

    # 4. UNREACHABLE forces stranded share to 1.0
    needs_unreachable = estimate_needs("ZONE_ISLAND_COMMUNITY", exposure_fraction=0.8, days=3.0, ground_reachable=False)
    for sc_name in ["low", "central", "high"]:
        assert needs_unreachable["scenarios"][sc_name]["stranded_share"] == 1.0
        assert needs_unreachable["scenarios"][sc_name]["stranded"] == needs_unreachable["demographics"]["exposed"]

    # 5. Priority loading manifest ordering (medical > survival water > sustenance water > food)
    plan = build_priority_loading_plan(100, days=3.0)
    assert len(plan) == 4
    assert plan[0]["category"] == "MEDICAL"
    assert plan[1]["category"] == "SURVIVAL_WATER"
    assert plan[2]["category"] == "SUSTENANCE_WATER"
    assert plan[3]["category"] == "FOOD_RATIONS"


def test_scenario_5_and_multimodal_cascade(graph):
    router = RescueRouter(graph)
    causeway_flooded = {("ZONE_NORTH_RESIDENTIAL", "ZONE_ISLAND_COMMUNITY"): 0.9}
    river_blocked = [("BOAT_RAMP_SOUTH", "ZONE_ISLAND_COMMUNITY")]

    # Unblocked river: multimodal boat from hospital succeeds
    cas1 = router.plan_cascade("ZONE_ISLAND_COMMUNITY", rainfall_rate=45.0, depth_map=causeway_flooded)
    assert cas1["selected_vehicle"] == "RESCUE_BOAT"
    assert len(cas1["selected_route"]["legs"]) == 2
    assert cas1["selected_route"]["legs"][0]["mode"] == "TRUCK_4X4"
    assert cas1["selected_route"]["legs"][1]["mode"] == "RESCUE_BOAT"

    # Blocked river: full escalation to helicopter
    cas2 = router.plan_cascade("ZONE_ISLAND_COMMUNITY", rainfall_rate=45.0, depth_map=causeway_flooded, blocked_edges=river_blocked)
    assert cas2["selected_vehicle"] == "HELICOPTER"
    assert cas2["selected_route"]["status"] == "OK"
    assert cas2["selected_route"]["geometry_quality"] == "great_circle"
    assert cas2["selected_route"]["eta_delta_min"] == 0.0

    # Helicopter briefing mentions severed surface access
    from modules.rescue_routing import generate_tactical_briefing
    heli_route = cas2["selected_route"]
    heli_route["surface_access_severed"] = True
    briefing, src = generate_tactical_briefing(heli_route)
    assert "Surface access corridors are completely severed" in briefing
    # Exactly two sentences (briefing consists of two sentences separated by '. ')
    sentences = [s.strip() for s in briefing.split(". ") if s.strip()]
    assert len(sentences) == 2


def test_v2_1_1_features(graph):
    router = RescueRouter(graph)
    # Test advisory on OK route
    res = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=15.0)
    assert res["status"] == "OK"
    assert "advisory" in res
    assert res["advisory"] in {"NONE", "LOW_RELIABILITY", "NO_SAFE_OPTION"}
    assert "max_planning_risk" in res
    assert "risk_warning" in res
    assert isinstance(res["risk_warning"], bool)

    # Test predictive detour avoided hazards has planning_risk and risk alias
    res2a = router.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=45.0)
    assert res2a["is_predictive_detour"] is True
    for h in res2a["avoided_hazards"]:
        assert "planning_risk" in h
        assert "risk" in h
        assert h["planning_risk"] == h["risk"]


def test_generator_determinism_separate_processes():
    import subprocess
    import sys
    from pathlib import Path

    # Run run_demo.py twice in separate Python processes
    p1 = subprocess.run([sys.executable, "run_demo.py", "--no-pause"], capture_output=True, text=True)
    assert p1.returncode == 0, f"run_demo process 1 failed: {p1.stderr}"
    routes1 = Path("routes.json").read_bytes()
    bench1 = Path("benchmark_results.json").read_bytes()

    p2 = subprocess.run([sys.executable, "run_demo.py", "--no-pause"], capture_output=True, text=True)
    assert p2.returncode == 0, f"run_demo process 2 failed: {p2.stderr}"
    routes2 = Path("routes.json").read_bytes()
    bench2 = Path("benchmark_results.json").read_bytes()

    assert routes1 == routes2, "routes.json must be byte-identical across separate generator processes"
    assert bench1 == bench2, "benchmark_results.json must be byte-identical across separate generator processes"


def test_manifest_integrity():
    import hashlib
    from pathlib import Path
    from tools.make_manifest import generate_manifest

    manifest_path = Path("MANIFEST.sha256")
    if not manifest_path.exists():
        generate_manifest()

    assert manifest_path.exists(), "MANIFEST.sha256 must exist"
    with open(manifest_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) >= 15, "Manifest must cover all critical engine files"
    for line in lines:
        expected_sha, rel_path = line.split("  ", 1)
        target = Path(rel_path)
        assert target.exists(), f"File listed in manifest does not exist: {rel_path}"
        h = hashlib.sha256()
        with open(target, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        actual_sha = h.hexdigest()
        assert actual_sha == expected_sha, f"SHA-256 mismatch for {rel_path}: expected {expected_sha}, got {actual_sha}"


def test_deprecated_features_and_superseded_integrity():
    import json
    with open("routes.json", "r", encoding="utf-8") as f:
        routes_data = json.load(f)

    feats = routes_data.get("features", [])
    scenarios = routes_data.get("scenarios", [])

    # Exactly 14 features without any deprecated or superseded duplicates
    assert len(feats) == 14
    for i, feat in enumerate(feats):
        props = feat["properties"]
        assert "deprecated" not in props, f"Feature {i} contains deprecated property"
        assert "superseded_by" not in props, f"Feature {i} contains superseded_by property"

    # Every feature belongs to exactly one scenario
    feat_sc_map = {i: [] for i in range(len(feats))}
    for sc in scenarios:
        for idx in sc.get("feature_indices", []):
            assert 0 <= idx < len(feats), f"Scenario {sc.get('id')} has invalid feature index {idx}"
            feat_sc_map[idx].append(sc["id"])
        sel_idx = sc.get("selected_feature_index")
        if sel_idx is not None:
            assert 0 <= sel_idx < len(feats)

    for idx, sc_list in feat_sc_map.items():
        assert len(sc_list) == 1, f"Feature {idx} belongs to {len(sc_list)} scenarios ({sc_list}), expected exactly 1"

    # In each scenario, no duplicate (vehicle_type, origin, destination) unless blocked_edges differ
    for sc in scenarios:
        seen = {}
        for idx in sc.get("feature_indices", []):
            p = feats[idx]["properties"]
            key = (p.get("vehicle_type"), p.get("origin"), p.get("destination"))
            b_edges = str(sorted([str(e) for e in p.get("blocked_edges", [])]))
            if key in seen:
                assert b_edges != seen[key], f"Scenario {sc['id']} has duplicate {key} with identical blocked edges"
            seen[key] = b_edges

    # Cascade scenarios have stage and stage_title
    for sc_id, exp_stages in [
        ("scenario_3a_island_cutoff_boat_success", [1, 2, 3]),
        ("scenario_3b_total_isolation_airdrop", [4, 5]),
        ("scenario_5_full_cascade", [1, 2, 3, 4, 5]),
    ]:
        sc = next(s for s in scenarios if s["id"] == sc_id)
        indices = sc["feature_indices"]
        assert len(indices) == len(exp_stages)
        for idx, stg in zip(indices, exp_stages):
            p = feats[idx]["properties"]
            assert p.get("stage") == stg
            assert isinstance(p.get("stage_title"), str) and len(p.get("stage_title")) > 0

    # Distance/geometry consistency
    for i, feat in enumerate(feats):
        p = feat["properties"]
        if p.get("status") == "OK":
            assert "geometry_length_km" in p
            g_len = p["geometry_length_km"]
            d_km = p.get("distance_km")
            if d_km is not None and g_len > 0 and abs(d_km - g_len) / g_len > 0.01:
                assert p.get("distance_basis") == "road_factor applied to schematic geometry"

    # Top-level verified flag
    assert routes_data.get("verified") is False

    # Dispatch honesty
    disp = routes_data.get("dispatch", {})
    assert "partially_served" in disp
    assert "total_unmet_kg" in disp




