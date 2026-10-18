"""
AegisDynamics + HighWater: Cyber-Physical Incident Response Simulator
Demonstrates autonomous cyber defense protecting disaster drone mesh & evacuation routing.

Usage:
    python simulate_cyber_physical_event.py
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from cyber_physical_bridge import CyberPhysicalBridge, GEO_NODE_REGISTRY

# ANSI styling for hackathon live demo output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
PURPLE = "\033[95m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_banner():
    print(f"""
{CYAN}{BOLD}========================================================================
   AEGIS DYNAMICS + HIGHWATER // CYBER-PHYSICAL INCIDENT RESPONSE
   Dual-Channel Graph Laplacian Cyber Defense for Disaster Drone Mesh
========================================================================{RESET}
""")

async def run_simulation():
    print_banner()

    bridge = CyberPhysicalBridge("ws://localhost:8787")
    try:
        await bridge.connect()
    except Exception as e:
        print(f"{RED}[!] Could not connect to Mesh Relay at ws://localhost:8787.{RESET}")
        print(f"{YELLOW}[*] Make sure the mesh relay is running:")
        print(f"    cd C:\\Users\\Koushik\\farlands\\modules\\dashboard")
        print(f"    node scripts/mesh-relay.mjs{RESET}")
        sys.exit(1)

    print(f"{GREEN}[+] Connected to HighWater Mesh Relay (ws://localhost:8787).{RESET}\n")

    # -------------------------------------------------------------
    # PHASE 1: Baseline Health
    # -------------------------------------------------------------
    print(f"{BOLD}[PHASE 1] Establishing Benign Mesh Baseline (Dernau AOI)...{RESET}")
    print(f"  * Active Nodes: 2 Drone Relays, 2 IoT Water Gauges, 1 SOC Gateway")
    print(f"  * Graph Laplacian Algebraic Connectivity: {GREEN}lambda_2 = 0.884{RESET} (Nominal)")
    print(f"  * Mahalanobis Residual e_G: {GREEN}0.42{RESET} (e_95 threshold = 1.00)")
    print(f"  * Evacuation Telemetry Status: {GREEN}TRUSTED (100%){RESET}")
    await bridge.publish_nodes_init()
    print(f"{GREEN}[OK] Phase 1 Broadcast complete. HighWater Map displaying 5 Healthy Nodes.{RESET}\n")
    
    await asyncio.sleep(4)

    # -------------------------------------------------------------
    # PHASE 2: Cyber Attack Infiltration
    # -------------------------------------------------------------
    print(f"{RED}{BOLD}[PHASE 2] CYBER ATTACK INJECTED -> Rogue IP 18.218.115.60 targeting DRONE-RELAY-01!{RESET}")
    print(f"  * Attack Vector: Telemetry Spoofing & High-Volume Syn Flood DoS")
    print(f"  * Spectral Anomaly Detected:")
    print(f"    - Graph Laplacian lambda_2 Drift: {RED}0.884 -> 0.118 (Spectral Collapse!){RESET}")
    print(f"    - Mahalanobis Graph Residual e_G: {RED}4.92 (Threshold = 1.00 EXCEEDED){RESET}")
    print(f"    - Spatiotemporal Cross-Momentum Risk: {RED}M_ST = 5.34 (P_ST = 89.2% CRITICAL){RESET}")
    
    attack_event = {
        "node_id": "DRONE-RELAY-01",
        "ip": "192.168.10.101",
        "status": "COMPROMISED",
        "alert_tier": "CRITICAL",
        "spectral_lambda2": 0.118,
        "mahalanobis_residual": 4.92,
        "fused_risk": 0.892,
        "telemetry_status": "UNTRUSTED",
        "soar_action": "PENDING_SOAR",
        "notes": "ATTACK IN PROGRESS: Rogue telemetry injection detected by AegisDynamics. Telemetry marked UNTRUSTED."
    }
    await bridge.dispatch_event(attack_event)
    print(f"{RED}[!] Alert broadcast to HighWater Dashboard! Drone Relay Alpha flashing RED.{RESET}\n")

    await asyncio.sleep(5)

    # -------------------------------------------------------------
    # PHASE 3: Autonomous Aegis SOAR Mitigation & Evacuation Rerouting
    # -------------------------------------------------------------
    print(f"{PURPLE}{BOLD}[PHASE 3] DISPATCHING AUTONOMOUS AEGIS SOAR PLAYBOOK...{RESET}")
    soar_rule = "iptables -A INPUT -s 18.218.115.60 -j DROP && quarantine-node --id DRONE-01 --isolate-mesh"
    print(f"  * Mitigation Rule: {PURPLE}{soar_rule}{RESET}")
    print(f"  * Disaster Action: HighWater disaster routing engine bypasses Sector 3 evacuation telemetry.")
    print(f"  * Safe routing recalculated around unverified water level sector.")

    quarantine_event = {
        "node_id": "DRONE-RELAY-01",
        "ip": "192.168.10.101",
        "status": "QUARANTINED",
        "alert_tier": "CRITICAL",
        "spectral_lambda2": 0.150,
        "mahalanobis_residual": 4.10,
        "fused_risk": 0.720,
        "telemetry_status": "QUARANTINED",
        "soar_action": soar_rule,
        "notes": "CONTAINED: Drone 01 quarantined by Aegis SOAR. HighWater routing rerouted safely around Sector 3."
    }
    await bridge.dispatch_event(quarantine_event)
    print(f"{PURPLE}[OK] SOAR containment published. HighWater Map updating node to QUARANTINED (Purple).{RESET}\n")

    await asyncio.sleep(4)

    # -------------------------------------------------------------
    # PHASE 4: Mesh Self-Healing & Telemetry Normalization
    # -------------------------------------------------------------
    print(f"{CYAN}{BOLD}[PHASE 4] MESH TOPOLOGY RECOVERY & EVACUATION SUCCESS{RESET}")
    print(f"  * Mesh rerouted via Drone Relay Beta (192.168.10.102)")
    print(f"  * Stabilized Laplacian lambda_2: {GREEN}0.812 (Restored){RESET}")
    print(f"  * Evacuation Corridors Protected: 100% of rescue paths safeguarded against corrupted telemetry.")
    print(f"{GREEN}{BOLD}========================================================================{RESET}")
    print(f"{GREEN}{BOLD}   CYBER-PHYSICAL INCIDENT NEUTRALIZED SUCCESSFULLY // 100% SECURE{RESET}")
    print(f"{GREEN}{BOLD}========================================================================{RESET}\n")

    await bridge.close()

if __name__ == "__main__":
    asyncio.run(run_simulation())
