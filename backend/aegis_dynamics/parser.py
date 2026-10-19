"""
AegisDynamics - Network Flow Ingestion & Temporal Feature Extraction Engine
Parses CSE-CIC-IDS2018 Flow CSV datasets, computes configurable sliding time windows (Delta_t),
and extracts topology-aware flow & packet features for Self-Supervised World Modeling.
"""

import math
import numpy as np
import pandas as pd
from typing import Tuple, List, Dict, Any, Optional

ALLOWED_BASELINE_PORTS = {80, 443, 53, 445, 3389}

STAGE_MAPPING = {
    "Normal": 0,
    "Reconnaissance": 1,
    "Initial Access": 2,
    "Lateral Movement": 3,
    "Exfiltration": 4
}

STAGE_NAMES = ["Normal", "Reconnaissance", "Initial Access", "Lateral Movement", "Exfiltration"]

FEATURE_NAMES = [
    "flow_count",
    "syn_ratio",
    "ack_ratio",
    "fin_ratio",
    "rst_ratio",
    "flow_duration_mean",
    "flow_duration_max",
    "flow_iat_mean",
    "pkt_len_var_mean",
    "pkt_len_mean",
    "dst_port_entropy",
    "unallowed_port_ratio",
    "service_web_ratio",
    "service_remote_ratio"
]

def shannon_entropy(series: pd.Series) -> float:
    """Computes Shannon entropy for discrete port distribution."""
    if len(series) == 0:
        return 0.0
    val_counts = series.value_counts(normalize=True)
    entropy = -sum(p * math.log2(p) for p in val_counts if p > 0)
    return float(entropy)

def map_raw_label_to_mitre(label: str) -> str:
    """Maps CSE-CIC-IDS2018 raw labels to standardized MITRE ATT&CK stages."""
    lbl = str(label).strip()
    if lbl.lower() in ["benign", "normal"]:
        return "Normal"
    elif any(k in lbl.lower() for k in ["portscan", "recon"]):
        return "Reconnaissance"
    elif any(k in lbl.lower() for k in ["bruteforce", "ssh", "ftp", "web"]):
        return "Initial Access"
    elif any(k in lbl.lower() for k in ["infilteration", "bot", "pivot", "lateral"]):
        return "Lateral Movement"
    elif any(k in lbl.lower() for k in ["dos", "ddos", "slowloris", "goldeneye", "hulk", "exfiltration"]):
        return "Exfiltration"
    return "Initial Access"

def parse_cic_csv(filepath: str, max_rows: Optional[int] = 120000) -> pd.DataFrame:
    """
    Ingests authentic CSE-CIC-IDS2018 Flow CSV with standardized column handling.
    """
    print(f"[*] Reading {filepath} (max_rows={max_rows})...")
    df = pd.read_csv(filepath, nrows=max_rows, low_memory=False)
    
    # Clean and standardize column names
    rename_dict = {}
    for col in df.columns:
        clean_col = col.strip().replace(" ", "_")
        rename_dict[col] = clean_col
    df = df.rename(columns=rename_dict)
    
    # Filter header repetition rows if present in dirty CSVs
    if "Dst_Port" in df.columns:
        df = df[df["Dst_Port"] != "Dst Port"].copy()
        df["Dst_Port"] = pd.to_numeric(df["Dst_Port"], errors="coerce").fillna(0).astype(int)
        
    # Timestamp parsing
    if "Timestamp" in df.columns:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], format="mixed", errors="coerce")
        df = df.dropna(subset=["Timestamp"]).sort_values(by="Timestamp").reset_index(drop=True)
    else:
        df["Timestamp"] = pd.date_range(start="2018-02-14 08:30:00", periods=len(df), freq="2s")
        
    # Numeric column coercion
    num_cols = [
        "Flow_Duration", "Flow_IAT_Mean", "Pkt_Len_Var", "Pkt_Len_Mean",
        "SYN_Flag_Cnt", "ACK_Flag_Cnt", "FIN_Flag_Cnt", "RST_Flag_Cnt"
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
            
    # Clean labels
    if "Label" in df.columns:
        df["Label"] = df["Label"].astype(str).str.strip()
        df["MITRE_Stage"] = df["Label"].apply(map_raw_label_to_mitre)
    else:
        df["Label"] = "Benign"
        df["MITRE_Stage"] = "Normal"
        
    print(f"[+] Successfully loaded {len(df)} flows. MITRE stages present: {df['MITRE_Stage'].value_counts().to_dict()}")
    return df

def extract_sliding_window_state(window_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Extracts 14 topology-aware flow & packet features from a sliding time window.
    """
    count = len(window_df)
    if count == 0:
        return {f: 0.0 for f in FEATURE_NAMES}
        
    # Flow flags
    syn_cnt = window_df["SYN_Flag_Cnt"].sum() if "SYN_Flag_Cnt" in window_df.columns else 0.0
    ack_cnt = window_df["ACK_Flag_Cnt"].sum() if "ACK_Flag_Cnt" in window_df.columns else 0.0
    fin_cnt = window_df["FIN_Flag_Cnt"].sum() if "FIN_Flag_Cnt" in window_df.columns else 0.0
    rst_cnt = window_df["RST_Flag_Cnt"].sum() if "RST_Flag_Cnt" in window_df.columns else 0.0
    
    syn_ratio = float(syn_cnt / count)
    ack_ratio = float(ack_cnt / count)
    fin_ratio = float(fin_cnt / count)
    rst_ratio = float(rst_cnt / count)
    
    # Timing & durations
    flow_dur_mean = float(window_df["Flow_Duration"].mean()) if "Flow_Duration" in window_df.columns else 0.0
    flow_dur_max = float(window_df["Flow_Duration"].max()) if "Flow_Duration" in window_df.columns else 0.0
    flow_iat_mean = float(window_df["Flow_IAT_Mean"].mean()) if "Flow_IAT_Mean" in window_df.columns else 0.0
    
    # Packet statistics
    pkt_len_var_mean = float(window_df["Pkt_Len_Var"].mean()) if "Pkt_Len_Var" in window_df.columns else 0.0
    pkt_len_mean = float(window_df["Pkt_Len_Mean"].mean()) if "Pkt_Len_Mean" in window_df.columns else 0.0
    
    # Topology & port metrics
    dst_ports = window_df["Dst_Port"] if "Dst_Port" in window_df.columns else pd.Series([], dtype=int)
    dst_port_entropy = shannon_entropy(dst_ports)
    
    unallowed_cnt = dst_ports.apply(lambda p: 1 if p not in ALLOWED_BASELINE_PORTS else 0).sum()
    unallowed_port_ratio = float(unallowed_cnt / count)
    
    web_cnt = dst_ports.isin([80, 443, 8080]).sum()
    service_web_ratio = float(web_cnt / count)
    
    remote_cnt = dst_ports.isin([21, 22, 445, 3389]).sum()
    service_remote_ratio = float(remote_cnt / count)
    
    # Ground truth determination for evaluation
    stages = [STAGE_MAPPING.get(s, 0) for s in window_df["MITRE_Stage"].dropna()]
    stage_idx = int(max(stages)) if len(stages) > 0 else 0
    is_attack = 1.0 if stage_idx > 0 else 0.0
    
    return {
        "flow_count": float(count),
        "syn_ratio": syn_ratio,
        "ack_ratio": ack_ratio,
        "fin_ratio": fin_ratio,
        "rst_ratio": rst_ratio,
        "flow_duration_mean": flow_dur_mean,
        "flow_duration_max": flow_dur_max,
        "flow_iat_mean": flow_iat_mean,
        "pkt_len_var_mean": pkt_len_var_mean,
        "pkt_len_mean": pkt_len_mean,
        "dst_port_entropy": dst_port_entropy,
        "unallowed_port_ratio": unallowed_port_ratio,
        "service_web_ratio": service_web_ratio,
        "service_remote_ratio": service_remote_ratio,
        "target_stage": stage_idx,
        "target_is_attack": is_attack
    }

def generate_sliding_window_states(
    df: pd.DataFrame, 
    window_size_sec: int = 60, 
    step_size_sec: int = 15
) -> pd.DataFrame:
    """
    Groups flow dataframe into sliding time windows of configurable Delta_t and stride.
    """
    start_time = df["Timestamp"].min()
    end_time = df["Timestamp"].max()
    
    records = []
    curr_start = start_time
    
    while curr_start + pd.Timedelta(seconds=window_size_sec) <= end_time + pd.Timedelta(seconds=step_size_sec):
        curr_end = curr_start + pd.Timedelta(seconds=window_size_sec)
        window_mask = (df["Timestamp"] >= curr_start) & (df["Timestamp"] < curr_end)
        window_slice = df[window_mask]
        
        if len(window_slice) > 0:
            st = extract_sliding_window_state(window_slice)
            st["window_start"] = curr_start
            st["window_end"] = curr_end
            records.append(st)
            
        curr_start += pd.Timedelta(seconds=step_size_sec)
        
    state_df = pd.DataFrame(records)
    return state_df

def create_temporal_sequences(
    state_df: pd.DataFrame, 
    seq_len: int = 5
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """
    Constructs temporal sequence datasets:
    X: [N, seq_len, num_features] ([S_{t-4}, ..., S_t])
    y_next_state: [N, num_features] (Actual S_{t+1} for self-supervised reconstruction)
    y_attack: [N] (Binary attack label at t+1 for evaluation)
    y_stage: [N] (MITRE ATT&CK stage index at t+1 for evaluation)
    meta_df: metadata per sequence window
    """
    if len(state_df) <= seq_len:
        raise ValueError(f"State dataframe length ({len(state_df)}) must exceed sequence length ({seq_len})")
        
    feature_matrix = state_df[FEATURE_NAMES].values.astype(np.float32)
    attack_targets = state_df["target_is_attack"].values.astype(np.float32)
    stage_targets = state_df["target_stage"].values.astype(np.int64)
    
    X, y_next_state, y_attack, y_stage = [], [], [], []
    meta = []
    
    for i in range(len(state_df) - seq_len):
        X.append(feature_matrix[i : i + seq_len])
        y_next_state.append(feature_matrix[i + seq_len])
        y_attack.append(attack_targets[i + seq_len])
        y_stage.append(stage_targets[i + seq_len])
        meta.append(state_df.iloc[i + seq_len].to_dict())
        
    return (
        np.array(X, dtype=np.float32),
        np.array(y_next_state, dtype=np.float32),
        np.array(y_attack, dtype=np.float32),
        np.array(y_stage, dtype=np.int64),
        pd.DataFrame(meta)
    )

if __name__ == "__main__":
    df = parse_cic_csv("data/02-14-2018.csv", max_rows=50000)
    states = generate_sliding_window_states(df, window_size_sec=60, step_size_sec=15)
    print(f"[+] Generated {len(states)} sliding window states.")
    X, y_next, y_atk, y_stg, meta = create_temporal_sequences(states, seq_len=5)
    print(f"[+] X: {X.shape}, y_next: {y_next.shape}, y_atk: {y_atk.shape}, y_stg: {y_stg.shape}")
