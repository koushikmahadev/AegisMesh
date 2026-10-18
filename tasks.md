# HighWater Dashboard: Tasks (Member 1)

Check items off as they meet their acceptance criteria (AC). Requirement IDs refer to `PRD.md`. Phases refer to `phases.md`.

Priority: **P0** must ship, **P1** if P0 is stable, **P2** extension.

---

## Phase 1: Setup

- [x] **T1.1 (P0)** Create React + Vite app in `modules/dashboard/`
  AC: `npm run dev` serves a page with no console errors.
- [x] **T1.2 (P0)** Install Leaflet, React Leaflet, Tailwind, Recharts, lucide-react, Vitest, React Testing Library
  AC: all packages in `package.json`; `npm test` runs.
- [x] **T1.3 (P0)** Create `config/theme.js` with colour, risk and spacing tokens from `design.md`
  AC: no hex codes outside `theme.js` and `index.css`.
- [x] **T1.4 (P0)** Create folder structure and `.env.example`
  AC: matches `architecture.md` sections 3 and 8.

## Phase 2: Layout and fixtures

- [x] **T2.1 (P0)** Create five mock fixtures with deterministic geometry (FR-02)
  AC: closed polygon rings; `[lng, lat]` order; `data_mode: "demo"`; at least one HIGH, MEDIUM, LOW and UNKNOWN zone; at least one zone with no geometry; at least one zone with a missing numeric field.
- [x] **T2.2 (P0)** Build `Header` with DEMO MODE badge, timestamp, refresh (FR-01, FR-02)
  AC: badge visible when `data_mode = "demo"`.
- [x] **T2.3 (P0)** Build `StatCard` x4 (FR-04, FR-05)
  AC: values derived from fixtures; demo values captioned "Illustrative".
- [x] **T2.4 (P0)** Build `DashboardLayout` with map area, side panel, list area, chart area
  AC: no layout break at 360, 768, 1280 px.

## Phase 3: Interactive map

- [x] **T3.1 (P0)** `FloodMap` base map with zoom and pan (FR-10, FR-19)
  AC: map renders and resizes with its container.
- [x] **T3.2 (P0)** `toLatLng()` helper and coordinate validator
  AC: unit tests cover swapped coords, out-of-range values, unclosed rings.
- [x] **T3.3 (P0)** `FloodLayer` (FR-11)
  AC: flood polygons render in the flood style.
- [x] **T3.4 (P0)** `RiskLayer` with risk colours, popup and click-to-select (FR-12, FR-13)
  AC: click selects; selected zone shows thick outline; UNKNOWN is visibly distinct.
- [x] **T3.5 (P0)** `RoadLayer`, `FacilityLayer`, `RouteLayer` (FR-11, FR-40, FR-41)
  AC: blocked roads dashed; route solid; route with no geometry draws nothing.
- [x] **T3.6 (P0)** `MapControls` layer toggles and reset-extent (FR-14, FR-15)
  AC: each layer toggles independently; map position unchanged by toggling; reset returns to default extent.
- [x] **T3.7 (P0)** `MapLegend` (FR-16)
  AC: lists only enabled overlays, each with swatch and text.
- [x] **T3.8 (P0)** Per-layer error boundaries (FR-52)
  AC: a deliberately broken layer shows an inline warning and the rest of the map still works.

## Phase 4: Wiring

- [x] **T4.1 (P0)** `dataAdapter.js` with all rules from `architecture.md` section 5.7
  AC: unit tests for unknown risk to UNKNOWN, non-finite to null, scale conversion, bad coordinates dropped and counted, bad payload throws.
- [x] **T4.2 (P0)** `useDashboardData` hook and `dashboardApi.js` (FR-03)
  AC: loads fixtures; refresh does not fire duplicate in-flight requests.
- [x] **T4.3 (P0)** Shared `selectedZoneId` state (FR-24)
  AC: map click highlights the row; row click highlights the polygon.
- [x] **T4.4 (P0)** `ZoneList` with sort, risk filter, search (FR-22, FR-23)
  AC: each control changes the list correctly; combined filters work together.
- [x] **T4.5 (P0)** `ZoneDetails` (FR-20, FR-21)
  AC: shows actual selected-zone data; missing fields show "Not available"; reasons render.
- [x] **T4.6 (P0)** Zones without geometry stay in the list (FR-26)
  AC: row shows "No map shape"; selecting it does not crash the map.
- [x] **T4.7 (P0)** List selection flies the map to the zone (FR-17)
  AC: map pans or zooms to the zone bounds.
- [x] **T4.8 (P0)** `dashboardSelectors.js` for stats and chart data (FR-05, FR-30, FR-31)
  AC: stats recompute from data; documented rule on whether filters affect stats.
- [x] **T4.9 (P0)** `RiskDistributionChart` and `ImpactChart` (FR-30 to FR-32)
  AC: titles, labelled axes, tooltips, no-data state.

## Phase 5: Test and polish

- [x] **T5.1 (P0)** `LoadingState`, `EmptyState`, `ErrorState` (FR-50)
  AC: each demonstrable by editing the fixture or blocking the request; error has a working retry.
- [x] **T5.2 (P1)** Stale-data banner (FR-51)
  AC: appears when `generated_at` exceeds `VITE_STALE_MINUTES`.
- [x] **T5.3 (P0)** Malformed-data handling (FR-53)
  AC: invalid GeoJSON produces a readable error; no blank page.
- [x] **T5.4 (P0)** Mobile layout and drawer
  AC: no horizontal overflow at 360 px; drawer opens and closes; map resizes correctly.
- [x] **T5.5 (P0)** Accessibility pass
  AC: keyboard operation of toggles, list and filters; visible focus; risk never colour-only; AA contrast spot-check.
- [x] **T5.6 (P0)** Offline tile fallback
  AC: with the network disabled, overlays still render over a neutral background and a notice is shown.
- [x] **T5.7 (P0)** README
  AC: setup, scripts, contracts, manual map checklist, screenshots (desktop and mobile), changelog.

## Phase 6: Integration

- [ ] **T6.1 (P0)** Confirm schemas and endpoints with each module owner
  AC: written agreement in the README; no guessed endpoint names.
- [x] **T6.2 (P0)** Implement the real fetch behind `getDashboardData()`; add `VITE_DATA_SOURCE`
  AC: switching between `mock` and `api` requires no component changes.
- [ ] **T6.3 (P0)** Map real field names in the adapter only
  AC: git diff touches `dataAdapter.js` and `dashboardApi.js`, not layer components.
- [ ] **T6.4 (P0)** Verify coordinate order and CRS (EPSG:4326)
  AC: real flood polygons overlay the correct location on the base map.
- [ ] **T6.5 (P0)** Real-data failure tests
  AC: failed request, empty response and missing field each behave per `design.md` state rules.
- [ ] **T6.6 (P0)** DEMO MODE badge driven by payload
  AC: badge hidden only when `data_mode` is not demo.

## Phase 7: Optional extensions (display only)

- [ ] **T7.1 (P1)** Provenance badges on layers, routes and details (FR-43, FR-60)
  AC: Observed, Derived and Simulated render distinctly; absent field shows no badge.
- [ ] **T7.2 (P2)** Confidence and rank-range display (FR-61)
  AC: shown only when supplied; never estimated by the frontend.
- [ ] **T7.3 (P2)** Survey-needed list (FR-62)
  AC: zones with `needs_survey` appear in a separate section.
- [ ] **T7.4 (P2)** What-if control with before/after rank diff (FR-63)
  AC: calls the agreed endpoint; loading and error states handled; no frontend-side simulation.
- [x] **T7.5 (P2)** Local network Mesh Sync for field survey updates
  AC: WebSocket relay on port 8787; `useMeshSync` hook with backoff and offline queue; Header badge with peer count; ZoneDetails survey section and keyboard-accessible form; zero impact on risk scores; unit tests passing.

---

## Test matrix

| # | Scenario | Expected behaviour | Type | Status |
|---|---|---|---|---|
| 1 | Normal dataset | Map, cards, charts, list render | Manual | [x] |
| 2 | Click polygon | Correct zone details appear; row highlighted | Component + manual | [headless verified, manual pending] |
| 3 | Click list row | Matching polygon selected; map pans | Component + manual | [headless verified, manual pending] |
| 4 | Filter by HIGH | Only HIGH zones in list; charts follow documented rule | Unit | [x] |
| 5 | Search by ID or name | List narrows correctly | Unit | [x] |
| 6 | Sort by score | Order correct; null scores sort last | Unit | [x] |
| 7 | No zones returned | Empty state; no fabricated risk | Component | [x] |
| 8 | Missing risk score | "Not available" | Component | [x] |
| 9 | Unknown risk category | Displayed as UNKNOWN, not LOW | Unit | [x] |
| 10 | Zone without geometry | In list; not on map; no crash | Component | [x] |
| 11 | Invalid flood GeoJSON | Readable error; app does not crash | Manual | [headless verified, manual pending] |
| 12 | Swapped lat/lon | Warning; feature dropped or flagged | Unit | [x] |
| 13 | Unclosed polygon ring | Feature skipped and counted | Unit | [x] |
| 14 | Route unavailable | No line; clear message | Component | [x] |
| 15 | All overlays off | Base map still usable | Manual | [headless verified, manual pending] |
| 16 | Narrow mobile viewport | No horizontal overflow | Manual | [headless verified, manual pending] |
| 17 | API request fails | Error visible; retry works | Component | [x] |
| 18 | Refresh clicked repeatedly | One in-flight request only | Unit | [x] |
| 19 | Tiles unreachable | Fallback notice; overlays still render | Manual | [headless verified, manual pending] |
| 20 | Stale `generated_at` | Stale banner shown | Unit | [x] |
| 21 | Mesh survey sync | Cross-tab / cross-device updates sync via local relay; offline queue flushes on connect | Component + unit | [x] |

## Final submission checklist

- [ ] Standalone React app runs from a fresh clone
- [ ] Interactive Leaflet map with five independent layers
- [ ] Cards, charts, filters, list and details all functional
- [ ] Mock fixtures and documented contracts
- [ ] Adapter and selector tests passing
- [ ] README with setup, screenshots and known limitations
- [ ] Dashboard demonstrated without any backend running
