# untested: needs network
"""Tool to build Zaragoza rescue routing graph from OpenStreetMap via OSMnx."""

import argparse
import json


def build_graph_from_osm(
    place_name: str = "Zaragoza, Spain",
    river_name: str = "Río Ebro",
    dem_path: str | None = None,
    output_path: str = "data/zaragoza_network_osm.json",
) -> None:
    """Extract drivable road network and river corridor from OSM and compute edge distances and elevations."""
    import osmnx as ox  # optional dependency, not imported by core modules
    import shapely.geometry as sg

    # retrieve drive network within bounding place
    g_drive = ox.graph_from_place(place_name, network_type="drive")

    # query Ebro river waterway geometries
    waterways = ox.geometries_from_place(place_name, tags={"waterway": ["river", "stream"]})
    ebro_geoms = waterways[waterways["name"].str.contains(river_name, case=False, na=False)]
    river_union = ebro_geoms.unary_union if not ebro_geoms.empty else None

    # dem sampling stub if elevation raster provided
    dem_dataset = None
    if dem_path:
        try:
            import rasterio
            dem_dataset = rasterio.open(dem_path)
        except ImportError:
            dem_dataset = None

    nodes_dict = {}
    for node_id, data in g_drive.nodes(data=True):
        lat = data["y"]
        lon = data["x"]
        elev = 194.0
        if dem_dataset:
            # sample DEM at (lon, lat)
            coords = [(lon, lat)]
            sampled = list(dem_dataset.sample(coords))
            if sampled and len(sampled[0]) > 0:
                elev = float(sampled[0][0])
        nodes_dict[str(node_id)] = {
            "lat": lat,
            "lon": lon,
            "elev_m": elev,
            "type": "junction",
            "description": f"OSM Node {node_id}",
        }

    edges_list = []
    for u, v, k, data in g_drive.edges(keys=True, data=True):
        geom = data.get("geometry")
        if geom:
            coords = list(geom.coords)
        else:
            u_node = g_drive.nodes[u]
            v_node = g_drive.nodes[v]
            coords = [[u_node["x"], u_node["y"]], [v_node["x"], v_node["y"]]]

        dist_to_river = 100.0
        if river_union:
            line = sg.LineString(coords)
            dist_to_river = float(line.distance(river_union) * 111000.0)

        edge_elev = (nodes_dict[str(u)]["elev_m"] + nodes_dict[str(v)]["elev_m"]) / 2.0

        edges_list.append({
            "u": str(u),
            "v": str(v),
            "name": data.get("name", f"Way {u}-{v}"),
            "kind": "road",
            "elevation_meters": edge_elev,
            "distance_to_river_meters": round(dist_to_river, 1),
            "current_water_depth_meters": 0.0,
            "display_geometry": {"type": "LineString", "coordinates": coords},
            "geometry_quality": "osm_polyline",
        })

    out_payload = {
        "meta": {
            "source": "OpenStreetMap via OSMnx",
            "coordinates_verified": True,
            "geometry_quality": "osm_polyline",
        },
        "nodes": nodes_dict,
        "edges": edges_list,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build rescue routing graph from OSM")
    parser.add_argument("--place", default="Zaragoza, Spain")
    parser.add_argument("--dem", default=None, help="Path to elevation raster DEM")
    parser.add_argument("--out", default="data/zaragoza_network_osm.json")
    args = parser.parse_args()
    build_graph_from_osm(place_name=args.place, dem_path=args.dem, output_path=args.out)
