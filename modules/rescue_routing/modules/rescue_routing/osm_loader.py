"""Network loader for curated Zaragoza sector (OSM-derived, approximate)."""

import json
import math
from pathlib import Path
import networkx as nx

EARTH_RADIUS_M = 6371000.0
ROAD_SPEED_MPS = 40.0 / 3.6  # 40 km/h ambulance baseline speed
RIVER_SPEED_MPS = 15.0 / 3.6  # 15 km/h river transit speed


def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def load_network(filepath: str | Path | None = None) -> nx.Graph:
    """Load the Zaragoza rescue network into a NetworkX graph."""
    if filepath is None:
        target = Path("data/zaragoza_network.json")
        if not target.exists():
            target = Path(__file__).resolve().parent.parent.parent / "data" / "zaragoza_network.json"
    else:
        target = Path(filepath)

    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)

    g = nx.Graph()

    for node_id, node_data in data["nodes"].items():
        g.add_node(
            node_id,
            lon=node_data["lon"],
            lat=node_data["lat"],
            elev_m=node_data["elev_m"],
            elevation_m=node_data["elev_m"],
            type=node_data["type"],
            description=node_data.get("description", ""),
            derived=node_data.get("derived", False),
        )

    seen_edges = set()
    for edge in data["edges"]:
        u, v = edge["u"], edge["v"]
        pair = tuple(sorted((u, v)))
        if pair in seen_edges:
            raise ValueError(f"Duplicate edge defined between {u} and {v}")
        seen_edges.add(pair)

        u_node, v_node = g.nodes[u], g.nodes[v]
        rf = edge.get("road_factor", 1.0)
        dist = edge.get("distance_meters")
        if dist is None:
            dist = haversine_distance(
                u_node["lon"], u_node["lat"], v_node["lon"], v_node["lat"]
            ) * rf

        kind = edge["kind"]
        speed = RIVER_SPEED_MPS if kind == "river" else ROAD_SPEED_MPS
        travel_time = edge.get("travel_time_seconds")
        if travel_time is None:
            travel_time = dist / speed

        g.add_edge(
            u,
            v,
            name=edge["name"],
            kind=kind,
            distance_meters=dist,
            travel_time_seconds=travel_time,
            current_water_depth_meters=edge.get("current_water_depth_meters", 0.0),
            elevation_meters=edge["elevation_meters"],
            distance_to_river_meters=edge["distance_to_river_meters"],
            derived=edge.get("derived", False),
        )

    return g


ASSUMED_FLOOD_DEPTH_M = 1.0  # assumed water depth in meters when proxying from binary flood masks
DATA_FRESHNESS_MAX_MIN = 180.0  # maximum observation latency in minutes to qualify as fresh data


class DepthMap(dict):
    """Dictionary mapping edge pairs to depths with optional metadata."""

    def __init__(self, mapping=None, metadata=None):
        super().__init__(mapping or {})
        self.metadata = metadata or {}


def load_depth_map(filepath: str | Path) -> dict[tuple[str, str], float]:
    """Load an edge depth map from a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    depths_dict = data.get("depths", data)
    result = {}
    for k, v in depths_dict.items():
        if isinstance(k, str) and "|" in k:
            u, w = k.split("|")
            result[tuple(sorted((u, w)))] = float(v)
    metadata = {k: v for k, v in data.items() if k != "depths"}
    return DepthMap(result, metadata)


def depth_from_mask_fraction(
    fractions: dict[tuple[str, str] | str, float],
    assumed_depth_m: float = ASSUMED_FLOOD_DEPTH_M,
) -> dict[tuple[str, str], float]:
    """Estimate water depth from flood mask pixel coverage fractions."""
    # a binary mask carries no depth, so proxy by multiplying coverage fraction by assumed depth
    result = {}
    for k, frac in fractions.items():
        if isinstance(k, str) and "|" in k:
            u, v = k.split("|")
            pair = tuple(sorted((u, v)))
        elif isinstance(k, (tuple, list)) and len(k) == 2:
            pair = tuple(sorted((k[0], k[1])))
        else:
            continue
        result[pair] = round(float(frac) * assumed_depth_m, 3)
    return DepthMap(result, {"depth_source": "mask_fraction_proxy"})

