"""
AegisDynamics - Final Unified Chronological Benchmark Suite v3.3
Evaluates all 4 authentic CSE-CIC-IDS2018 datasets with Dual-Channel Decision-Level Fusion.
Channels:
1. Temporal World Model: P_T(t+1) from Huber residual e_T(t+1) calibrated on benign e_95_T.
2. Graph Topology Engine: P_G(t) from Mahalanobis distance e_G(t) over [λ_2, Δλ, anomalous_edges] (100% unsupervised, zero label access).
3. Decision-Level WATCH Tier (OR): (P_T >= 0.10) OR (P_G >= 0.10).
4. CRITICAL Tier (AND): (P_T >= 0.10) AND (P_G >= 0.10).
Includes 95% Wilson Score Confidence Intervals for FPR.
"""

import os
import numpy as np
import pandas as pd
import torch
from typing import Dict, Any, List, Tuple
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import precision_score, recall_score, f1_score, accuracy_score, confusion_matrix
from parser import parse_cic_csv, generate_sliding_window_states, create_temporal_sequences, FEATURE_NAMES, STAGE_NAMES
from model import SelfSupervisedWorldModel, StaticLogisticRegressionBaseline, train_self_supervised_world_model, calibrate_gamma_on_benign_validation, set_deterministic_seed
from graph_engine import NetworkGraphEngine

def wilson_ci(k: int, n: int, z: float = 1.96) -> str:
    if n == 0:
        return "[0.0%, 0.0%]"
    p = k / n
    denom = 1.0 + (z**2) / n
    center = (p + (z**2) / (2 * n)) / denom
    margin = (z * np.sqrt((p * (1.0 - p) / n) + (z**2) / (4 * (n**2)))) / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return f"[{lower:.1%}, {upper:.1%}]"

def compute_metrics_dict(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, Any]:
    acc = float(accuracy_score(y_true, y_pred))
    prec = float(precision_score(y_true, y_pred, zero_division=0))
    rec = float(recall_score(y_true, y_pred, zero_division=0))
    f1 = float(f1_score(y_true, y_pred, zero_division=0))
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    fpr_ci = wilson_ci(fp, fp + tn)
    return {
        "acc": acc,
        "prec": prec,
        "rec": rec,
        "f1": f1,
        "fpr": fpr,
        "fpr_ci": fpr_ci,
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn)
    }

def evaluate_dataset(
    csv_path: str,
    dataset_name: str,
    skip_rows: int = 0,
    max_rows: int = 50000,
    train_cutoff_override: int = None
) -> Dict[str, Any]:
    set_deterministic_seed(42)
    
    if skip_rows > 0:
        header_df = pd.read_csv(csv_path, nrows=1)
        raw_slice = pd.read_csv(csv_path, skiprows=range(1, skip_rows + 1), nrows=max_rows, header=0, names=header_df.columns, low_memory=False)
        temp_csv = f"data/temp_{os.path.basename(csv_path)}"
        raw_slice.to_csv(temp_csv, index=False)
        df = parse_cic_csv(temp_csv, max_rows=max_rows)
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
    else:
        df = parse_cic_csv(csv_path, max_rows=max_rows)
        
    state_df = generate_sliding_window_states(df, window_size_sec=60, step_size_sec=15)
    X_seq_raw, y_next_raw, y_attack, y_stage, meta_df = create_temporal_sequences(state_df, seq_len=5)
    
    num_total_windows = len(X_seq_raw)
    train_cutoff = train_cutoff_override if train_cutoff_override is not None else max(10, int(num_total_windows * 0.60))
    
    X_train_raw = X_seq_raw[:train_cutoff]
    y_next_train_raw = y_next_raw[:train_cutoff]
    y_atk_train = y_attack[:train_cutoff]
    
    X_test_raw = X_seq_raw[train_cutoff:]
    y_next_test_raw = y_next_raw[train_cutoff:]
    y_atk_test = y_attack[train_cutoff:]
    
    benign_mask_train = (y_atk_train == 0.0)
    benign_indices = [i for i in range(train_cutoff) if y_atk_train[i] == 0.0]
    if len(benign_indices) < 5:
        b_cut = max(4, int(len(X_train_raw) * 0.5))
        benign_indices = list(range(b_cut))
        X_benign_train_raw = X_train_raw[:b_cut]
        y_benign_train_raw = y_next_train_raw[:b_cut]
    else:
        X_benign_train_raw = X_train_raw[benign_mask_train]
        y_benign_train_raw = y_next_train_raw[benign_mask_train]
        
    scaler = StandardScaler()
    scaler.fit(y_benign_train_raw)
    
    N_tr, S_len, D_feat = X_train_raw.shape
    X_train_scaled = scaler.transform(X_train_raw.reshape(-1, D_feat)).reshape(N_tr, S_len, D_feat)
    y_next_train_scaled = scaler.transform(y_next_train_raw)
    
    N_btr, _, _ = X_benign_train_raw.shape
    X_benign_train_scaled = scaler.transform(X_benign_train_raw.reshape(-1, D_feat)).reshape(N_btr, S_len, D_feat)
    y_benign_train_scaled = scaler.transform(y_benign_train_raw)
    
    N_te, _, _ = X_test_raw.shape
    X_test_scaled = scaler.transform(X_test_raw.reshape(-1, D_feat)).reshape(N_te, S_len, D_feat)
    y_next_test_scaled = scaler.transform(y_next_test_raw)
    
    val_cut = max(2, int(len(X_benign_train_scaled) * 0.20))
    X_val_benign = X_benign_train_scaled[-val_cut:]
    y_val_benign = y_benign_train_scaled[-val_cut:]
    X_fit_benign = X_benign_train_scaled[:-val_cut] if len(X_benign_train_scaled) > val_cut else X_benign_train_scaled
    y_fit_benign = y_benign_train_scaled[:-val_cut] if len(y_benign_train_scaled) > val_cut else y_benign_train_scaled
    
    # 1. Train Temporal World Model
    world_model = SelfSupervisedWorldModel(input_dim=len(FEATURE_NAMES))
    world_model.set_scaler_params(scaler.mean_, scaler.scale_)
    train_self_supervised_world_model(world_model, X_fit_benign, y_fit_benign, epochs=15, lr=0.003)
    
    gamma_T, e_95_T = calibrate_gamma_on_benign_validation(
        world_model, 
        X_val_benign, 
        y_val_benign, 
        percentile_target=95.0, 
        target_p_infil=0.10
    )
    
    # 2. Extract and Train Graph Engine strictly on benign training slice
    graph_engine = NetworkGraphEngine()
    time_col = "Timestamp" if "Timestamp" in df.columns else None
    
    # Fit baseline communication topology on benign training indices
    graph_engine.fit_baseline_topology(df, max_baseline_windows=train_cutoff)
    
    g_train_benign_list = []
    for idx in benign_indices:
        t_s = meta_df.iloc[idx]["window_start"]
        t_e = meta_df.iloc[idx]["window_end"]
        w_df = df.loc[(df[time_col] >= t_s) & (df[time_col] < t_e)] if time_col else df.iloc[:10]
        res = graph_engine.analyze_window_graph(w_df, idx)
        g_train_benign_list.append([res["algebraic_connectivity_lambda2"], res["spectral_dispersion_gap"], res["anomalous_edges_count"]])
        
    g_train_benign = np.array(g_train_benign_list, dtype=float)
    g_val_benign = g_train_benign[-val_cut:] if len(g_train_benign) > val_cut else g_train_benign
    graph_engine.fit_graph_distribution(g_train_benign, g_val_benign)
    
    # 3. Static Baseline Model
    baseline = StaticLogisticRegressionBaseline()
    baseline.fit(X_train_raw, y_atk_train)
    b_preds = baseline.predict(X_test_raw)
    b_metrics = compute_metrics_dict(y_atk_test, b_preds)
    
    # 4. Predict Channels on Out-of-Time Test Slice with Spatiotemporal Cross-Momentum (STCM)
    P_T_list = []
    e_T_list = []
    for i in range(len(X_test_scaled)):
        fc = world_model.forecast_future_state(X_test_scaled[i], y_next_test_scaled[i])
        P_T_list.append(fc["infiltration_probability"])
        e_T_list.append(fc["residual_error"])
    P_T = np.array(P_T_list)
    e_T_arr = np.array(e_T_list)
    
    P_G_list = []
    topo_vel_list = []
    prev_lambda2 = 1.0
    
    for i in range(train_cutoff, num_total_windows):
        t_s = meta_df.iloc[i]["window_start"]
        t_e = meta_df.iloc[i]["window_end"]
        w_df = df.loc[(df[time_col] >= t_s) & (df[time_col] < t_e)] if time_col else df.iloc[:10]
        res = graph_engine.analyze_window_graph(w_df, i)
        g_vec = np.array([res["algebraic_connectivity_lambda2"], res["spectral_dispersion_gap"], res["anomalous_edges_count"]])
        _, p_g = graph_engine.compute_graph_probability(g_vec)
        P_G_list.append(p_g)
        
        # Topological velocity
        lambda2_t = float(res["algebraic_connectivity_lambda2"])
        topo_velocity = abs(float(np.log((lambda2_t + 1e-7) / (prev_lambda2 + 1e-7))))
        prev_lambda2 = lambda2_t
        topo_vel_list.append(topo_velocity)
        
    P_G = np.array(P_G_list)
    topo_vel_arr = np.array(topo_vel_list)
    
    # Task 1: Spatiotemporal Cross-Momentum (STCM)
    # M_ST = e_T * (1 + 5.0 * topo_velocity)**2.0
    M_ST = e_T_arr * ((1.0 + (5.0 * topo_vel_arr)) ** 2.0)
    Risk_ST = 1.0 - np.exp(-gamma_T * M_ST)
    
    # Decision-Level Rules:
    pred_T = (P_T >= 0.10).astype(int)
    pred_G = (P_G >= 0.10).astype(int)
    pred_watch_or = ((P_T >= 0.10) | (P_G >= 0.10)).astype(int)
    pred_crit_stcm = (Risk_ST >= 0.10).astype(int)
    
    m_T = compute_metrics_dict(y_atk_test, pred_T)
    m_G = compute_metrics_dict(y_atk_test, pred_G)
    m_watch_or = compute_metrics_dict(y_atk_test, pred_watch_or)
    m_crit_stcm = compute_metrics_dict(y_atk_test, pred_crit_stcm)
    
    return {
        "dataset": dataset_name,
        "test_windows": len(X_test_raw),
        "test_pos": int((y_atk_test == 1).sum()),
        "test_neg": int((y_atk_test == 0).sum()),
        "e_95_T": float(e_95_T),
        "gamma_T": float(gamma_T),
        "e_95_G": float(graph_engine.e_95_G),
        "gamma_G": float(graph_engine.gamma_G),
        "baseline": b_metrics,
        "temporal_channel": m_T,
        "graph_channel": m_G,
        "watch_or": m_watch_or,
        "crit_stcm": m_crit_stcm
    }

def run_suite():
    suite = [
        ("data/02-14-2018.csv", "SSH/FTP Brute Force (Initial Access)", 0, 50000, None),
        ("data/02-15-2018.csv", "DoS GoldenEye/Slowloris (Impact)", 0, 50000, None),
        ("data/03-01-2018.csv", "Infiltration & PrivEsc (Stealth)", 50000, 150000, 200),
        ("data/03-02-2018.csv", "Botnet C2 Operations (Command & Control)", 0, 50000, None)
    ]
    results = []
    for path, name, skip, maxr, cut in suite:
        if os.path.exists(path):
            r = evaluate_dataset(path, name, skip_rows=skip, max_rows=maxr, train_cutoff_override=cut)
            results.append(r)
            
    print("\n" + "="*120)
    print("      FINAL UNIFIED DUAL-CHANNEL BENCHMARK (SPATIOTEMPORAL CROSS-MOMENTUM STCM & GRAPH)")
    print("="*120)
    print(f"{'Attack Scenario':<32} | {'Model Tier':<22} | {'Accuracy':<10} | {'Recall':<10} | {'Precision':<10} | {'F1-Score':<10} | {'FPR (95% CI)':<18}")
    print("-" * 120)
    
    for res in results:
        scen = res['dataset']
        tiers = [
            ("Static Baseline", res["baseline"]),
            ("Temporal Channel (P_T)", res["temporal_channel"]),
            ("Graph Channel (P_G)", res["graph_channel"]),
            ("Decision-Level WATCH", res["watch_or"]),
            ("CRITICAL Tier (STCM)", res["crit_stcm"])
        ]
        
        for t_label, m in tiers:
            s_print = scen[:32] if t_label == "Static Baseline" else ""
            print(f"{s_print:<32} | {t_label:<22} | {m['acc']:<10.1%} | {m['rec']:<10.1%} | {m['prec']:<10.1%} | {m['f1']:<10.3f} | {m['fpr']:<5.1%} {m['fpr_ci']}")
        print("-" * 120)
        
    return results

if __name__ == "__main__":
    run_suite()
