# Flood Analysis & Geospatial Processing (Module 2)

HighWater Mission 6 (Disaster Response Drones). Processes real, human-labelled
flood ground truth into small contract-based JSON/GeoJSON files other modules
can consume without importing this code. Standalone — no dependency on the
frontend, backend, or other modules.

## Dataset, license, attribution

**SpaceNet 8 (SN8) Flood Detection Challenge, Germany training set** (Dernau
area, Western Europe floods, June 2021). Combines OSM-derived building
footprints and road networks with human-labelled flood status, over PRE- and
POST-event Maxar satellite imagery. Already extracted at `data/raw/` (not
downloaded by this module, and never committed — see `.gitignore`).

- **Annotations license**: CC BY-SA 4.0 (attribution + share-alike).
- **Imagery license**: the SN8 paper states Maxar imagery is CC BY-NC 4.0.
  This module never redistributes imagery — only small derived vector
  outputs (building/road/flood-extent geometries and per-zone statistics).
  Whether derived vector outputs trained on NC-licensed imagery inherit any
  restriction is an open question we have **not** resolved — flagged here
  rather than assumed either way.
- **Attribution**: SpaceNet 8 (SpaceNet on AWS), Maxar Technologies.
- Known from official SN8 sources (not re-derived here): across the *full*
  SN8 dataset, ~13% of buildings and ~15% of roads are flooded. Our AOI
  subset numbers below are independently computed and differ from that
  global figure, as expected for a small spatial sample.

## Install / run / test

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/python -m flood_analysis.cli --input data/raw --out output
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Data inspection used to understand the raw files is in
[`scripts/inspect_sample.py`](scripts/inspect_sample.py), with its output saved to
[`docs/data_inspection.txt`](docs/data_inspection.txt).

## What the data actually contains (verified by inspection)

- `data/raw/annotations/*.geojson` (202 tiles): vector buildings (Polygon)
  and roads (LineString), **already in lon/lat** (`OGC:CRS84`, equivalent to
  EPSG:4326) — no raster-to-vector or reprojection needed for these.
  Each feature has either a `building` tag or a `highway` tag (never both),
  and a `flooded` property that is the string `"yes"` when flooded, or
  absent/`None` when not flooded. This is the **human-labelled ground
  truth**, not a model prediction.
- `data/raw/PRE-event/*.tif`, `POST-event/*.tif`: plain 3-band uint8 RGB
  Maxar imagery, EPSG:4326, ~0.3–0.4 m/pixel. **No flood-extent raster or
  water mask exists in this dataset** — confirmed by inspecting band value
  distributions (continuous color imagery, not a classified mask).
- The two CSVs (`Germany_Training_Public_reference.csv`,
  `..._label_image_mapping.csv`) give pixel-coordinate (`Wkt_Pix`) building/
  road flood labels per image tile and a PRE/POST image-pairing table. They
  duplicate information already available in geo coordinates in the
  annotation GeoJSONs, so this module uses the GeoJSONs directly rather than
  pixel coordinates, avoiding an unnecessary raster-to-geo conversion step.

**Decision**: because no flood-extent raster exists, `flood_extent.geojson`
is **derived from labelled flooded buildings/roads**, not a measured water
boundary, as explicitly permitted by the mission brief's fallback path. The
Sen1Floods11 fallback dataset was not needed.

## Area of interest (AOI)

A contiguous 6×4 block of SN8 tiles (rows 36–41, cols 59–62 in the tile
naming scheme) in [`src/flood_analysis/cli.py`](src/flood_analysis/cli.py), chosen because it
contains a real mix of flooded and non-flooded buildings and roads (not
every tile in the rectangle exists; missing tiles are skipped).

## Processing (`src/flood_analysis/processor.py`)

1. Load all building/road features from the AOI tiles, dedup by OSM `id`.
2. Reproject to a local UTM zone (picked from the AOI centroid) for all area
   and length calculations — never in degrees.
3. **Flood extent**: union of labelled-flooded building polygons and
   labelled-flooded road lines buffered by 5 m, dissolved and simplified.
   Properties: `source: derived_from_labelled_flooded_buildings_roads`,
   `label_class: derived_flood_extent`.
4. **Zones**: regular 300 m × 300 m grid over the AOI (in UTM). Per zone:
   `flooded_percent` (derived flood-extent area ÷ cell area), `total_buildings`,
   `exposed_buildings` (buildings with the ground-truth `flooded == "yes"`
   label — **not** flood-extent intersection, to avoid circularity with a
   flood extent that is itself derived from those same labels),
   `road_length_m` / `flooded_road_length_m`, and `accessibility`. Zones with
   no buildings or roads are skipped (not fabricated as zero).
5. **Accessibility** from flooded road length share within the zone:
   - `ACCESSIBLE`: share < 10%
   - `PARTIAL`: 10% ≤ share < 60%
   - `BLOCKED`: share ≥ 60%
   - `UNKNOWN`: zone has no road data

## Outputs (`output/`, contract)

### `zones.json`

```json
{
  "schema_version": "1.0",
  "source": "SpaceNet 8 Germany (Dernau)",
  "crs": "EPSG:4326",
  "zones": [
    {
      "zone_id": "zone-001",
      "bbox": [7.015, 50.512, 7.018, 50.515],
      "centroid": [7.0165, 50.5135],
      "flooded_percent": 12.5,
      "flooded_area_m2": 4200.3,
      "total_buildings": 14,
      "exposed_buildings": 3,
      "road_length_m": 820.5,
      "flooded_road_length_m": 120.0,
      "accessibility": "PARTIAL"
    }
  ]
}
```

`zone_id`, `flooded_percent`, `exposed_buildings`, `accessibility` are the
fixed team-contract field names. Other fields are additive (see "Proposed
contract changes" below).

### `flood_extent.geojson`

FeatureCollection, EPSG:4326, valid Polygon/MultiPolygon, properties
`source`, `label_class`.

### `roads_status.geojson` / `buildings_exposed.geojson`

FeatureCollection, EPSG:4326, each feature has `id` and a boolean `flooded`
property (from the ground-truth label).

### `metadata.json`

Dataset, license/attribution, AOI tiles and bbox, input/output CRS, label
semantics, flood-extent method, grid config, accessibility thresholds, area
method, counts, and limitations — all read from the real run, not hardcoded.

## Real numbers from the last run

See `output/metadata.json` `counts` for the authoritative, current numbers.
As of the last run: 38 zones, 759 buildings (203 flooded), 117 roads (45
flooded), flooded_percent ranges 0–18.85% across zones. `output/` total size
well under 6 MB.

## Tests

`PYTHONPATH=src .venv/bin/python -m pytest -q` — 10 tests, fully offline,
synthetic fixtures: nodata exclusion, flooded-percentage math (including the
zero-valid-pixels edge case), polygon validity after union, UTM↔lon/lat
round-trip, grid zoning (skips empty cells), accessibility thresholds,
flood-extent derivation (including the "nothing flooded" case), and
`zones.json` contract parsing.

## Decisions

- Used the annotation GeoJSONs (already EPSG:4326) directly instead of the
  pixel-coordinate CSVs, since they carry the same ground truth without a
  manual raster transform step.
- `exposed_buildings` = ground-truth flooded label, not flood-extent
  intersection, to avoid circular reasoning (the extent is itself built from
  these labels).
- Fixed AOI tile block picked for a realistic flooded/non-flooded mix rather
  than the full 202-tile dataset, to keep outputs small and processing fast
  within the hackathon time budget.
- `python3.11 -m venv` here needed `get-pip.py` bootstrapping because the
  `python3.11-venv` system package (providing ensurepip) wasn't installed
  and there was no sudo access; recorded here since it's an environment
  quirk, not a design choice.

## Limitations / unverified

- `flood_extent.geojson` is a **derived** extent from labelled flooded
  buildings/roads, not a remotely-sensed water boundary — do not treat it as
  measured.
- Only a 6×4 tile subset of the 202-tile Germany set was processed, by
  design, to keep output small (<2 MB per layer, <6 MB total).
- Whether SN8's derived-vector outputs inherit the Maxar CC BY-NC 4.0
  imagery restriction is **unverified** — flagged, not assumed.
- Single flood event (Dernau, June 2021); not a general flood model.
- `output/map.html` basemap shows real streets and buildings beyond the
  processed AOI for geographic context only — colored flood/building/road
  overlays only exist for the labelled SN8 tile set in the AOI; anything
  outside that boundary has no flood status data.

## Proposed contract changes

- Additive `zones.json` fields beyond the required four: `bbox`, `centroid`,
  `flooded_area_m2`, `total_buildings`, `road_length_m`,
  `flooded_road_length_m` — useful for downstream display/ranking, safe to
  ignore if unused.
- Consider adding a `source: "derived"` vs `"measured"` flag convention at
  the top level of `flood_extent.geojson`-style outputs across modules, so
  consumers can distinguish real sensor-derived extents from
  labelled/inferred ones like this one.
