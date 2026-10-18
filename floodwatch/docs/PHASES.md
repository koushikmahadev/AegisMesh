# Delivery Phases

Each phase ends with something demonstrable.

## Phase 0 – Setup & Sanity (≈ 2 h)
- Create repo, venv, install `requirements.txt`.
- Place the checkpoint in `models/segformer/`.
- Place data under `data/raw/PRE-event` and `data/raw/POST-event`.
- Run `python -m src.flood_inference --tile 0_39_62` and confirm numbers look sane.
- **Exit:** CLI prints Before %, After %, Net %, latency.

## Phase 1 – Inference Core (≈ 3 h)
- Harden `flood_inference.py`: model singleton, fp16, resize/upsample, class-index config.
- Add timing and error handling for missing tiles.
- Spot-check 10 tiles against known ground truth.
- **Exit:** Warm latency < 0.5 s; deterministic results.

## Phase 2 – API Layer (≈ 3 h)
- FastAPI app with `/api/analyze/{tile_id}`, `/api/tiles`, `/api/health`.
- In-memory LRU cache keyed by tile ID.
- Mask → PNG (RGBA) endpoint.
- **Exit:** `curl` returns JSON + working mask URLs.

## Phase 3 – Map UI (≈ 5 h)
- Leaflet map (or tile-grid canvas) with clickable tiles.
- Result panel: Before %, After %, Net %, latency badge.
- Overlay toggles + before/after swipe slider.
- Loading and error states.
- **Exit:** Click a tile → full result in < 1 s.

## Phase 4 – Polish & Demo Hardening (≈ 3 h)
- Pre-warm cache for demo tiles.
- Stress test: 50 consecutive clicks, watch VRAM.
- Offline test: disable Wi-Fi and run through the whole demo.
- Write the 2-minute demo script.
- **Exit:** Rehearsed demo with zero failures.

## Phase 5 – Stretch (only if time)
- Bounding-box region analysis (stitch multiple tiles).
- Building/road overlay with flooded-asset counts.
- Export report (PDF/CSV) of selected zones.
- Side-by-side comparison with a cloud API for the latency story.
