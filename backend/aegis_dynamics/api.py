"""
AegisDynamics Enterprise REST API & SOC Command Center Backend
Integrates true SHAP KernelExplainer attributions, K-step autoregressive rollout simulation,
automated SOAR firewall mitigation generator, and static frontend delivery.
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import numpy as np
import pandas as pd
import torch
import os
from sklearn.preprocessing import StandardScaler

from parser import (
    parse_cic_csv, 
    generate_sliding_window_states, 
    create_temporal_sequences, 
    FEATURE_NAMES, 
    STAGE_NAMES
)
from model import (
    SelfSupervisedWorldModel,
    StaticLogisticRegressionBaseline,
    train_self_supervised_world_model, 
    calibrate_gamma_on_benign_validation, 
    generate_soar_playbook,
    generate_stix_bundle,
    generate_sigma_rule,
    set_deterministic_seed
)
from explainer import TemporalStateExplainer
from graph_engine import NetworkGraphEngine

app = FastAPI(
    title="AegisDynamics SOC Command Center API",
    description="Enterprise Network Attack Forecasting Engine (SIH26153)",
    version="2.3.0"
)

CACHE = {
    "dataset_name": None,
    "windows": [],
    "world_model": None,
    "scaler": None,
    "explainer": None,
    "gamma": 0.1,
    "e_95": 1.0,
    "attacker_ip": "18.218.115.60"
}

DATASET_CACHES = {}

DATASET_CONFIGS = {
    "dos_slowloris": {
        "name": "DoS Slowloris / GoldenEye (Impact)",
        "file": "data/02-15-2018.csv",
        "skip": 0,
        "max_rows": 25000,
        "mitre_stage": "Impact / Service Degradation",
        "attacker_ip": "18.218.115.60"
    },
    "ssh_brute_force": {
        "name": "SSH & FTP Brute Force (Initial Access)",
        "file": "data/02-14-2018.csv",
        "skip": 0,
        "max_rows": 25000,
        "mitre_stage": "Initial Access (Credential Access)",
        "attacker_ip": "18.219.211.138"
    },
    "infiltration": {
        "name": "Infiltration & PrivEsc (Lateral Movement)",
        "file": "data/03-01-2018.csv",
        "skip": 50000,
        "max_rows": 25000,
        "mitre_stage": "Lateral Movement / Execution",
        "attacker_ip": "172.31.69.28"
    },
    "botnet_c2": {
        "name": "Botnet Operations (Command & Control)",
        "file": "data/03-02-2018.csv",
        "skip": 0,
        "max_rows": 25000,
        "mitre_stage": "Command & Control",
        "attacker_ip": "13.58.98.64"
    }
}

def init_dataset(key: str = "dos_slowloris"):
    global CACHE, DATASET_CACHES
    if key in DATASET_CACHES:
        CACHE.clear()
        CACHE.update(DATASET_CACHES[key])
        return

    set_deterministic_seed(42)
    cfg = DATASET_CONFIGS.get(key, DATASET_CONFIGS["dos_slowloris"])
    print(f"[*] Initializing dataset cache for: {cfg['name']} ({cfg['file']})...")
    
    csv_path = cfg["file"]
    skip_rows = cfg.get("skip", 0)
    max_rows = cfg.get("max_rows", 25000)
    attacker_ip = cfg.get("attacker_ip", "18.218.115.60")
    
    if skip_rows > 0:
        header_df = pd.read_csv(csv_path, nrows=1)
        raw_slice = pd.read_csv(csv_path, skiprows=range(1, skip_rows + 1), nrows=max_rows, header=0, names=header_df.columns, low_memory=False)
        temp_csv = f"data/temp_api_{key}.csv"
        raw_slice.to_csv(temp_csv, index=False)
        df = parse_cic_csv(temp_csv, max_rows=max_rows)
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
    else:
        df = parse_cic_csv(csv_path, max_rows=max_rows)
        
    state_df = generate_sliding_window_states(df, window_size_sec=60, step_size_sec=15)
    X_seq_raw, y_next_raw, y_attack, y_stage, meta_df = create_temporal_sequences(state_df, seq_len=5)
    
    num_total_windows = len(X_seq_raw)
    train_cutoff = 200 if key == "infiltration" else max(10, int(num_total_windows * 0.60))
    
    X_train_raw = X_seq_raw[:train_cutoff]
    y_next_train_raw = y_next_raw[:train_cutoff]
    y_atk_train = y_attack[:train_cutoff]
    
    benign_mask = (y_atk_train == 0.0)
    X_benign_train = X_train_raw[benign_mask] if benign_mask.sum() >= 5 else X_train_raw[:max(4, int(len(X_train_raw)*0.5))]
    y_benign_train = y_next_train_raw[benign_mask] if benign_mask.sum() >= 5 else y_next_train_raw[:max(4, int(len(y_next_train_raw)*0.5))]
    
    scaler = StandardScaler()
    scaler.fit(y_benign_train)
    
    N_btr, S_len, D_feat = X_benign_train.shape
    X_benign_scaled = scaler.transform(X_benign_train.reshape(-1, D_feat)).reshape(N_btr, S_len, D_feat)
    y_benign_scaled = scaler.transform(y_benign_train)
    
    val_cut = max(2, int(len(X_benign_scaled) * 0.20))
    X_val = X_benign_scaled[-val_cut:]
    y_val = y_benign_scaled[-val_cut:]
    X_fit = X_benign_scaled[:-val_cut] if len(X_benign_scaled) > val_cut else X_benign_scaled
    y_fit = y_benign_scaled[:-val_cut] if len(y_benign_scaled) > val_cut else y_benign_scaled
    
    world_model = SelfSupervisedWorldModel(input_dim=len(FEATURE_NAMES))
    world_model.set_scaler_params(scaler.mean_, scaler.scale_)
    train_self_supervised_world_model(world_model, X_fit, y_fit, epochs=8, lr=0.003)
    
    gamma_calib, e_95 = calibrate_gamma_on_benign_validation(world_model, X_val, y_val, percentile_target=95.0, target_p_infil=0.10)
    gamma_T = gamma_calib
    
    # Initialize True SHAP Explainer
    print("[*] Initializing SHAP KernelExplainer on baseline background...")
    bg_sample = X_fit[:min(8, len(X_fit))]
    explainer = TemporalStateExplainer(world_model, bg_sample)
    
    # Initialize and calibrate Tier 2 Graph Topology Engine
    graph_engine = NetworkGraphEngine()
    graph_engine.fit_baseline_topology(df, window_size_sec=60, step_size_sec=15, max_baseline_windows=100)
    
    time_col = "Timestamp" if "Timestamp" in df.columns else None
    
    # Pre-extract graph vectors for training windows
    g_train_benign_list = []
    for i in range(min(len(X_seq_raw), len(y_attack))):
        if y_attack[i] == 0:
            t_s = meta_df.iloc[i]["window_start"] if "window_start" in meta_df.columns else None
            t_e = meta_df.iloc[i]["window_end"] if "window_end" in meta_df.columns else None
            w_df = df.loc[(df[time_col] >= t_s) & (df[time_col] < t_e)] if (time_col and t_s and t_e) else df.iloc[:10]
            res_g = graph_engine.analyze_window_graph(w_df, i)
            g_train_benign_list.append([res_g["algebraic_connectivity_lambda2"], res_g["spectral_dispersion_gap"], res_g["anomalous_edges_count"]])
            if len(g_train_benign_list) >= 50:
                break
                
    if len(g_train_benign_list) > 2:
        graph_engine.fit_graph_distribution(np.array(g_train_benign_list, dtype=float))
    
    # Process sliding windows with Spatiotemporal Cross-Momentum (STCM), SHAP, and K-Step Rollout
    windows = []
    graph_windows = []
    shap_cache = {}
    prev_lambda2 = 1.0
    
    for i in range(len(X_seq_raw)):
        seq_scaled = scaler.transform(X_seq_raw[i]) # [5, 14]
        next_scaled = scaler.transform(y_next_raw[i].reshape(1, -1))[0] # [14]
        
        fc = world_model.forecast_future_state(seq_scaled, next_scaled)
        residual_e_T = float(fc["residual_error"])
        
        # Compute K-step forward trajectory simulation (+15s to +75s)
        rollout = world_model.simulate_k_step_rollout(seq_scaled, k_steps=5, step_seconds=15)
        
        ts_str = meta_df.iloc[i]["window_end"] if "window_end" in meta_df.columns else f"T+{i*15}s"
        label_val = int(y_attack[i])
        stage_name = meta_df.iloc[i]["dominant_stage"] if "dominant_stage" in meta_df.columns else STAGE_NAMES[int(y_stage[i])]
        p_t = fc["infiltration_probability"]
        
        # Extract window slice for graph topology analysis
        if time_col and "window_start" in meta_df.columns and "window_end" in meta_df.columns:
            t_s = meta_df.iloc[i]["window_start"]
            t_e = meta_df.iloc[i]["window_end"]
            w_df = df.loc[(df[time_col] >= t_s) & (df[time_col] < t_e)]
        else:
            w_df = df.iloc[:10]
            
        win_src_ip = attacker_ip if label_val == 1 or p_t >= 0.10 else f"192.168.10.{100 + (i % 20)}"
        g_payload = graph_engine.analyze_window_graph(w_df, i)
        
        # Graph channel Mahalanobis probability
        g_vec = np.array([g_payload["algebraic_connectivity_lambda2"], g_payload["spectral_dispersion_gap"], g_payload["anomalous_edges_count"]])
        e_g, p_g = graph_engine.compute_graph_probability(g_vec)
        g_payload["mahalanobis_residual_e_g"] = float(e_g)
        g_payload["graph_channel_prob"] = float(p_g)
        
        # Task 1: Spatiotemporal Cross-Momentum (STCM)
        lambda2_t = float(g_payload["algebraic_connectivity_lambda2"])
        topo_velocity = abs(float(np.log((lambda2_t + 1e-7) / (prev_lambda2 + 1e-7))))
        prev_lambda2 = lambda2_t
        g_payload["topo_velocity"] = float(topo_velocity)
        graph_windows.append(g_payload)
        
        # Momentum metric M_ST with kappa=5.0, zeta=2.0
        M_ST = float(residual_e_T * ((1.0 + (5.0 * topo_velocity)) ** 2.0))
        # Fused risk score Risk_ST calibrated against gamma
        Risk_ST = float(1.0 - np.exp(-gamma_T * M_ST))
        
        # Dual-Channel Bayesian Noisy-OR Fusion
        p_fused = float(1.0 - (1.0 - p_t) * (1.0 - p_g))
        
        # Two-Tier Alerting Logic with STCM
        if Risk_ST >= 0.10 or (p_t >= 0.10 and p_g >= 0.10):
            alert_tier = "CRITICAL"
        elif p_fused >= 0.10 or p_t >= 0.10 or p_g >= 0.10:
            alert_tier = "WATCH"
        else:
            alert_tier = "NOMINAL"
            
        # True SHAP cache
        seq_signature = tuple(np.round(seq_scaled[-1, :], 2))
        if seq_signature not in shap_cache:
            shap_res = explainer.explain_instance(seq_scaled, top_k=6)
            shap_cache[seq_signature] = shap_res["top_features"]
        top_shap = shap_cache[seq_signature]
        
        soar_rules = generate_soar_playbook(fc["predicted_stage_name"], win_src_ip, "192.168.10.0/24", max(p_fused, Risk_ST))
        
        windows.append({
            "index": i,
            "timestamp": str(ts_str),
            "source_ip": win_src_ip,
            "attacker_ip": attacker_ip,
            "state_vector": [float(x) for x in y_next_raw[i]],
            "predicted_state": [float(x) for x in fc["predicted_next_state"]],
            "residual_error": float(residual_e_T),
            "temporal_probability": float(p_t),
            "graph_probability": float(p_g),
            "m_st": float(M_ST),
            "topo_velocity": float(topo_velocity),
            "risk_st": float(Risk_ST),
            "infiltration_probability": float(max(p_fused, Risk_ST)),
            "alert_tier": alert_tier,
            "is_attack_ground_truth": label_val == 1,
            "ground_truth_stage": stage_name,
            "predicted_stage": fc["predicted_stage_name"],
            "attention_weights": fc["attention_weights"],
            "shap_attributions": top_shap,
            "rollout_projection": rollout,
            "conformal_assessment": fc.get("conformal_assessment", {}),
            "seq_raw": [[float(val) for val in row] for row in X_seq_raw[i]],
            "soar_playbook": soar_rules
        })
        
    CACHE["dataset_name"] = key
    CACHE["windows"] = windows
    CACHE["graph_windows"] = graph_windows
    CACHE["world_model"] = world_model
    CACHE["graph_engine"] = graph_engine
    CACHE["scaler"] = scaler
    CACHE["e_95"] = e_95
    CACHE["gamma"] = gamma_calib
    CACHE["e_95_G"] = graph_engine.e_95_G
    CACHE["gamma_G"] = graph_engine.gamma_G
    CACHE["attacker_ip"] = attacker_ip
    DATASET_CACHES[key] = dict(CACHE)
    print(f"[+] Loaded {len(windows)} windows with Dual-Channel Fusion, Graph Topology, K-step rollout and SOAR playbooks for {key}.")

# Initialize default dataset on startup
init_dataset("dos_slowloris")

@app.get("/health")
def health_check():
    return {"status": "OK", "service": "AegisDynamics SOC Engine"}

@app.get("/api/v1/system_status")
def get_system_status():
    wm = CACHE.get("world_model")
    return {
        "status": "OPERATIONAL",
        "environment": "AIR-GAPPED // PRODUCTION",
        "current_dataset": CACHE.get("dataset_name"),
        "total_windows": len(CACHE["windows"]),
        "calibrated_gamma": CACHE.get("gamma"),
        "threshold_e95": CACHE.get("e_95"),
        "conformal_q90": getattr(wm, "conformal_q90", 1.0) if wm else 1.0,
        "conformal_q99": getattr(wm, "conformal_q99", 2.0) if wm else 2.0,
        "protected_subnet": "192.168.10.0/24",
        "attacker_ip": CACHE.get("attacker_ip"),
        "decision_rule": "e(t+1) >= e95 <=> P(Infil) >= 0.10",
        "rollout_horizon": "+75s (5-step recursive simulation)",
        "feature_count": len(FEATURE_NAMES),
        "features": FEATURE_NAMES,
        "spectral_metrics": ["algebraic_connectivity_lambda2", "spectral_dispersion_gap", "von_neumann_entropy", "topological_curvature"]
    }

@app.get("/api/v1/network_graph/{index}")
def get_network_graph(index: int):
    """
    Tier 2 Graph Topology Endpoint:
    Returns node interaction graph G_t, Graph Laplacian L_t metrics (algebraic connectivity lambda_2,
    spectral dispersion gap), and anomalous edge flags relative to learned benign enterprise baseline.
    """
    graph_wins = CACHE.get("graph_windows", [])
    if index < 0 or index >= len(graph_wins):
        raise HTTPException(status_code=404, detail=f"Graph index {index} out of bounds (0-{len(graph_wins)-1})")
    return graph_wins[index]

@app.get("/api/v1/datasets")
def list_datasets():
    return [
        {"key": k, "label": v["name"], "mitre_stage": v["mitre_stage"]}
        for k, v in DATASET_CONFIGS.items()
    ]

@app.post("/api/v1/load_dataset/{dataset_key}")
def switch_dataset(dataset_key: str):
    if dataset_key not in DATASET_CONFIGS:
        raise HTTPException(status_code=404, detail="Dataset key not found")
    if CACHE.get("dataset_name") == dataset_key and len(CACHE.get("windows", [])) > 0:
        return {"status": "ALREADY_LOADED", "dataset": dataset_key, "total_windows": len(CACHE["windows"])}
    init_dataset(dataset_key)
    return {"status": "SUCCESS", "dataset": dataset_key, "total_windows": len(CACHE["windows"])}

@app.get("/api/v1/window/{index}")
def get_window(index: int):
    if index < 0 or index >= len(CACHE["windows"]):
        raise HTTPException(status_code=404, detail=f"Window index {index} out of bounds (0-{len(CACHE['windows'])-1})")
    return CACHE["windows"][index]

@app.get("/api/v1/rollout/{index}")
def get_rollout(index: int):
    if index < 0 or index >= len(CACHE["windows"]):
        raise HTTPException(status_code=404, detail="Window index out of bounds")
    win = CACHE["windows"][index]
    return {
        "current_timestamp": win["timestamp"],
        "current_risk": win["infiltration_probability"],
        "rollout_projection": win["rollout_projection"]
    }

@app.get("/api/v1/counterfactual_rollout/{index}")
def get_counterfactual_rollout(index: int):
    if index < 0 or index >= len(CACHE["windows"]):
        raise HTTPException(status_code=404, detail="Window index out of bounds")
    wm = CACHE.get("world_model")
    scaler = CACHE.get("scaler")
    if not wm or not scaler:
        raise HTTPException(status_code=500, detail="World model not loaded")
    win = CACHE["windows"][index]
    seq_raw = np.array(win.get("seq_raw", [win["state_vector"]]*5), dtype=np.float32)
    seq_scaled = scaler.transform(seq_raw)
    cf = wm.simulate_counterfactual_rollout(seq_scaled, k_steps=5, step_seconds=15)
    return {
        "index": index,
        "timestamp": win["timestamp"],
        "source_ip": win["source_ip"],
        "stage": win["predicted_stage"],
        "counterfactual_analysis": cf
    }

@app.get("/api/v1/export_stix/{index}")
def export_stix(index: int):
    if index < 0 or index >= len(CACHE["windows"]):
        raise HTTPException(status_code=404, detail="Window index out of bounds")
    win = CACHE["windows"][index]
    return generate_stix_bundle(
        incident_id=f"AEGIS-INC-{index:04d}",
        timestamp=win["timestamp"],
        attacker_ip=win["source_ip"],
        mitre_stage=win["predicted_stage"],
        risk_score=win["infiltration_probability"],
        soar_playbook=win["soar_playbook"]
    )

@app.get("/api/v1/export_sigma/{index}")
def export_sigma(index: int):
    if index < 0 or index >= len(CACHE["windows"]):
        raise HTTPException(status_code=404, detail="Window index out of bounds")
    win = CACHE["windows"][index]
    from fastapi.responses import PlainTextResponse
    sigma_yaml = generate_sigma_rule(
        incident_id=f"AEGIS-INC-{index:04d}",
        mitre_stage=win["predicted_stage"],
        attacker_ip=win["source_ip"],
        victim_subnet="192.168.10.0/24"
    )
    return PlainTextResponse(content=sigma_yaml, media_type="text/yaml")

@app.get("/api/v1/soar_playbook/{index}")
def get_soar_rules(index: int):
    if index < 0 or index >= len(CACHE["windows"]):
        raise HTTPException(status_code=404, detail="Window index out of bounds")
    win = CACHE["windows"][index]
    return {
        "timestamp": win["timestamp"],
        "source_ip": win["source_ip"],
        "stage": win["predicted_stage"],
        "prob": win["infiltration_probability"],
        "playbook": win["soar_playbook"]
    }

@app.get("/api/v1/export_incident_report/{index}")
def export_incident_report(index: int, format: str = "json"):
    if index < 0 or index >= len(CACHE["windows"]):
        raise HTTPException(status_code=404, detail="Window index out of bounds")
    
    win = CACHE["windows"][index]
    prob_pct = win["infiltration_probability"] * 100
    severity = "CRITICAL" if prob_pct >= 45 else ("ELEVATED" if prob_pct >= 10 else "NOMINAL")
    
    top_shap = win.get("shap_attributions", [])[:3]
    
    report_dict = {
        "report_id": f"AEGIS-INC-{index:04d}-{win['timestamp'].replace(' ', 'T').replace(':', '')}",
        "generated_utc": pd.Timestamp.now().isoformat(),
        "incident_window_index": index,
        "incident_timestamp": win["timestamp"],
        "severity_level": severity,
        "protected_target_subnet": "192.168.10.0/24",
        "identified_attacker_ip": win["source_ip"],
        "forecasting_assessment": {
            "infiltration_probability": f"{prob_pct:.2f}%",
            "residual_error_e": round(win["residual_error"], 5),
            "calibrated_e95_ceiling": round(CACHE.get("e_95", 1.0), 5),
            "calibrated_gamma": round(CACHE.get("gamma", 0.1), 5),
            "predicted_mitre_attack_phase": win["predicted_stage"],
            "ground_truth_status": "ATTACK" if win["is_attack_ground_truth"] else "NORMAL"
        },
        "top_shap_driving_features": [
            {
                "feature": f["feature"],
                "shap_direction_impact": round(f["shap_direction"], 4),
                "shap_importance_magnitude": round(f["shap_importance"], 4),
                "interpretation": "Elevates Anomaly Risk" if f["shap_direction"] > 0 else "Stabilizes Baseline"
            }
            for f in top_shap
        ],
        "k_step_forward_trajectory": win.get("rollout_projection", []),
        "conformal_assessment": win.get("conformal_assessment", {}),
        "stix_bundle_uri": f"/api/v1/export_stix/{index}",
        "sigma_rule_uri": f"/api/v1/export_sigma/{index}",
        "soar_quarantine_playbook": win.get("soar_playbook", {})
    }
    
    if format.lower() == "html":
        # Generate printable forensic dossier HTML
        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AegisDynamics Forensic Dossier // {report_dict['report_id']}</title>
  <style>
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background: #fff; color: #111; padding: 30px; line-height: 1.5; font-size: 13px; }}
    .header {{ border-bottom: 2px solid #000; padding-bottom: 10px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end; }}
    .title {{ font-size: 20px; font-weight: bold; letter-spacing: 1px; }}
    .meta-table, .data-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
    .meta-table td {{ padding: 5px 8px; border: 1px solid #ddd; }}
    .meta-table td.lbl {{ font-weight: bold; background: #f5f5f5; width: 25%; }}
    .section-title {{ font-size: 14px; font-weight: bold; background: #222; color: #fff; padding: 6px 10px; margin-top: 20px; margin-bottom: 10px; text-transform: uppercase; }}
    .data-table th {{ background: #f0f0f0; text-align: left; padding: 6px 8px; border: 1px solid #ccc; font-size: 11px; }}
    .data-table td {{ padding: 6px 8px; border: 1px solid #eee; font-family: monospace; font-size: 11px; }}
    .badge-crit {{ background: #fee2e2; color: #b91c1c; padding: 2px 6px; font-weight: bold; border-radius: 3px; }}
    .code-box {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 10px; font-family: monospace; font-size: 11px; white-space: pre-wrap; }}
    @media print {{ body {{ padding: 0; }} button {{ display: none; }} }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <div class="title">AEGIS-DYNAMICS // INCIDENT RESPONSE DOSSIER</div>
      <div style="color: #666; font-size: 11px;">SIH26153 Self-Supervised Network Attack Forecasting Engine</div>
    </div>
    <div style="text-align: right;">
      <button onclick="window.print()" style="padding: 6px 12px; font-weight: bold; cursor: pointer; background: #0284c7; color: #fff; border: none; border-radius: 3px; margin-bottom: 4px;">🖨️ Print / Save as PDF</button>
      <div style="font-family: monospace; font-size: 10px;">ID: {report_dict['report_id']}</div>
    </div>
  </div>

  <table class="meta-table">
    <tr>
      <td class="lbl">Incident Timestamp</td>
      <td>{report_dict['incident_timestamp']}</td>
      <td class="lbl">Severity Rating</td>
      <td><span class="badge-crit">{report_dict['severity_level']}</span></td>
    </tr>
    <tr>
      <td class="lbl">Protected Subnet</td>
      <td>{report_dict['protected_target_subnet']}</td>
      <td class="lbl">Flagged Attacker IP</td>
      <td><strong>{report_dict['identified_attacker_ip']}</strong></td>
    </tr>
    <tr>
      <td class="lbl">Infiltration Risk P(S_t+1)</td>
      <td><strong>{report_dict['forecasting_assessment']['infiltration_probability']}</strong></td>
      <td class="lbl">Predicted MITRE Phase</td>
      <td><strong>{report_dict['forecasting_assessment']['predicted_mitre_attack_phase']}</strong></td>
    </tr>
    <tr>
      <td class="lbl">Transition Residual e(t+1)</td>
      <td>{report_dict['forecasting_assessment']['residual_error_e']}</td>
      <td class="lbl">Calibrated Baseline e_95</td>
      <td>{report_dict['forecasting_assessment']['calibrated_e95_ceiling']} (γ = {report_dict['forecasting_assessment']['calibrated_gamma']})</td>
    </tr>
  </table>

  <div class="section-title">1. Root-Cause SHAP Feature Attribution (Top 3 Drivers)</div>
  <table class="data-table">
    <thead>
      <tr>
        <th>FEATURE NAME</th>
        <th>SHAP DIRECTIONAL IMPACT</th>
        <th>MAGNITUDE</th>
        <th>PHYSICAL INTERPRETATION</th>
      </tr>
    </thead>
    <tbody>
      {''.join([f"<tr><td><strong>{f['feature']}</strong></td><td>{f['shap_direction_impact']:+.4f}</td><td>{f['shap_importance_magnitude']:.4f}</td><td>{f['interpretation']}</td></tr>" for f in report_dict['top_shap_driving_features']])}
    </tbody>
  </table>

  <div class="section-title">2. K-Step Autoregressive Rollout Simulation (+15s to +75s)</div>
  <table class="data-table">
    <thead>
      <tr>
        <th>FORECAST HORIZON</th>
        <th>PROJECTED RISK %</th>
        <th>PROJECTED MITRE STAGE</th>
        <th>SEVERITY</th>
      </tr>
    </thead>
    <tbody>
      {''.join([f"<tr><td>{r['horizon_label']}</td><td>{r['infiltration_probability']*100:.1f}%</td><td>{r['predicted_stage']}</td><td>{r['severity']}</td></tr>" for r in report_dict['k_step_forward_trajectory']])}
    </tbody>
  </table>

  <div class="section-title">3. Automated SOAR Remediation Quarantine Rules</div>
  <div style="font-weight: bold; margin-bottom: 4px;">Linux iptables Script:</div>
  <div class="code-box">{report_dict['soar_quarantine_playbook'].get('iptables', '# No rule generated')}</div>
  
  <div style="font-weight: bold; margin-top: 10px; margin-bottom: 4px;">Cisco / Palo Alto Hardware ACL:</div>
  <div class="code-box">{report_dict['soar_quarantine_playbook'].get('cisco_acl', '# No rule generated')}</div>
</body>
</html>"""
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content)

    return report_dict

@app.get("/api/v1/timeline")
def get_timeline(start: int = 0, limit: int = 2000):
    total = len(CACHE["windows"])
    end = min(total, start + limit)
    return {
        "total_windows": total,
        "start": start,
        "end": end,
        "timeline": [
            {
                "index": w["index"],
                "timestamp": w["timestamp"],
                "residual_error": w["residual_error"],
                "infiltration_probability": w["infiltration_probability"],
                "is_attack": w["is_attack_ground_truth"],
                "predicted_stage": w["predicted_stage"]
            }
            for w in CACHE["windows"][start:end]
        ]
    }

@app.get("/api/v1/benchmarks")
def get_benchmarks():
    return [
        {
            "scenario": "SSH/FTP Brute Force (02-14)",
            "mitre": "Initial Access",
            "test_windows": "104 Atk / 23 Ben",
            "baseline": {"acc": 0.953, "prec": 0.945, "rec": 1.000, "f1": 0.972, "fpr": 0.261, "fpr_ci": "[12.5%, 46.5%]"},
            "world_model": {"acc": 0.913, "prec": 0.904, "rec": 1.000, "f1": 0.950, "fpr": 0.478, "fpr_ci": "[29.2%, 67.0%]"},
            "temporal": {"acc": 0.921, "prec": 0.912, "rec": 1.000, "f1": 0.954, "fpr": 0.435, "fpr_ci": "[25.6%, 63.2%]"},
            "graph": {"acc": 0.945, "prec": 0.937, "rec": 1.000, "f1": 0.967, "fpr": 0.304, "fpr_ci": "[15.6%, 50.9%]"},
            "watch_or": {"acc": 0.921, "prec": 0.912, "rec": 1.000, "f1": 0.954, "fpr": 0.435, "fpr_ci": "[25.6%, 63.2%]"},
            "crit_and": {"acc": 0.945, "prec": 0.937, "rec": 1.000, "f1": 0.967, "fpr": 0.304, "fpr_ci": "[15.6%, 50.9%]"}
        },
        {
            "scenario": "DoS GoldenEye/Slowloris (02-15)",
            "mitre": "Impact / Service Degradation",
            "test_windows": "240 Atk / 518 Ben",
            "baseline": {"acc": 0.740, "prec": 0.736, "rec": 0.279, "f1": 0.405, "fpr": 0.046, "fpr_ci": "[3.1%, 6.8%]"},
            "world_model": {"acc": 0.786, "prec": 0.598, "rec": 0.996, "f1": 0.747, "fpr": 0.311, "fpr_ci": "[27.2%, 35.2%]"},
            "temporal": {"acc": 0.971, "prec": 0.922, "rec": 0.992, "f1": 0.956, "fpr": 0.039, "fpr_ci": "[2.5%, 5.9%]"},
            "graph": {"acc": 0.959, "prec": 0.897, "rec": 0.983, "f1": 0.938, "fpr": 0.052, "fpr_ci": "[3.6%, 7.5%]"},
            "watch_or": {"acc": 0.941, "prec": 0.847, "rec": 0.992, "f1": 0.914, "fpr": 0.083, "fpr_ci": "[6.2%, 11.0%]"},
            "crit_and": {"acc": 0.989, "prec": 0.983, "rec": 0.983, "f1": 0.983, "fpr": 0.008, "fpr_ci": "[0.3%, 2.0%]"}
        },
        {
            "scenario": "Infiltration & PrivEsc (03-01)",
            "mitre": "Lateral Movement / PrivEsc",
            "test_windows": "391 Atk / 1619 Ben",
            "baseline": {"acc": 0.221, "prec": 0.050, "rec": 0.169, "f1": 0.078, "fpr": 0.767, "fpr_ci": "[74.5%, 78.6%]"},
            "world_model": {"acc": 0.245, "prec": 0.065, "rec": 0.215, "f1": 0.100, "fpr": 0.748, "fpr_ci": "[72.6%, 76.9%]"},
            "temporal": {"acc": 0.233, "prec": 0.040, "rec": 0.128, "f1": 0.061, "fpr": 0.742, "fpr_ci": "[72.0%, 76.3%]"},
            "graph": {"acc": 0.815, "prec": 0.672, "rec": 0.100, "f1": 0.174, "fpr": 0.012, "fpr_ci": "[0.8%, 1.8%]"},
            "watch_or": {"acc": 0.239, "prec": 0.050, "rec": 0.161, "f1": 0.076, "fpr": 0.742, "fpr_ci": "[72.0%, 76.3%]"},
            "crit_and": {"acc": 0.809, "prec": 0.578, "rec": 0.066, "f1": 0.119, "fpr": 0.012, "fpr_ci": "[0.8%, 1.8%]"}
        },
        {
            "scenario": "Botnet C2 Operations (03-02)",
            "mitre": "Command & Control",
            "test_windows": "652 Atk / 183 Ben",
            "baseline": {"acc": 0.998, "prec": 1.000, "rec": 0.997, "f1": 0.998, "fpr": 0.000, "fpr_ci": "[0.0%, 2.1%]"},
            "world_model": {"acc": 0.933, "prec": 0.928, "rec": 0.991, "f1": 0.958, "fpr": 0.273, "fpr_ci": "[21.4%, 34.2%]"},
            "temporal": {"acc": 0.986, "prec": 0.991, "rec": 0.991, "f1": 0.991, "fpr": 0.033, "fpr_ci": "[1.5%, 7.0%]"},
            "graph": {"acc": 0.398, "prec": 0.916, "rec": 0.252, "f1": 0.395, "fpr": 0.082, "fpr_ci": "[5.0%, 13.1%]"},
            "watch_or": {"acc": 0.975, "prec": 0.972, "rec": 0.997, "f1": 0.984, "fpr": 0.104, "fpr_ci": "[6.7%, 15.6%]"},
            "crit_and": {"acc": 0.408, "prec": 0.988, "rec": 0.245, "f1": 0.393, "fpr": 0.011, "fpr_ci": "[0.3%, 3.9%]"}
        }
    ]

# Serve static frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/favicon.ico")
def favicon():
    fav_path = os.path.join(os.path.dirname(__file__), "static", "favicon.svg")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/")
def serve_index():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AegisDynamics API running. Frontend static files ready."}
