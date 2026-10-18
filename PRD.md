# HighWater Dashboard: Product Requirements (Member 1)

**Module:** `modules/dashboard/`
**Owner:** Member 1 (Frontend and Dashboard)
**Status:** Draft v1.0
**Hackathon context:** Mission 6, Disaster Response Drones: Predictive Search and Situational Awareness

---

## 1. Purpose

Build the complete user-facing interface of HighWater: an interactive flood-monitoring and response-prioritisation dashboard. It must run, demo and test **standalone on mock data**, then connect to the other three modules through agreed data contracts without a redesign.

The dashboard **displays** flood, risk, road and route outputs. It does not generate them.

## 2. Users and their jobs

| User | Job to be done | What the dashboard must give them |
|---|---|---|
| Incident commander | Decide where to send resources first | Ranked zones, reasons, access status at a glance |
| Field coordinator | Understand one zone in depth | Zone details, flooded %, exposed buildings, route |
| Hackathon judge | Verify the system is real, functional and honest | Visible data provenance, working interactions, no fake numbers |

## 3. Scope

### 3.1 Owned by Member 1
- App setup and layout
- Interactive Leaflet map and overlay layers
- Flood visualisation, legend, layer controls
- Statistic cards and charts
- Zone selection, filtering, search, sorting, details panel
- Risk colours and priority display
- Route and blocked-road display (when data is supplied)
- Loading, empty, error, stale and responsive states
- Mock fixtures, UI tests, frontend README

### 3.2 Not owned by Member 1
- Flood detection from imagery, or any ML model
- The risk-scoring formula
- Route computation or road-network optimisation
- Backend endpoints, databases, data collection or validation

## 4. Functional requirements

Priority: **P0** = must ship, **P1** = ship if P0 is stable, **P2** = extension.

### 4.1 Layout and header
| ID | Requirement | Pri |
|---|---|---|
| FR-01 | Compact header: logo and name, study-area label, data timestamp, source status | P0 |
| FR-02 | Visible **DEMO MODE** badge whenever `data_mode = "demo"` | P0 |
| FR-03 | Refresh button re-fetches data without duplicate in-flight requests | P0 |
| FR-04 | Four stat cards: flooded area, high-priority zones, exposed buildings, blocked roads | P0 |
| FR-05 | Every stat is derived from loaded data; any demo value is labelled | P0 |

### 4.2 Map
| ID | Requirement | Pri |
|---|---|---|
| FR-10 | Leaflet base map with zoom and pan | P0 |
| FR-11 | Independent layers: flood extent, risk zones, blocked roads, facilities, routes | P0 |
| FR-12 | Click a zone polygon to select it; selected zone is highlighted | P0 |
| FR-13 | Popup or tooltip on zones | P0 |
| FR-14 | Layer toggle panel; toggling never resets map position | P0 |
| FR-15 | Reset-extent control | P0 |
| FR-16 | Legend showing only currently enabled overlays | P0 |
| FR-17 | Selecting a zone from the list pans or zooms to it | P0 |
| FR-18 | Coordinates validated before reaching Leaflet; bad geometry is skipped and reported | P0 |
| FR-19 | Map resizes correctly with its container | P0 |

### 4.3 Zones
| ID | Requirement | Pri |
|---|---|---|
| FR-20 | Zone details panel: ID, name, risk level, score, flooded %, exposed buildings, access status, reasons, last updated | P0 |
| FR-21 | Missing field renders "Not available", never an invented value | P0 |
| FR-22 | Sortable zone list (priority or score) | P0 |
| FR-23 | Filter by risk level; search by ID or name | P0 |
| FR-24 | List and map share one `selectedZoneId` | P0 |
| FR-25 | UNKNOWN and unassessed zones are visually distinct and never shown as LOW | P0 |
| FR-26 | A zone may have attributes but no geometry (list only, no map shape) | P0 |

### 4.4 Charts
| ID | Requirement | Pri |
|---|---|---|
| FR-30 | Risk distribution chart: HIGH, MEDIUM, LOW, UNKNOWN counts | P0 |
| FR-31 | Impact chart: exposed buildings or flooded area across zones | P0 |
| FR-32 | Each chart has a title, labelled axes and a no-data state | P0 |
| FR-33 | Time-series chart only if real timestamped history exists; never fabricated from one snapshot | P2 |

### 4.5 Routing display
| ID | Requirement | Pri |
|---|---|---|
| FR-40 | Draw a supplied route polyline with distance, ETA and status | P0 |
| FR-41 | Draw blocked-road segments (red dashed) when supplied | P0 |
| FR-42 | Unreachable or missing route shows a clear message and no line | P0 |
| FR-43 | Label each route and closure as **observed / derived / simulated** when the field is supplied | P1 |

### 4.6 States
| ID | Requirement | Pri |
|---|---|---|
| FR-50 | Loading skeleton, empty state, error state with retry | P0 |
| FR-51 | Stale-data warning past a configurable freshness threshold | P1 |
| FR-52 | One failed overlay must not break the base map or other panels | P0 |
| FR-53 | Malformed payloads produce a readable error, never a blank page | P0 |

### 4.7 Optional extensions (display only)
These render fields the other modules may add. Member 1 builds the UI hooks only if the field exists in the contract.

| ID | Requirement | Pri |
|---|---|---|
| FR-60 | Provenance badge per layer: Observed, Derived, Simulated | P1 |
| FR-61 | Confidence and rank-stability range on a zone (for example "rank 3, range 2 to 5") | P2 |
| FR-62 | "Survey needed" list for low-confidence zones | P2 |
| FR-63 | What-if control (for example water-rise slider) that calls an agreed API and shows a before/after rank diff | P2 |

## 5. Non-functional requirements

| Area | Requirement |
|---|---|
| Responsiveness | Usable at desktop, tablet and mobile widths; no horizontal page overflow |
| Accessibility | Keyboard-reachable controls; risk never conveyed by colour alone; readable contrast |
| Performance | Initial render under 3 s on a mid-range laptop for roughly 500 polygons |
| Resilience | Malformed data degrades gracefully; one failing layer is isolated |
| Honesty | Demo data is always labelled; missing is never zero |
| Portability | Runs from a fresh clone with `npm install && npm run dev` |
| Offline fallback | Document the tile-provider dependency; provide a plain no-tiles fallback for venue Wi-Fi failure |

## 6. Data contracts (summary)

Full schemas live in `architecture.md`. Five inputs, all read through one adapter:

| Input | Format | Producer |
|---|---|---|
| `zones.json` | JSON | Risk engine (Member 3) |
| `flood_extent.geojson` | GeoJSON | Flood analysis (Member 2) |
| `blocked_roads.geojson` | GeoJSON | Routing (Member 4) |
| `facilities.geojson` | GeoJSON | Shared or routing |
| `routes.json` | JSON | Routing (Member 4) |

GeoJSON uses `[longitude, latitude]`. A flood extent polygon and a risk zone polygon are separate layers, linked by `zone_id` when supplied.

## 7. Success criteria (Definition of Done)

1. A teammate can clone, follow the README and run the full dashboard on mock data with no backend.
2. Every visible control has real behaviour.
3. Map and list selection stay in sync.
4. Every state in section 4.6 is demonstrable.
5. Swapping mock fixtures for real module outputs requires changing only the service and adapter.
6. Automated tests pass for adapter, filtering, selectors and selection.
7. Desktop and mobile screenshots are in the README.

## 8. Assumptions and open questions

| # | Item | Default until resolved |
|---|---|---|
| 1 | Study area for mock data (the brief example uses Bengaluru) vs the real demo AOI | Keep mock geometry deterministic and labelled DEMO; swap to real AOI at integration |
| 2 | Zone geometry source: embedded in `zones.json` or a separate polygon file | Support both: join by `zone_id` |
| 3 | Risk scale: 0 to 100 (example) vs 0.0 to 1.0 (other contracts) | Adapter normalises to 0 to 100 and records the original scale |
| 4 | Backend endpoint names | Do not guess; agree with module owners before Phase 6 |
| 5 | Freshness threshold | 60 minutes, configurable via env |
| 6 | Tile provider | OpenStreetMap standard tiles for development; confirm usage terms and keep the no-tiles fallback |

## 9. Out of scope

3D globe, authentication, heavy animation frameworks, global state libraries, real-time websockets, and any backend or ML code.
