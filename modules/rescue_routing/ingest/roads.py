"""Build road network graph from GeoJSON or OSM XML with OSM tags and polylines."""

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import networkx as nx

ROAD_SPEED_KMH = {
    "motorway": 80,
    "trunk": 70,
    "primary": 60,
    "secondary": 50,
    "tertiary": 40,
    "unclassified": 30,
    "residential": 30,
    "living_street": 20,
    "service": 20,
    "track": 20,
    "motorway_link": 60,
    "trunk_link": 50,
    "primary_link": 40,
    "secondary_link": 30,
    "tertiary_link": 25,
}
DEFAULT_ROAD_SPEED_KMH = 30
NON_DRIVABLE_HIGHWAYS = {
    "footway",
    "steps",
    "cycleway",
    "pedestrian",
    "path",
    "bridleway",
    "abandoned",
    "proposed",
    "construction",
}


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters between two points."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def polyline_length_m(coords: list[list[float]]) -> float:
    """Total length in meters along a polyline."""
    total = 0.0
    for i in range(len(coords) - 1):
        total += haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
    return total


def _parse_geojson(path: Path) -> nx.Graph:
    """Parse GeoJSON road network into nx.Graph."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    valid_ways = []
    coord_counts = {}

    for feat in features:
        props = feat.get("properties") or {}
        tunnel = str(props.get("tunnel", "")).lower()
        if tunnel in ("yes", "true", "1"):
            continue
        highway = str(props.get("highway", "")).lower()
        if not highway or highway in NON_DRIVABLE_HIGHWAYS:
            continue

        geom = feat.get("geometry") or {}
        g_type = geom.get("type")
        raw_lines = []
        if g_type == "LineString":
            raw_lines.append(geom.get("coordinates", []))
        elif g_type == "MultiLineString":
            raw_lines.extend(geom.get("coordinates", []))

        for line in raw_lines:
            if len(line) < 2:
                continue
            valid_ways.append((line, props, highway))
            for pt in line:
                key = (round(pt[0], 6), round(pt[1], 6))
                coord_counts[key] = coord_counts.get(key, 0) + 1

    g = nx.Graph()
    for line, props, highway in valid_ways:
        # split line into segments at intersection/junction nodes
        junction_indices = [0]
        for idx in range(1, len(line) - 1):
            key = (round(line[idx][0], 6), round(line[idx][1], 6))
            if coord_counts.get(key, 0) > 1:
                junction_indices.append(idx)
        junction_indices.append(len(line) - 1)

        for s_idx in range(len(junction_indices) - 1):
            start_i = junction_indices[s_idx]
            end_i = junction_indices[s_idx + 1]
            seg_coords = line[start_i : end_i + 1]
            if len(seg_coords) < 2:
                continue

            u_key = (round(seg_coords[0][0], 6), round(seg_coords[0][1], 6))
            v_key = (round(seg_coords[-1][0], 6), round(seg_coords[-1][1], 6))
            if u_key == v_key and len(seg_coords) <= 2:
                continue

            u_id = f"node_{u_key[0]:.6f}_{u_key[1]:.6f}"
            v_id = f"node_{v_key[0]:.6f}_{v_key[1]:.6f}"

            if u_id not in g:
                g.add_node(u_id, lon=seg_coords[0][0], lat=seg_coords[0][1])
            if v_id not in g:
                g.add_node(v_id, lon=seg_coords[-1][0], lat=seg_coords[-1][1])

            dist_m = polyline_length_m(seg_coords)
            speed = ROAD_SPEED_KMH.get(highway, DEFAULT_ROAD_SPEED_KMH)
            speed_ms = max(speed * 1000.0 / 3600.0, 0.1)
            travel_time_s = dist_m / speed_ms
            is_bridge = str(props.get("bridge", "")).lower() in ("yes", "true", "1")
            kind = "bridge" if is_bridge else "road"
            name = props.get("name") or f"{highway}_{u_id}_{v_id}"

            if g.has_edge(u_id, v_id):
                if dist_m < g[u_id][v_id]["distance_meters"]:
                    g[u_id][v_id].update({
                        "distance_meters": dist_m,
                        "travel_time_seconds": travel_time_s,
                        "speed_kmh": speed,
                        "kind": kind,
                        "name": name,
                        "geometry": seg_coords,
                    })
            else:
                g.add_edge(
                    u_id,
                    v_id,
                    distance_meters=dist_m,
                    travel_time_seconds=travel_time_s,
                    speed_kmh=speed,
                    kind=kind,
                    name=name,
                    geometry=seg_coords,
                    elevation_meters=None,
                    distance_to_river_meters=1000.0,
                    current_water_depth_meters=0.0,
                )

    return g


def _parse_osm_xml(path: Path) -> nx.Graph:
    """Parse OSM XML road network into nx.Graph using stdlib."""
    tree = ET.parse(path)
    root = tree.getroot()

    nodes_dict = {}
    for elem in root.findall("node"):
        n_id = elem.get("id")
        lat = float(elem.get("lat"))
        lon = float(elem.get("lon"))
        nodes_dict[n_id] = (lon, lat)

    valid_ways = []
    nd_counts = {}

    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        tunnel = str(tags.get("tunnel", "")).lower()
        if tunnel in ("yes", "true", "1"):
            continue
        highway = str(tags.get("highway", "")).lower()
        if not highway or highway in NON_DRIVABLE_HIGHWAYS:
            continue

        nd_refs = [nd.get("ref") for nd in way.findall("nd") if nd.get("ref") in nodes_dict]
        if len(nd_refs) < 2:
            continue

        valid_ways.append((nd_refs, tags, highway))
        for ref in nd_refs:
            nd_counts[ref] = nd_counts.get(ref, 0) + 1

    g = nx.Graph()
    for nd_refs, tags, highway in valid_ways:
        junction_indices = [0]
        for idx in range(1, len(nd_refs) - 1):
            if nd_counts.get(nd_refs[idx], 0) > 1:
                junction_indices.append(idx)
        junction_indices.append(len(nd_refs) - 1)

        for s_idx in range(len(junction_indices) - 1):
            start_i = junction_indices[s_idx]
            end_i = junction_indices[s_idx + 1]
            seg_refs = nd_refs[start_i : end_i + 1]
            if len(seg_refs) < 2:
                continue

            u_id = seg_refs[0]
            v_id = seg_refs[-1]
            if u_id == v_id and len(seg_refs) <= 2:
                continue

            seg_coords = [[nodes_dict[r][0], nodes_dict[r][1]] for r in seg_refs]
            if u_id not in g:
                g.add_node(u_id, lon=seg_coords[0][0], lat=seg_coords[0][1])
            if v_id not in g:
                g.add_node(v_id, lon=seg_coords[-1][0], lat=seg_coords[-1][1])

            dist_m = polyline_length_m(seg_coords)
            speed = ROAD_SPEED_KMH.get(highway, DEFAULT_ROAD_SPEED_KMH)
            speed_ms = max(speed * 1000.0 / 3600.0, 0.1)
            travel_time_s = dist_m / speed_ms
            is_bridge = str(tags.get("bridge", "")).lower() in ("yes", "true", "1")
            kind = "bridge" if is_bridge else "road"
            name = tags.get("name") or f"{highway}_{u_id}_{v_id}"

            if g.has_edge(u_id, v_id):
                if dist_m < g[u_id][v_id]["distance_meters"]:
                    g[u_id][v_id].update({
                        "distance_meters": dist_m,
                        "travel_time_seconds": travel_time_s,
                        "speed_kmh": speed,
                        "kind": kind,
                        "name": name,
                        "geometry": seg_coords,
                    })
            else:
                g.add_edge(
                    u_id,
                    v_id,
                    distance_meters=dist_m,
                    travel_time_seconds=travel_time_s,
                    speed_kmh=speed,
                    kind=kind,
                    name=name,
                    geometry=seg_coords,
                    elevation_meters=None,
                    distance_to_river_meters=1000.0,
                    current_water_depth_meters=0.0,
                )

    return g


def load_roads(path: str | Path) -> nx.Graph:
    """Build road network nx.Graph from GeoJSON or OSM XML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Road network file not found: {path}")

    suffix = p.suffix.lower()
    if suffix in (".osm", ".xml"):
        return _parse_osm_xml(p)
    return _parse_geojson(p)
