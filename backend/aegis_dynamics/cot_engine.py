"""
AegisMesh - Cursor-on-Target (CoT) Tactical Datalink Engine
Converts AegisDynamics spatiotemporal cyber threat telemetry and HighWater
disaster rescue coordinates into MIL-STD Cursor-on-Target (CoT 2.0) XML streams
compatible with ATAK (Android Tactical Assault Kit), WinTAK, and TAK Servers.
"""

import socket
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

# Standard ATAK Multicast & UDP configuration
DEFAULT_ATAK_MULTICAST_IP = "239.2.3.1"
DEFAULT_ATAK_PORT = 4242

# CoT MIL-STD-2525 Symbology Mapping
COT_TYPE_MAPPING = {
    # Friendly Air Drone
    "drone_friendly": "a-f-A-M-F-Q",
    # Degraded / Suspect Air Drone
    "drone_suspect": "a-u-A-M-F-Q",
    # Compromised / Rogue Drone (Hostile)
    "drone_hostile": "a-h-A-M-F-Q",
    
    # Friendly Rescue Vessel (Surface)
    "boat_friendly": "a-f-G-E-V-U",
    # Route Recalculating Rescue Boat
    "boat_alert": "a-f-G-E-V-U",
    
    # Friendly IoT Water Depth Sensor / Infrastructure
    "sensor_trusted": "a-f-G-I-U-T",
    # Poisoned / Tampered Sensor (Suspect/Hostile)
    "sensor_compromised": "a-h-G-I-U-T",
    
    # Command Center / Gateway
    "gateway": "a-f-G-U-C",
    
    # Malicious External Attacker (Hostile Ground)
    "attacker": "a-h-G"
}

# Default AOI Nodes (Ahr Valley / Kerala Flood Zone)
TACTICAL_NODES = [
    {
        "id": "AEGIS-UAV-01",
        "callsign": "Drone Relay Alpha",
        "type": "drone",
        "ip": "192.168.10.101",
        "lat": 50.5365,
        "lon": 7.0410,
        "hae": 125.0,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "fused_risk": 0.04,
        "lambda2": 0.88,
        "trust_score": 1.0,
        "battery": "86%",
        "notes": "Primary UAV mesh repeater for evacuation axis"
    },
    {
        "id": "AEGIS-UAV-02",
        "callsign": "Drone Relay Beta",
        "type": "drone",
        "ip": "192.168.10.102",
        "lat": 50.5392,
        "lon": 7.0485,
        "hae": 140.0,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "fused_risk": 0.05,
        "lambda2": 0.85,
        "trust_score": 0.98,
        "battery": "79%",
        "notes": "Secondary high-altitude LoRa cross-link"
    },
    {
        "id": "AEGIS-BOAT-01",
        "callsign": "Rescue Craft Charlie-1",
        "type": "boat",
        "ip": "192.168.10.120",
        "lat": 50.5335,
        "lon": 7.0390,
        "hae": 45.0,
        "status": "MISSION ACTIVE",
        "alert_tier": "NOMINAL",
        "fused_risk": 0.02,
        "lambda2": 0.92,
        "trust_score": 1.0,
        "battery": "94%",
        "notes": "Rescue boat navigating sector 1 evacuation route"
    },
    {
        "id": "AEGIS-SENSOR-01",
        "callsign": "IoT Depth Gauge Alpha",
        "type": "sensor",
        "ip": "192.168.10.25",
        "lat": 50.5320,
        "lon": 7.0375,
        "hae": 42.0,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "fused_risk": 0.03,
        "lambda2": 0.91,
        "trust_score": 1.0,
        "depth_m": 0.45,
        "notes": "Ultrasonic depth sensor at river confluence"
    },
    {
        "id": "AEGIS-SENSOR-02",
        "callsign": "IoT Depth Gauge Beta",
        "type": "sensor",
        "ip": "192.168.10.50",
        "lat": 50.5435,
        "lon": 7.0520,
        "hae": 44.0,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "fused_risk": 0.03,
        "lambda2": 0.87,
        "trust_score": 1.0,
        "depth_m": 1.85,
        "notes": "Dike crest water pressure & depth monitor"
    },
    {
        "id": "AEGIS-EOC-01",
        "callsign": "EOC Tactical Command",
        "type": "gateway",
        "ip": "192.168.10.1",
        "lat": 50.5290,
        "lon": 7.0340,
        "hae": 60.0,
        "status": "OPERATIONAL",
        "alert_tier": "NOMINAL",
        "fused_risk": 0.01,
        "lambda2": 0.95,
        "trust_score": 1.0,
        "notes": "Central operations vehicle & satellite uplink"
    }
]

class CotEngine:
    """Generates Cursor-on-Target (CoT) 2.0 XML messages for ATAK/WinTAK integration."""

    def __init__(self, nodes: Optional[List[Dict[str, Any]]] = None):
        self.nodes = [dict(n) for n in (nodes if nodes else TACTICAL_NODES)]

    def update_node_state(self, node_id_or_ip: str, telemetry: Dict[str, Any]):
        """Updates internal node state based on AegisDynamics window telemetry."""
        for n in self.nodes:
            if n["id"] == node_id_or_ip or n["ip"] == node_id_or_ip:
                n.update(telemetry)
                break

    def determine_cot_type(self, node: Dict[str, Any]) -> str:
        """Determines the appropriate 2525 CoT type based on node role and threat tier."""
        tier = node.get("alert_tier", "NOMINAL").upper()
        ntype = node.get("type", "sensor").lower()

        if ntype == "drone":
            if tier == "CRITICAL":
                return COT_TYPE_MAPPING["drone_hostile"]
            elif tier == "WATCH":
                return COT_TYPE_MAPPING["drone_suspect"]
            return COT_TYPE_MAPPING["drone_friendly"]

        elif ntype == "boat":
            return COT_TYPE_MAPPING["boat_friendly"]

        elif ntype == "sensor":
            if tier == "CRITICAL" or node.get("trust_score", 1.0) < 0.2:
                return COT_TYPE_MAPPING["sensor_compromised"]
            return COT_TYPE_MAPPING["sensor_trusted"]

        elif ntype == "gateway":
            return COT_TYPE_MAPPING["gateway"]

        return "a-f-G"

    def build_cot_event_xml(self, node: Dict[str, Any], stale_minutes: int = 5) -> str:
        """Builds a single Cursor-on-Target (CoT) XML event string."""
        now = datetime.now(timezone.utc)
        time_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_time = (now + timedelta(minutes=stale_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cot_type = self.determine_cot_type(node)
        uid = node.get("id", "AEGIS-NODE")
        callsign = node.get("callsign", uid)
        lat = node.get("lat", 50.5365)
        lon = node.get("lon", 7.0410)
        hae = node.get("hae", 50.0)

        risk_pct = round(node.get("fused_risk", 0.0) * 100, 1)
        tier = node.get("alert_tier", "NOMINAL")
        trust = round(node.get("trust_score", 1.0) * 100, 1)

        xml = (
            f'<event version="2.0" uid="{uid}" type="{cot_type}" '
            f'time="{time_str}" start="{time_str}" stale="{stale_time}" how="m-g">\n'
            f'  <point lat="{lat:.6f}" lon="{lon:.6f}" hae="{hae:.1f}" ce="10.0" le="5.0"/>\n'
            f'  <detail>\n'
            f'    <contact callsign="{callsign}" endpoint="{node.get("ip", "0.0.0.0")}"/>\n'
            f'    <remarks>{node.get("notes", "")} | Risk: {risk_pct}% [{tier}] | Trust: {trust}%</remarks>\n'
            f'    <status readiness="true"/>\n'
            f'    <aegisTelemetry risk="{node.get("fused_risk", 0.0):.4f}" tier="{tier}" '
            f'lambda2="{node.get("lambda2", 1.0):.4f}" trust="{node.get("trust_score", 1.0):.2f}"/>\n'
            f'    <emergencyMesh nodeType="{node.get("type", "generic")}" battery="{node.get("battery", "100%")}"/>\n'
            f'  </detail>\n'
            f'</event>'
        )
        return xml

    def generate_cot_bundle(self) -> str:
        """Generates an XML bundle containing CoT events for all active tactical nodes."""
        events = [self.build_cot_event_xml(n) for n in self.nodes]
        bundle = (
            '<?xml version="1.0" standalone="yes"?>\n'
            '<events version="2.0">\n'
            + "\n".join(events) +
            '\n</events>'
        )
        return bundle

    def generate_geojson(self) -> Dict[str, Any]:
        """Generates GeoJSON FeatureCollection formatted for ATAK Data Package import."""
        features = []
        for n in self.nodes:
            feat = {
                "type": "Feature",
                "id": n["id"],
                "geometry": {
                    "type": "Point",
                    "coordinates": [n["lon"], n["lat"], n.get("hae", 50.0)]
                },
                "properties": {
                    "callsign": n["callsign"],
                    "node_type": n["type"],
                    "ip": n["ip"],
                    "status": n["status"],
                    "alert_tier": n["alert_tier"],
                    "risk_percent": round(n.get("fused_risk", 0.0) * 100, 1),
                    "trust_percent": round(n.get("trust_score", 1.0) * 100, 1),
                    "cot_type": self.determine_cot_type(n),
                    "notes": n["notes"]
                }
            }
            features.append(feat)

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "source": "AegisMesh Autonomous Tactical Telemetry",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "aoi": "Disaster Evacuation Zone (Ahr / Kerala)"
            }
        }

    def broadcast_cot_udp(self, target_ip: str = "127.0.0.1", port: int = DEFAULT_ATAK_PORT) -> Dict[str, Any]:
        """
        Broadcasts CoT XML events over UDP socket directly to an ATAK client or TAK Server.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if target_ip.startswith("239.") or target_ip.startswith("224."):
            # Enable multicast TTL
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        sent_count = 0
        for n in self.nodes:
            cot_xml = self.build_cot_event_xml(n)
            sock.sendto(cot_xml.encode("utf-8"), (target_ip, port))
            sent_count += 1

        sock.close()
        return {
            "status": "SUCCESS",
            "protocol": "UDP/CoT",
            "target": f"{target_ip}:{port}",
            "events_transmitted": sent_count,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# Global Singleton Instance
COT_ENGINE = CotEngine()
