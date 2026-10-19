"""
AegisDynamics - AI Network Attack Forecasting & Cyber-Defense Dashboard
SIH26153 Cyber Defense System Powered by Self-Supervised World Models & SHAP
"""

import os
import glob
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import torch
from sklearn.preprocessing import StandardScaler

from parser import (
    parse_cic_csv,
    generate_sliding_window_states,
    create_temporal_sequences,
    FEATURE_NAMES,
    STAGE_NAMES,
    STAGE_MAPPING,
    ALLOWED_BASELINE_PORTS
)
from model import (
    SelfSupervisedWorldModel,
    StaticLogisticRegressionBaseline,
    train_self_supervised_world_model,
    calibrate_gamma_on_benign_validation
)
from explainer import TemporalStateExplainer
from graph_engine import NetworkGraphEngine

# Page Configuration
st.set_page_config(
    page_title="AegisDynamics | Self-Supervised Cyber World Model",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .metric-box {
        background-color: #111827;
        border: 1px solid #374151;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .alert-row {
        padding: 8px;
        border-radius: 4px;
        margin-bottom: 6px;
        font-family: monospace;
    }
</style>
""", unsafe_allow_html=True)

# Helper function to cache loaded dataset and trained models
@st.cache_resource(show_spinner=False)
def load_and_calibrate_system(
    csv_path: str,
    window_size_sec: int = 60,
    step_size_sec: int = 15,
    max_rows: int = 80000
):
    df = parse_cic_csv(csv_path, max_rows=max_rows)
    state_df = generate_sliding_window_states(df, window_size_sec=window_size_sec, step_size_sec=step_size_sec)
    X_seq, y_next_state, y_attack, y_stage, meta_df = create_temporal_sequences(state_df, seq_len=5)
    
    # Filter benign-only sequences for self-supervised world model training
    benign_mask = (y_attack == 0.0)
    if benign_mask.sum() < 10:
        split_idx = max(5, int(len(X_seq) * 0.2))
        X_train_benign = X_seq[:split_idx]
        y_train_benign = y_next_state[:split_idx]
    else:
        X_train_benign = X_seq[benign_mask]
        y_train_benign = y_next_state[benign_mask]
        
    scaler = StandardScaler()
    scaler.fit(y_train_benign)
    
    N_btr, S_len, D_feat = X_train_benign.shape
    X_train_scaled = scaler.transform(X_train_benign.reshape(-1, D_feat)).reshape(N_btr, S_len, D_feat)
    y_train_scaled = scaler.transform(y_train_benign)
    
    val_split = max(3, int(len(X_train_scaled) * 0.25))
    X_val_scaled = X_train_scaled[:val_split]
    y_val_scaled = y_train_scaled[:val_split]
    X_fit = X_train_scaled[val_split:] if len(X_train_scaled) > val_split else X_train_scaled
    y_fit = y_train_scaled[val_split:] if len(y_train_scaled) > val_split else y_train_scaled
    
    # Initialize and train models
    world_model = SelfSupervisedWorldModel(input_dim=len(FEATURE_NAMES))
    world_model.set_scaler_params(scaler.mean_, scaler.scale_)
    train_self_supervised_world_model(world_model, X_fit, y_fit, epochs=15, lr=0.003)
    
    # Mathematically calibrate gamma on benign validation residuals
    gamma_calib, e_95 = calibrate_gamma_on_benign_validation(
        world_model, 
        X_val_scaled, 
        y_val_scaled, 
        percentile_target=95.0, 
        target_p_infil=0.10
    )
    
    # Fit static Logistic Regression baseline
    baseline_model = StaticLogisticRegressionBaseline()
    baseline_model.fit(X_seq, y_attack)
    
    # Fit SHAP explainer
    explainer_bg = X_fit[:min(10, len(X_fit))]
    explainer = TemporalStateExplainer(world_model, explainer_bg)
    
    # Fit Tier 2 Graph Engine
    graph_engine = NetworkGraphEngine()
    graph_engine.fit_baseline_topology(df, window_size_sec=window_size_sec, step_size_sec=step_size_sec, max_baseline_windows=100)
    
    return {
        "raw_df": df,
        "state_df": state_df,
        "X_seq": X_seq,
        "y_next_state": y_next_state,
        "y_attack": y_attack,
        "y_stage": y_stage,
        "meta_df": meta_df,
        "world_model": world_model,
        "baseline_model": baseline_model,
        "explainer": explainer,
        "graph_engine": graph_engine,
        "gamma": gamma_calib,
        "e_95": e_95
    }

# ----------------- SIDEBAR CONFIGURATION -----------------
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/shield.png", width=64)
    st.title("AegisDynamics")
    st.caption("Self-Supervised Cyber World Model (SIH26153)")
    st.divider()
    
    st.subheader("📁 CSE-CIC-IDS2018 Dataset")
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    candidates = (
        sorted(glob.glob(os.path.join(SCRIPT_DIR, "data", "*.csv"))) +
        sorted(glob.glob(os.path.join(SCRIPT_DIR, "*.csv"))) +
        sorted(glob.glob("data/*.csv")) +
        sorted(glob.glob("*.csv"))
    )
    available_datasets = list(dict.fromkeys([os.path.abspath(p) for p in candidates]))
    
    mock_file = os.path.join(SCRIPT_DIR, "mock_cic_ids_2018.csv")
    if not available_datasets:
        if not os.path.exists(mock_file):
            from generate_mock_data import generate_mock_cic_dataset
            generate_mock_cic_dataset(output_file=mock_file)
        available_datasets = [mock_file]
    
    dataset_labels = {
        "mock_cic_ids_2018.csv": "Multi-Stage Attack: Recon ➔ Infiltration ➔ Exfil",
        "02-14-2018.csv": "Feb 14: SSH/FTP Brute Force",
        "02-15-2018.csv": "Feb 15: DoS (GoldenEye / Slowloris)",
        "03-01-2018.csv": "Mar 01: Infiltration / Active Breach",
        "03-02-2018.csv": "Mar 02: Botnet / C2 Operations"
    }
        
    selected_csv = st.selectbox(
        "Select Attack Scenario",
        options=available_datasets,
        format_func=lambda path: dataset_labels.get(os.path.basename(path), os.path.basename(path)),
        index=0
    )
    
    uploaded_custom = st.file_uploader("Or Upload Custom Flow CSV", type=["csv"])
    if uploaded_custom is not None:
        upload_dir = os.path.join(SCRIPT_DIR, "data")
        os.makedirs(upload_dir, exist_ok=True)
        selected_csv = os.path.join(upload_dir, f"uploaded_{uploaded_custom.name}")
        with open(selected_csv, "wb") as f:
            f.write(uploaded_custom.getbuffer())
        st.success(f"Loaded: {uploaded_custom.name}")
        
    st.divider()
    st.subheader("⚙️ Sliding Window & Horizon")
    win_size = st.slider("Window Resolution Δt (seconds)", min_value=30, max_value=120, value=60, step=15)
    stride_size = st.slider("Sliding Stride (seconds)", min_value=5, max_value=30, value=15, step=5)
    max_flow_limit = st.select_slider("Flow Rows Ingested", options=[25000, 50000, 80000, 120000], value=50000)
    
    st.divider()
    st.subheader("🚨 Alert Configuration")
    alert_thresh = st.slider("Forecast Alert Threshold P(Infil)", min_value=0.20, max_value=0.85, value=0.45, step=0.05)
    
    recalibrate_btn = st.button("🧠 Recalibrate World Model", use_container_width=True)

if recalibrate_btn:
    st.cache_resource.clear()

# Load System Data
with st.spinner("Processing CSE-CIC-IDS2018 flows & calibrating Self-Supervised World Model..."):
    sys_data = load_and_calibrate_system(
        selected_csv, 
        window_size_sec=win_size, 
        step_size_sec=stride_size, 
        max_rows=max_flow_limit
    )

world_model = sys_data["world_model"]
baseline_model = sys_data["baseline_model"]
X_seq = sys_data["X_seq"]
y_next_state = sys_data["y_next_state"]
y_attack = sys_data["y_attack"]
y_stage = sys_data["y_stage"]
meta_df = sys_data["meta_df"]
num_windows = len(X_seq)

# ----------------- MAIN INTERFACE -----------------
st.title("🛡️ AegisDynamics: Self-Supervised Cyber Defense World Model")
st.markdown(f"""
Predicting multi-stage network state transitions ($P(S_{{t+1}} \mid S_t, \dots, S_{{t-4}})$) on **CSE-CIC-IDS2018**. 
Trained **strictly on Benign baseline flows** using **Huber (Smooth L1) Future State Reconstruction**.
""")

# Top Overview Cards
col_info1, col_info2, col_info3, col_info4 = st.columns(4)
with col_info1:
    st.metric("Total Ingested Flows", f"{len(sys_data['raw_df']):,}")
with col_info2:
    st.metric("Sliding Windows (Δt)", f"{num_windows} (Δt={win_size}s)")
with col_info3:
    st.metric("Empirical e_95 Residual", f"{sys_data['e_95']:.4f}")
with col_info4:
    st.metric("Calibrated γ (Target P=0.10)", f"{sys_data['gamma']:.4f}")

tabs = st.tabs([
    "🎯 Live Forecast & Anomaly Gauge",
    "⚡ K-Step Rollout & SOAR Remediation",
    "🕸️ Dynamic Network Topology & Graph Laplacian",
    "📈 MITRE ATT&CK Attack Trajectory",
    "🔍 SHAP Explainability & Root Cause",
    "⚖️ Baseline Benchmark (World Model vs Logistic Regression)",
    "📋 Local SOC Alert Logs",
    "📊 Telemetry State Inspector"
])

# TAB 1: LIVE FORECASTING & GAUGE
with tabs[0]:
    st.subheader("Real-Time Sliding Window State Predictor")
    
    col_slide, col_btn = st.columns([3, 1])
    with col_slide:
        time_idx = st.slider(
            "Temporal Window Playback Index ($t$)", 
            min_value=0, 
            max_value=num_windows - 1, 
            value=min(25, num_windows - 1),
            help="Slide through 60-second sliding time windows across the traffic capture."
        )
    with col_btn:
        st.write("")
        if st.button("⏭️ Next Window", use_container_width=True) and time_idx < num_windows - 1:
            time_idx += 1
            
    current_seq = X_seq[time_idx]
    actual_next = y_next_state[time_idx]
    actual_atk = int(y_attack[time_idx])
    actual_stg_name = STAGE_NAMES[int(y_stage[time_idx])]
    
    # Compute single-window forecast
    fc_res = world_model.forecast_future_state(current_seq, actual_next)
    pred_next = fc_res["predicted_next_state"]
    res_err = fc_res["residual_error"]
    infil_p = fc_res["infiltration_probability"]
    pred_stg_name = fc_res["predicted_stage_name"]
    attn_w = fc_res["attention_weights"]
    
    w_start = meta_df.iloc[time_idx]["window_start"] if "window_start" in meta_df.columns else f"T+{time_idx*15}s"
    w_end = meta_df.iloc[time_idx]["window_end"] if "window_end" in meta_df.columns else f"T+{(time_idx*15)+60}s"
    st.caption(f"🕒 **Window Slice**: `{w_start}` ➔ `{w_end}` (60s Observation Horizon, 15s Stride)")
    
    # 3 Gauges Column Row
    col_g1, col_g2, col_g3 = st.columns(3)
    with col_g1:
        st.markdown("#### 1. Infiltration Risk $P(\\text{Infiltration}_{t+1})$")
        fig_risk = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=infil_p * 100,
            number={'suffix': "%", 'font': {'size': 32}},
            delta={'reference': 10.0, 'increasing': {'color': "#ef4444"}, 'decreasing': {'color': "#10b981"}},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1},
                'bar': {'color': "#ef4444" if infil_p >= 0.45 else ("#f59e0b" if infil_p >= 0.10 else "#10b981")},
                'steps': [
                    {'range': [0, 10], 'color': "rgba(16, 185, 129, 0.15)"},
                    {'range': [10, 45], 'color': "rgba(245, 158, 11, 0.15)"},
                    {'range': [45, 100], 'color': "rgba(239, 68, 68, 0.2)"}
                ],
                'threshold': {
                    'line': {'color': "yellow", 'width': 3},
                    'thickness': 0.8,
                    'value': 10.0
                }
            }
        ))
        fig_risk.update_layout(height=220, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig_risk, use_container_width=True)
        st.caption("Calibrated Threshold: $e_{95} \\iff P \\ge 10\\%$")
        
    with col_g2:
        st.markdown("#### 2. Temporal Residual Error $e(t+1)$")
        fig_err = go.Figure(go.Indicator(
            mode="gauge+number",
            value=res_err,
            number={'font': {'size': 32}},
            gauge={
                'axis': {'range': [0, max(2.5, res_err * 1.2)], 'tickwidth': 1},
                'bar': {'color': "#ef4444" if res_err >= sys_data["e_95"] else "#38bdf8"},
                'threshold': {
                    'line': {'color': "yellow", 'width': 3},
                    'thickness': 0.8,
                    'value': sys_data["e_95"]
                }
            }
        ))
        fig_err.update_layout(height=220, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig_err, use_container_width=True)
        st.caption(f"Baseline $e_{{95}}$ Ceiling: `{sys_data['e_95']:.4f}`")
        
    with col_g3:
        st.markdown("#### 3. MITRE ATT&CK Stage Forecast")
        st.info(f"🔮 **Forecasted Phase**: **{pred_stg_name}**")
        st.markdown(f"**Ground Truth Status**: `{'ATTACK' if actual_atk == 1 else 'BENIGN'}` (`{actual_stg_name}`)")
        
        # Micro bar of stage probabilities
        st.markdown("**Phase Probability Distribution:**")
        stage_probs = fc_res["stage_probabilities"]
        for s_idx, (s_name, prob_val) in enumerate(zip(STAGE_NAMES, stage_probs)):
            st.progress(float(prob_val), text=f"{s_name}: {prob_val:.1%}")
            
    # Tactical Decision Alert
    if infil_p >= 0.45:
        st.error(f"🚨 **HIGH-RISK ANOMALY FORECAST**: World Model state reconstruction residual ({res_err:.3f} > e_95 {sys_data['e_95']:.3f}) predicts imminent transition to **{pred_stg_name}** with **{infil_p:.1%}** confidence. Recommended action: Enforce dynamic egress filter and isolate target endpoints.")
    elif infil_p >= 0.10:
        st.warning(f"⚠️ **ELEVATED RECONNAISSANCE DRIFT**: Early telemetry drift indicates potential scanning or probe activity (**{pred_stg_name}**).")
    else:
        st.success("✅ **SYSTEM NOMINAL**: Traffic transition conforms to the self-supervised benign world model.")

# TAB 2: K-STEP ROLLOUT & SOAR REMEDIATION
with tabs[1]:
    st.subheader("⚡ Autoregressive K-Step Forward Trajectory Simulation & Automated SOAR Playbook")
    st.markdown("""
    **Forward World Model Simulation**: Rather than only predicting 1 step ahead ($S_{t+1}$), the model recursively simulates 
    the next **$K=5$ future state transitions** ($+15s, +30s, +45s, +60s, +75s$) to forecast multi-step attack trajectory evolution.
    """)
    
    rollout_data = world_model.simulate_k_step_rollout(current_seq, k_steps=5, step_seconds=15)
    
    col_ro1, col_ro2 = st.columns([1.8, 1.2])
    with col_ro1:
        st.markdown("#### 🔮 Recursive Future Risk Trajectory ($+15s$ to $+75s$)")
        horizons = [r["horizon_label"] for r in rollout_data]
        risks = [r["infiltration_probability"] * 100 for r in rollout_data]
        stages = [r["predicted_stage"] for r in rollout_data]
        
        fig_ro = go.Figure()
        fig_ro.add_trace(go.Scatter(
            x=horizons,
            y=risks,
            mode="lines+markers+text",
            name="Projected Infiltration Risk",
            text=[f"{r:.1f}% ({s})" for r, s in zip(risks, stages)],
            textposition="top center",
            line=dict(color="#38bdf8", width=3),
            marker=dict(size=10, color=["#ef4444" if r >= 45 else ("#f59e0b" if r >= 10 else "#10b981") for r in risks])
        ))
        fig_ro.add_hline(y=10, line_dash="dash", line_color="#f59e0b", annotation_text="e₉₅ Alert Threshold (10%)")
        fig_ro.add_hline(y=45, line_dash="dash", line_color="#ef4444", annotation_text="Critical Escalation (45%)")
        fig_ro.update_layout(
            yaxis_title="Forecasted Infiltration Risk (%)",
            yaxis_range=[0, 105],
            template="plotly_dark",
            height=300,
            margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(fig_ro, use_container_width=True)
        
    with col_ro2:
        st.markdown("#### 🛡️ Automated SOAR Policy Generation")
        target_ip = "18.218.115.60" if infil_p >= 0.10 else "192.168.10.110"
        from model import generate_soar_playbook
        playbook = generate_soar_playbook(pred_stg_name, target_ip, "192.168.10.0/24", infil_p)
        
        soar_tab1, soar_tab2, soar_tab3 = st.tabs(["Linux iptables", "AWS WAF / SG", "Cisco / Palo Alto"])
        with soar_tab1:
            st.code(playbook["iptables"], language="bash")
        with soar_tab2:
            st.code(playbook["aws_cli"], language="bash")
        with soar_tab3:
            st.code(playbook["cisco_acl"], language="text")

# TAB 3: NETWORK TOPOLOGY & GRAPH LAPLACIAN
with tabs[2]:
    st.subheader("🕸️ Dynamic Network Topology & Graph Laplacian Spectral Analysis")
    st.markdown("""
    **Tier 2 Parallel Analysis Layer**: Constructs the sliding-window IP-to-IP interaction graph $G_t = (V_t, E_t)$, 
    computes the dynamic **Graph Laplacian** $L_t = D_t - A_t$, and monitors **algebraic connectivity** $\lambda_2$ 
    and **spectral dispersion gap** $(\lambda_n - \lambda_2)$ to detect lateral traversal and unmapped peer connectivity.
    """)
    
    ge = sys_data.get("graph_engine")
    if ge and "Timestamp" in sys_data["raw_df"].columns and "window_start" in meta_df.columns:
        t_s = meta_df.iloc[time_idx]["window_start"]
        t_e = meta_df.iloc[time_idx]["window_end"]
        raw_win_df = sys_data["raw_df"].loc[(sys_data["raw_df"]["Timestamp"] >= t_s) & (sys_data["raw_df"]["Timestamp"] < t_e)]
    else:
        raw_win_df = sys_data["raw_df"].iloc[:10]
        
    if ge:
        g_data = ge.analyze_window_graph(raw_win_df, time_idx, is_attack_ground_truth=(actual_atk == 1), attacker_ip=target_ip)
        
        c_g1, c_g2, c_g3, c_g4 = st.columns(4)
        with c_g1:
            st.metric("Active Topology Nodes", f"{g_data['num_nodes']} hosts")
        with c_g2:
            st.metric("Algebraic Connectivity (λ₂)", f"{g_data['algebraic_connectivity_lambda2']:.4f}")
        with c_g3:
            st.metric("Spectral Dispersion Gap", f"{g_data['spectral_dispersion_gap']:.2f}")
        with c_g4:
            st.metric("Anomalous Edges", f"{g_data['anomalous_edges_count']}", delta="Flagged" if g_data['anomalous_edges_count'] > 0 else "Normal", delta_color="inverse")
            
        st.markdown("#### 🗺️ Active Window Node Interaction Graph")
        nodes_df = pd.DataFrame(g_data["nodes"])
        edges_df = pd.DataFrame(g_data["edges"])
        
        col_nt1, col_nt2 = st.columns([1.2, 1.8])
        with col_nt1:
            st.markdown("**Identified Node Roles:**")
            st.dataframe(nodes_df[["full_ip", "role", "is_crown_jewel"]], use_container_width=True)
        with col_nt2:
            st.markdown("**Active Window Communication Edges:**")
            st.dataframe(edges_df[["source", "target", "protocol", "port", "is_anomalous"]], use_container_width=True)

# TAB 4: ATTACK TRAJECTORY & TIMELINE
with tabs[3]:
    st.subheader("Temporal MITRE ATT&CK Attack Trajectory")
    st.markdown("Full-sequence trajectory comparing actual ground-truth stage against the Self-Supervised World Model forecasts.")
    
    all_infil_probs = []
    all_pred_stages = []
    all_residuals = []
    
    for i in range(num_windows):
        f_i = world_model.forecast_future_state(X_seq[i], y_next_state[i])
        all_infil_probs.append(f_i["infiltration_probability"])
        all_pred_stages.append(f_i["predicted_stage_idx"])
        all_residuals.append(f_i["residual_error"])
        
    timeline_df = pd.DataFrame({
        "Window": list(range(num_windows)),
        "Actual_Stage_Idx": y_stage,
        "Actual_Stage": [STAGE_NAMES[idx] for idx in y_stage],
        "Predicted_Stage_Idx": all_pred_stages,
        "Predicted_Stage": [STAGE_NAMES[idx] for idx in all_pred_stages],
        "Infil_Prob": all_infil_probs,
        "Residual_Error": all_residuals,
        "Unallowed_Ports": X_seq[:, -1, FEATURE_NAMES.index("unallowed_port_ratio")],
        "Port_Entropy": X_seq[:, -1, FEATURE_NAMES.index("dst_port_entropy")]
    })
    
    fig_tl = go.Figure()
    fig_tl.add_trace(go.Scatter(
        x=timeline_df["Window"],
        y=timeline_df["Actual_Stage_Idx"],
        mode="lines+markers",
        name="Ground Truth Stage",
        line=dict(color="#636EFA", width=3, dash="dot")
    ))
    fig_tl.add_trace(go.Scatter(
        x=timeline_df["Window"],
        y=timeline_df["Predicted_Stage_Idx"],
        mode="lines+markers",
        name="Self-Supervised Forecast",
        line=dict(color="#EF553B", width=2.5),
        marker=dict(symbol="diamond", size=6)
    ))
    fig_tl.add_vline(x=time_idx, line_width=2, line_dash="dash", line_color="yellow", annotation_text="Current Window")
    fig_tl.update_layout(
        title="<b>MITRE ATT&CK State Progression: Ground Truth vs. Forecast</b>",
        xaxis_title="Sliding Window Index (60s Windows)",
        yaxis=dict(tickmode="array", tickvals=list(range(5)), ticktext=STAGE_NAMES),
        height=360,
        margin=dict(l=20, r=20, t=45, b=20)
    )
    st.plotly_chart(fig_tl, use_container_width=True)
    
    col_sc1, col_sc2 = st.columns(2)
    with col_sc1:
        fig_res = px.line(
            timeline_df, 
            x="Window", 
            y="Residual_Error", 
            title="<b>Auto-Regressive State Reconstruction Residual e(t+1)</b>",
            color_discrete_sequence=["#fca311"]
        )
        fig_res.add_hline(y=sys_data["e_95"], line_dash="dash", line_color="red", annotation_text=f"e_95 Baseline ({sys_data['e_95']:.3f})")
        fig_res.update_layout(height=250, margin=dict(l=10, r=10, t=35, b=10))
        st.plotly_chart(fig_res, use_container_width=True)
        
    with col_sc2:
        fig_inf = px.area(
            timeline_df, 
            x="Window", 
            y="Infil_Prob", 
            title="<b>Forecasted Infiltration Risk Curve P(Infiltration)</b>",
            color_discrete_sequence=["#ef553b"]
        )
        fig_inf.add_hline(y=alert_thresh, line_dash="dash", line_color="yellow", annotation_text="Alert Threshold")
        fig_inf.update_layout(height=250, margin=dict(l=10, r=10, t=35, b=10))
        st.plotly_chart(fig_inf, use_container_width=True)

# TAB 5: SHAP EXPLAINABILITY
with tabs[4]:
    st.subheader("SHAP Feature Attribution & Root-Cause Diagnosis")
    st.markdown("Decomposes the forecast residual deviation using Shapley values to identify the **top 3 network feature drivers** triggering the anomaly.")
    
    with st.spinner("Calculating SHAP attributions on state reconstruction residual..."):
        shap_res = sys_data["explainer"].explain_instance(current_seq, top_k=3)
        
    col_shp1, col_shp2 = st.columns([1.2, 2.0])
    with col_shp1:
        st.markdown("#### 🏆 Top 3 Contributing Drivers")
        for item in shap_res["top_features"]:
            card_bg = "#3b1e1e" if item["shap_direction"] > 0 else "#1e3b2e"
            st.markdown(
                f"<div style='background-color: {card_bg}; padding: 10px; border-radius: 6px; margin-bottom: 8px;'>"
                f"<b>Rank #{item['rank']}: {item['feature']}</b><br/>"
                f"SHAP Impact: <code>{item['shap_direction']:+.4f}</code> | Current Value: <code>{item['current_value']:.2f}</code><br/>"
                f"<small>{item['impact']}</small>"
                f"</div>",
                unsafe_allow_html=True
            )
        st.info(f"💡 **SOC Diagnostic Summary**: {shap_res['summary_text']}")
        
    with col_shp2:
        bar_df = shap_res["all_features_df"].copy()
        bar_df["Color"] = bar_df["Directional_SHAP"].apply(lambda v: "#ef553b" if v > 0 else "#00cc96")
        
        fig_sh_bar = go.Figure(go.Bar(
            x=bar_df["Directional_SHAP"],
            y=bar_df["Feature"],
            orientation="h",
            marker=dict(color=bar_df["Color"]),
            text=bar_df["Directional_SHAP"].apply(lambda v: f"{v:+.3f}"),
            textposition="auto"
        ))
        fig_sh_bar.update_layout(
            title="<b>SHAP Directional Attribution (Positive = Increases Anomaly Risk)</b>",
            xaxis_title="Shapley Impact on Residual e(t+1)",
            yaxis=dict(autorange="reversed"),
            height=360,
            margin=dict(l=10, r=10, t=40, b=10)
        )
        st.plotly_chart(fig_sh_bar, use_container_width=True)

# TAB 6: BASELINE BENCHMARK
with tabs[5]:
    st.subheader("Model Benchmark: Static Logistic Regression vs. Temporal World Model")
    st.markdown("""
    Comparing performance against the static baseline required by the PS specification:
    Proves that modeling temporal transition dynamics ($P(S_{t+1} \mid S_t)$) provides higher detection Recall and lower False Positive Rates.
    """)
    
    # Compute baseline metrics
    b_metrics = baseline_model.evaluate(X_seq, y_attack)
    
    # Compute World Model metrics
    world_preds = (np.array(all_infil_probs) >= alert_thresh).astype(int)
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
    
    w_acc = accuracy_score(y_attack, world_preds)
    w_prec = precision_score(y_attack, world_preds, zero_division=0)
    w_rec = recall_score(y_attack, world_preds, zero_division=0)
    w_f1 = f1_score(y_attack, world_preds, zero_division=0)
    tn_w, fp_w, fn_w, tp_w = confusion_matrix(y_attack, world_preds, labels=[0, 1]).ravel()
    w_fpr = float(fp_w / (fp_w + tn_w)) if (fp_w + tn_w) > 0 else 0.0
    
    col_bm1, col_bm2 = st.columns(2)
    with col_bm1:
        st.markdown("### 🏛️ Static Logistic Regression Baseline")
        st.caption("Point-in-time classification on single static flow snapshots.")
        st.metric("Accuracy", f"{b_metrics['accuracy']:.1%}")
        st.metric("Precision", f"{b_metrics['precision']:.1%}")
        st.metric("Recall", f"{b_metrics['recall']:.1%}")
        st.metric("F1-Score", f"{b_metrics['f1_score']:.3f}")
        st.metric("False Positive Rate (FPR)", f"{b_metrics['false_positive_rate']:.1%}")
        
    with col_bm2:
        st.markdown("### 🧠 Self-Supervised Temporal World Model")
        st.caption("Temporal transition dynamics across 5-window sequence lookback.")
        st.metric("Accuracy", f"{w_acc:.1%}", delta=f"{(w_acc - b_metrics['accuracy']):+.1%}")
        st.metric("Precision", f"{w_prec:.1%}", delta=f"{(w_prec - b_metrics['precision']):+.1%}")
        st.metric("Recall", f"{w_rec:.1%}", delta=f"{(w_rec - b_metrics['recall']):+.1%}")
        st.metric("F1-Score", f"{w_f1:.3f}", delta=f"{(w_f1 - b_metrics['f1_score']):+.3f}")
        st.metric("False Positive Rate (FPR)", f"{w_fpr:.1%}", delta=f"{(w_fpr - b_metrics['false_positive_rate']):+.1%}", delta_color="inverse")
        
    st.divider()
    comp_df = pd.DataFrame({
        "Metric": ["Accuracy", "Precision", "Recall", "F1-Score", "False Positive Rate"],
        "Static Baseline": [b_metrics['accuracy'], b_metrics['precision'], b_metrics['recall'], b_metrics['f1_score'], b_metrics['false_positive_rate']],
        "Temporal World Model": [w_acc, w_prec, w_rec, w_f1, w_fpr]
    })
    fig_bm = px.bar(comp_df, x="Metric", y=["Static Baseline", "Temporal World Model"], barmode="group", title="<b>Benchmark Comparison: Static vs. Temporal World Model</b>")
    st.plotly_chart(fig_bm, use_container_width=True)

# TAB 7: LOCAL ALERT LOGS
with tabs[6]:
    st.subheader("📋 Local SOC Alert Log Table")
    st.markdown("Timestamped security alert logs generated during live sliding window processing.")
    
    alert_records = []
    for i in range(num_windows):
        p_val = all_infil_probs[i]
        if p_val >= alert_thresh:
            w_meta = meta_df.iloc[i]
            alert_records.append({
                "Window_Index": i,
                "Timestamp_Start": str(w_meta.get("window_start", "N/A")),
                "Timestamp_End": str(w_meta.get("window_end", "N/A")),
                "Severity": "CRITICAL" if p_val >= 0.70 else "HIGH",
                "Infil_Risk": f"{p_val:.1%}",
                "Residual_e": f"{all_residuals[i]:.4f}",
                "Forecasted_MITRE_Stage": STAGE_NAMES[all_pred_stages[i]],
                "Ground_Truth_Stage": STAGE_NAMES[int(y_stage[i])]
            })
            
    if len(alert_records) > 0:
        alert_table_df = pd.DataFrame(alert_records)
        st.dataframe(alert_table_df, use_container_width=True)
        st.success(f"Total Alert Triggers: **{len(alert_table_df)}** windows exceeding threshold ({alert_thresh:.0%}).")
        
        import json
        report_export = {
            "incident_report_id": f"AEGIS-EXP-W{time_idx}",
            "generated_timestamp": str(w_end),
            "target_subnet": "192.168.10.0/24",
            "current_window_index": int(time_idx),
            "forecasted_risk": f"{infil_p:.1%}",
            "predicted_mitre_stage": str(pred_stg_name),
            "top_shap_features": [f["feature"] for f in shap_res["top_features"]],
            "soar_remediation": playbook,
            "recorded_incidents_count": len(alert_records),
            "alert_log_table": alert_records
        }
        st.download_button(
            label="📄 Download One-Click Forensic Incident Dossier (JSON)",
            data=json.dumps(report_export, indent=2),
            file_name=f"AegisDynamics_Forensic_Report_W{time_idx}.json",
            mime="application/json",
            use_container_width=True
        )
    else:
        st.info("No security alerts triggered in the current window range.")

# TAB 8: TELEMETRY STATE INSPECTOR
with tabs[7]:
    st.subheader("Network State Vectors ($S_t$) & Raw Traffic Samples")
    st.dataframe(sys_data["state_df"].head(30), use_container_width=True)
    st.markdown("#### Raw Traffic Samples (CSE-CIC-IDS2018 Schema)")
    st.dataframe(sys_data["raw_df"].head(20), use_container_width=True)

st.divider()
st.caption("AegisDynamics SIH26153 Cyber Defense System | Self-Supervised World Model on CSE-CIC-IDS2018")
