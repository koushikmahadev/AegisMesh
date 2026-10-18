# Dashboard Architecture & Data Pipeline

This document describes the unidirectional data pipeline, data models, layer isolation rules, and multi-source configuration for the Flood Operations Dashboard (`modules/dashboard`).

---

## 1. Unidirectional Data Flow

All application data flows through a strict one-way pipeline:

```
Service Layer (dashboardApi.js)
        │
        ▼
Adapter Layer (dataAdapter.js)
        │
        ▼
State Hook (useDashboardData.js)
        │
        ▼
Selectors (dashboardSelectors.js) & Component Tree
```

### Layer Responsibilities
- **`src/services/dashboardApi.js`**: Fetches raw JSON / GeoJSON payloads from local mock endpoints or backend REST endpoints. Catches network failures gracefully per secondary layer and returns structured error envelopes instead of failing completely.
- **`src/data/dataAdapter.js`**: Validates geometries (RFC 7946 EPSG:4326 `[lng, lat]`, closed polygon rings), standardizes attribute names, isolates malformed features without throwing unhandled exceptions, and maps backend property names to standardized frontend schemas.
- **`src/hooks/useDashboardData.js`**: Manages state, loading flags, error boundaries, stale data checks (`VITE_STALE_MINUTES`), and in-flight request deduplication.
- **`src/selectors/dashboardSelectors.js`**: Performs memoized derived calculations (summary cards, risk distributions, ranking charts).

---

## 2. Supported Data Modes (`VITE_DATA_SOURCE`)

The dashboard dynamically switches operational datasets based on `VITE_DATA_SOURCE`:

| `VITE_DATA_SOURCE` | Path / Configuration | Purpose & Characteristics |
|---|---|---|
| `mock` (Default) | `public/mock-data/` | Synthetic Bangalore assessment dataset for initial prototype verification. |
| `mock-dernau` | `public/mock-data-dernau/` | Historical SpaceNet 8 flood labels for Dernau (Ahr valley, Germany) with 38 assessment zones and exposed buildings. |
| `mock-floodwatch` | `public/mock-data-floodwatch/` | Exported ML inference predictions (SegFormer-B0 fast/accurate) and SpaceNet 8 ground truth features. |
| `api` | `VITE_API_BASE_URL` | Live backend REST API endpoints. |

---

## 3. FloodWatch Integration (`VITE_DATA_SOURCE=mock-floodwatch`)

### Data Files
Located in `modules/dashboard/public/mock-data-floodwatch/`:
- `flood_extent_groundtruth.geojson`: SpaceNet 8 human-annotated ground truth (building footprints and unbuffered road line segments) labelled flooded. Provenance: `"observed"`.
- `flood_extent_predicted_fast.geojson`: SegFormer-B0 model predictions in fast inference mode. Provenance: `"derived"`.
- `flood_extent_predicted_accurate.geojson`: SegFormer-B0 model predictions in sliding-window accurate mode. Provenance: `"derived"`.
- `zones.json`: Assessment zones covering the demonstration tiles in the Germany AOI.

### Adapter Contract & Invariants
`adaptFloodWatchFeature` and `adaptFloodWatchCollection` in `src/data/dataAdapter.js` enforce:
1. **Coordinate Verification**: Coordinates must strictly follow EPSG:4326 `[longitude, latitude]` within valid numerical ranges (`-180 <= lng <= 180`, `-90 <= lat <= 90`).
2. **Ring Closure**: Polygon rings must be explicitly closed (first coordinate equals last coordinate). Open rings are dropped and recorded in `droppedFeatureCount`.
3. **LineString Support**: Road ground-truth features (`type: 'LineString'`) require at least 2 valid coordinates.
4. **Property Preservation**:
   - `provenance`: Passed through explicitly (`"observed"` for ground truth, `"derived"` for model predictions).
   - `tile_id`: Tile identifier (e.g., `0_41_58`).
   - `mode`: `"fast"` or `"accurate"`.
   - `mask_pixels`: Model pixel count.
   - `in_training_pool`: Strict boolean.
   - `feature_type`: `"building"` or `"road"` for ground truth.
   - Missing fields are preserved as `null` and **never** defaulted or coerced.
5. **Training Pool Disclosure**: All demonstration tiles with flood damage in this dataset were in the SegFormer-B0 model's training pool. Observed-versus-predicted overlap is illustrative of model recall on trained tiles, not a held-out test evaluation.

---

## 4. Map Canvas Layout & Side Panel Docking

To maintain an unobstructed operational view for tactical emergency commanders:
- **Map Canvas**: Kept 100% clean. Only Leaflet zoom buttons (+/-), the reset extent button, and map attribution are positioned over the map.
- **Docked Side Panel**: On desktop, a collapsible right-hand side panel houses layer controls, legends, layer failure notices, dropped feature notices, and provenance disclaimers.
- **Layout Responsiveness**: Resizing or toggling the side panel invokes Leaflet `map.invalidateSize()` via a `ResizeObserver`, ensuring the map smoothly fills available space without resetting the center or zoom level.
