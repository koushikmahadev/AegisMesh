"""
AegisDynamics <-> HighWater Cyber-Physical Integration Bridge
Bridges Tier 2 Graph Laplacian spectral anomaly detection & SOAR mitigation
with HighWater's aerial drone relay mesh and disaster evacuation command.
"""

import asyncio
import json
import logging
import sys
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

try:
    import websockets
except ImportError:
    print("[!] 'websockets' package required. Run: pip install websockets")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CyberPhysicalBridge")

# Disaster operations geospatial node registry (Ahr Valley / Dernau AOI)
GEO_NODE_REGISTRY = [
    {
        "id": "DRONE-RELAY-01",
        "name": "Drone Relay Alpha",
        "type": "drone",
        "ip": "192.168.10.101",
        "lat": 50.5365,
        "lng": 7.0410,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "spectral_lambda2": 0.88,
        "mahalanobis_residual": 0.42,
        "fused_risk": 0.03,
        "soar_action": "NONE",
        "telemetry_status": "TRUSTED",
        "notes": "Aerial field relay covering Ahr valley central evacuation axis"
    },
    {
        "id": "DRONE-RELAY-02",
        "name": "Drone Relay Beta",
        "type": "drone",
        "ip": "192.168.10.102",
        "lat": 50.5392,
        "lng": 7.0485,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "spectral_lambda2": 0.85,
        "mahalanobis_residual": 0.51,
        "fused_risk": 0.04,
        "soar_action": "NONE",
        "telemetry_status": "TRUSTED",
        "notes": "High-altitude mesh repeater linked to sector 2 command post"
    },
    {
        "id": "SENSOR-GATEWAY-01",
        "name": "IoT Water Gauge Alpha",
        "type": "sensor",
        "ip": "192.168.10.25",
        "lat": 50.5320,
        "lng": 7.0375,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "spectral_lambda2": 0.91,
        "mahalanobis_residual": 0.38,
        "fused_risk": 0.02,
        "soar_action": "NONE",
        "telemetry_status": "TRUSTED",
        "notes": "Submersible ultrasonic river depth gauge & telemetry uplink"
    },
    {
        "id": "SENSOR-GATEWAY-02",
        "name": "IoT Water Gauge Beta",
        "type": "sensor",
        "ip": "192.168.10.50",
        "lat": 50.5435,
        "lng": 7.0520,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "spectral_lambda2": 0.87,
        "mahalanobis_residual": 0.45,
        "fused_risk": 0.03,
        "soar_action": "NONE",
        "telemetry_status": "TRUSTED",
        "notes": "Dike crest water pressure monitor & siren activation trigger"
    },
    {
        "id": "SOC-GATEWAY-01",
        "name": "Aegis SOC Command Uplink",
        "type": "gateway",
        "ip": "192.168.10.1",
        "lat": 50.5290,
        "lng": 7.0340,
        "status": "HEALTHY",
        "alert_tier": "NOMINAL",
        "spectral_lambda2": 0.94,
        "mahalanobis_residual": 0.29,
        "fused_risk": 0.01,
        "soar_action": "NONE",
        "telemetry_status": "TRUSTED",
        "notes": "Central dispatch operations vehicle & secure satellite uplink"
    }
]

class CyberPhysicalBridge:
    def __init__(self, relay_url: str = "ws://localhost:8787"):
        self.relay_url = relay_url
        self.nodes = [dict(n) for n in GEO_NODE_REGISTRY]
        self.ws = None

    async def connect(self):
        """Connect to HighWater local mesh relay."""
        logger.info(f"Connecting to HighWater Mesh Relay at {self.relay_url}...")
        self.ws = await websockets.connect(self.relay_url)
        logger.info("Connected to Mesh Relay.")
        # Broadcast initial cyber nodes registry
        await self.publish_nodes_init()

    async def publish_nodes_init(self):
        """Sends full initial cyber physical node topology."""
        if not self.ws:
            return
        payload = {
            "type": "cyber_nodes_init",
            "nodes": self.nodes,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.ws.send(json.dumps(payload))
        logger.info(f"Published cyber_nodes_init ({len(self.nodes)} nodes).")

    async def dispatch_event(self, event_data: Dict[str, Any]):
        """Dispatches an anomaly or mitigation update for a specific node."""
        if not self.ws:
            return
            
        target_ip = event_data.get("ip")
        node_id = event_data.get("node_id")

        for n in self.nodes:
            if (node_id and n["id"] == node_id) or (target_ip and n["ip"] == target_ip):
                n.update(event_data)
                break

        payload = {
            "type": "cyber_mesh_update",
            "event": event_data,
            "nodes": self.nodes,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.ws.send(json.dumps(payload))
        logger.info(f"Dispatched cyber_mesh_update: Node={node_id or target_ip} Status={event_data.get('status')} Tier={event_data.get('alert_tier')}")

    async def close(self):
        if self.ws:
            await self.ws.close()
            logger.info("Bridge connection closed.")
