# PRD: FloodWatch – Instant Offline Flood Intrusion Analysis

## 1. Problem
Assessing flood impact from satellite imagery is slow and often depends on cloud APIs (with high latency, per-call cost, and network dependency). Responders and demo judges need an answer the moment they click a location.

## 2. Product Vision
An interactive map where a user clicks a tile (or draws a box) and within ~1 second sees how much new water appeared between pre-event and post-event imagery, computed entirely by a local SegFormer model on the user's GPU.

## 3. Target Users
- **Primary:** Hackathon judges / evaluators interacting live with the demo.
- **Secondary:** Disaster-response analysts needing quick, offline triage.

## 4. Goals & Non-Goals
**Goals**
- G1: Click-to-result latency under 1 s per tile on an RTX 3050 (target under 1 s inference + I/O).
- G2: Zero network dependency and zero per-query cost during the demo.
- G3: Clear visual output: before/after imagery, water masks, and net flood intrusion %.

**Non-Goals (v1)**
- Training or fine-tuning UI.
- Live satellite data ingestion.
- Multi-user hosting or authentication.
- Building-level damage classification (possible v2).

## 5. Core User Stories
| ID | Story | Acceptance Criteria |
|----|-------|---------------------|
| U1 | As a user, I click a tile on the map and see flood intrusion. | Result card shows Before %, After %, Net (+/-) % within 1 s. |
| U2 | As a user, I see where the water is. | Water mask overlay toggles for Before and After. |
| U3 | As a user, I compare before and after. | Side-by-side or swipe slider of both images. |
| U4 | As a presenter, I click 50 zones in a row without failure. | No crash, no memory growth, no network calls. |
| U5 | As a user, I get a sensible message for tiles with missing imagery. | Friendly error, UI keeps working. |

## 6. Functional Requirements
- FR1: Resolve a tile ID (e.g. `0_39_62`) to its pre/post image paths.
- FR2: Run SegFormer on both images and compute water fraction.
- FR3: Compute `net_intrusion = after_pct - before_pct`.
- FR4: Return masks as PNG overlays for the map.
- FR5: Cache results per tile so repeat clicks are instant.
- FR6: Expose everything over a local HTTP API consumed by the web map.

## 7. Non-Functional Requirements
- **Performance:** p95 per-tile latency < 1 s (warm model).
- **Offline:** No outbound network calls at runtime.
- **Reliability:** Model loaded once at startup; graceful errors.
- **Portability:** Runs on a laptop with an RTX 3050 (4 GB VRAM) – use fp16 and batch of 2.

## 8. Success Metrics
- Median latency < 0.5 s; zero failures across 50 consecutive clicks.
- Net-intrusion values match offline evaluation on a spot-check of 10 tiles.
- Judges can operate the demo without instructions.

## 9. Assumptions (verify early)
- Dataset follows a SpaceNet-8-style layout: `data/raw/PRE-event/*_{tile_id}.tif` and `data/raw/POST-event/*_{tile_id}.tif`.
- A trained SegFormer checkpoint exists locally with a known "water/flood" class index.
- Imagery is RGB GeoTIFF.

## 10. Risks
| Risk | Mitigation |
|------|-----------|
| Class index for water is wrong | Config constant + a 1-minute sanity script on a known flooded tile. |
| Pre/post images misaligned | Use tiles from the same grid; show warning if shapes differ. |
| 4 GB VRAM OOM | fp16, resize to 512, `torch.no_grad()`, batch of 2 max. |
| Negative net values from noise | Display raw value; clamp only in the headline label. |
| Demo-day surprises | Pre-warm cache for the top 20 demo tiles. |

## 11. Open Questions
1. Exact model checkpoint path and training resolution?
2. Is a map basemap needed offline (pre-downloaded tiles), or is a simple tile-grid canvas enough?
3. Do we show building/road impact in v1?
