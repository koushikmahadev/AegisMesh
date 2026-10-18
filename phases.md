# HighWater Dashboard: Phases (Member 1)

Time estimates are planning ranges for a hackathon, not guarantees. If time runs short, protect Phases 1 to 4. They deliver the minimum demonstrable dashboard.

## Overview

| Phase | Name | Est. | Output |
|---|---|---|---|
| 1 | Setup | 1 to 2 h | Empty app that runs |
| 2 | Layout | 2 to 3 h | Complete static interface on mock data |
| 3 | Interactive map | 3 to 5 h | Working multi-layer map |
| 4 | Wiring | 2 to 3 h | Map, list, details, stats and charts all connected |
| 5 | Test and polish | 2 to 3 h | States, responsive, accessibility, tests, README |
| 6 | Integration | 1 to 2 h | Real module outputs displayed |
| 7 | Optional extensions | as time allows | Provenance, confidence, what-if display |

**Early milestone (about hour 6):** the browser shows a real Leaflet map with the mock flood polygon, a clickable zone list, and a details panel that updates on selection. Integration is not left to the end; Phase 6 can start in part as soon as any module publishes a sample file.

---

## Phase 1: Setup (1 to 2 h)

**Work**
- Create React + Vite app in `modules/dashboard/`
- Install Leaflet, React Leaflet, Tailwind, Recharts, lucide-react, Vitest, React Testing Library
- Configure Tailwind and global design tokens (`config/theme.js`)
- Create the folder structure (only the files you need now)
- Add `.env.example`

**Exit criteria**
- `npm run dev` serves a page without errors
- `npm test` runs (even with zero tests)
- Folder structure matches `architecture.md`

**Fallback:** if Tailwind setup stalls for over 30 minutes, use plain CSS modules and keep going.

---

## Phase 2: Layout (2 to 3 h)

**Work**
- Header with DEMO MODE badge, study area, timestamp, refresh
- Four stat cards, wired to placeholder data via the adapter
- Map container, side panel, zone-list area, chart areas
- Desktop layout and breakpoints
- Create all five mock fixtures with deterministic geometry

**Exit criteria**
- A complete static page on mock fixtures
- Fixtures validate against the contracts in `architecture.md`
- Layout does not break at 360, 768 and 1280 px

**Fallback:** start with desktop only; add the tablet breakpoint in Phase 5.

---

## Phase 3: Interactive map (3 to 5 h)

**Work**
- Base map with zoom and pan
- Flood layer from GeoJSON
- Risk layer with risk-level colours and popups
- Zone click selects
- Layer toggle panel, legend, reset-extent
- Blocked-road, facility and route layers
- Coordinate validation and `toLatLng` helper

**Exit criteria**
- Each of the five layers toggles independently
- Toggling does not move the map
- Bad geometry is skipped with a visible count, not a crash
- Legend shows only enabled overlays

**Fallback:** build flood, risk and facilities first; routes and roads are P0 but can wait until Phase 4 if needed.

---

## Phase 4: Wiring (2 to 3 h)

**Work**
- Single `selectedZoneId` shared by map, list and details
- Zone list with search, risk filter and sort
- Zone details panel with "Not available" handling
- Selectors for stats and charts
- Risk distribution chart and impact chart
- List selection flies the map to the zone

**Exit criteria**
- Clicking a polygon highlights the row and fills the panel
- Clicking a row highlights the polygon and pans to it
- Filters change list and charts consistently
- Zones without geometry still show in the list

**Fallback:** if charts consume too much time, ship the risk distribution chart first and add the impact chart in Phase 5.

---

## Phase 5: Test and polish (2 to 3 h)

**Work**
- Loading, empty, error and stale states
- Malformed-data tests (invalid GeoJSON, missing fields, unknown risk, empty arrays)
- Mobile drawer or stacked layout
- Keyboard focus, contrast check, text alternatives for risk colours
- Vitest suites listed in `tasks.md`
- README with setup, contracts and screenshots

**Exit criteria**
- Every row in the test table of `tasks.md` passes
- No console errors on the happy path
- A teammate can clone and run it from the README alone
- Offline tile fallback documented and tested by disabling the network

---

## Phase 6: Integration (1 to 2 h)

**Work**
- Confirm schemas and endpoints with each module owner
- Implement the real fetch behind `getDashboardData()`; flip `VITE_DATA_SOURCE`
- Map real field names in the adapter only
- Verify coordinate order and CRS (expect EPSG:4326)
- Test missing fields, failed requests and empty responses

**Exit criteria**
- Real flood, risk and route outputs display with no change to map or list components
- DEMO MODE badge disappears only when the payload says `data_mode` is not demo

**Fallback:** if a module is late, keep that layer on its mock fixture and label it as demo while the others run on real data.

---

## Phase 7: Optional extensions (display only)

Build only if Phases 1 to 6 are stable, and only if the producing module supplies the fields.

| Extension | Needs from other modules | UI work |
|---|---|---|
| Provenance badges | `provenance` per layer and route | Badge in legend, popup and details |
| Confidence and rank range | `confidence`, `rank_p10`, `rank_p90` | Show in details and as a list indicator |
| Survey-needed queue | `needs_survey` | Separate list section |
| What-if control | An agreed scenario endpoint | Slider, loading state, before and after rank diff |

---

## Cut rules

| Situation | Decision |
|---|---|
| Behind schedule at end of Phase 3 | Drop the impact chart and tablet polish; keep selection sync |
| Map library issue that takes over 1 h | Stop and fix before anything else; the map is the core |
| A module delivers late | Continue on its fixture, label it demo |
| Optional extension competes with testing | Testing wins |
