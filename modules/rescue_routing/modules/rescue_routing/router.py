"""Vehicle routing engine with flood clearance and predictive risk detour."""

import heapq
import math
from enum import Enum
import networkx as nx

from .osm_loader import haversine_distance
from .risk_engine import (
    calculate_edge_risk,
    HAZARD_RISK_MIN,
    RISK_TIME_PENALTY,
    RELIABILITY_MIN,
    HELI_SPEED_KMH,
    HELI_GROUND_MM_H,
    HELI_LAUNCH_MINUTES,
    LAUNCH_MINUTES,
    ON_SCENE_DWELL_MIN,
    ADVISORY_NONE,
    ADVISORY_LOW_RELIABILITY,
    ADVISORY_NO_SAFE_OPTION,
    STABILITY_MIN,
)



class GroundedWeatherStatus(str):
    """String status matching GROUNDED_WEATHER while preserving backwards compatibility."""
    def __eq__(self, other):
        if super().__eq__(other):
            return True
        return other in ("UNREACHABLE", "GROUNDED_WEATHER", "WEATHER_GROUNDED")
    def __hash__(self):
        return super().__hash__()


class NoRoadRouteStatus(str):
    """String status matching NO_ROAD_ROUTE while preserving backwards compatibility."""
    def __eq__(self, other):
        if super().__eq__(other):
            return True
        return other in ("UNREACHABLE", "NO_ROAD_ROUTE")
    def __hash__(self):
        return super().__hash__()


class VehicleType(str, Enum):
    AMBULANCE = "AMBULANCE"
    TRUCK_4X4 = "TRUCK_4X4"
    RESCUE_BOAT = "RESCUE_BOAT"
    HELICOPTER = "HELICOPTER"


TRUCK_WADING_LIMIT_M = 0.4  # maximum water depth clearance before 4x4 truck wading becomes impassable
BOAT_MIN_DRAFT_M = 0.5  # minimum water depth draft required for rescue boat navigation

SPEED_MULTIPLIERS = {
    VehicleType.AMBULANCE: 1.0,
    VehicleType.TRUCK_4X4: 1.3,
    VehicleType.RESCUE_BOAT: 2.0,
}


def load_vehicle_limits(config_path: str | None = None) -> dict:
    """Load vehicle clearance limits, capacities, and weather thresholds from config."""
    import json
    from pathlib import Path

    defaults = {
        "limits_meters": {
            "AMBULANCE": 0.0,
            "TRUCK_4X4": 0.40,
            "RESCUE_BOAT": 0.50,
            "HELICOPTER": None,
        },
        "payload_capacity_kg": {
            "AMBULANCE": 400.0,
            "TRUCK_4X4": 1500.0,
            "RESCUE_BOAT": 800.0,
            "HELICOPTER": 1200.0,
        },
        "weather_limits": {
            "HELICOPTER": {
                "max_rainfall_mmh": 60.0,
                "max_wind_kmh": 75.0,
                "min_visibility_km": 1.5,
            }
        },
        "launch_minutes": {
            "RESCUE_BOAT": 5.0,
            "HELICOPTER": 10.0,
        },
        "default_launch_points": {
            "HELICOPTER": "HOSPITAL_BASE",
        },
        "concurrent_vehicles": {
            "AMBULANCE": 1,
            "TRUCK_4X4": 1,
            "RESCUE_BOAT": 1,
            "HELICOPTER": 1,
        },
        "provenance": {
            "source": "ASSUMED_NOT_SOURCED",
            "note": "Standard emergency response agency heuristic limits. Not empirically certified for live flood operations without vehicle manufacturer verification.",
        },
    }

    p = Path(config_path) if config_path else Path(__file__).resolve().parent.parent.parent / "config" / "vehicle_limits.json"
    if not p.exists():
        p = Path("config/vehicle_limits.json")
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    if isinstance(v, dict) and k in defaults and isinstance(defaults[k], dict):
                        defaults[k].update(v)
                    else:
                        defaults[k] = v
        except Exception:
            pass
    return defaults


def _decorate_distance_consistency(payload: dict) -> dict:
    """Add geometry_length_km and optional distance_basis to route payload."""
    if payload.get("status") != "OK":
        return payload
    geom = payload.get("geojson_geometry")
    if not geom or not isinstance(geom, dict):
        return payload
    coords = geom.get("coordinates")
    if not coords or len(coords) < 2:
        payload["geometry_length_km"] = 0.0
        return payload

    total_len_m = 0.0
    for k in range(len(coords) - 1):
        total_len_m += haversine_distance(coords[k][0], coords[k][1], coords[k + 1][0], coords[k + 1][1])
    geom_len_km = round(total_len_m / 1000.0, 3)
    payload["geometry_length_km"] = geom_len_km

    dist_km = payload.get("distance_km")
    if dist_km is not None and geom_len_km > 0:
        rel_diff = abs(dist_km - geom_len_km) / geom_len_km
        if rel_diff > 0.01:
            payload["distance_basis"] = "road_factor applied to schematic geometry"

    if "legs" in payload and isinstance(payload["legs"], list):
        for leg in payload["legs"]:
            if isinstance(leg, dict):
                _decorate_distance_consistency(leg)

    return payload


class RescueRouter:
    """Calculates flood-aware emergency rescue routes."""

    def __init__(self, graph: nx.Graph, limits_config: dict | None = None) -> None:
        self.graph = graph
        self.config = limits_config or load_vehicle_limits()
        self.limits_meters = self.config.get("limits_meters", {})
        self.payload_capacity_kg = self.config.get("payload_capacity_kg", {})
        self.weather_limits = self.config.get("weather_limits", {})
        self.launch_minutes_config = self.config.get("launch_minutes", {})
        self.default_launch_points = self.config.get("default_launch_points", {})

    def _is_passable(self, vehicle: VehicleType, depth: float) -> bool:
        if vehicle == VehicleType.AMBULANCE:
            limit = self.limits_meters.get("AMBULANCE", 0.0)
            return depth <= limit
        if vehicle == VehicleType.TRUCK_4X4:
            limit = self.limits_meters.get("TRUCK_4X4", TRUCK_WADING_LIMIT_M)
            return depth <= limit
        if vehicle == VehicleType.RESCUE_BOAT:
            min_draft = self.limits_meters.get("RESCUE_BOAT", BOAT_MIN_DRAFT_M)
            return depth >= min_draft
        return True

    def _travel_time_s(self, vehicle: VehicleType, edge_data: dict, depth: float) -> float:
        base_t = edge_data["travel_time_seconds"] * SPEED_MULTIPLIERS[vehicle]
        if vehicle == VehicleType.TRUCK_4X4:
            wading_limit = self.limits_meters.get("TRUCK_4X4", TRUCK_WADING_LIMIT_M)
            factor = 1.0 - 0.5 * (depth / wading_limit) if wading_limit > 0 else 1.0
            return base_t / max(factor, 0.01)
        return base_t


    def _compute_path_metrics(
        self,
        nodes: list[str],
        v_type: VehicleType,
        rainfall_rate: float,
        depart_in_min: float,
        depths: dict,
        round_trip: bool = True,
        return_details: bool = False,
    ) -> tuple:
        dist_m = 0.0
        times = []
        for i in range(len(nodes) - 1):
            u, v = nodes[i], nodes[i + 1]
            pair = tuple(sorted((u, v)))
            edge_data = self.graph[u][v]
            dist_m += edge_data["distance_meters"]
            d = depths.get(pair, edge_data.get("current_water_depth_meters", 0.0))
            times.append(self._travel_time_s(v_type, edge_data, d))
        total_t_s = sum(times)
        total_t_min = total_t_s / 60.0

        exposure_risks = []
        planning_risks = []
        outbound_risks = []
        el_s = 0.0
        for i in range(len(nodes) - 1):
            u, v = nodes[i], nodes[i + 1]
            edge_data = self.graph[u][v]
            t_s = times[i]
            kind = edge_data.get("kind", "road")
            r_plan = calculate_edge_risk(
                edge_data["elevation_meters"],
                edge_data["distance_to_river_meters"],
                rainfall_rate,
                horizon_min=30.0,
                kind=kind,
            )
            planning_risks.append(r_plan)

            h_out = depart_in_min + (el_s + t_s) / 60.0
            r_out = calculate_edge_risk(
                edge_data["elevation_meters"],
                edge_data["distance_to_river_meters"],
                rainfall_rate,
                horizon_min=h_out,
                kind=kind,
            )
            outbound_risks.append(r_out)

            if round_trip:
                h_exp = depart_in_min + 2.0 * total_t_min + ON_SCENE_DWELL_MIN - (el_s / 60.0)
                r_exp = calculate_edge_risk(
                    edge_data["elevation_meters"],
                    edge_data["distance_to_river_meters"],
                    rainfall_rate,
                    horizon_min=h_exp,
                    kind=kind,
                )
            else:
                r_exp = r_out
            exposure_risks.append(r_exp)
            el_s += t_s

        rounded_exp_risks = [round(r, 4) for r in exposure_risks]
        rounded_plan_risks = [round(r, 4) for r in planning_risks]
        route_rel = round(math.prod(1.0 - r for r in rounded_exp_risks), 4) if rounded_exp_risks else 1.0
        outbound_rel = round(math.prod(1.0 - r for r in outbound_risks), 4) if outbound_risks else 1.0

        if return_details:
            return dist_m, total_t_s, rounded_exp_risks, route_rel, rounded_plan_risks, outbound_rel
        return dist_m, total_t_s, rounded_exp_risks, route_rel

    def _dijkstra_time_dependent(
        self,
        view: nx.Graph,
        origin: str,
        destination: str,
        v_type: VehicleType,
        rainfall_rate: float,
        depart_in_min: float,
        depths: dict,
        round_trip: bool = True,
    ) -> tuple[list[str], float] | None:
        """Heuristic Dijkstra search tracking elapsed minutes per label for time-dependent edge risk."""
        def path_exact_cost(p: list[str]) -> tuple[float, float]:
            times = [
                self._travel_time_s(
                    v_type,
                    self.graph[u][v],
                    depths.get(tuple(sorted((u, v))), self.graph[u][v].get("current_water_depth_meters", 0.0)),
                )
                for u, v in zip(p[:-1], p[1:])
            ]
            tot_min = sum(times) / 60.0
            c = 0.0
            el = 0.0
            for idx, (u, v) in enumerate(zip(p[:-1], p[1:])):
                ed = self.graph[u][v]
                t_s = times[idx]
                kind = ed.get("kind", "road")
                if round_trip:
                    h = depart_in_min + 2.0 * tot_min + ON_SCENE_DWELL_MIN - (el / 60.0)
                else:
                    h = depart_in_min + (el + t_s) / 60.0
                r = calculate_edge_risk(
                    ed["elevation_meters"],
                    ed["distance_to_river_meters"],
                    rainfall_rate,
                    horizon_min=h,
                    kind=kind,
                )
                c += t_s * (1.0 + RISK_TIME_PENALTY * r)
                el += t_s
            return c, sum(times)

        pq = [(0.0, 0.0, origin, [origin])]
        best_cost = float("inf")
        best_path = None
        best_elapsed_s = 0.0
        expansions = 0
        max_expansions = 2000

        while pq:
            lb_cost, el_s, u, path = heapq.heappop(pq)
            expansions += 1
            if expansions > max_expansions:
                break
            if lb_cost >= best_cost:
                continue

            if u == destination:
                exact_c, t_s = path_exact_cost(path)
                if exact_c < best_cost:
                    best_cost = exact_c
                    best_path = path
                    best_elapsed_s = t_s
                continue

            for v in view[u]:
                if v in path:
                    continue
                pair = tuple(sorted((u, v)))
                ed = self.graph[u][v]
                d = depths.get(pair, ed.get("current_water_depth_meters", 0.0))
                t_s = self._travel_time_s(v_type, ed, d)
                next_el_s = el_s + t_s
                h_lb = depart_in_min + next_el_s / 60.0
                kind = ed.get("kind", "road")
                r_lb = calculate_edge_risk(
                    ed["elevation_meters"],
                    ed["distance_to_river_meters"],
                    rainfall_rate,
                    horizon_min=h_lb,
                    kind=kind,
                )
                step_c = t_s * (1.0 + RISK_TIME_PENALTY * r_lb)
                heapq.heappush(pq, (lb_cost + step_c, next_el_s, v, path + [v]))

        if best_path is not None:
            return best_path, best_elapsed_s
        return None

    def find_route(
        self,
        origin: str,
        destination: str,
        vehicle_type: VehicleType | str,
        blocked_edges: set | list | None = None,
        rainfall_rate: float = 15.0,
        edge_depths: dict | None = None,
        depth_map: dict | None = None,
        depart_in_min: float = 0.0,
        depth_source: str | None = None,
        depth_age_min: float | None = None,
        round_trip: bool = True,
        wind_kmh: float | None = None,
        visibility_km: float | None = None,
        launch_point: str | None = None,
        scenario_id: str | None = None,
        stage: int | None = None,
        stage_title: str | None = None,
    ) -> dict:
        """Find optimal route avoiding flooded or high-risk segments."""
        v_type = VehicleType(vehicle_type)

        depths_input = depth_map if depth_map is not None else edge_depths
        if depth_source is None:
            if depths_input is not None:
                depth_source = getattr(depths_input, "metadata", {}).get("depth_source", "depth_map")
            else:
                depth_source = "scenario"
        if depth_age_min is None and depths_input is not None:
            depth_age_min = getattr(depths_input, "metadata", {}).get("depth_age_min")

        # inherit satellite depth_source or coverage if defined on network edges
        sat_depth_source = None
        sat_coverage = None
        for _, _, e_d in self.graph.edges(data=True):
            if sat_depth_source is None and "depth_source" in e_d:
                sat_depth_source = e_d["depth_source"]
            if sat_coverage is None and "satellite_coverage" in e_d:
                sat_coverage = e_d["satellite_coverage"]
            if sat_depth_source and sat_coverage:
                break
        if sat_depth_source and depth_source == "scenario":
            depth_source = sat_depth_source

        data_freshness = "UNKNOWN"
        if depth_age_min is not None:
            data_freshness = "FRESH" if depth_age_min <= 180.0 else "STALE"

        blocked_list = [list(e) for e in (blocked_edges or [])]
        meta = {
            "rainfall_mmh": rainfall_rate,
            "blocked_edges": blocked_list,
            "depth_source": depth_source,
            "data_freshness": data_freshness,
        }
        if sat_coverage is not None:
            meta["satellite_coverage"] = sat_coverage
        if depth_age_min is not None:
            meta["depth_age_min"] = depth_age_min

        # validate rainfall rate
        if rainfall_rate is None or math.isnan(rainfall_rate) or rainfall_rate < 0:
            return {
                "status": "INVALID_REQUEST",
                "vehicle_type": v_type.value,
                "origin": origin,
                "destination": destination,
                "reason": f"Invalid rainfall rate: {rainfall_rate}",
                "geojson_geometry": None,
                "max_planning_risk": 0.0,
                "risk_warning": False,
                **meta,
            }

        # validate origin and destination
        if origin not in self.graph:
            return {
                "status": "INVALID_REQUEST",
                "vehicle_type": v_type.value,
                "origin": origin,
                "destination": destination,
                "reason": f"Unknown origin node: {origin}",
                "geojson_geometry": None,
                "max_planning_risk": 0.0,
                "risk_warning": False,
                **meta,
            }
        if destination not in self.graph:
            return {
                "status": "INVALID_REQUEST",
                "vehicle_type": v_type.value,
                "origin": origin,
                "destination": destination,
                "reason": f"Unknown destination node: {destination}",
                "geojson_geometry": None,
                "max_planning_risk": 0.0,
                "risk_warning": False,
                **meta,
            }

        # trivial origin == destination route
        if origin == destination:
            triv_res = _decorate_distance_consistency({
                "status": "OK",
                "vehicle_type": v_type.value,
                "origin": origin,
                "destination": destination,
                "eta_minutes": 0.0,
                "distance_km": 0.0,
                "path_nodes": [origin],
                "geojson_geometry": None,
                "geometry_quality": "schematic_straight_lines",
                "corridor_type": "ROAD_CORRIDOR",
                "corridor_label": "lowest-risk route (model)",
                "wording": "lowest-risk route (model)",
                "uncertain_segments_count": 0,
                "max_water_depth_meters": 0.0,
                "data_age_hours": round(depth_age_min / 60.0, 1) if depth_age_min is not None else None,
                "avoided_hazards": [],
                "is_predictive_detour": False,
                "route_reliability": 1.0 if v_type != VehicleType.HELICOPTER else None,
                "outbound_reliability": 1.0 if v_type != VehicleType.HELICOPTER else None,
                "edge_risks": [],
                "planning_edge_risks": [],
                "max_planning_risk": 0.0,
                "risk_warning": False,
                "advisory": ADVISORY_NONE,
                "risk_horizon_note": "edge_risks reflects round-trip exposure horizon; planning_edge_risks reflects 30-minute planning horizon",
                "round_trip": round_trip,
                "eta_delta_min": 0.0,
                "counterfactual": {
                    "reactive_path_nodes": [origin],
                    "reactive_eta_min": 0.0,
                    "reactive_reliability": 1.0 if v_type != VehicleType.HELICOPTER else None,
                    "eta_delta_min": 0.0,
                    "reliability_gain": 0.0,
                },
                "departure_window_min": 120,
                "window_capped": True,
                "note": "ORIGIN_EQUALS_DESTINATION",
                **meta,
            })
            if scenario_id is not None:
                triv_res["scenario_id"] = scenario_id
            if stage is not None:
                triv_res["stage"] = stage
            if stage_title is not None:
                triv_res["stage_title"] = stage_title
            return triv_res

        # helicopter straight-line great-circle flight
        if v_type == VehicleType.HELICOPTER:
            heli_weather = self.weather_limits.get("HELICOPTER", {})
            max_rain = heli_weather.get("max_rainfall_mmh", HELI_GROUND_MM_H)
            max_wind = heli_weather.get("max_wind_kmh", 75.0)
            min_vis = heli_weather.get("min_visibility_km", 1.5)

            grounded_reason = None
            if rainfall_rate >= max_rain:
                grounded_reason = "WEATHER_GROUNDED"
            elif wind_kmh is not None and wind_kmh > max_wind:
                grounded_reason = f"WEATHER_GROUNDED: wind speed {wind_kmh} km/h exceeds limit {max_wind} km/h"
            elif visibility_km is not None and visibility_km < min_vis:
                grounded_reason = f"WEATHER_GROUNDED: visibility {visibility_km} km below limit {min_vis} km"

            lp = launch_point or self.default_launch_points.get("HELICOPTER", "HOSPITAL_BASE")
            lp_assump = f"Launch point assumed to be {lp}" if launch_point is None else f"Launch point configured as {lp}"

            if grounded_reason is not None:
                res = {
                    "status": GroundedWeatherStatus("GROUNDED_WEATHER"),
                    "vehicle_type": VehicleType.HELICOPTER.value,
                    "origin": origin,
                    "destination": destination,
                    "reason": grounded_reason,
                    "isolated_nodes": [destination],
                    "cut_edges": [],
                    "component_scope": "vehicle_passable_subgraph",
                    "geojson_geometry": None,
                    "route_reliability": None,
                    "outbound_reliability": None,
                    "max_planning_risk": 0.0,
                    "risk_warning": False,
                    "launch_point": lp,
                    "assumption": lp_assump,
                    "weather_assessment": "GROUNDED_WEATHER",
                    "wording": "lowest-risk route (model)",
                    **meta,
                }
                if scenario_id is not None:
                    res["scenario_id"] = scenario_id
                if stage is not None:
                    res["stage"] = stage
                if stage_title is not None:
                    res["stage_title"] = stage_title
                return res

            weather_ass = "WEATHER_UNKNOWN" if (wind_kmh is None and visibility_km is None) else "WEATHER_OK"
            u_node = self.graph.nodes.get(lp, self.graph.nodes[origin])
            v_node = self.graph.nodes[destination]
            dist_m = haversine_distance(u_node["lon"], u_node["lat"], v_node["lon"], v_node["lat"])
            dist_km = round(dist_m / 1000.0, 3)
            flight_min = (dist_km / HELI_SPEED_KMH) * 60.0
            launch_min = float(self.launch_minutes_config.get("HELICOPTER", HELI_LAUNCH_MINUTES))
            eta_min = round(launch_min + flight_min, 2)
            coords = [[u_node["lon"], u_node["lat"]], [v_node["lon"], v_node["lat"]]]
            res = _decorate_distance_consistency({
                "status": "OK",
                "vehicle_type": VehicleType.HELICOPTER.value,
                "origin": origin,
                "destination": destination,
                "eta_minutes": eta_min,
                "distance_km": dist_km,
                "corridor_length_m": round(dist_m, 1),
                "path_nodes": [origin, destination],
                "geojson_geometry": {"type": "LineString", "coordinates": coords},
                "geometry_quality": "great_circle",
                "corridor_type": "AIR_LINE",
                "corridor_label": "Air/boat line, not a road route",
                "avoided_hazards": [],
                "is_predictive_detour": False,
                "route_reliability": None,
                "outbound_reliability": None,
                "edge_risks": [],
                "planning_edge_risks": [],
                "max_planning_risk": 0.0,
                "risk_warning": False,
                "advisory": ADVISORY_NONE,
                "risk_horizon_note": "edge_risks reflects round-trip exposure horizon; planning_edge_risks reflects 30-minute planning horizon",
                "round_trip": round_trip,
                "eta_delta_min": 0.0,
                "launch_minutes": launch_min,
                "counterfactual": {
                    "reactive_path_nodes": [origin, destination],
                    "reactive_eta_min": eta_min,
                    "reactive_reliability": None,
                    "eta_delta_min": 0.0,
                    "reliability_gain": 0.0,
                },
                "departure_window_min": 120,
                "window_capped": True,
                "launch_point": lp,
                "assumption": lp_assump,
                "weather_assessment": weather_ass,
                "wording": "lowest-risk route (model)",
                **meta,
            })
            if scenario_id is not None:
                res["scenario_id"] = scenario_id
            if stage is not None:
                res["stage"] = stage
            if stage_title is not None:
                res["stage_title"] = stage_title
            return res

        # validate depth map and edge existence
        depths = {}
        if depths_input:
            for k, val in depths_input.items():
                if isinstance(k, str) and "|" in k:
                    u_k, v_k = k.split("|")
                elif isinstance(k, (tuple, list)) and len(k) == 2:
                    u_k, v_k = k[0], k[1]
                else:
                    raise ValueError(f"Invalid edge key in depth map: {k}")
                if not self.graph.has_edge(u_k, v_k):
                    raise ValueError(f"Edge ({u_k}, {v_k}) in depth map does not exist in graph")
                depths[tuple(sorted((u_k, v_k)))] = float(val)

        # validate blocked edges and edge existence
        blocked = set()
        if blocked_edges:
            for e in blocked_edges:
                if isinstance(e, (tuple, list)) and len(e) == 2:
                    u_e, v_e = e[0], e[1]
                else:
                    raise ValueError(f"Invalid edge in blocked_edges: {e}")
                if not self.graph.has_edge(u_e, v_e):
                    raise ValueError(f"Edge ({u_e}, {v_e}) in blocked_edges does not exist in graph")
                blocked.add(tuple(sorted((u_e, v_e))))

        def get_edge_depth(u: str, v: str) -> float:
            pair = tuple(sorted((u, v)))
            if pair in depths:
                return depths[pair]
            return self.graph[u][v].get("current_water_depth_meters", 0.0)

        def filter_edge(u: str, v: str) -> bool:
            if tuple(sorted((u, v))) in blocked:
                return False
            d = get_edge_depth(u, v)
            if v_type == VehicleType.AMBULANCE and self.graph[u][v].get("has_flood_water", False):
                return False
            return self._is_passable(v_type, d)

        # prune edges by vehicle clearance and physical blocks without copying graph
        view = nx.subgraph_view(self.graph, filter_edge=filter_edge)

        if not (origin in view and destination in view and nx.has_path(view, origin, destination)):
            isolated = (
                sorted(nx.node_connected_component(view, destination))
                if destination in view
                else [destination]
            )
            iso_set = set(isolated)
            cut_edges = [
                sorted([u, v])
                for u, v in self.graph.edges
                if (u in iso_set) != (v in iso_set)
            ]
            cut_edges.sort()
            unreach_res = {
                "status": NoRoadRouteStatus("UNREACHABLE"),
                "substatus": "NO_ROAD_ROUTE",
                "vehicle_type": v_type.value,
                "origin": origin,
                "destination": destination,
                "reason": f"No passable route available for {v_type.value}.",
                "wording": "No road route: area cut off",
                "isolated_nodes": isolated,
                "isolated_node_count": len(isolated),
                "cut_edges": cut_edges,
                "component_scope": "vehicle_passable_subgraph",
                "geojson_geometry": None,
                "route_reliability": None,
                "outbound_reliability": None,
                "max_planning_risk": 0.0,
                "risk_warning": False,
                **meta,
            }
            if scenario_id is not None:
                unreach_res["scenario_id"] = scenario_id
            if stage is not None:
                unreach_res["stage"] = stage
            if stage_title is not None:
                unreach_res["stage_title"] = stage_title
            return unreach_res

        dijkstra_res = self._dijkstra_time_dependent(
            view, origin, destination, v_type, rainfall_rate, depart_in_min, depths, round_trip=round_trip
        )
        if dijkstra_res is None:
            path_nodes = nx.dijkstra_path(view, origin, destination, weight="distance_meters")
            dist_m, eta_sec, raw_edge_risks, rel, planning_risks, outbound_rel = self._compute_path_metrics(
                path_nodes, v_type, rainfall_rate, depart_in_min, depths, round_trip=round_trip, return_details=True
            )
        else:
            path_nodes, eta_sec = dijkstra_res
            dist_m, _, raw_edge_risks, rel, planning_risks, outbound_rel = self._compute_path_metrics(
                path_nodes, v_type, rainfall_rate, depart_in_min, depths, round_trip=round_trip, return_details=True
            )

        # Check if geometry or display_geometry exists on edges along path_nodes
        has_display_geom = any(
            (self.graph[path_nodes[i]][path_nodes[i + 1]].get("geometry") is not None
             or self.graph[path_nodes[i]][path_nodes[i + 1]].get("display_geometry") is not None)
            for i in range(len(path_nodes) - 1)
        )
        if has_display_geom and len(path_nodes) > 1:
            coords = []
            for i in range(len(path_nodes) - 1):
                u_n, v_n = path_nodes[i], path_nodes[i + 1]
                e_data = self.graph[u_n][v_n]
                d_geom = e_data.get("geometry") or e_data.get("display_geometry")
                if d_geom:
                    if isinstance(d_geom, dict) and "coordinates" in d_geom:
                        seg_coords = d_geom["coordinates"]
                    elif isinstance(d_geom, (list, tuple)):
                        seg_coords = list(d_geom)
                    else:
                        seg_coords = None
                else:
                    seg_coords = None

                if seg_coords and len(seg_coords) >= 2:
                    u_pt = [self.graph.nodes[u_n]["lon"], self.graph.nodes[u_n]["lat"]]
                    dist_start = (seg_coords[0][0] - u_pt[0]) ** 2 + (seg_coords[0][1] - u_pt[1]) ** 2
                    dist_end = (seg_coords[-1][0] - u_pt[0]) ** 2 + (seg_coords[-1][1] - u_pt[1]) ** 2
                    if dist_end < dist_start:
                        seg_coords = list(reversed(seg_coords))
                else:
                    seg_coords = [
                        [self.graph.nodes[u_n]["lon"], self.graph.nodes[u_n]["lat"]],
                        [self.graph.nodes[v_n]["lon"], self.graph.nodes[v_n]["lat"]],
                    ]
                if coords:
                    coords.extend(seg_coords[1:])
                else:
                    coords.extend(seg_coords)
            geom_quality = "osm_polyline"
        else:
            coords = [[self.graph.nodes[n]["lon"], self.graph.nodes[n]["lat"]] for n in path_nodes]
            geom_quality = "schematic_straight_lines"

        # counterfactual reactive path on pruned view with pure distance
        reactive_nodes = nx.dijkstra_path(view, origin, destination, weight="distance_meters")
        is_predictive = path_nodes != reactive_nodes

        _, react_el_s, _, react_rel, _, _ = self._compute_path_metrics(
            reactive_nodes, v_type, rainfall_rate, depart_in_min, depths, round_trip=round_trip, return_details=True
        )
        react_eta = round(react_el_s / 60.0, 2)
        chosen_eta = round(eta_sec / 60.0, 2)
        chosen_rel = round(rel, 4)
        react_rel_rnd = round(react_rel, 4)
        eta_delta = round(chosen_eta - react_eta, 2)

        counterfactual = {
            "reactive_path_nodes": reactive_nodes,
            "reactive_eta_min": react_eta,
            "reactive_reliability": react_rel_rnd,
            "eta_delta_min": eta_delta,
            "reliability_gain": round(chosen_rel - react_rel_rnd, 4),
        }

        # departure window scan in {0, 5, ..., 120} min
        # compute from the same round-trip route_reliability as the headline value; null if it fails at d = 0
        rel_0 = chosen_rel if depart_in_min == 0.0 else self._compute_path_metrics(path_nodes, v_type, rainfall_rate, 0.0, depths, round_trip=round_trip)[3]
        if rel_0 < RELIABILITY_MIN:
            departure_window_min = None
            window_capped = False
        else:
            last_valid_d = 0
            for d in range(5, 125, 5):
                _, _, _, rel_d = self._compute_path_metrics(path_nodes, v_type, rainfall_rate, float(d), depths, round_trip=round_trip)
                if rel_d >= RELIABILITY_MIN:
                    last_valid_d = d
                else:
                    break
            departure_window_min = last_valid_d
            window_capped = (last_valid_d == 120)

        pure_path = nx.dijkstra_path(self.graph, origin, destination, weight="distance_meters")
        chosen_set = {tuple(sorted((path_nodes[i], path_nodes[i + 1]))) for i in range(len(path_nodes) - 1)}
        avoided_hazards = []

        for i in range(len(pure_path) - 1):
            u, v = pure_path[i], pure_path[i + 1]
            pair = tuple(sorted((u, v)))
            if pair not in chosen_set:
                d = get_edge_depth(u, v)
                edge_data = self.graph[u][v]
                kind = edge_data.get("kind", "road")
                risk = calculate_edge_risk(
                    edge_data["elevation_meters"],
                    edge_data["distance_to_river_meters"],
                    rainfall_rate,
                    kind=kind,
                )
                if pair in blocked:
                    reason = "BLOCKED"
                elif kind == "river" and (risk >= HAZARD_RISK_MIN or not self._is_passable(v_type, d)):
                    reason = "RIVER_HAZARD"
                elif not self._is_passable(v_type, d) or (v_type == VehicleType.AMBULANCE and edge_data.get("has_flood_water", False)):
                    reason = "SUBMERGED"
                elif risk >= HAZARD_RISK_MIN and not str(depth_source).startswith("satellite_mask"):
                    reason = "PREDICTED_SUBMERSION"
                else:
                    continue
                e_geom = edge_data.get("geometry") or edge_data.get("display_geometry")
                geom_dict = {"type": "LineString", "coordinates": e_geom} if isinstance(e_geom, (list, tuple)) else e_geom
                avoided_hazards.append(
                    {
                        "edge": [u, v],
                        "name": edge_data["name"],
                        "reason": reason,
                        "depth_m": d,
                        "planning_risk": round(risk, 4),
                        "risk": round(risk, 4),
                        "geometry": geom_dict,
                    }
                )

        max_plan_risk = max([round(r, 4) for r in planning_risks], default=0.0)
        risk_warn = bool(max_plan_risk > 0.9 and (chosen_rel or 0.0) > 0.5)
        advisory = ADVISORY_LOW_RELIABILITY if chosen_rel is not None and chosen_rel < RELIABILITY_MIN else ADVISORY_NONE

        res_ok = _decorate_distance_consistency({
            "status": "OK",
            "vehicle_type": v_type.value,
            "origin": origin,
            "destination": destination,
            "eta_minutes": chosen_eta,
            "distance_km": round(dist_m / 1000.0, 3),
            "corridor_length_m": round(dist_m, 1),
            "corridor_type": "WATER_LINE" if v_type == VehicleType.RESCUE_BOAT else "ROAD_CORRIDOR",
            "corridor_label": "Air/boat line, not a road route" if v_type == VehicleType.RESCUE_BOAT else "lowest-risk route (model)",
            "wording": "lowest-risk route (model)",
            "uncertain_segments_count": sum(1 for r in planning_risks if 0.20 <= r <= 0.50),
            "max_water_depth_meters": round(max([get_edge_depth(u, v) for u, v in zip(path_nodes[:-1], path_nodes[1:])], default=0.0), 2),
            "data_age_hours": round(depth_age_min / 60.0, 1) if depth_age_min is not None else None,
            "path_nodes": path_nodes,
            "geojson_geometry": {"type": "LineString", "coordinates": coords},
            "geometry_quality": geom_quality,
            "avoided_hazards": avoided_hazards,
            "is_predictive_detour": is_predictive,
            "route_reliability": chosen_rel,
            "outbound_reliability": round(outbound_rel, 4),
            "edge_risks": [round(r, 4) for r in raw_edge_risks],
            "planning_edge_risks": [round(r, 4) for r in planning_risks],
            "max_planning_risk": max_plan_risk,
            "risk_warning": risk_warn,
            "advisory": advisory,
            "risk_horizon_note": "edge_risks reflects round-trip exposure horizon; planning_edge_risks reflects 30-minute planning horizon",
            "round_trip": round_trip,
            "eta_delta_min": eta_delta,
            "counterfactual": counterfactual,
            "departure_window_min": departure_window_min,
            "window_capped": window_capped,
            **meta,
        })
        if scenario_id is not None:
            res_ok["scenario_id"] = scenario_id
        if stage is not None:
            res_ok["stage"] = stage
        if stage_title is not None:
            res_ok["stage_title"] = stage_title
        return res_ok

    def find_multimodal_route(
        self,
        origin: str,
        destination: str,
        vehicle_type: VehicleType | str = VehicleType.RESCUE_BOAT,
        rainfall_rate: float = 15.0,
        blocked_edges: set | list | None = None,
        depth_map: dict | None = None,
        depart_in_min: float = 0.0,
        depth_source: str | None = None,
        depth_age_min: float | None = None,
        round_trip: bool = True,
        scenario_id: str | None = None,
        stage: int | None = None,
        stage_title: str | None = None,
    ) -> dict:
        """Calculate multimodal ground-to-water rescue route via slipway staging."""
        v_type = VehicleType(vehicle_type)
        if v_type != VehicleType.RESCUE_BOAT:
            return self.find_route(
                origin,
                destination,
                v_type,
                blocked_edges=blocked_edges,
                rainfall_rate=rainfall_rate,
                depth_map=depth_map,
                depart_in_min=depart_in_min,
                depth_source=depth_source,
                depth_age_min=depth_age_min,
                round_trip=round_trip,
                scenario_id=scenario_id,
                stage=stage,
                stage_title=stage_title,
            )

        # if origin is already a boat ramp, single boat leg
        if self.graph.nodes.get(origin, {}).get("type") == "ramp":
            res = self.find_route(
                origin,
                destination,
                VehicleType.RESCUE_BOAT,
                blocked_edges=blocked_edges,
                rainfall_rate=rainfall_rate,
                depth_map=depth_map,
                depart_in_min=depart_in_min,
                depth_source=depth_source,
                depth_age_min=depth_age_min,
                round_trip=round_trip,
                scenario_id=scenario_id,
                stage=stage,
                stage_title=stage_title,
            )
            if res.get("status") == "OK":
                res["corridor_type"] = "WATER_LINE"
                res["corridor_label"] = "Air/boat line, not a road route"
                res["wording"] = "lowest-risk route (model)"
                res["legs"] = [
                    {
                        "mode": VehicleType.RESCUE_BOAT.value,
                        "path_nodes": res["path_nodes"],
                        "eta_minutes": res["eta_minutes"],
                        "geometry": res["geojson_geometry"],
                    }
                ]
            return res

        # find cheapest ramp via truck ground leg then boat leg
        ramp_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("type") == "ramp"]
        best_eta = float("inf")
        best_ground = None
        best_boat = None

        launch_boat_min = float(self.launch_minutes_config.get("RESCUE_BOAT", LAUNCH_MINUTES))

        for ramp in ramp_nodes:
            ground = self.find_route(
                origin,
                ramp,
                VehicleType.TRUCK_4X4,
                blocked_edges=blocked_edges,
                rainfall_rate=rainfall_rate,
                depth_map=depth_map,
                depart_in_min=depart_in_min,
                depth_source=depth_source,
                depth_age_min=depth_age_min,
                round_trip=round_trip,
            )
            if ground.get("status") != "OK":
                continue

            boat_depart = depart_in_min + ground["eta_minutes"] + launch_boat_min
            boat = self.find_route(
                ramp,
                destination,
                VehicleType.RESCUE_BOAT,
                blocked_edges=blocked_edges,
                rainfall_rate=rainfall_rate,
                depth_map=depth_map,
                depart_in_min=boat_depart,
                depth_source=depth_source,
                depth_age_min=depth_age_min,
                round_trip=round_trip,
            )
            if boat.get("status") != "OK":
                continue

            total_eta = ground["eta_minutes"] + launch_boat_min + boat["eta_minutes"]
            if total_eta < best_eta:
                best_eta = total_eta
                best_ground = ground
                best_boat = boat

        depths_input = depth_map
        if depth_source is None:
            depth_source = getattr(depths_input, "metadata", {}).get("depth_source", "depth_map") if depths_input is not None else "scenario"
        if depth_age_min is None and depths_input is not None:
            depth_age_min = getattr(depths_input, "metadata", {}).get("depth_age_min")
        data_freshness = ("FRESH" if depth_age_min <= 180.0 else "STALE") if depth_age_min is not None else "UNKNOWN"
        blocked_list = [list(e) for e in (blocked_edges or [])]
        meta = {
            "rainfall_mmh": rainfall_rate,
            "blocked_edges": blocked_list,
            "depth_source": depth_source,
            "data_freshness": data_freshness,
        }
        if depth_age_min is not None:
            meta["depth_age_min"] = depth_age_min

        if best_ground is None or best_boat is None:
            unreach_boat = {
                "status": "UNREACHABLE",
                "vehicle_type": VehicleType.RESCUE_BOAT.value,
                "origin": origin,
                "destination": destination,
                "reason": "No passable multimodal route available via boat ramps.",
                "wording": "No road route: area cut off",
                "isolated_nodes": [destination],
                "isolated_node_count": 1,
                "cut_edges": [],
                "component_scope": "vehicle_passable_subgraph",
                "geojson_geometry": None,
                "route_reliability": None,
                "outbound_reliability": None,
                "max_planning_risk": 0.0,
                "risk_warning": False,
                **meta,
            }
            if scenario_id is not None:
                unreach_boat["scenario_id"] = scenario_id
            if stage is not None:
                unreach_boat["stage"] = stage
            if stage_title is not None:
                unreach_boat["stage_title"] = stage_title
            return unreach_boat

        # combine legs
        combined_nodes = best_ground["path_nodes"][:-1] + best_boat["path_nodes"]
        combined_coords = (
            best_ground["geojson_geometry"]["coordinates"][:-1]
            + best_boat["geojson_geometry"]["coordinates"]
        )
        total_dist_km = round(best_ground["distance_km"] + best_boat["distance_km"], 3)
        total_eta_min = round(best_eta, 2)
        rel_combined = round((best_ground["route_reliability"] or 1.0) * (best_boat["route_reliability"] or 1.0), 4)
        outbound_rel_combined = round((best_ground.get("outbound_reliability") or 1.0) * (best_boat.get("outbound_reliability") or 1.0), 4)

        legs = [
            {
                "mode": VehicleType.TRUCK_4X4.value,
                "path_nodes": best_ground["path_nodes"],
                "eta_minutes": best_ground["eta_minutes"],
                "geometry": best_ground["geojson_geometry"],
            },
            {
                "mode": VehicleType.RESCUE_BOAT.value,
                "path_nodes": best_boat["path_nodes"],
                "eta_minutes": best_boat["eta_minutes"],
                "geometry": best_boat["geojson_geometry"],
            },
        ]

        comb_plan_risks = best_ground.get("planning_edge_risks", []) + best_boat.get("planning_edge_risks", [])
        max_plan_risk = max(comb_plan_risks, default=0.0)
        risk_warn = bool(max_plan_risk > 0.9 and (rel_combined or 0.0) > 0.5)
        advisory = ADVISORY_LOW_RELIABILITY if rel_combined < RELIABILITY_MIN else ADVISORY_NONE

        if rel_combined < RELIABILITY_MIN or best_ground.get("departure_window_min") is None or best_boat.get("departure_window_min") is None:
            departure_window_min = None
            window_capped = False
        else:
            departure_window_min = min(best_ground["departure_window_min"], best_boat["departure_window_min"])
            window_capped = bool(best_ground["window_capped"] and best_boat["window_capped"])

        res_multi = _decorate_distance_consistency({
            "status": "OK",
            "vehicle_type": VehicleType.RESCUE_BOAT.value,
            "origin": origin,
            "destination": destination,
            "eta_minutes": total_eta_min,
            "distance_km": total_dist_km,
            "corridor_length_m": round(total_dist_km * 1000.0, 1),
            "corridor_type": "WATER_LINE",
            "corridor_label": "Air/boat line, not a road route",
            "wording": "lowest-risk route (model)",
            "uncertain_segments_count": sum(1 for r in comb_plan_risks if 0.20 <= r <= 0.50),
            "max_water_depth_meters": max(best_ground.get("max_water_depth_meters", 0.0), best_boat.get("max_water_depth_meters", 0.0)),
            "data_age_hours": round(depth_age_min / 60.0, 1) if depth_age_min is not None else None,
            "path_nodes": combined_nodes,
            "geojson_geometry": {"type": "LineString", "coordinates": combined_coords},
            "geometry_quality": "schematic_straight_lines",
            "avoided_hazards": best_ground["avoided_hazards"] + best_boat["avoided_hazards"],
            "is_predictive_detour": best_ground["is_predictive_detour"] or best_boat["is_predictive_detour"],
            "route_reliability": rel_combined,
            "outbound_reliability": outbound_rel_combined,
            "edge_risks": best_ground["edge_risks"] + best_boat["edge_risks"],
            "planning_edge_risks": best_ground.get("planning_edge_risks", []) + best_boat.get("planning_edge_risks", []),
            "max_planning_risk": max_plan_risk,
            "risk_warning": risk_warn,
            "advisory": advisory,
            "risk_horizon_note": "edge_risks reflects round-trip exposure horizon; planning_edge_risks reflects 30-minute planning horizon",
            "round_trip": round_trip,
            "eta_delta_min": 0.0,
            "legs": legs,
            "launch_minutes": launch_boat_min,
            "counterfactual": {
                "reactive_path_nodes": combined_nodes,
                "reactive_eta_min": total_eta_min,
                "reactive_reliability": rel_combined,
                "eta_delta_min": 0.0,
                "reliability_gain": 0.0,
            },
            "departure_window_min": departure_window_min,
            "window_capped": window_capped,
            **meta,
        })
        if scenario_id is not None:
            res_multi["scenario_id"] = scenario_id
        if stage is not None:
            res_multi["stage"] = stage
        if stage_title is not None:
            res_multi["stage_title"] = stage_title
        return res_multi

    def plan_cascade(
        self,
        destination: str,
        origin: str = "HOSPITAL_BASE",
        rainfall_rate: float = 15.0,
        blocked_edges: set | list | None = None,
        depth_map: dict | None = None,
        scenario_id: str | None = None,
        wind_kmh: float | None = None,
        visibility_km: float | None = None,
        launch_point: str | None = None,
    ) -> dict:
        """Evaluate vehicle dispatch cascade in order of escalation until first reachable mode."""
        sc_id = scenario_id or "cascade"
        attempts = []
        selected_vehicle = None
        selected_route = None

        # 1. AMBULANCE from origin (Stage 1)
        amb_res = self.find_route(
            origin,
            destination,
            VehicleType.AMBULANCE,
            blocked_edges=blocked_edges,
            rainfall_rate=rainfall_rate,
            depth_map=depth_map,
            scenario_id=sc_id,
            stage=1,
            stage_title="Ambulance",
        )
        attempts.append({
            "scenario_id": sc_id,
            "stage": 1,
            "stage_title": "Ambulance",
            "vehicle_type": VehicleType.AMBULANCE.value,
            "status": amb_res["status"],
            "reason": amb_res.get("reason"),
            "payload": amb_res,
        })
        if amb_res["status"] == "OK" and selected_vehicle is None:
            selected_vehicle = VehicleType.AMBULANCE.value
            selected_route = amb_res

        # 2. TRUCK_4X4 from origin (Stage 2)
        trk_res = self.find_route(
            origin,
            destination,
            VehicleType.TRUCK_4X4,
            blocked_edges=blocked_edges,
            rainfall_rate=rainfall_rate,
            depth_map=depth_map,
            scenario_id=sc_id,
            stage=2,
            stage_title="4x4 Truck",
        )
        attempts.append({
            "scenario_id": sc_id,
            "stage": 2,
            "stage_title": "4x4 Truck",
            "vehicle_type": VehicleType.TRUCK_4X4.value,
            "status": trk_res["status"],
            "reason": trk_res.get("reason"),
            "payload": trk_res,
        })
        if trk_res["status"] == "OK" and selected_vehicle is None:
            selected_vehicle = VehicleType.TRUCK_4X4.value
            selected_route = trk_res

        # 3. RESCUE_BOAT (multimodal) from origin (Stage 3)
        boat_res = self.find_multimodal_route(
            origin,
            destination,
            VehicleType.RESCUE_BOAT,
            blocked_edges=blocked_edges,
            rainfall_rate=rainfall_rate,
            depth_map=depth_map,
            scenario_id=sc_id,
            stage=3,
            stage_title="Rescue Boat (Multimodal)",
        )
        attempts.append({
            "scenario_id": sc_id,
            "stage": 3,
            "stage_title": "Rescue Boat (Multimodal)",
            "vehicle_type": VehicleType.RESCUE_BOAT.value,
            "status": boat_res["status"],
            "reason": boat_res.get("reason"),
            "payload": boat_res,
        })
        if boat_res["status"] == "OK" and selected_vehicle is None:
            selected_vehicle = VehicleType.RESCUE_BOAT.value
            selected_route = boat_res

        # 4. HELICOPTER from origin (Stage 4)
        heli_res = self.find_route(
            origin,
            destination,
            VehicleType.HELICOPTER,
            rainfall_rate=rainfall_rate,
            wind_kmh=wind_kmh,
            visibility_km=visibility_km,
            launch_point=launch_point,
            scenario_id=sc_id,
            stage=4,
            stage_title="Helicopter",
        )
        attempts.append({
            "scenario_id": sc_id,
            "stage": 4,
            "stage_title": "Helicopter",
            "vehicle_type": VehicleType.HELICOPTER.value,
            "status": heli_res["status"],
            "reason": heli_res.get("reason"),
            "payload": heli_res,
        })
        if heli_res["status"] == "OK" and selected_vehicle is None:
            selected_vehicle = VehicleType.HELICOPTER.value
            selected_route = heli_res

        return {
            "scenario_id": sc_id,
            "destination": destination,
            "selected_vehicle": selected_vehicle,
            "selected_route": selected_route,
            "attempts": attempts,
        }

    def export_network_geojson(self) -> dict:
        """Export network topology as a GeoJSON FeatureCollection of edges."""
        features = []
        for u, v, data in self.graph.edges(data=True):
            d_geom = data.get("geometry") or data.get("display_geometry")
            if d_geom:
                if isinstance(d_geom, dict) and "coordinates" in d_geom:
                    coords = d_geom["coordinates"]
                    quality = "osm_polyline"
                elif isinstance(d_geom, (list, tuple)):
                    coords = list(d_geom)
                    quality = "osm_polyline"
                else:
                    u_node = self.graph.nodes[u]
                    v_node = self.graph.nodes[v]
                    coords = [
                        [u_node["lon"], u_node["lat"]],
                        [v_node["lon"], v_node["lat"]],
                    ]
                    quality = data.get("geometry_quality", "schematic_straight_lines")
            else:
                u_node = self.graph.nodes[u]
                v_node = self.graph.nodes[v]
                coords = [
                    [u_node["lon"], u_node["lat"]],
                    [v_node["lon"], v_node["lat"]],
                ]
                quality = data.get("geometry_quality", "schematic_straight_lines")
            feat = {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "edge": [u, v],
                    "name": data.get("name", f"{u}-{v}"),
                    "kind": data.get("kind", "road"),
                    "depth": data.get("current_water_depth_meters", 0.0),
                    "current_water_depth_meters": data.get("current_water_depth_meters", 0.0),
                    "elevation": data.get("elevation_meters"),
                    "distance_to_river_m": data.get("distance_to_river_meters"),
                    "geometry_quality": quality,
                },
            }
            features.append(feat)
            if len(features) >= 20000:
                break
        return {"type": "FeatureCollection", "features": features}

    def _evaluate_decision_stability(
        self,
        origin: str,
        destination: str,
        v_type: VehicleType,
        rainfall_rate: float,
        base_path_nodes: list[str] | None,
        is_multimodal: bool = False,
    ) -> dict:
        """Compute fraction of parameter perturbations leaving optimal path unchanged."""
        import modules.rescue_routing.risk_engine as risk_mod
        import modules.rescue_routing.router as router_mod

        named_constants = [
            "RAINFALL_COEFFICIENT",
            "ELEVATION_COEFFICIENT",
            "RIVER_DISTANCE_COEFFICIENT",
            "RISK_THRESHOLD_BIAS",
            "ON_SCENE_DWELL_MIN",
            "RISK_TIME_PENALTY",
        ]
        unchanged = 0
        total = len(named_constants) * 2

        for const_name in named_constants:
            orig_val = getattr(risk_mod, const_name)
            for factor in [0.8, 1.2]:
                pert_val = orig_val * factor
                setattr(risk_mod, const_name, pert_val)
                if hasattr(router_mod, const_name):
                    setattr(router_mod, const_name, pert_val)

                if is_multimodal:
                    cur = self.find_multimodal_route(origin, destination, v_type, rainfall_rate=rainfall_rate)
                else:
                    cur = self.find_route(origin, destination, v_type, rainfall_rate=rainfall_rate)

                if cur.get("path_nodes") == base_path_nodes:
                    unchanged += 1

            setattr(risk_mod, const_name, orig_val)
            if hasattr(router_mod, const_name):
                setattr(router_mod, const_name, orig_val)

        share = round(unchanged / total, 4)
        label = "STABLE" if share >= STABILITY_MIN else "SENSITIVE"
        return {"share_unchanged": share, "label": label}

    def build_slider_dataset(
        self,
        queries: list[dict] | None = None,
        rainfall_steps: list[float] | None = None,
    ) -> dict:
        """Build interactive slider dataset across rainfall steps and query scenarios."""
        if rainfall_steps is None:
            rainfall_steps = [0, 15, 30, 45, 60]
        is_default_queries = queries is None
        if queries is None:
            queries = [
                {
                    "id": "ambulance_hospital_to_north",
                    "vehicle_type": VehicleType.AMBULANCE.value,
                    "origin": "HOSPITAL_BASE",
                    "destination": "ZONE_NORTH_RESIDENTIAL",
                    "multimodal": False,
                },
                {
                    "id": "truck_hospital_to_island",
                    "vehicle_type": VehicleType.TRUCK_4X4.value,
                    "origin": "HOSPITAL_BASE",
                    "destination": "ZONE_ISLAND_COMMUNITY",
                    "multimodal": False,
                },
                {
                    "id": "boat_multimodal_hospital_to_island",
                    "vehicle_type": VehicleType.RESCUE_BOAT.value,
                    "origin": "HOSPITAL_BASE",
                    "destination": "ZONE_ISLAND_COMMUNITY",
                    "multimodal": True,
                },
            ]

        steps = []
        for rain in rainfall_steps:
            edge_risks = {}
            for u, v, data in sorted(self.graph.edges(data=True)):
                key = f"{u}|{v}"
                r = calculate_edge_risk(
                    data["elevation_meters"],
                    data["distance_to_river_meters"],
                    float(rain),
                    horizon_min=30.0,
                    kind=data.get("kind", "road"),
                )
                edge_risks[key] = round(r, 4)

            if is_default_queries:
                res1 = self.find_route("HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, rainfall_rate=float(rain))
                res1["decision_stability"] = self._evaluate_decision_stability(
                    "HOSPITAL_BASE", "ZONE_NORTH_RESIDENTIAL", VehicleType.AMBULANCE, float(rain), res1.get("path_nodes")
                )

                res2 = self.find_route("HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.TRUCK_4X4, rainfall_rate=float(rain))
                res2["decision_stability"] = self._evaluate_decision_stability(
                    "HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.TRUCK_4X4, float(rain), res2.get("path_nodes")
                )

                res3 = self.find_multimodal_route("HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.RESCUE_BOAT, rainfall_rate=float(rain))
                res3["decision_stability"] = self._evaluate_decision_stability(
                    "HOSPITAL_BASE", "ZONE_ISLAND_COMMUNITY", VehicleType.RESCUE_BOAT, float(rain), res3.get("path_nodes"), is_multimodal=True
                )
                res_list = [res1, res2, res3]
            else:
                res_list = []
                for q in queries:
                    q_id = q["id"]
                    orig = q["origin"]
                    dest = q["destination"]
                    vt = q["vehicle_type"]
                    is_multi = q.get("multimodal", False)
                    if is_multi:
                        res = self.find_multimodal_route(orig, dest, VehicleType(vt), rainfall_rate=float(rain))
                    else:
                        res = self.find_route(orig, dest, VehicleType(vt), rainfall_rate=float(rain))
                    res["query_id"] = q_id
                    res["decision_stability"] = self._evaluate_decision_stability(
                        orig, dest, VehicleType(vt), float(rain), res.get("path_nodes"), is_multimodal=is_multi
                    )
                    res_list.append(res)

            all_low = all(
                r.get("advisory") == ADVISORY_LOW_RELIABILITY or r.get("status") == "UNREACHABLE"
                for r in res_list
            )
            step_obj = {
                "rainfall_mm_h": rain,
                "planning_risk_horizon_min": 30,
                "edge_risks": edge_risks,
                "results": res_list,
            }
            if rain >= HELI_GROUND_MM_H and all_low:
                first_orig = queries[0]["origin"] if queries else "BASE"
                no_safe_entry = {
                    "id": "no_safe_option",
                    "query_id": "no_safe_option",
                    "status": "UNREACHABLE",
                    "advisory": ADVISORY_NO_SAFE_OPTION,
                    "vehicle_type": "ALL",
                    "origin": first_orig,
                    "destination": "ALL",
                    "route_reliability": 0.0,
                    "max_planning_risk": 1.0,
                    "risk_warning": False,
                    "reason": "Helicopter grounded by weather and all surface options below reliability threshold",
                    "decision_stability": {
                        "share_unchanged": 1.0,
                        "label": "STABLE",
                    },
                }
                res_list.append(no_safe_entry)
                step_obj["advisory"] = ADVISORY_NO_SAFE_OPTION
            else:
                step_obj["advisory"] = ADVISORY_LOW_RELIABILITY if any(r.get("advisory") == ADVISORY_LOW_RELIABILITY for r in res_list) else ADVISORY_NONE

            steps.append(step_obj)

        flip_points = {}
        for q in queries:
            q_id = q["id"]
            orig = q["origin"]
            dest = q["destination"]
            vt = q["vehicle_type"]
            is_multi = q.get("multimodal", False)
            flips = []
            prev_nodes = None
            for r in range(61):
                if is_multi:
                    out = self.find_multimodal_route(orig, dest, VehicleType(vt), rainfall_rate=float(r))
                else:
                    out = self.find_route(orig, dest, VehicleType(vt), rainfall_rate=float(r))
                nodes = tuple(out.get("path_nodes") or [])
                if r == 0:
                    prev_nodes = nodes
                else:
                    if nodes != prev_nodes:
                        flips.append(r)
                        prev_nodes = nodes
            flip_points[q_id] = flips

        return {
            "rainfall_steps_mm_h": rainfall_steps,
            "planning_risk_horizon_min": 30,
            "queries": queries,
            "steps": steps,
            "route_flip_points": flip_points,
        }

    def replan(self, previous_payload: dict, new_conditions: dict) -> dict:
        """Replan route given updated weather, blockages, or depth observations."""
        origin = previous_payload["origin"]
        destination = previous_payload["destination"]
        vehicle_type = previous_payload["vehicle_type"]

        rainfall_rate = new_conditions.get("rainfall_rate", previous_payload.get("rainfall_mmh", 15.0))
        blocked_edges = new_conditions.get("blocked_edges", previous_payload.get("blocked_edges"))
        depth_map = new_conditions.get("depth_map")
        depart_in_min = new_conditions.get("depart_in_min", 0.0)
        depth_source = new_conditions.get("depth_source")
        depth_age_min = new_conditions.get("depth_age_min")

        if vehicle_type == VehicleType.RESCUE_BOAT.value and previous_payload.get("legs"):
            new_payload = self.find_multimodal_route(
                origin,
                destination,
                rainfall_rate=rainfall_rate,
                blocked_edges=blocked_edges,
                depth_map=depth_map,
                depart_in_min=depart_in_min,
                depth_source=depth_source,
                depth_age_min=depth_age_min,
            )
        else:
            new_payload = self.find_route(
                origin,
                destination,
                vehicle_type,
                rainfall_rate=rainfall_rate,
                blocked_edges=blocked_edges,
                depth_map=depth_map,
                depart_in_min=depart_in_min,
                depth_source=depth_source,
                depth_age_min=depth_age_min,
            )

        old_path = previous_payload.get("path_nodes")
        new_path = new_payload.get("path_nodes")
        old_status = previous_payload.get("status")
        new_status = new_payload.get("status")

        changed = (old_path != new_path) or (old_status != new_status)

        if not changed:
            reason = "ROUTE_UNCHANGED"
        elif new_status != "OK":
            reason = new_payload.get("reason", f"STATUS_{new_status}")
        elif new_payload.get("is_predictive_detour") and not previous_payload.get("is_predictive_detour"):
            reason = "PREDICTIVE_RISK_DETOUR"
        elif any(h.get("reason") in ["SUBMERGED", "BLOCKED"] for h in new_payload.get("avoided_hazards", [])):
            reason = "FLOOD_DETOUR"
        else:
            reason = "CONDITIONS_UPDATED"

        old_eta = previous_payload.get("eta_minutes")
        new_eta = new_payload.get("eta_minutes")
        eta_delta_min = round(new_eta - old_eta, 2) if (old_eta is not None and new_eta is not None) else None

        return {
            "changed": changed,
            "reason": reason,
            "eta_delta_min": eta_delta_min,
            "new_payload": new_payload,
        }


def polyline_length_m(coords: list) -> float:
    """Calculate total length of a polyline in meters from [[lon, lat], ...]."""
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    for k in range(len(coords) - 1):
        total += haversine_distance(coords[k][0], coords[k][1], coords[k + 1][0], coords[k + 1][1])
    return total


def validate_route(payload: dict, graph: nx.Graph) -> bool:
    """Validate safety postconditions, topological continuity, and geometry consistency."""
    props = payload.get("properties", payload)
    status = props.get("status")
    if status == "UNREACHABLE":
        geom = payload.get("geometry")
        if geom is not None and geom != {}:
            raise ValueError(f"UNREACHABLE route must have geometry null, got {geom}")
        if not props.get("reason"):
            raise ValueError("UNREACHABLE route must include reason")
        if "isolated_node_count" not in props:
            raise ValueError("UNREACHABLE route must include isolated_node_count")
        return True

    if status != "OK":
        return True

    v_type = props.get("vehicle_type")
    path_nodes = props.get("path_nodes") or []
    if not path_nodes:
        raise ValueError("OK route missing path_nodes")

    origin = props.get("origin")
    dest = props.get("destination")
    if origin and path_nodes[0] != origin:
        raise ValueError(f"Route origin {origin} does not match start node {path_nodes[0]}")
    if dest and path_nodes[-1] != dest:
        raise ValueError(f"Route destination {dest} does not match end node {path_nodes[-1]}")

    if v_type != "HELICOPTER":
        for i in range(len(path_nodes) - 1):
            u, v = path_nodes[i], path_nodes[i + 1]
            if not graph.has_edge(u, v):
                continue
            ed = graph[u][v]
            depth = ed.get("current_water_depth_meters", 0.0)
            has_flood = ed.get("has_flood_water", False)
            if v_type == "AMBULANCE":
                if depth > 0.0 or has_flood:
                    raise ValueError(f"Ambulance route violates depth rule on edge ({u}, {v}): depth={depth}m, flooded={has_flood}")
            elif v_type == "TRUCK_4X4":
                if depth > 0.4:
                    raise ValueError(f"Truck route violates depth rule on edge ({u}, {v}): depth={depth}m > 0.4m")

    geom = payload.get("geometry") or props.get("geometry") or props.get("geojson_geometry")
    coords = geom.get("coordinates") if isinstance(geom, dict) else geom
    if not coords or len(coords) < 2:
        raise ValueError("OK route geometry must have at least 2 coordinate pairs")

    drawn_len_km = polyline_length_m(coords) / 1000.0
    dist_km = props.get("distance_km")
    geom_len_km = props.get("geometry_length_km")

    if dist_km is not None and drawn_len_km > 0.01:
        diff_pct = abs(dist_km - drawn_len_km) / drawn_len_km
        if diff_pct > 0.01 and not props.get("distance_basis"):
            raise ValueError(f"distance_km ({dist_km}) differs from polyline length ({drawn_len_km:.3f} km) by {diff_pct*100:.2f}% without distance_basis")

    if geom_len_km is not None and drawn_len_km > 0.01:
        diff_geom_pct = abs(geom_len_km - drawn_len_km) / drawn_len_km
        if diff_geom_pct > 0.01:
            raise ValueError(f"geometry_length_km ({geom_len_km}) differs from polyline length ({drawn_len_km:.3f} km) by {diff_geom_pct*100:.2f}%")

    return True

