# HighWater Rescue Routing Engine: Assumptions and Limitations Register

This document serves as the formal assumptions and limitations register for the Zaragoza Rescue Routing Engine v2.1 (Person 4 of the HighWater Disaster Response Platform). Every assumed heuristic, physical simplification, tuned numerical constant, and operational constraint is documented below with its formal definition, design rationale, operational consequence, and recommended upgrade path.

> [!IMPORTANT]
> **Operational Disclaimer**: Risk model constants were tuned empirically so that the demonstration scenarios are informative and illustrate the algorithmic mechanism of risk-aware flood routing. They are uncalibrated against empirical flood measurements or gauge observations and must not be used for real-world life-critical dispatch without field calibration.

---

## 1. Assumptions and Limitations Register

### 1.1 Uncalibrated Flood Risk Heuristic & Tuned Constants (`risk_heuristic`)
- **What**: Edge flood submersion probability $r_i$ for road links is modeled via an empirical logistic sigmoid:
  $$r_i = \sigma\left(c_r \cdot R_{\text{eff}} - c_e \cdot (E_i - E_{\text{base}}) - c_d \cdot D_i - B\right)$$
  where $R_{\text{eff}} = R \cdot (\text{horizon\_min} / 30.0)$, $c_r = 0.38$, $c_e = 0.70$, $c_d = 0.005$, $E_{\text{base}} = 194.0$, and $B = 10.40$. River channel hazards model debris and flow velocity rather than depth:
  $$r_{\text{river}} = \sigma\left(c_{\text{flow}} \cdot R_{\text{eff}} - B_{\text{flow}}\right)$$
  where $c_{\text{flow}} = 0.09$ and $B_{\text{flow}} = 6.0$.
- **Why**: HighWater Person 4 operates strictly offline-first without requiring runtime dependencies on heavy external hydraulic solvers (HEC-RAS, Iber 2D, TELEMAC). The constants were calibrated to produce distinct, informative routing behaviors across demonstration scenarios (15 mm/h baseline via Puente de Piedra; 45 mm/h predictive detour via Puente de Santiago; causeway cutoff at 45 mm/h).
- **Effect**: Calculated risk values represent rank-preserving relative flood hazard probabilities rather than empirical return-period flood frequencies.
- **Upgrade Path**: Calibrate coefficients against 2D mesh flood extent simulations of the Ebro river basin (e.g., Iber model runs) or stream gauge stage data from the Sistema Automático de Información Hidrológica (SAIH Ebro).

### 1.2 Round-Trip Exposure Model and Dwell Time (`round_trip_exposure_and_dwell_time`)
- **What**: Path risk evaluation assumes a round-trip mission profile (`round_trip=True`) by default. For edge $i$, exposure time is evaluated at the return crossing time:
  $$t_{\text{exposure}} = t_{\text{outbound}} + \text{ON\_SCENE\_DWELL\_MIN} + t_{\text{return\_to\_edge\_i}}$$
  where `ON_SCENE_DWELL_MIN = 15.0` minutes and return travel time mirrors outbound travel time.
- **Why**: Emergency rescue vehicles must not only reach an incident site but also return patients or rescue teams safely across the same infrastructure. Because floodwaters rise monotonically during active rainstorms, the return crossing represents the maximum vulnerability window.
- **Effect**: Edges that appear passable during initial departure may be flagged as impassable or high-risk due to expected inundation during the return leg, preventing vehicle stranding.
- **Upgrade Path**: Ingest dynamic return routing allowing alternate egress routes and variable on-scene triage durations.

### 1.3 Synthetic Road Factor for Distance Tie-Breaking (`road_factor`)
- **What**: A 1.05 multiplier applied to bridgehead highway links in v1 to break Euclidean geometric distance ties.
- **Why**: Straight-line schematic coordinates between sparse centroid nodes resulted in mathematically identical path lengths for symmetric river-crossing corridors.
- **Effect**: Artificially broke the distance tie between Puente de Piedra and Puente de Santiago, giving Puente de Piedra the nominal dry-route baseline preference.
- **Upgrade Path**: Ingest real road network geometries with true curve lengths and OpenStreetMap `length` attributes via osmnx or raw OSM PBF data.

### 1.4 Schematic Straight-Line Geometry (`schematic_straight_lines`)
- **What**: Road links and river channels default to two-point straight LineString vectors between node coordinates unless tagged with OSM polylines.
- **Why**: Simplifies graph representation for rapid unit testing, lightweight demonstration rendering, and zero-dependency offline operation.
- **Effect**: Underestimates true road length (winding curves, street corners) by 10–25%; visual map polylines cut through urban city blocks and riverbank terrain.
- **Upgrade Path**: Replace 2-point line segments with multi-coordinate shape polylines extracted from OpenStreetMap ways or official municipal cartography.

### 1.5 Unverified Geodetic Coordinates & Elevations (`unverified_coordinates`)
- **What**: Latitudes, longitudes, and elevations in `data/zaragoza_network.json` are estimated approximations for landmark nodes in central Zaragoza.
- **Why**: Developed as a benchmark prototype without access to surveyed topographic ground truth.
- **Effect**: Haversine distances and vertical clearance calculations relative to baseline water surface are approximate ($\pm 1$ m vertical, $\pm 50$ m horizontal).
- **Upgrade Path**: Sample high-resolution 5m/2m Digital Elevation Models (MDT05/MDT02) from the Spanish National Geographic Institute (IGN) and query official municipal GIS databases.

### 1.6 Helicopter Dispatch and Cruising Assumptions (`helicopter_assumptions`)
- **What**: Rotary-wing sorties assume launch from `HOSPITAL_BASE`, fixed pre-flight inspection and spool-up staging duration of `HELI_LAUNCH_MINUTES = 10.0` min (matching boat launch staging), straight-line flight at `HELI_SPEED_KMH = 180.0` km/h, and zero ground risk. Aviation operations are grounded when rainfall reaches `HELI_GROUND_MM_H = 60.0` mm/h.
- **Why**: Emergency air operations incur mandatory pre-flight readiness checks, avionics alignment, turbine spool-up, and air traffic coordination before wheels-up, equivalent to marine slipway launch staging (`LAUNCH_MINUTES = 10.0`).
- **Effect**: Helicopter ETAs reflect realistic total mission elapsed time ($t = \text{HELI\_LAUNCH\_MINUTES} + \frac{d}{\text{HELI\_SPEED\_KMH}} \times 60$), preventing overly optimistic zero-latency flight assumptions.
- **Upgrade Path**: Model airspace restrictions, microbarograph wind gust limits, and designated hospital helipad landing zones.

### 1.7 Boat Slipway Launch Staging (`launch_minutes`)
- **What**: Multimodal vehicle transitions from truck towing to river navigation incur a fixed staging duration of `LAUNCH_MINUTES = 10.0` min at boat ramps.
- **Why**: Offloading an inflatable or rigid-hull rescue craft from a trailer, securing painter lines, priming the outboard engine, and embarking rescue crew requires physical time.
- **Effect**: Multimodal rescue routes via slipways carry a flat 10-minute time penalty, ensuring ground routes are preferred unless roads are submerged.
- **Upgrade Path**: Model ramp congestion queues and riverbank slipway approach conditions dynamically.

### 1.8 Independence Assumption in Route Reliability (`independence_assumption`)
- **What**: Route reliability is computed as the product of edge passability probabilities:
  $$\text{route\_reliability} = \prod_{i \in \text{path}} (1 - r_i)$$
- **Why**: Joint distributions with full spatial covariance across arbitrary networks cannot be computed in real-time without full 2D hydraulic flood field simulations.
- **Effect**: Because flood events across adjacent edges in the same river basin are positively correlated, assuming independence makes the product conservative (underestimates true route reliability).
- **Upgrade Path**: Implement spatial copula models or multivariate Gaussian processes conditioned on catchment river stage to model edge risk spatial covariance.

### 1.9 Mask-to-Depth Satellite Proxy (`mask_to_depth_proxy`)
- **What**: `depth_from_mask_fraction()` maps binary satellite water detection fractions to physical water depth using a constant `ASSUMED_FLOOD_DEPTH_M = 1.0` m.
- **Why**: Optical and SAR satellite binary water masks (e.g., Sentinel-1 SAR amplitude thresholding) classify water presence versus dry land, but carry zero vertical depth information.
- **Effect**: Any edge identified as flooded receives a uniform 1.0m depth proxy, exceeding the wading clearance of ambulances (0.0m) and 4x4 trucks (0.4m) regardless of actual water depth.
- **Upgrade Path**: Intersect satellite inundation extents with high-resolution DEMs using Height Above Nearest Drainage (HAND) or Floodwater Depth Estimation Tools (FwDET).

### 1.10 Satellite Latency and Observation Staleness (`satellite_latency`)
- **What**: Depth observation maps older than `DATA_FRESHNESS_MAX_MIN = 180.0` minutes are flagged as `STALE`.
- **Why**: Polar-orbiting SAR satellites have revisit cycles of 6 to 24 hours, whereas urban flash flooding can peak and recede within 2 to 4 hours.
- **Effect**: Routing engines using stale satellite observations may divert around roads that have already drained, or dispatch into flash-flooded corridors that flooded after satellite pass.
- **Upgrade Path**: Integrate real-time telemetry from automated river gauge networks (SAIH Ebro stations) and municipal ultrasonic street sensors.

### 1.11 Single Sortie per Asset Fleet Dispatch (`single_sortie_dispatch`)
- **What**: The dispatch engine solves a single-period bipartite matching (`One sortie per asset`) using `scipy.optimize.linear_sum_assignment`.
- **Why**: Guarantees polynomial-time solvability and deterministic optimal asset allocation without combinatorial exponential explosion.
- **Effect**: Assets cannot execute multi-stop sequential rescue tours (e.g., evacuation of Island followed by transfer to North Residential).
- **Upgrade Path**: Implement a multi-period Vehicle Routing Problem with Time Windows (VRPTW) or dynamic rollout policy for multi-hop evacuation schedules.

### 1.12 Synthetic Benchmark and Synthetic Population (`synthetic_data`)
- **What**: The Monte Carlo benchmark (300 scenarios) and demographic data (`data/population_zones.json`) are synthetic representations constructed for demonstration and validation. The benchmark ground truth shares the risk model with the routing engine, so it is a mechanism test of predictive risk-awareness rather than an empirical validation against independent physics.
- **Why**: Enables zero-network, fully deterministic offline testing without requiring confidential census files or live GIS web services.
- **Effect**: Demonstrates the algorithmic mechanism of risk-aware switching versus reactive shortest-path routing, but does not constitute empirical validation against observed flood ground truth. In sensitivity analysis, `BASE_RIVER_ELEVATION_M` is the most sensitive constant (producing the largest fraction of route choice flips under $\pm 20\%$ perturbation, with only 50-69% choices remaining unchanged).
- **Upgrade Path**: Ingest official Spanish INE census block data, validate against independent 2D mesh simulations (e.g. Iber/HEC-RAS), and calibrate `BASE_RIVER_ELEVATION_M` against geodetic gauge data.

### 1.13 Sphere Humanitarian Standards (`sphere_standards`)
- **What**: Disaster relief supplies and commodity manifests are derived from the Sphere Project Humanitarian Charter minimum standards:
  - `WATER_L_PER_PERSON_DAY = 15.0` L/person/day
  - `KCAL_PER_PERSON_DAY = 2100.0` kcal/person/day
  - `FOOD_KG_PER_PERSON_DAY = 0.5` kg/person/day
  - `MEDICAL_KIT_PEOPLE = 50` persons per kit (5.0 kg per kit)
- **Why**: Ground relief payload demand in internationally recognized humanitarian assistance metrics.
- **Effect**: Accurately scales logistical sortie requirements (truck, boat, helicopter) based on affected population size and planning duration.
- **Upgrade Path**: Incorporate field-specific climate adjustments (increased hydration during summer heatwaves) and specialized nutritional kits for infants and elderly.

### 1.14 Misspecified Ground Truth in Benchmark (`misspecified_water_level`)
- **What**: Simplified linear water-level model (not a hydraulic simulation); shares the elevation ordering of the route network, so it is a second mechanism check, not independent validation.
- **Why**: Evaluates whether predictive flood routing preserves its safety advantage when the physical data-generating process deviates structurally from the routing engine's internal logistic probability model.
- **Effect**: Demonstrates non-zero stranding rates for both policies under high rainfall (45–60 mm/h), confirming predictive risk reduction is robust to model structural misspecification. However, linear rise ignores 2D backwater hydraulic curves, upstream catchment lag, and bridge backwater afflux.
- **Upgrade Path**: Couple the benchmark Monte Carlo harness to pre-computed unsteady depth rasters from 2D hydraulic solvers (e.g., Iber or Telemac-2D).

### 1.15 Decision Stability Under Parameter Perturbation (`decision_stability`)
- **What**: Evaluates optimal path invariance across 12 systematic $\pm 20\%$ parameter perturbations over the 6 core sensitivity constants (`RAINFALL_COEFFICIENT`, `ELEVATION_COEFFICIENT`, `RIVER_DISTANCE_COEFFICIENT`, `RISK_THRESHOLD_BIAS`, `ON_SCENE_DWELL_MIN`, `RISK_TIME_PENALTY`). Routes retaining $\ge 90\%$ (`STABILITY_MIN = 0.9`) path identity are flagged `STABLE`; routes prone to switching are labeled `SENSITIVE`.
- **Why**: Operational commanders require transparency on whether an algorithmic detour is robust or brittle to parameter tuning errors. The $\pm 20\%$ bracket represents typical hydrologic calibration uncertainty, while 0.9 requires tolerance to parameter drift.
- **Effect**: Identifies ambiguous operational decision regimes (e.g. truck wading decisions near transition thresholds) while confirming high certainty at extreme rainfall boundaries (0 and 60 mm/h).
- **Upgrade Path**: Extend discrete deterministic sensitivity to full Bayesian posterior parameter distributions and compute path Pareto-front confidence intervals.

### 1.16 Geographic Coordinates and Bridge Ordering (`synthetic_coordinates`)
- **What**: Node coordinates and elevations in `data/zaragoza_network.json` are curated schematic approximations. Specifically, Puente de Piedra is positioned downstream of Puente de Santiago with lower clearance (198m vs 208m).
- **Why**: Prototype network constructed for zero-network testing and unit test determinism. In actual Zaragoza geography on the Ebro, Puente de Piedra is historically downstream of Puente de Santiago, but actual elevations and approach profiles must be verified against surveyed DEMs.
- **Effect**: While topological ordering matches regional flow conventions, synthetic coordinates must not be used for navigational GPS guidance. `coordinates_verified` remains strictly `false`.
- **Upgrade Path**: Run `tools/coordinate_check.py` to inspect each node against OpenStreetMap, replace synthetic coordinates with authoritative IGN Spain geodesy, and verify bridge elevations against SAIH Ebro river gauges.

---

## 2. Register of Tuned and Assumed Constants

All numerical constants across modules are named, commented in source with lowercase one-line why comments, and cataloged here:

| Constant Name | Value | File:Line | Rationale / Purpose |
|:---|:---:|:---|:---|
| `BASE_RIVER_ELEVATION_M` | `194.0` | `modules/rescue_routing/risk_engine.py:6` | Baseline river surface elevation (m) in Zaragoza sector of the Ebro. |
| `RAINFALL_COEFFICIENT` | `0.38` | `modules/rescue_routing/risk_engine.py:7` | Hydraulic head growth rate per mm/h of cumulative rainfall. |
| `ELEVATION_COEFFICIENT` | `0.70` | `modules/rescue_routing/risk_engine.py:8` | Flood risk reduction rate per meter of elevation clearance above baseline. |
| `RIVER_DISTANCE_COEFFICIENT` | `0.005`| `modules/rescue_routing/risk_engine.py:9` | Attenuation factor reducing flood probability per meter distance from river channel. |
| `RISK_THRESHOLD_BIAS` | `10.40` | `modules/rescue_routing/risk_engine.py:10` | Empirical logistic offset ensuring sub-1% baseline risk at 15 mm/h rainfall. |
| `RIVER_FLOW_COEFFICIENT` | `0.09` | `modules/rescue_routing/risk_engine.py:11` | Growth rate of river current and debris hazard with rainfall intensity. |
| `RIVER_FLOW_THRESHOLD_BIAS` | `6.0` | `modules/rescue_routing/risk_engine.py:12` | Logistic bias ensuring low river hazard during dry conditions. |
| `RISK_TIME_PENALTY` | `1500.0` | `modules/rescue_routing/risk_engine.py:14` | Penalty scaling factor balancing travel time vs risk (Piedra at 15 mm/h, Santiago at 45 mm/h). |
| `ON_SCENE_DWELL_MIN` | `15.0` | `modules/rescue_routing/risk_engine.py:5` | Assumed duration for on-scene medical stabilization and evacuation loading. |
| `HAZARD_RISK_MIN` | `0.25` | `modules/rescue_routing/risk_engine.py:13` | Minimum flood submersion probability to qualify as an avoided hazard. |
| `RELIABILITY_MIN` | `0.90` | `modules/rescue_routing/risk_engine.py:15` | Minimum route reliability threshold for safe departure window scan. |
| `DISPATCH_MIN_RELIABILITY` | `0.50` | `modules/rescue_routing/risk_engine.py:19` | Minimum route reliability threshold for ground/boat asset dispatch feasibility. |
| `HELI_SPEED_KMH` | `180.0` | `modules/rescue_routing/risk_engine.py:16` | Cruising flight speed (km/h) for emergency rescue helicopter. |
| `HELI_GROUND_MM_H` | `60.0` | `modules/rescue_routing/risk_engine.py:17` | Rainfall intensity threshold grounding all rotary-wing aviation operations. |
| `LAUNCH_MINUTES` | `10.0` | `modules/rescue_routing/risk_engine.py:18` | Staging, uncoupling, and slipway launch duration for boat trailer. |
| `ADVISORY_NONE` | `"NONE"` | `modules/rescue_routing/risk_engine.py:20` | Nominal route advisory state when reliability >= RELIABILITY_MIN. |
| `ADVISORY_LOW_RELIABILITY` | `"LOW_RELIABILITY"` | `modules/rescue_routing/risk_engine.py:21` | Route advisory warning when reliability < RELIABILITY_MIN. |
| `ADVISORY_NO_SAFE_OPTION` | `"NO_SAFE_OPTION"` | `modules/rescue_routing/risk_engine.py:22` | Slider advisory state when all surface/boat routes are degraded and heli grounded. |
| `STABILITY_MIN` | `0.9` | `modules/rescue_routing/risk_engine.py:23` | Route should tolerate 20% parameter drift without changing path choice. |
| `WATER_LEVEL_RISE_RATE` | `0.0003` | `modules/rescue_routing/benchmark.py:26` | Hydrograph river stage rise rate in m/(mm/h)/min under intense rainfall. |
| `WATER_LEVEL_BASE_OFFSET_M` | `0.1` | `modules/rescue_routing/benchmark.py:27` | Baseline standing water level before arrival of severe storm peak. |
| `WATER_LEVEL_NOISE_STD_M` | `0.15` | `modules/rescue_routing/benchmark.py:28` | Gaussian noise std dev capturing unmodelled local pooling and micro-topography. |
| `STORM_ACCUMULATION_HORIZON_MIN` | `240.0` | `modules/rescue_routing/benchmark.py:29` | Assumed 4-hour antecedent rainfall accumulation prior to mission return crossing. |
| `BENCHMARK_SCENARIOS` | `1000` | `modules/rescue_routing/benchmark.py:20` | Number of stochastic Monte Carlo scenarios for empirical routing evaluation. |
| `BENCHMARK_SEED` | `42` | `modules/rescue_routing/benchmark.py:21` | Fixed PRNG seed guaranteeing deterministic benchmark reproducibility. |
| `BOOTSTRAP_RESAMPLES` | `1000` | `modules/rescue_routing/benchmark.py:22` | Number of bootstrap resamples for 95% confidence interval estimation. |
| `WATER_L_PER_PERSON_DAY` | `15.0` | `modules/rescue_routing/needs.py:7` | Sphere minimum survival water standard (liters per person per day). |
| `KCAL_PER_PERSON_DAY` | `2100.0` | `modules/rescue_routing/needs.py:8` | Sphere minimum nutritional energy standard (kcal per person per day). |
| `FOOD_KG_PER_PERSON_DAY` | `0.5` | `modules/rescue_routing/needs.py:9` | Emergency dry food ration density (kg per person per day). |
| `MEDICAL_KIT_PEOPLE` | `50` | `modules/rescue_routing/needs.py:10` | Population coverage per emergency medical trauma kit. |
| `MEDICAL_KIT_KG` | `5.0` | `modules/rescue_routing/needs.py:11` | Physical weight of standard emergency medical trauma kit. |
| `INITIAL_WATER_L_PER_PERSON` | `3.0` | `modules/rescue_routing/needs.py:12` | Immediate lifesaving drinking water allocation per person. |
| `ELDERLY_VULNERABILITY_MULTIPLIER` | `1.2` | `modules/rescue_routing/needs.py:13` | Sphere-derived mobility assistance vulnerability multiplier. |
| `INFANT_VULNERABILITY_MULTIPLIER` | `1.3` | `modules/rescue_routing/needs.py:14` | Sphere-derived pediatric nutrition and hydration multiplier. |
| `AMBULANCE_CAPACITY_KG` | `400.0` | `modules/rescue_routing/needs.py:17` | Medical cargo payload limit for emergency ambulance. |
| `TRUCK_CAPACITY_KG` | `1500.0` | `modules/rescue_routing/needs.py:18` | Cargo payload limit for high-clearance 4x4 rescue truck. |
| `BOAT_CAPACITY_KG` | `800.0` | `modules/rescue_routing/needs.py:19` | Cargo payload limit for inflatable river rescue boat. |
| `HELI_CAPACITY_KG` | `1200.0` | `modules/rescue_routing/needs.py:20` | External sling / cabin payload limit for rescue helicopter. |
| `IN_NEED_SHARE` | `0.8` | `modules/rescue_routing/needs.py:28` | Assumed share of stranded population lacking private emergency reserves. |
| `EARTH_RADIUS_M` | `6371000.0` | `modules/rescue_routing/osm_loader.py:8` | WGS84 volumetric mean earth radius in meters. |
| `ROAD_SPEED_MPS` | `11.11` | `modules/rescue_routing/osm_loader.py:9` | 40 km/h baseline vehicle transit speed. |
| `RIVER_SPEED_MPS` | `4.17` | `modules/rescue_routing/osm_loader.py:10` | 15 km/h baseline river craft navigation speed. |
| `ASSUMED_FLOOD_DEPTH_M` | `1.0` | `modules/rescue_routing/osm_loader.py:88` | Default depth proxy applied to binary satellite water mask detections. |
| `DATA_FRESHNESS_MAX_MIN` | `180.0` | `modules/rescue_routing/osm_loader.py:89` | Maximum observation age before satellite depth observations are flagged as STALE. |
| `SPEED_MULTIPLIERS` | `{AMB: 1.0, TRK: 1.3, BOAT: 2.0}` | `modules/rescue_routing/router.py:35` | Baseline transit time multipliers per vehicle modality. |
| `TRUCK_WADING_LIMIT_M` | `0.4` | `modules/rescue_routing/router.py:32` | Maximum water depth clearance before truck wading becomes impassable. |
| `BOAT_MIN_DRAFT_M` | `0.5` | `modules/rescue_routing/router.py:33` | Minimum water depth draft required for rescue boat navigation. |

---

## 3. Production Replacement Checklist for Person 1

Before deploying this routing engine to operational rescue dispatch in Zaragoza or any real-world basin, Person 1 must replace the following synthetic inputs and prototype artifacts:

1. **Authoritative OSM Network Topologies & DEM Elevations (`data/zaragoza_network.json`)**:
   - Replace synthetic node coordinates and schematic straight lines with real-world OpenStreetMap highway ways and geometry.
   - Replace approximate synthetic elevations with Copernicus European Digital Elevation Model (EU-DEM 25m) or IGN Spain 5m LiDAR DEM.
   - Use `tools/coordinate_check.py` and `data/coordinate_check.csv` to verify approach elevations and bridgehead clearances.
2. **Geodetic Gauge Telemetry & River Surface Datum**:
   - Calibrate baseline river surface elevation `BASE_RIVER_ELEVATION_M = 194.0` against real-time telemetry from SAIH Ebro station A011 (Ebro en Zaragoza).
   - Ingest live river stage telemetry rather than relying on synthetic linear hydrographs.
3. **Census Demographics & Vulnerability Microdata (`data/population_zones.json`)**:
   - Replace synthetic resident headcounts and age distributions with official Spanish National Statistics Institute (INE) census block data and municipal registers (Padrón municipal de habitantes).
4. **Hydraulic Risk Model Calibration**:
   - Calibrate logistic flood risk coefficients (`RAINFALL_COEFFICIENT`, `ELEVATION_COEFFICIENT`, `RIVER_DISTANCE_COEFFICIENT`, `RISK_THRESHOLD_BIAS`) against certified 2D hydraulic simulation rasters (Iber 2D or HEC-RAS 2D) calibrated to historical Ebro return intervals (10-yr, 50-yr, 100-yr flood maps).
5. **Earth Observation Pipeline Integration**:
   - Connect `load_depth_map` and `depth_from_mask_fraction` to automated Copernicus Emergency Management Service (EMS) rapid mapping vectors or Sentinel-1 SAR flood extent extractions.
6. **Coordinates Verification Sign-Off**:
   - Once real geodetic survey data is ingested, update `data/zaragoza_network.json` `"meta"`: set `"coordinates_verified": true`, `"bridge_order_unverified": false`, and add non-empty `"verified_by": "<Auditor Name / Agency>"`.

---

## 4. Future Work (Out of Scope)

The following capabilities are explicitly designated as future work:

1. **Multi-Sortie Dispatch**: Dynamic multi-stop routing schedules allowing single vehicles to service sequences of incidents with dynamic capacity depletion and replenishment.
2. **Back-Testing Against Real Ebro Floods**: Validation of simulated route closures and risk curves against historical Ebro flood events (e.g., major Zaragoza inundation events of 2003, 2015, and 2018).
3. **Hydraulic Calibration of Risk Constants**: Empirical calibration of logistic risk model coefficients against 2D hydraulic flood models (e.g., Iber 2D or HEC-RAS 2D) and automated river gauge telemetry from the Sistema Automático de Información Hidrológica (SAIH Ebro).
4. **Ingestion of Full OSM Polylines**: Ingestion of detailed multi-point street polylines and true network topologies from OpenStreetMap to replace schematic straight-line geometries.
