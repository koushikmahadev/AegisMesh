# HighWater Dashboard: Rules (Member 1)

These rules apply to everyone writing code in `modules/dashboard/`, including AI coding assistants. Read this file before starting any task.

## 1. Ownership

1. Work only inside `modules/dashboard/`. Never edit another member's folder.
2. Shared contracts may change only by agreement with the producing member. Record every change in the README changelog.
3. Do not implement flood detection, risk scoring, route computation, backend endpoints or databases. Display what is supplied.

## 2. Data honesty (non-negotiable)

| Rule | Detail |
|---|---|
| Missing is not zero | Missing numeric data renders "Not available". It is never `0`, never LOW. |
| Unknown risk | Anything not exactly HIGH, MEDIUM or LOW becomes UNKNOWN. |
| No invented values | Do not fabricate numbers, trends or timestamps. A single snapshot gets no time-series chart. |
| Label demo data | Mock mode always shows the DEMO MODE badge, and stat cards derived from fixtures are marked illustrative. |
| Derive, do not hardcode | Stats, counts and chart data come from the loaded dataset. |
| Provenance | If a layer or route carries `provenance` (`observed`, `derived`, `simulated`), show it. Never present a simulated closure as detected. |
| No misleading routes | Missing or unreachable route draws no line and shows a message. |

## 3. Architecture rules

1. Data path is fixed: service, adapter, hook, selectors, components.
2. Components and map layers never call `fetch`.
3. Only `dataAdapter.js` knows backend field names. Components read the normalised model only.
4. One source of truth for selection: `selectedZoneId`. Never duplicate selected-zone data in state.
5. Derive filtered and sorted lists from the full array. Do not store a second filtered list.
6. Toggling a layer changes `visibleLayers` only; it does not change data or reset the map view.
7. All colours and risk styles live in `config/theme.js`. No hex codes scattered in components.
8. A failure in one overlay must not crash the base map or other panels (error boundary per layer).
9. No global-state library, 3D globe or animation framework unless a written justification is approved.

## 4. Geospatial rules

1. GeoJSON order is `[longitude, latitude]`. Leaflet's own coordinate arrays are `[latitude, longitude]`. Convert in exactly one helper (`toLatLng`) and test it.
2. Validate every coordinate before it reaches Leaflet: lng in [-180, 180], lat in [-90, 90]. Warn if the values look swapped.
3. Polygons must be closed rings (first point equals last). Invalid features are skipped and counted, not rendered.
4. A flood extent polygon and a risk zone polygon are different layers. Link them by `zone_id` only when supplied.
5. A zone may have no geometry. It stays in the list and is simply absent from the map.
6. Mock geometry is deterministic. No runtime random generation.
7. Call `map.invalidateSize()` after any container resize.

## 5. UI rules

1. Every visible control has real behaviour. No decorative toggles or dead buttons.
2. Never rely on colour alone. Pair risk colours with text labels, icons or patterns.
3. Map and list stay in sync through shared selection.
4. Design empty, loading, error and stale states from the start, not at the end.
5. No horizontal page overflow at 360 px width.
6. Controls are keyboard reachable with visible focus.
7. Red means HIGH risk, not "flood". Do not use red as a background theme.

## 6. Code rules

| Area | Rule |
|---|---|
| Language | JavaScript (JSX). Add JSDoc types to adapter and selectors. |
| Components | Small, single purpose, props in, events out. Do not split every tiny element into its own file. |
| Naming | Components `PascalCase`; functions and variables `camelCase`; constants `UPPER_SNAKE_CASE`; fixtures `snake_case` JSON matching the contracts. |
| Side effects | Only in hooks. Selectors and utils are pure. |
| Memoisation | Memoise derived lists and map style functions; avoid re-creating GeoJSON layers each render. |
| Dependencies | Add a package only if it saves meaningful time, and note it in the README. |
| Secrets | No API keys or credentials in frontend code. |
| Comments | Explain why, not what. |

## 7. Testing rules

1. Every adapter rule has a test (bad risk level, non-finite number, bad coordinates, scale conversion).
2. Selectors and filtering are covered by unit tests.
3. Selection sync between list and details panel is covered by a component test.
4. Map rendering is verified manually; list the manual checks in the README.
5. A task is not done until its tests pass and its acceptance criteria in `tasks.md` are met.

## 8. Git rules

1. Branch per phase or feature: `dashboard/phase-3-map`.
2. Small commits with imperative messages: `Add zone filter bar`.
3. Pull and rebase before pushing. Never force-push shared branches.
4. Do not commit `node_modules`, `.env` or build output.
5. Every PR states which tasks in `tasks.md` it completes and attaches a screenshot for UI changes.

## 9. Instructions for AI coding assistants

1. Read `PRD.md`, `architecture.md`, this file and the current phase in `phases.md` before editing.
2. Implement only the task you were given. Do not refactor unrelated files.
3. If a requirement is ambiguous or conflicts with these rules, ask. Do not guess backend field names or endpoints.
4. Do not invent data to make a screen look complete. Use the labelled fixtures.
5. After a change, run the tests and the dev server, and report what you verified and what you could not.

## 10. Definition of done for any change

- [ ] Meets the acceptance criteria in `tasks.md`
- [ ] Follows sections 2 to 6 above
- [ ] Tests added or updated and passing
- [ ] Works at desktop and mobile widths
- [ ] No console errors on the happy path or on malformed-data tests
- [ ] README updated if setup, contracts or behaviour changed
