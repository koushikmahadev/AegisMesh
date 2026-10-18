"""Snap rescue facilities, bases, zones, and boat ramps to nearest graph nodes."""

import json
import math
from pathlib import Path
import sys
import networkx as nx

SNAP_MAX_M = 500.0  # maximum snapping radius in meters from facility to road network


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters between two points."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def snap_sites(graph: nx.Graph, sites_input: str | Path | list[dict]) -> dict[str, dict]:
    """Snap each site to nearest graph node within SNAP_MAX_M (500m); exits if exceeded."""
    if isinstance(sites_input, (str, Path)):
        p = Path(sites_input)
        if not p.exists():
            raise FileNotFoundError(f"Sites file not found: {sites_input}")
        with open(p, "r", encoding="utf-8") as f:
            sites = json.load(f)
    else:
        sites = sites_input

    site_map = {}
    for site in sites:
        s_id = str(site["id"])
        s_lat = float(site["lat"])
        s_lon = float(site["lon"])
        s_kind = site.get("kind", "zone")
        residents = site.get("residents")

        # find closest existing graph node
        best_node = None
        best_dist = float("inf")
        for node, n_data in graph.nodes(data=True):
            dist = haversine_m(s_lon, s_lat, n_data["lon"], n_data["lat"])
            if dist < best_dist:
                best_dist = dist
                best_node = node

        if best_node is None or best_dist > SNAP_MAX_M:
            sys.exit(
                f"Site '{s_id}' at ({s_lat}, {s_lon}) is {best_dist:.1f}m from nearest "
                f"road network node, exceeding SNAP_MAX_M ({SNAP_MAX_M}m)."
            )

        if s_id in graph:
            graph.nodes[s_id]["lat"] = s_lat
            graph.nodes[s_id]["lon"] = s_lon
            graph.nodes[s_id]["site_kind"] = s_kind
            if residents is not None:
                graph.nodes[s_id]["residents"] = residents
        elif best_dist <= 1.0 or graph.degree[best_node] == 1:
            # relabel endpoint or close node directly
            nx.relabel_nodes(graph, {best_node: s_id}, copy=False)
            graph.nodes[s_id]["lat"] = s_lat
            graph.nodes[s_id]["lon"] = s_lon
            graph.nodes[s_id]["site_kind"] = s_kind
            if residents is not None:
                graph.nodes[s_id]["residents"] = residents
        else:
            # add node and short connector edge to junction
            graph.add_node(s_id, lat=s_lat, lon=s_lon, site_kind=s_kind)
            if residents is not None:
                graph.nodes[s_id]["residents"] = residents
            b_data = graph.nodes[best_node]
            geom = [[s_lon, s_lat], [b_data["lon"], b_data["lat"]]]
            tt_s = best_dist / (30.0 * 1000.0 / 3600.0)
            graph.add_edge(
                s_id,
                best_node,
                distance_meters=best_dist,
                travel_time_seconds=tt_s,
                speed_kmh=30,
                kind="road",
                name=f"access_{s_id}",
                geometry=geom,
                current_water_depth_meters=0.0,
                depth_source="scenario",
                satellite_coverage="OK",
                nodata_fraction=0.0,
                distance_to_river_meters=1000.0,
                elevation_meters=b_data.get("elevation_meters"),
            )

        site_map[s_id] = {
            "id": s_id,
            "kind": s_kind,
            "lat": s_lat,
            "lon": s_lon,
            "residents": residents,
            "snapped_dist_m": round(best_dist, 1),
        }

    return site_map
