"""Forwarding package to ingest."""

import sys
from pathlib import Path

# ensure parent of modules is in path
root = Path(__file__).resolve().parent.parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from ingest.roads import load_roads
from ingest.satellite import load_satellite_mask
from ingest.edge_state import populate_edge_state
from ingest.snapping import snap_sites

__all__ = ["load_roads", "load_satellite_mask", "populate_edge_state", "snap_sites"]
