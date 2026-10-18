"""Audit tool validating routes.json against Person 1 contract and v2.1 specifications."""

import json
import math
import re
import sys
from pathlib import Path
import jsonschema


def audit():
    routes_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("routes.json")
    schema_path = Path("schema.json")

    print(f"[AUDIT] Starting comprehensive verification of {routes_path}...")

    if not routes_path.exists():
        print(f"FAIL: {routes_path} not found")
        sys.exit(1)
    if not schema_path.exists():
        print("FAIL: schema.json not found")
        sys.exit(1)

    with open(routes_path, "r", encoding="utf-8") as f:
        routes_data = json.load(f)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # 1. Schema validity
    try:
        jsonschema.validate(instance=routes_data, schema=schema)
        print("PASS: Schema validation against schema.json")
    except jsonschema.ValidationError as e:
        print(f"FAIL: Schema validation error: {e.message}")
        sys.exit(1)

    ver = routes_data.get("schema_version")
    if ver == "2.3":
        # Schema 2.3 Regional Output Verification
        print("PASS: Verified schema_version 2.3")
        disclaimer = routes_data.get("disclaimer", "")
        if "PLANNING AID ONLY" not in disclaimer:
            print("FAIL: Missing mandatory disclaimer banner in schema 2.3 output")
            sys.exit(1)
        print("PASS: Verified disclaimer banner")

        prov = routes_data.get("provenance", {})
        if "flood_observation" not in prov or "osm" not in prov:
            print("FAIL: Missing flood_observation or osm in provenance")
            sys.exit(1)
        if "data_freshness" not in prov or prov["data_freshness"] not in ("FRESH", "AGING", "STALE", "UNKNOWN"):
            print(f"FAIL: Invalid data_freshness in provenance: {prov.get('data_freshness')}")
            sys.exit(1)
        print(f"PASS: Verified provenance and data_freshness ({prov['data_freshness']})")

        # Feature checks
        for i, feat in enumerate(routes_data.get("features", [])):
            p = feat.get("properties", {})
            if "confidence" not in p or p["confidence"] not in ("HIGH", "MEDIUM", "LOW", "UNVERIFIED"):
                print(f"FAIL: Feature {i} missing valid confidence: {p.get('confidence')}")
                sys.exit(1)
            if "confidence_reasons" not in p or not isinstance(p["confidence_reasons"], list):
                print(f"FAIL: Feature {i} missing confidence_reasons list")
                sys.exit(1)
        print(f"PASS: Verified {len(routes_data.get('features', []))} feature confidence ratings and reasons")

        # 5-state road model checks
        net_feats = routes_data.get("network", {}).get("features", [])
        valid_states = {"DRY", "FLOODED_PASSABLE", "FLOODED_IMPASSABLE", "UNCERTAIN", "UNKNOWN"}
        for nf in net_feats:
            st = nf.get("properties", {}).get("road_state")
            if st not in valid_states:
                print(f"FAIL: Road segment has invalid road_state: {st}")
                sys.exit(1)
        print(f"PASS: Verified 5-state road classification across {len(net_feats)} network features")

        if routes_data.get("verified") is not False:
            print("FAIL: Expected top-level verified: False")
            sys.exit(1)
        print("PASS: Top-level verified: False verified")

        print(f"\n[AUDIT COMPLETE] ALL CHECKS PASSED FOR {routes_path} (Exit Code 0).")
        sys.exit(0)

    # If schema 2.2, run contract comparison against routes_v2_1_1.json
    contract_path = Path("contract/routes_v2_1_1.json")
    if not contract_path.exists():
        contract_path = Path("contract/routes_v2_0.json")
    if not contract_path.exists():
        print(f"FAIL: {contract_path} not found")
        sys.exit(1)
    with open(contract_path, "r", encoding="utf-8") as f:
        contract_data = json.load(f)

    # 2. Contract diff vs contract file
    for key in contract_data.keys():
        if key not in routes_data:
            print(f"FAIL: Missing top-level key from contract: {key}")
            sys.exit(1)
    print("PASS: Top-level keys contract preserved")
    if routes_data.get("schema_version") != "2.2":
        print(f"FAIL: Expected schema_version 2.2, got: {routes_data.get('schema_version')}")
        sys.exit(1)
    if routes_data.get("provenance", {}).get("code_version") != "2.2.1":
        print(f"FAIL: Expected code_version 2.2.1, got: {routes_data.get('provenance', {}).get('code_version')}")
        sys.exit(1)
    print("PASS: schema_version 2.2 and code_version 2.2.1 verified")

    # Contract feature preservation (baseline features 0 to 8 preserved from contract)
    contract_feats = contract_data["features"]

    new_feats = routes_data["features"]
    if len(new_feats) != 14:
        print(f"FAIL: Expected exactly 14 features, got {len(new_feats)}")
        sys.exit(1)

    for i in range(9):
        c_p = contract_feats[i]["properties"]
        n_p = new_feats[i]["properties"]
        for prop in c_p.keys():
            if prop not in n_p:
                print(f"FAIL: Feature {i} missing contract property: {prop}")
                sys.exit(1)
        if c_p["scenario_id"] != n_p["scenario_id"]:
            print(f"FAIL: Feature {i} scenario_id reordered or changed: {c_p['scenario_id']} != {n_p['scenario_id']}")
            sys.exit(1)
        if c_p["vehicle_type"] != n_p["vehicle_type"]:
            print(f"FAIL: Feature {i} vehicle_type changed: {c_p['vehicle_type']} != {n_p['vehicle_type']}")
            sys.exit(1)
        if c_p["status"] != n_p["status"]:
            print(f"FAIL: Feature {i} status changed: {c_p['status']} != {n_p['status']}")
            sys.exit(1)
    for i in range(9, 14):
        if new_feats[i]["properties"].get("scenario_id") != "scenario_5_full_cascade":
            print(f"FAIL: Feature {i} scenario_id is not scenario_5_full_cascade: {new_feats[i]['properties'].get('scenario_id')}")
            sys.exit(1)
    print("PASS: Baseline features 0-8 order and properties preserved, and features 9-13 match scenario 5")

    # Contract scenario preservation
    contract_scenarios = contract_data["scenarios"]
    new_scenarios = routes_data["scenarios"]
    if len(new_scenarios) < len(contract_scenarios):
        print(f"FAIL: Scenario count reduced: {len(new_scenarios)} < {len(contract_scenarios)}")
        sys.exit(1)

    for i in range(len(contract_scenarios)):
        c_sc = contract_scenarios[i]
        n_sc = new_scenarios[i]
        if c_sc["id"] != n_sc["id"]:
            print(f"FAIL: Scenario {i} ID mismatch: {c_sc['id']} != {n_sc['id']}")
            sys.exit(1)
    print("PASS: Baseline scenarios order and mappings preserved")

    # 3. Reliability == product of edge_risks
    for i, feat in enumerate(new_feats):
        props = feat["properties"]
        if props.get("status") == "OK" and props.get("edge_risks"):
            edge_risks = props["edge_risks"]
            exp_rel = round(math.prod(1.0 - r for r in edge_risks), 4)
            actual_rel = props.get("route_reliability")
            if actual_rel is not None and abs(actual_rel - exp_rel) > 1e-4:
                print(f"FAIL: Feature {i} reliability contradiction: published {actual_rel} != computed {exp_rel}")
                sys.exit(1)

    # Check slider steps reliability
    for step in routes_data.get("slider", {}).get("steps", []):
        for q_res in step.get("results", []):
            if q_res.get("status") == "OK" and q_res.get("edge_risks"):
                edge_risks = q_res["edge_risks"]
                exp_rel = round(math.prod(1.0 - r for r in edge_risks), 4)
                actual_rel = q_res.get("route_reliability")
                if actual_rel is not None and abs(actual_rel - exp_rel) > 1e-4:
                    print(f"FAIL: Slider result reliability contradiction: published {actual_rel} != computed {exp_rel}")
                    sys.exit(1)
    print("PASS: Mathematical consistency: route_reliability == prod(1 - r_i) across features and slider")

    # 4. Same-horizon checks, risk_warning, avoided hazards aliases, advisory, component_scope, and great_circle
    for i, feat in enumerate(new_feats):
        props = feat["properties"]
        rel = props.get("route_reliability")
        risks = props.get("edge_risks", [])
        if props.get("status") == "OK" and risks:
            exp_rel = round(math.prod(1.0 - r for r in risks), 4)
            if rel is not None and abs(rel - exp_rel) > 1e-4:
                print(f"FAIL: Feature {i} same-horizon reliability mismatch: {rel} != {exp_rel}")
                sys.exit(1)
        max_plan = props.get("max_planning_risk", 0.0)
        exp_warn = bool(max_plan > 0.9 and (rel or 0.0) > 0.5)
        act_warn = props.get("risk_warning", False)
        if act_warn != exp_warn:
            print(f"FAIL: Feature {i} risk_warning contradiction: {act_warn} != {exp_warn} (max_plan={max_plan}, rel={rel})")
            sys.exit(1)
        for h in props.get("avoided_hazards", []):
            if "planning_risk" not in h or "risk" not in h or h["planning_risk"] != h["risk"]:
                print(f"FAIL: Feature {i} avoided hazard missing planning_risk/risk alias consistency: {h}")
                sys.exit(1)
        if props.get("status") == "OK":
            adv = props.get("advisory")
            if adv not in {"NONE", "LOW_RELIABILITY", "NO_SAFE_OPTION"}:
                print(f"FAIL: Feature {i} invalid advisory state: {adv}")
                sys.exit(1)
            if rel is not None and rel < 0.90 and adv != "LOW_RELIABILITY":
                print(f"FAIL: Feature {i} has rel {rel} < 0.90 but advisory is {adv}")
                sys.exit(1)
            if "eta_delta_min" not in props or props["eta_delta_min"] is None:
                print(f"FAIL: Feature {i} OK status missing eta_delta_min")
                sys.exit(1)
            if "max_planning_risk" not in props:
                print(f"FAIL: Feature {i} OK status missing max_planning_risk")
                sys.exit(1)
            if "risk_warning" not in props:
                print(f"FAIL: Feature {i} OK status missing risk_warning")
                sys.exit(1)
        if props.get("status") == "UNREACHABLE":
            if props.get("component_scope") != "vehicle_passable_subgraph":
                print(f"FAIL: Feature {i} UNREACHABLE missing component_scope: {props.get('component_scope')}")
                sys.exit(1)
        if props.get("vehicle_type") == "HELICOPTER":
            if props.get("geometry_quality") != "great_circle":
                print(f"FAIL: Feature {i} helicopter missing geometry_quality great_circle: {props.get('geometry_quality')}")
                sys.exit(1)

    print("PASS: Same-horizon checks, risk_warning transparency, advisory, component_scope, and great_circle verified")

    # 5. Check no deprecated or superseded features
    for i, feat in enumerate(new_feats):
        props = feat["properties"]
        if "deprecated" in props or "superseded_by" in props:
            print(f"FAIL: Feature {i} contains deprecated or superseded_by: {props}")
            sys.exit(1)
    print("PASS: No deprecated or superseded features in payload")

    # 6. Scenario exclusivity & uniqueness
    feat_scenarios = {i: [] for i in range(len(new_feats))}
    for sc in new_scenarios:
        for idx in sc.get("feature_indices", []):
            if idx not in feat_scenarios:
                print(f"FAIL: Scenario {sc.get('id')} feature index {idx} out of range")
                sys.exit(1)
            feat_scenarios[idx].append(sc["id"])

    for idx, sc_ids in feat_scenarios.items():
        if len(sc_ids) != 1:
            print(f"FAIL: Feature {idx} belongs to {len(sc_ids)} scenarios ({sc_ids}), expected exactly 1")
            sys.exit(1)
    print("PASS: Every feature belongs to exactly one scenario")

    # In each scenario, no duplicate (vehicle_type, origin, destination) unless blocked_edges differ
    for sc in new_scenarios:
        seen_keys = {}
        for idx in sc.get("feature_indices", []):
            f_props = new_feats[idx]["properties"]
            vt = f_props.get("vehicle_type")
            orig = f_props.get("origin")
            dest = f_props.get("destination")
            key = (vt, orig, dest)
            b_edges = str(sorted([str(e) for e in f_props.get("blocked_edges", [])]))
            if key in seen_keys:
                prev_b_edges = seen_keys[key]
                if b_edges == prev_b_edges:
                    print(f"FAIL: Scenario {sc['id']} has duplicate {key} with identical blocked_edges")
                    sys.exit(1)
            seen_keys[key] = b_edges
    print("PASS: No duplicate (vehicle_type, origin, destination) within any scenario without differing blocked_edges")

    # 7. Cascade order and stages in scenarios 3a, 3b, 5
    for sc_id, exp_stages in [
        ("scenario_3a_island_cutoff_boat_success", [(1, "Ambulance"), (2, "4x4 Truck"), (3, "Rescue Boat")]),
        ("scenario_3b_total_isolation_airdrop", [(4, "Rescue Boat (River Blocked)"), (5, "Helicopter")]),
        ("scenario_5_full_cascade", [(1, "Ambulance"), (2, "4x4 Truck"), (3, "Rescue Boat"), (4, "Rescue Boat (River Blocked)"), (5, "Helicopter")]),
    ]:
        sc_obj = next((s for s in new_scenarios if s["id"] == sc_id), None)
        if not sc_obj:
            print(f"FAIL: Missing cascade scenario {sc_id}")
            sys.exit(1)
        indices = sc_obj.get("feature_indices", [])
        if len(indices) != len(exp_stages):
            print(f"FAIL: Cascade scenario {sc_id} expected {len(exp_stages)} features, got {len(indices)}")
            sys.exit(1)
        for idx, (stg, stg_title) in zip(indices, exp_stages):
            f_props = new_feats[idx]["properties"]
            if f_props.get("stage") != stg:
                print(f"FAIL: Feature {idx} in {sc_id} expected stage {stg}, got {f_props.get('stage')}")
                sys.exit(1)
            if f_props.get("stage_title") != stg_title:
                print(f"FAIL: Feature {idx} in {sc_id} expected stage_title '{stg_title}', got '{f_props.get('stage_title')}'")
                sys.exit(1)
    print("PASS: Cascade order and stages (3a, 3b, 5) verified")

    # Verify scenario 5 full cascade feature indices and attempts
    sc5 = next((sc for sc in new_scenarios if sc["id"] == "scenario_5_full_cascade"), None)
    if sc5.get("selected_feature_index") != 13:
        print(f"FAIL: scenario_5_full_cascade selected_feature_index is {sc5.get('selected_feature_index')}, expected 13")
        sys.exit(1)
    if sc5.get("feature_indices") != [9, 10, 11, 12, 13]:
        print(f"FAIL: scenario_5_full_cascade feature_indices is {sc5.get('feature_indices')}, expected [9, 10, 11, 12, 13]")
        sys.exit(1)
    for att in sc5.get("attempts", []):
        if "feature_index" not in att or "blocked_edges" not in att or "stage" not in att:
            print(f"FAIL: scenario_5_full_cascade attempt missing feature_index, blocked_edges, or stage: {att}")
            sys.exit(1)
    if not any(att.get("selected") is True for att in sc5.get("attempts", [])):
        print("FAIL: scenario_5_full_cascade missing selected attempt")
        sys.exit(1)
    print("PASS: scenario_5_full_cascade cascade features 9-13 and attempts verified")

    # 8. Distance/geometry consistency
    for i, feat in enumerate(new_feats):
        props = feat["properties"]
        if props.get("status") == "OK":
            geom_len = props.get("geometry_length_km")
            dist_km = props.get("distance_km")
            if geom_len is None:
                print(f"FAIL: OK Feature {i} missing geometry_length_km")
                sys.exit(1)
            if dist_km is not None and geom_len > 0:
                rel_diff = abs(dist_km - geom_len) / geom_len
                if rel_diff > 0.01:
                    if props.get("distance_basis") != "road_factor applied to schematic geometry":
                        print(f"FAIL: Feature {i} diff > 1% ({rel_diff:.4f}) but distance_basis is '{props.get('distance_basis')}'")
                        sys.exit(1)
    print("PASS: Distance/geometry consistency and distance_basis verified")

    # 9. Helicopter timing
    for i, feat in enumerate(new_feats):
        props = feat["properties"]
        if props.get("vehicle_type") == "HELICOPTER" and props.get("status") == "OK":
            if props.get("launch_minutes") != 10.0:
                print(f"FAIL: Helicopter Feature {i} missing launch_minutes: 10.0, got: {props.get('launch_minutes')}")
                sys.exit(1)
            if props.get("eta_minutes", 0) < 10.0:
                print(f"FAIL: Helicopter Feature {i} ETA {props.get('eta_minutes')} does not include 10 min launch duration")
                sys.exit(1)
    print("PASS: Helicopter timing (HELI_LAUNCH_MINUTES = 10.0) verified")

    # Verify slider NO_SAFE_OPTION shape
    for step in routes_data.get("slider", {}).get("steps", []):
        if step.get("rainfall_mm_h", 0) >= 60:
            no_safe = next((r for r in step.get("results", []) if r.get("id") == "no_safe_option"), None)
            if not no_safe:
                print("FAIL: Missing NO_SAFE_OPTION entry in slider step >= 60 mm/h")
                sys.exit(1)
            if no_safe.get("vehicle_type") != "ALL" or no_safe.get("query_id") != "no_safe_option" or no_safe.get("destination") != "ALL":
                print(f"FAIL: NO_SAFE_OPTION shape invalid: {no_safe}")
                sys.exit(1)
    # Verify slider results have decision_stability
    for step in routes_data.get("slider", {}).get("steps", []):
        for r in step.get("results", []):
            if "decision_stability" not in r:
                print(f"FAIL: Slider result missing decision_stability: {r.get('id')}")
                sys.exit(1)
            stab = r["decision_stability"]
            if "share_unchanged" not in stab or stab.get("label") not in {"STABLE", "SENSITIVE"}:
                print(f"FAIL: Invalid decision_stability structure: {stab}")
                sys.exit(1)
    print("PASS: Slider decision_stability (share_unchanged & label) verified")

    # Verify dispatch objective, partially_served, and honesty
    disp = routes_data.get("dispatch", {})
    if disp.get("objective") != "priority*reliability*people*delivered_share":
        print(f"FAIL: Dispatch missing or incorrect objective: {disp.get('objective')}")
        sys.exit(1)
    if "total_people_equivalents" not in disp:
        print("FAIL: Dispatch missing total_people_equivalents")
        sys.exit(1)
    if "partially_served" not in disp:
        print("FAIL: Dispatch missing partially_served")
        sys.exit(1)
    if "total_unmet_kg" not in disp:
        print("FAIL: Dispatch missing total_unmet_kg")
        sys.exit(1)
    assigned_inc_ids = {a["incident"] for a in disp.get("assignments", [])}
    for u in disp.get("unserved", []):
        if u["incident"] in assigned_inc_ids:
            print(f"FAIL: Incident {u['incident']} in unserved but has an assignment")
            sys.exit(1)
    for ps in disp.get("partially_served", []):
        if ps["demanded_kg"] <= ps["delivered_kg"]:
            print(f"FAIL: partially_served incident {ps['incident']} has demanded <= delivered: {ps}")
            sys.exit(1)
        req_unmet = round(ps["demanded_kg"] - ps["delivered_kg"], 1)
        if abs(ps["unmet_kg"] - req_unmet) > 0.1:
            print(f"FAIL: partially_served incident {ps['incident']} unmet_kg mismatch: {ps['unmet_kg']} != {req_unmet}")
            sys.exit(1)
    if not disp.get("note"):
        print("FAIL: Dispatch missing note")
        sys.exit(1)
    for ass in disp.get("assignments", []):
        if ass.get("objective") != "priority*reliability*people*delivered_share":
            print(f"FAIL: Assignment missing or incorrect objective: {ass}")
            sys.exit(1)
        if "people_equivalents_supplied" not in ass:
            print(f"FAIL: Assignment missing people_equivalents_supplied: {ass}")
            sys.exit(1)
    print("PASS: Dispatch honesty (partially_served, total_unmet_kg, people equivalents) verified")

    # Verify benchmark ground truth variants
    bench = routes_data.get("benchmark", {})
    if "ground_truth_variants" not in bench or len(bench["ground_truth_variants"]) != 2:
        print(f"FAIL: Benchmark missing ground_truth_variants of length 2: {bench.get('ground_truth_variants')}")
        sys.exit(1)
    if "predictive_reduces_stranding_misspecified" not in bench:
        print("FAIL: Benchmark missing predictive_reduces_stranding_misspecified")
        sys.exit(1)
    variant_names = {v["variant"] for v in bench["ground_truth_variants"]}
    if variant_names != {"perturbed_same_model", "misspecified_water_level"}:
        print(f"FAIL: Unexpected benchmark variant names: {variant_names}")
        sys.exit(1)
    print("PASS: Benchmark ground_truth_variants (perturbed_same_model & misspecified_water_level) verified")

    # 5. Provenance keys present
    req_prov_keys = [
        "generated_by",
        "code_version",
        "network",
        "coordinates_verified",
        "bridge_order_unverified",
        "risk_model",
        "geometry_quality",
        "benchmark",
        "population",
        "input_files",
        "deterministic_seed",
    ]
    prov = routes_data.get("provenance", {})
    for k in req_prov_keys:
        if k not in prov:
            print(f"FAIL: Missing provenance key: {k}")
            sys.exit(1)
    with open("data/zaragoza_network.json", "r", encoding="utf-8") as f:
        net_raw = json.load(f)
    expected_verified = bool(net_raw.get("meta", {}).get("coordinates_verified") is True and net_raw.get("meta", {}).get("verified_by"))
    if prov.get("coordinates_verified") != expected_verified:
        print(f"FAIL: Provenance coordinates_verified ({prov.get('coordinates_verified')}) does not match network meta rule ({expected_verified})")
        sys.exit(1)
    expected_bridge_unverified = bool(net_raw.get("meta", {}).get("bridge_order_unverified", True))
    if prov.get("bridge_order_unverified") != expected_bridge_unverified:
        print(f"FAIL: Provenance bridge_order_unverified ({prov.get('bridge_order_unverified')}) does not match network meta ({expected_bridge_unverified})")
        sys.exit(1)
    print("PASS: All required provenance keys present and coordinates/bridge_order match network meta")

    # 6. No timestamps anywhere
    routes_raw = json.dumps(routes_data)
    iso_time_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
    if iso_time_pattern.search(routes_raw):
        print("FAIL: ISO-8601 timestamp found in routes.json payload (non-deterministic output prohibited)")
        sys.exit(1)
    if "generated_at" in prov:
        print("FAIL: 'generated_at' timestamp key found in provenance")
        sys.exit(1)
    print("PASS: Deterministic verification: zero timestamps in payload")

    # 7. Briefings exactly 2 sentences
    for sc in new_scenarios:
        b = sc["briefing"]
        # Split on sentence boundary '. '
        parts = [s.strip() for s in b.split(". ") if s.strip()]
        if len(parts) != 2:
            print(f"FAIL: Scenario '{sc['id']}' briefing does not have exactly 2 sentences (got {len(parts)}): {b}")
            sys.exit(1)
        if not b.endswith("."):
            print(f"FAIL: Scenario '{sc['id']}' briefing does not terminate with a period: {b}")
            sys.exit(1)
    print("PASS: Tactical briefings verified: exactly 2 sentences ending with period across all scenarios")

    # 8. Every OK feature has eta_delta_min and geometry_quality
    for i, feat in enumerate(new_feats):
        props = feat["properties"]
        if props.get("status") == "OK":
            if "eta_delta_min" not in props or props["eta_delta_min"] is None:
                print(f"FAIL: OK Feature {i} missing eta_delta_min")
                sys.exit(1)
            if "geometry_quality" not in props or not props["geometry_quality"]:
                print(f"FAIL: OK Feature {i} missing geometry_quality")
                sys.exit(1)
    print("PASS: Every OK feature contains eta_delta_min and geometry_quality")

    # 9. Needs funnel monotone
    needs_data = routes_data.get("needs")
    if not needs_data or not isinstance(needs_data, dict):
        print("FAIL: Missing top-level 'needs' dictionary in routes.json")
        sys.exit(1)

    for zone_id, z_needs in needs_data.items():
        if not z_needs.get("synthetic"):
            print(f"FAIL: Zone '{zone_id}' needs missing 'synthetic': true flag")
            sys.exit(1)
        demo = z_needs["demographics"]
        res = demo["residents"]
        exp = demo["exposed"]
        if not (res >= exp >= 0):
            print(f"FAIL: Zone '{zone_id}' demographics funnel violated: residents {res} < exposed {exp}")
            sys.exit(1)
        sc = z_needs["scenarios"]
        for sc_name in ["low", "central", "high"]:
            s = sc[sc_name]
            st = s["stranded"]
            in_nd = s["in_need"]
            if not (exp >= st >= in_nd >= 0):
                print(f"FAIL: Zone '{zone_id}' scenario '{sc_name}' funnel violated: exposed {exp} >= stranded {st} >= in_need {in_nd}")
                sys.exit(1)
        if not (sc["low"]["stranded"] <= sc["central"]["stranded"] <= sc["high"]["stranded"]):
            print(f"FAIL: Zone '{zone_id}' stranded monotonicity violated across low <= central <= high")
            sys.exit(1)
        if not (sc["low"]["total_payload_kg"] <= sc["central"]["total_payload_kg"] <= sc["high"]["total_payload_kg"]):
            print(f"FAIL: Zone '{zone_id}' payload monotonicity violated across low <= central <= high")
            sys.exit(1)
    # 10. Top-level verified flag
    if routes_data.get("verified") is not False:
        print(f"FAIL: Expected top-level 'verified': False, got: {routes_data.get('verified')}")
        sys.exit(1)
    print("PASS: Top-level verified: False verified")

    print("\n[AUDIT COMPLETE] ALL AUDIT CHECKS PASSED SUCCESSFULLY (Exit Code 0).")
    sys.exit(0)


if __name__ == "__main__":
    audit()
