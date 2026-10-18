"""
Symlink / Wrapper for AegisDynamics Cyber-Physical Bridge
Allows running directly from farlands directory:
    python scripts/simulate_cyber_physical_event.py
"""
import os
import sys

AEGIS_DIR = r"C:\Users\Koushik\Documents\shreyas-AI\AegisDynamics"
if AEGIS_DIR not in sys.path:
    sys.path.insert(0, AEGIS_DIR)

from simulate_cyber_physical_event import run_simulation
import asyncio

if __name__ == "__main__":
    asyncio.run(run_simulation())
