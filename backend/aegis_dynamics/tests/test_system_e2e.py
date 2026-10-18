"""
Master Automated End-to-End Self-Verification Suite
AegisDynamics Backend REST API Audit (Ports 8000 & 8501)
"""

import sys
import json
import requests
import time

BASE_URL = "http://127.0.0.1:8000"
STREAMLIT_URL = "http://127.0.0.1:8501"

class TestReport:
    def __init__(self):
        self.results = []

    def log(self, category, test_name, status, details=""):
        self.results.append({
            "category": category,
            "test_name": test_name,
            "status": status,
            "details": details
        })
        mark = "[PASS]" if status == "PASS" else "[FAIL]" if status == "FAIL" else "[WARN]"
        print(f" {mark} [{category}] {test_name}: {details}")

def run_backend_audit():
    report = TestReport()
    print("\n" + "="*80)
    print("      AEGISDYNAMICS MASTER E2E BACKEND API VERIFICATION SUITE")
    print("="*80)

    # 1. System Health & Status
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        assert r.status_code == 200 and r.json().get("status") == "OK"
        report.log("Health", "GET /health", "PASS", "HTTP 200, status == 'OK'")
    except Exception as e:
        report.log("Health", "GET /health", "FAIL", str(e))

    try:
        r = requests.get(f"{BASE_URL}/api/v1/system_status", timeout=5)
        data = r.json()
        assert r.status_code == 200
        assert "calibrated_gamma" in data
        assert "threshold_e95" in data
        assert len(data.get("features", [])) == 14
        report.log("Health", "GET /api/v1/system_status", "PASS", f"e_95={data['threshold_e95']:.4f}, gamma={data['calibrated_gamma']:.4f}, 14 features")
    except Exception as e:
        report.log("Health", "GET /api/v1/system_status", "FAIL", str(e))

    # 2. Benchmarks Endpoint
    try:
        r = requests.get(f"{BASE_URL}/api/v1/benchmarks", timeout=5)
        data = r.json()
        assert r.status_code == 200 and len(data) == 4
        scens = [d.get("scenario") for d in data]
        report.log("Benchmarks", "GET /api/v1/benchmarks", "PASS", f"Returned 4 scenarios: {', '.join(scens)}")
    except Exception as e:
        report.log("Benchmarks", "GET /api/v1/benchmarks", "FAIL", str(e))

    # 3. Multi-Scenario Dataset Switching & Telemetry
    scenarios = [
        ("dos_slowloris", "DoS GoldenEye / Slowloris"),
        ("ssh_brute_force", "SSH / FTP Brute Force"),
        ("infiltration", "Infiltration & Lateral Movement"),
        ("botnet_c2", "Botnet C2 Beaconing")
    ]

    for key, name in scenarios:
        print(f"\n[*] Testing Scenario Pipeline: {name} ({key})...")
        try:
            t0 = time.time()
            r = requests.post(f"{BASE_URL}/api/v1/load_dataset/{key}", timeout=90)
            data = r.json()
            assert r.status_code == 200 and (data.get("status") in ["OK", "SUCCESS", "ALREADY_LOADED"])
            report.log("Dataset", f"POST /api/v1/load_dataset/{key}", "PASS", f"Loaded in {time.time()-t0:.2f}s, windows={data.get('total_windows')}")
        except Exception as e:
            report.log("Dataset", f"POST /api/v1/load_dataset/{key}", "FAIL", str(e))
            continue

        # Test Timeline
        try:
            r = requests.get(f"{BASE_URL}/api/v1/timeline?limit=100", timeout=5)
            data = r.json()
            assert r.status_code == 200
            assert "timeline" in data and len(data["timeline"]) > 0
            report.log("Timeline", f"GET /api/v1/timeline ({key})", "PASS", f"Total windows: {data.get('total_windows')}, returned {len(data['timeline'])}")
        except Exception as e:
            report.log("Timeline", f"GET /api/v1/timeline ({key})", "FAIL", str(e))

        # Test Window Telemetry (STCM variables)
        try:
            r = requests.get(f"{BASE_URL}/api/v1/window/0", timeout=5)
            win = r.json()
            assert r.status_code == 200
            assert "m_st" in win
            assert "topo_velocity" in win
            assert "risk_st" in win
            assert "predicted_stage" in win
            assert "soar_playbook" in win and len(win["soar_playbook"]) > 0
            report.log("STCM Telemetry", f"GET /api/v1/window/0 ({key})", "PASS", f"M_ST={win['m_st']:.4f}, v_topo={win['topo_velocity']:.4f}, Risk_ST={win['risk_st']:.4f}, Stage={win['predicted_stage']}")
        except Exception as e:
            report.log("STCM Telemetry", f"GET /api/v1/window/0 ({key})", "FAIL", str(e))

        # Test Rollout (+15s to +75s)
        try:
            r = requests.get(f"{BASE_URL}/api/v1/rollout/0", timeout=5)
            rollout = r.json()
            assert r.status_code == 200
            assert "rollout_projection" in rollout
            steps = len(rollout["rollout_projection"])
            assert steps == 5
            report.log("Rollout", f"GET /api/v1/rollout/0 ({key})", "PASS", f"Verified {steps}-step forward projection (+15s to +75s)")
        except Exception as e:
            report.log("Rollout", f"GET /api/v1/rollout/0 ({key})", "FAIL", str(e))

        # Test Network Graph Topology
        try:
            r = requests.get(f"{BASE_URL}/api/v1/network_graph/0", timeout=5)
            graph = r.json()
            assert r.status_code == 200
            assert "nodes" in graph and len(graph["nodes"]) > 0
            assert "algebraic_connectivity_lambda2" in graph
            assert "spectral_dispersion_gap" in graph
            report.log("Graph Topology", f"GET /api/v1/network_graph/0 ({key})", "PASS", f"Nodes: {graph.get('num_nodes')}, Edges: {len(graph.get('edges', []))}, lambda2={graph.get('algebraic_connectivity_lambda2'):.4f}")
        except Exception as e:
            report.log("Graph Topology", f"GET /api/v1/network_graph/0 ({key})", "FAIL", str(e))

    # 4. Upgraded Advanced Threat Intel & Simulation Endpoints
    print("\n[*] Testing Counterfactual Rollout Simulation & Threat Intel Export Engines...")
    try:
        r = requests.get(f"{BASE_URL}/api/v1/counterfactual_rollout/0", timeout=5)
        cf_data = r.json()
        assert r.status_code == 200
        assert "counterfactual_analysis" in cf_data
        cf = cf_data["counterfactual_analysis"]
        assert "status_quo_trajectory" in cf
        assert "mitigated_trajectory" in cf
        assert "risk_reduction_efficiency_pct" in cf
        report.log("Counterfactual", "GET /api/v1/counterfactual_rollout/0", "PASS", f"Twin trajectories simulated: {cf['remediation_verdict']}")
    except Exception as e:
        report.log("Counterfactual", "GET /api/v1/counterfactual_rollout/0", "FAIL", str(e))

    try:
        r = requests.get(f"{BASE_URL}/api/v1/export_stix/0", timeout=5)
        stix_data = r.json()
        assert r.status_code == 200
        assert stix_data.get("type") == "bundle"
        assert stix_data.get("spec_version") == "2.1"
        assert len(stix_data.get("objects", [])) >= 4
        report.log("Threat Intel", "GET /api/v1/export_stix/0", "PASS", f"Valid OASIS STIX 2.1 Bundle: {len(stix_data['objects'])} objects")
    except Exception as e:
        report.log("Threat Intel", "GET /api/v1/export_stix/0", "FAIL", str(e))

    try:
        r = requests.get(f"{BASE_URL}/api/v1/export_sigma/0", timeout=5)
        sigma_txt = r.text
        assert r.status_code == 200
        assert "title: AegisDynamics Detected" in sigma_txt
        assert "detection:" in sigma_txt
        report.log("SIEM Export", "GET /api/v1/export_sigma/0", "PASS", f"Valid Sigma Rule YAML ({len(sigma_txt)} bytes)")
    except Exception as e:
        report.log("SIEM Export", "GET /api/v1/export_sigma/0", "FAIL", str(e))

    # 5. Forensic Report Export Engine
    print("\n[*] Testing Forensic Report Export Engine...")
    try:
        r = requests.get(f"{BASE_URL}/api/v1/export_incident_report/10?format=json", timeout=5)
        dossier = r.json()
        assert r.status_code == 200
        assert "report_id" in dossier
        assert "identified_attacker_ip" in dossier
        assert "forecasting_assessment" in dossier
        assert "soar_quarantine_playbook" in dossier
        report.log("Export", "GET /export_incident_report (JSON)", "PASS", f"Valid incident structure {dossier['report_id']}. Attacker: {dossier.get('identified_attacker_ip')}")
    except Exception as e:
        report.log("Export", "GET /export_incident_report (JSON)", "FAIL", str(e))

    try:
        r = requests.get(f"{BASE_URL}/api/v1/export_incident_report/10?format=html", timeout=5)
        html_text = r.text
        assert r.status_code == 200
        assert len(html_text) > 1000
        assert "AEGIS-DYNAMICS // INCIDENT RESPONSE DOSSIER" in html_text
        report.log("Export", "GET /export_incident_report (HTML)", "PASS", f"Valid HTML dossier ({len(html_text)} bytes)")
    except Exception as e:
        report.log("Export", "GET /export_incident_report (HTML)", "FAIL", str(e))

    # 6. Streamlit Health Probe
    print("\n[*] Testing Streamlit Forensic Dashboard Probe (Port 8501)...")
    try:
        r = requests.get(STREAMLIT_URL, timeout=5)
        assert r.status_code == 200
        report.log("Streamlit", "GET http://127.0.0.1:8501", "PASS", f"Streamlit Dashboard UP & responding with HTTP {r.status_code}")
    except Exception as e:
        report.log("Streamlit", "GET http://127.0.0.1:8501", "FAIL", str(e))

    print("\n" + "="*80)
    print("                     BACKEND TEST EXECUTION COMPLETE")
    print("="*80)
    return report

if __name__ == "__main__":
    report = run_backend_audit()
    passed = sum(1 for r in report.results if r["status"] == "PASS")
    failed = sum(1 for r in report.results if r["status"] == "FAIL")
    print(f"\nFinal Backend Summary: Total: {len(report.results)} | Passed: {passed} | Failed: {failed}")
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
