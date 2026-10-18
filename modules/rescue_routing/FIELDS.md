# Rescue Routing Engine Feature Fields Specification (v2.2)

This document provides a one-line specification for every property of a GeoJSON feature within `routes.json`.

## Risk Horizons Note
- **`edge_risks`**: Probabilities of edge failure computed over the actual mission traversal duration (round-trip exposure horizon based on vehicle speed and segment length).
- **`planning_edge_risks`**: Probabilities of edge failure standardized across all edges over a fixed 30-minute planning horizon, independent of transit speed.

---

## Feature Properties

- `scenario_id`: Unique identifier of the test scenario or operational run producing the feature.
- `rainfall_mmh`: Rain precipitation rate in mm/hour applied to the routing query.
- `blocked_edges`: List of node pairs `[u, v]` manually or scenario-imposed as completely impassable.
- `depth_source`: Origin of water depth measurements (`"scenario"`, `"depth_map"`, or `"mask_fraction_proxy"`).
- `data_freshness`: Sensor data staleness status relative to freshness threshold (`"FRESH"`, `"STALE"`, or `"UNKNOWN"`).
- `depth_age_min`: Elapsed time in minutes since the depth observation was recorded (null if synthetic or scenario-imposed).
- `status`: Outcome status of the routing query (`"OK"`, `"UNREACHABLE"`, or `"INVALID_REQUEST"`).
- `vehicle_type`: Dispatched operational vehicle class (`"AMBULANCE"`, `"TRUCK_4X4"`, `"RESCUE_BOAT"`, `"HELICOPTER"`, or `"ALL"`).
- `origin`: Starting node identifier in the rescue network graph.
- `destination`: Target destination node identifier in the rescue network graph.
- `query_id`: Identifier linking the feature or slider evaluation to a specific query instance.
- `eta_minutes`: Estimated one-way transit time in minutes along the chosen route (null if unreachable).
- `distance_km`: Total path distance in kilometers along the chosen route (null if unreachable).
- `path_nodes`: Ordered list of graph node IDs traversed from origin to destination.
- `avoided_hazards`: Array of bypassed edges from the shortest nominal path qualifying as blocked, submerged, or high-risk.
- `is_predictive_detour`: Boolean indicating if the engine deviated from the shortest nominal path solely to avoid predicted flood risks.
- `route_reliability`: Compound survival probability over the mission exposure horizon ($P = \prod (1 - r_i)$ over round-trip traversal duration).
- `outbound_reliability`: Compound survival probability across the chosen path for the one-way outbound leg.
- `edge_risks`: Sequential probabilities of edge failure calculated specifically over the mission traversal duration (round-trip exposure horizon).
- `planning_edge_risks`: Sequential probabilities of edge failure standardized over a fixed 30-minute planning horizon, independent of vehicle speed.
- `risk_horizon_note`: Explanatory label stating whether reported edge_risks represent mission traversal duration or a fixed planning horizon.
- `round_trip`: Boolean indicating whether route_reliability accounts for a return leg back to origin.
- `geometry_quality`: Source fidelity level of line coordinates (`"schematic_straight_lines"`, `"osm_polyline"`, or `"great_circle"`).
- `eta_delta_min`: Transit time difference in minutes relative to the pure-distance shortest path (0.0 if optimal or unavailable).
- `counterfactual`: Comparison metrics evaluating the selected route against the reactive (nominal shortest) baseline.
- `departure_window_min`: Safe departure delay window in minutes within which route reliability remains $\ge$ RELIABILITY_MIN.
- `window_capped`: Boolean indicating if departure window calculation reached the maximum evaluation horizon limit.
- `component_scope`: Subgraph boundary used for connectivity analysis (`"vehicle_passable_subgraph"`).
- `isolated_nodes`: List of node IDs in the destination's disconnected component when target is unreachable.
- `cut_edges`: List of impassable boundary edges isolating the destination component from the origin.
- `legs`: Array of multimodal transit legs detailing mode, staging points, transfer delays, and sub-trajectories.
- `launch_minutes`: Pre-deployment staging and vehicle launch overhead time in minutes.
- `standing_water_note`: Caveat explaining whether standing water depth was scenario-imposed or rainfall-derived.
- `surface_access_severed`: Boolean indicating that all terrestrial and amphibious corridors are blocked, forcing aerial escalation.
- `reason`: Machine-readable diagnostic explanation for an unreachable status.
- `note`: Operational note or caveat pertaining to the feature route execution.
- `assumption`: Explicit assumptions applied during route computation or penalty modeling.
- `advisory`: High-level operational advisory state (`"NONE"`, `"LOW_RELIABILITY"`, or `"NO_SAFE_OPTION"`).
- `max_planning_risk`: Maximum edge failure risk encountered along the route under the 30-minute planning horizon.
- `risk_warning`: Boolean flag raised when max_planning_risk > 0.9 while overall route_reliability remains > 0.5.
- `deprecated`: Boolean flag marking legacy or orphaned route features superseded by later schema versions.
- `superseded_by`: Integer feature index identifying the updated feature replacement for a deprecated entry.
