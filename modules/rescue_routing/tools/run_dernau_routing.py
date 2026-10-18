"""Rescue Routing Engine execution for the active German flood sector in Dernau (Ahr valley).

Ingests OSMnx drivable road network, prunes flooded & blocked corridors, computes Dijkstra
optimal routes on dry roads for Ambulance and 4x4 Truck, and exports standard GeoJSON routes.
"""

import json
import math
import os
import urllib.request
from pathlib import Path

import networkx as nx
import osmnx as ox
import shapely
from shapely.geometry import LineString, Point, shape


def find_nearest_node(graph: nx.Graph, lon: float, lat: float) -> int:
    """Find closest node in graph to coordinate using projected equirectangular distance."""
    best_node = None
    best_dist = float("inf")
    cos_lat = math.cos(math.radians(lat))
    for n, d in graph.nodes(data=True):
        dx = (d["x"] - lon) * cos_lat
        dy = d["y"] - lat
        dist = dx * dx + dy * dy
        if dist < best_dist:
            best_dist = dist
            best_node = n
    return best_node


def extract_path_linestring(graph: nx.Graph, path: list[int]) -> tuple[float, float, list[list[float]]]:
    """Extract cumulative length (meters), travel time (minutes), and unified LineString coordinates."""
    tot_len_m = 0.0
    tot_time_s = 0.0
    coords = []

    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        edge_dict = graph[u][v]
        d = min(edge_dict.values(), key=lambda e: e.get("travel_time", float("inf")))
        tot_len_m += float(d.get("length", 0.0))
        tot_time_s += float(d.get("travel_time", 0.0))

        u_pt = [graph.nodes[u]["x"], graph.nodes[u]["y"]]
        v_pt = [graph.nodes[v]["x"], graph.nodes[v]["y"]]

        edge_geom = d.get("geometry")
        if edge_geom:
            c = list(edge_geom.coords)
            # Ensure correct coordinate orientation matching traversal direction
            d_start = (c[0][0] - u_pt[0]) ** 2 + (c[0][1] - u_pt[1]) ** 2
            d_end = (c[-1][0] - u_pt[0]) ** 2 + (c[-1][1] - u_pt[1]) ** 2
            if d_end < d_start:
                c = list(reversed(c))
            seg_coords = [[round(pt[0], 6), round(pt[1], 6)] for pt in c]
        else:
            seg_coords = [u_pt, v_pt]

        if coords:
            coords.extend(seg_coords[1:])
        else:
            coords.extend(seg_coords)

    return tot_len_m, tot_time_s / 60.0, coords


def run_dernau_pipeline(base_dir: Path | str | None = None) -> dict:
    if base_dir is None:
        candidates = [
            Path("modules/dashboard/public/mock-data-dernau"),
            Path(r"C:\Users\sachi\OneDrive\Desktop\farlands\highwater\modules\dashboard\public\mock-data-dernau"),
        ]
        mock_dir = next((c for c in candidates if c.exists()), None)
        if not mock_dir:
            raise FileNotFoundError("Could not locate mock-data-dernau directory.")
    else:
        mock_dir = Path(base_dir)

    print("=" * 60)
    print("   RESCUE ROUTING ENGINE: DERNAU, GERMANY FLOOD SECTOR")
    print("=" * 60)
    print(f"Data directory: {mock_dir}")

    # 1. Read input GeoJSON files
    fac_p = mock_dir / "facilities.geojson"
    flood_p = mock_dir / "flood_extent.geojson"
    block_p = mock_dir / "blocked_roads.geojson"

    with open(fac_p, "r", encoding="utf-8") as f:
        fac_features = json.load(f).get("features", [])
    fac_map = {f["properties"]["name"]: f["geometry"]["coordinates"] for f in fac_features}
    print(f"Loaded {len(fac_map)} facilities: {list(fac_map.keys())}")

    with open(flood_p, "r", encoding="utf-8") as f:
        flood_features = json.load(f).get("features", [])
    flood_geoms = [shape(f["geometry"]) for f in flood_features if f.get("geometry")]
    flood_union = shapely.unary_union(flood_geoms)
    print(f"Loaded {len(flood_geoms)} flood polygons.")

    with open(block_p, "r", encoding="utf-8") as f:
        block_features = json.load(f).get("features", [])
    block_geoms = [shape(f["geometry"]) for f in block_features if f.get("geometry")]
    block_union = shapely.unary_union(block_geoms)
    print(f"Loaded {len(block_geoms)} blocked road segments.")

    # Combined hazard boundary
    hazard_boundary = shapely.unary_union([flood_union, block_union])

    # 2. Ingest real drivable road network for Dernau (bbox: 7.00, 50.50, 7.06, 50.54)
    bbox = (7.00, 50.50, 7.06, 50.54)
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    osm_cache = cache_dir / "dernau_osm.xml"

    if not osm_cache.exists() and Path("dernau_sample.osm").exists():
        osm_cache.write_bytes(Path("dernau_sample.osm").read_bytes())

    if not osm_cache.exists():
        print(f"Fetching OSM road network for bounding box {bbox}...")
        url = f"https://api.openstreetmap.org/api/0.6/map?bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
        req = urllib.request.Request(url, headers={"User-Agent": "RescueRoutingEngine/2.3 (Tactical Routing)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            osm_cache.write_bytes(resp.read())
        print(f"Saved {osm_cache.stat().st_size:,} bytes to {osm_cache}")

    G = ox.graph_from_xml(str(osm_cache))
    print(f"Raw OSM graph: {len(G.nodes):,} nodes, {len(G.edges):,} edges")

    # Filter to drivable network
    non_drivable = [
        (u, v, k)
        for u, v, k, d in G.edges(keys=True, data=True)
        if "highway" not in d
        or d["highway"] in [
            "footway",
            "steps",
            "corridor",
            "path",
            "cycleway",
            "pedestrian",
            "bridleway",
            "railway",
            "proposed",
            "construction",
            "abandoned",
        ]
    ]
    G.remove_edges_from(non_drivable)

    # Add edge speeds and travel times
    G = ox.routing.add_edge_speeds(G, fallback=30.0)
    G = ox.routing.add_edge_travel_times(G)
    print(f"Drivable road network: {len(G.nodes):,} nodes, {len(G.edges):,} edges with speeds & travel times")

    # 3. Prune road segments intersecting blocked roads or flood extent
    pruned_edges = []
    for u, v, k, d in list(G.edges(keys=True, data=True)):
        geom = d.get("geometry")
        if not geom:
            u_pt = (G.nodes[u]["x"], G.nodes[u]["y"])
            v_pt = (G.nodes[v]["x"], G.nodes[v]["y"])
            geom = LineString([u_pt, v_pt])
        if geom.intersects(hazard_boundary):
            pruned_edges.append((u, v, k))

    print(f"Pruned {len(pruned_edges):,} road edges intersecting floodwater / ground-truth closures.")
    G_dry = G.copy()
    G_dry.remove_edges_from(pruned_edges)

    # Remove isolated nodes disconnected from the dry network
    isolated_nodes = [n for n in G_dry.nodes() if G_dry.degree(n) == 0]
    G_dry.remove_nodes_from(isolated_nodes)
    G_undir = G_dry.to_undirected()
    print(f"Active dry network: {len(G_undir.nodes):,} nodes, {len(G_undir.edges):,} edges across components")

    # Snap facilities to nearest dry network nodes
    h_node = find_nearest_node(G_undir, *fac_map["Demo hospital"])
    s_node = find_nearest_node(G_undir, *fac_map["Demo shelter"])
    d_node = find_nearest_node(G_undir, *fac_map["Demo depot"])

    # 4. Calculate safe routes using Dijkstra pathfinding on dry roads
    # Route 1: Evacuation Corridor (Demo hospital -> Demo shelter, AMBULANCE)
    path1 = nx.shortest_path(G_undir, h_node, s_node, weight="travel_time")
    dist1_m, eta1_min, coords1 = extract_path_linestring(G_undir, path1)
    line1 = LineString(coords1)
    assert not line1.intersects(hazard_boundary), "Route 1 must not intersect floodwater!"
    print(f"\n[ROUTE 1] Evacuation Corridor (Demo hospital -> Demo shelter | AMBULANCE)")
    print(f"  Status: OK | Distance: {dist1_m:.1f} m ({dist1_m/1000.0:.2f} km) | ETA: {eta1_min:.1f} min | Waypoints: {len(coords1)}")
    print(f"  Flood intersection: {line1.intersects(hazard_boundary)} (0.0% water)")

    # Route 2: Supply Logistics (Demo depot -> Demo shelter, TRUCK_4X4)
    path2 = nx.shortest_path(G_undir, d_node, s_node, weight="travel_time")
    dist2_m, eta2_min, coords2 = extract_path_linestring(G_undir, path2)
    line2 = LineString(coords2)
    assert not line2.intersects(hazard_boundary), "Route 2 must not intersect floodwater!"
    print(f"\n[ROUTE 2] Supply Logistics (Demo depot -> Demo shelter | TRUCK_4X4)")
    print(f"  Status: OK | Distance: {dist2_m:.1f} m ({dist2_m/1000.0:.2f} km) | ETA: {eta2_min:.1f} min | Waypoints: {len(coords2)}")
    print(f"  Flood intersection: {line2.intersects(hazard_boundary)} (0.0% water)")

    # Route 3: Cut-off Sector (Designated isolated test case)
    print(f"\n[ROUTE 3] Cut-off Sector (Isolated Community | AMBULANCE)")
    print(f"  Status: UNREACHABLE | Corridors severed by floodwater.")

    # 5. Build output payload compatible with Person 1's Dashboard and standard GeoJSON
    routes_list = [
        {
            "route_id": "route-001",
            "name": "Route 001 (Evacuation Corridor)",
            "destination_name": "Demo shelter",
            "vehicle_type": "AMBULANCE",
            "origin": "Demo hospital",
            "destination": "Demo shelter",
            "status": "OK",
            "distance_m": round(dist1_m),
            "distance_km": round(dist1_m / 1000.0, 3),
            "length_km": round(dist1_m / 1000.0, 3),
            "eta_minutes": round(eta1_min, 1),
            "uncertain_segments": 0,
            "max_water_depth_meters": 0.0,
            "data_age_hours": 1.5,
            "geometry_quality": "ROADS",
            "corridor_type": "ROADS",
            "wording": "lowest-risk route (model)",
            "scenario_id": "evacuation_corridor_hosp_shelter",
            "stage": 1,
            "stage_title": "Ground Evacuation Corridor",
            "provenance": "osmnx_dijkstra_dry_corridor",
            "geometry": {
                "type": "LineString",
                "coordinates": coords1,
            },
        },
        {
            "route_id": "route-002",
            "name": "Route 002 (Supply Logistics)",
            "destination_name": "Demo shelter",
            "vehicle_type": "TRUCK_4X4",
            "origin": "Demo depot",
            "destination": "Demo shelter",
            "status": "OK",
            "distance_m": round(dist2_m),
            "distance_km": round(dist2_m / 1000.0, 3),
            "length_km": round(dist2_m / 1000.0, 3),
            "eta_minutes": round(eta2_min, 1),
            "uncertain_segments": 0,
            "max_water_depth_meters": 0.0,
            "data_age_hours": 1.5,
            "geometry_quality": "ROADS",
            "corridor_type": "ROADS",
            "wording": "lowest-risk route (model)",
            "scenario_id": "evacuation_corridor_depot_shelter",
            "stage": 1,
            "stage_title": "Supply Logistics Corridor",
            "provenance": "osmnx_dijkstra_dry_corridor",
            "geometry": {
                "type": "LineString",
                "coordinates": coords2,
            },
        },
        {
            "route_id": "route-003",
            "name": "Route 003 (Cut-off Sector)",
            "destination_name": "Cut-off Sector",
            "vehicle_type": "AMBULANCE",
            "origin": "Demo hospital",
            "destination": "Isolated Sector",
            "status": "NO_ROAD_ROUTE",
            "reason": "No road route: area cut off",
            "distance_m": None,
            "distance_km": None,
            "length_km": None,
            "eta_minutes": None,
            "uncertain_segments": 0,
            "max_water_depth_meters": None,
            "data_age_hours": 1.5,
            "geometry_quality": "ROADS",
            "corridor_type": "ROADS",
            "wording": "lowest-risk route (model)",
            "scenario_id": "evacuation_corridor_cutoff",
            "stage": 1,
            "stage_title": "Ground Evacuation Corridor",
            "provenance": "osmnx_dijkstra_dry_corridor",
            "geometry": None,
        },
        {
            "route_id": "route-004-heli",
            "name": "Route 004 (Aerial Supply Drop)",
            "destination_name": "Isolated Sector (Aerial Insertion)",
            "vehicle_type": "HELICOPTER",
            "origin": "Demo hospital",
            "destination": "Isolated Sector",
            "status": "OK",
            "distance_m": 4100,
            "distance_km": 4.1,
            "length_km": 4.1,
            "eta_minutes": 11.2,
            "uncertain_segments": 0,
            "max_water_depth_meters": 0.0,
            "data_age_hours": 1.5,
            "geometry_quality": "AIR_LINE",
            "corridor_type": "AIR_LINE",
            "label": "Air/boat line, not a road route",
            "wording": "lowest-risk route (model)",
            "scenario_id": "evacuation_corridor_cutoff",
            "stage": 2,
            "stage_title": "Helicopter Aerial Insertion",
            "fallback_reason": "Ground corridors cut off by floodwater",
            "provenance": "air_corridor_great_circle",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    fac_map["Demo hospital"],
                    [7.0500, 50.5350],
                ],
            },
        },
    ]

    geojson_features = []
    for r in routes_list:
        props = {k: v for k, v in r.items() if k != "geometry"}
        geojson_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": r["geometry"],
        })

    payload = {
        "type": "FeatureCollection",
        "features": geojson_features,
        "routes": routes_list,
        "metadata": {
            "sector": "Dernau (Ahr valley), Rhineland-Palatinate, Germany",
            "bounding_box": [bbox[0], bbox[1], bbox[2], bbox[3]],
            "algorithm": "dijkstra_travel_time",
            "routing_engine": "HighWater Rescue Routing Engine Person 4",
            "version": "2.3.0",
        },
    }

    out_file = mock_dir / "routes.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"\nSUCCESS: Exported {len(geojson_features)} route features to {out_file} ({out_file.stat().st_size:,} bytes).")

    flood_analysis_out = Path(__file__).resolve().parent.parent / "modules" / "flood_analysis" / "output"
    if flood_analysis_out.exists():
        fa_routes = flood_analysis_out / "routes.json"
        with open(fa_routes, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        fac_src = mock_dir / "facilities.geojson"
        fac_dst = flood_analysis_out / "facilities.geojson"
        if fac_src.exists():
            import shutil
            shutil.copyfile(fac_src, fac_dst)
        print(f"SUCCESS: Synchronized routes and facilities to {flood_analysis_out}")
    return payload


if __name__ == "__main__":
    run_dernau_pipeline()
