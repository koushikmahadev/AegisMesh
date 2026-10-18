"""Coordinate verification aid exporting node locations and OSM inspection links."""

import csv
import json
from pathlib import Path


def generate_coordinate_check_csv(
    network_path: str | Path = "data/zaragoza_network.json",
    output_path: str | Path = "data/coordinate_check.csv",
) -> Path:
    """Generate coordinate verification CSV with OSM verification links for all graph nodes."""
    network_file = Path(network_path)
    output_file = Path(output_path)

    with open(network_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes = data.get("nodes", {})
    fieldnames = ["id", "lat", "lon", "elevation_m", "osm_link", "verified", "notes"]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for node_id, node_data in nodes.items():
            lat = node_data["lat"]
            lon = node_data["lon"]
            elev = node_data.get("elev_m", node_data.get("elevation_m", 0.0))
            osm_link = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}"
            writer.writerow(
                {
                    "id": node_id,
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": elev,
                    "osm_link": osm_link,
                    "verified": False,
                    "notes": "",
                }
            )

    return output_file


if __name__ == "__main__":
    out = generate_coordinate_check_csv()
    print(f"Exported coordinate verification aid to {out}")
