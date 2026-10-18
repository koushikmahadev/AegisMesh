"""
AegisDynamics - Standardized & Scaled Self-Supervised World Model Engine
Implements:
1. Feature standardization fitted strictly on benign baseline training data.
2. Self-Supervised Future State Reconstruction (BiLSTM + Temporal Attention).
3. Autoregressive K-Step Forward Rollout Simulation P(S_{t+1}, ..., S_{t+K} | S_t).
4. Deterministic Gamma Calibration on empirical 95th percentile validation residual.
5. Automated SOAR Policy Generation (iptables, AWS SG, Cisco ACL).
"""

import os
import pickle
import uuid
from datetime import datetime, timezone
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
from typing import Tuple, Dict, Any, Optional, List
from parser import FEATURE_NAMES, STAGE_NAMES, STAGE_MAPPING

def set_deterministic_seed(seed: int = 42):
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

class StaticLogisticRegressionBaseline:
    """
    Evaluates single static point-in-time state vectors S_t.
    """
    def __init__(self):
        self.scaler = StandardScaler()
        self.clf = LogisticRegression(max_iter=1000, random_state=42, class_weight="balanced")
        self.fallback_iso = IsolationForest(random_state=42, contamination=0.1)
        self.is_fitted = False
        self.single_class_mode = False
        
    def fit(self, X: np.ndarray, y: np.ndarray):
        X_static = X[:, -1, :] if len(X.shape) == 3 else X
        X_scaled = self.scaler.fit_transform(X_static)
        
        unique_classes = np.unique(y)
        if len(unique_classes) >= 2:
            self.clf.fit(X_scaled, y)
            self.single_class_mode = False
        else:
            self.fallback_iso.fit(X_scaled)
            self.single_class_mode = True
            
        self.is_fitted = True
        return self
        
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Baseline is not fitted yet.")
        X_static = X[:, -1, :] if len(X.shape) == 3 else X
        X_scaled = self.scaler.transform(X_static)
        if not self.single_class_mode:
            return self.clf.predict_proba(X_scaled)
        else:
            scores = -self.fallback_iso.decision_function(X_scaled)
            probs = 1.0 / (1.0 + np.exp(-scores))
            return np.vstack([1.0 - probs, probs]).T
        
    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Baseline is not fitted yet.")
        X_static = X[:, -1, :] if len(X.shape) == 3 else X
        X_scaled = self.scaler.transform(X_static)
        if not self.single_class_mode:
            return self.clf.predict(X_scaled)
        else:
            preds = self.fallback_iso.predict(X_scaled)
            return np.array([1 if p == -1 else 0 for p in preds])

    def evaluate(self, X: np.ndarray, y_true: np.ndarray) -> Dict[str, float]:
        preds = self.predict(X)
        acc = float(accuracy_score(y_true, preds))
        prec = float(precision_score(y_true, preds, zero_division=0))
        rec = float(recall_score(y_true, preds, zero_division=0))
        f1 = float(f1_score(y_true, preds, zero_division=0))
        
        tn, fp, fn, tp = confusion_matrix(y_true, preds, labels=[0, 1]).ravel()
        fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
        
        return {
            "accuracy": acc,
            "precision": prec,
            "recall": rec,
            "f1_score": f1,
            "false_positive_rate": fpr
        }


class TemporalAttention(nn.Module):
    def __init__(self, hidden_dim: int):
        super().__init__()
        self.attn = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.Tanh(),
            nn.Linear(hidden_dim // 2, 1)
        )
        
    def forward(self, rnn_out: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        scores = self.attn(rnn_out)
        weights = torch.softmax(scores, dim=1)
        context = torch.sum(weights * rnn_out, dim=1)
        return context, weights.squeeze(-1)


class SelfSupervisedWorldModel(nn.Module):
    r"""
    Self-Supervised Recurrent AI World Model:
    Learns continuous normal network transition dynamics P(S_{t+1} | S_t, ..., S_{t-4})
    operating on standardized state vectors.
    """
    def __init__(
        self, 
        input_dim: int = 14, 
        hidden_dim: int = 64, 
        num_layers: int = 2, 
        dropout: float = 0.2
    ):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0
        )
        
        self.attention = TemporalAttention(hidden_dim * 2)
        
        self.decoder = nn.Sequential(
            nn.Linear(hidden_dim * 2, 64),
            nn.LayerNorm(64),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(64, 32),
            nn.GELU(),
            nn.Linear(32, input_dim)
        )
        
        # Empirical baseline parameters
        self.register_buffer("benign_mean", torch.zeros(input_dim))
        self.register_buffer("benign_std", torch.ones(input_dim))
        self.gamma: float = 1.0
        self.residual_threshold_95: float = 1.0
        self.conformal_q90: float = 1.0
        self.conformal_q99: float = 2.0

    def set_scaler_params(self, mean: np.ndarray, std: np.ndarray):
        std_clean = np.where(std == 0, 1.0, std)
        self.benign_mean.copy_(torch.tensor(mean, dtype=torch.float32))
        self.benign_std.copy_(torch.tensor(std_clean, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        lstm_out, _ = self.lstm(x)
        context, attn_weights = self.attention(lstm_out)
        pred_next_state = self.decoder(context)
        return pred_next_state, attn_weights

    def compute_residual_error(
        self, 
        pred_state: torch.Tensor, 
        actual_state: torch.Tensor
    ) -> torch.Tensor:
        diff = torch.abs(pred_state - actual_state)
        return torch.mean(diff, dim=-1)

    def forecast_future_state(
        self, 
        x_seq: np.ndarray, 
        actual_next_state: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        self.eval()
        with torch.no_grad():
            if len(x_seq.shape) == 2:
                x_t = torch.tensor(x_seq, dtype=torch.float32).unsqueeze(0)
            else:
                x_t = torch.tensor(x_seq, dtype=torch.float32)
                
            pred_state_t, attn_t = self.forward(x_t)
            pred_np = pred_state_t.squeeze(0).cpu().numpy()
            attn_np = attn_t.squeeze(0).cpu().numpy()
            
            if actual_next_state is not None:
                act_t = torch.tensor(actual_next_state, dtype=torch.float32)
                if len(act_t.shape) == 1:
                    act_t = act_t.unsqueeze(0)
                residual_t = self.compute_residual_error(pred_state_t, act_t)
                residual = float(residual_t.squeeze().cpu().numpy())
            else:
                mean_t = torch.zeros_like(pred_state_t)
                residual_t = self.compute_residual_error(pred_state_t, mean_t)
                residual = float(residual_t.squeeze().cpu().numpy())
                
            infil_prob = float(1.0 - np.exp(-self.gamma * max(0.0, residual)))
            infil_prob = float(np.clip(infil_prob, 0.0, 1.0))
            
            unscaled_pred = pred_np * self.benign_std.cpu().numpy() + self.benign_mean.cpu().numpy()
            pred_stage_name, stage_probs = profile_mitre_stage(unscaled_pred, infil_prob)
            pred_stage_idx = STAGE_MAPPING.get(pred_stage_name, 0)
            
            # Split Conformal Prediction Assessment
            epistemic_status = "CRITICAL_INVARIANT_VIOLATION" if residual > self.conformal_q99 else (
                "ELEVATED_COVARIANCE" if residual > self.conformal_q90 else "NOMINAL_CONFORMAL_BOUNDS"
            )
            conformal_p = float(np.clip(1.0 - (residual / (self.conformal_q99 + 1e-5)), 0.001, 0.999))
            
            return {
                "predicted_next_state": unscaled_pred,
                "predicted_scaled_state": pred_np,
                "residual_error": residual,
                "infiltration_probability": infil_prob,
                "calibrated_gamma": float(self.gamma),
                "threshold_95": float(self.residual_threshold_95),
                "predicted_stage_name": pred_stage_name,
                "predicted_stage_idx": pred_stage_idx,
                "stage_probabilities": stage_probs,
                "attention_weights": attn_np.tolist(),
                "conformal_assessment": {
                    "conformal_q90": float(round(self.conformal_q90, 4)),
                    "conformal_q99": float(round(self.conformal_q99, 4)),
                    "epistemic_status": epistemic_status,
                    "conformal_confidence_p": float(round(conformal_p, 4))
                }
            }

    def simulate_k_step_rollout(
        self, 
        current_seq: np.ndarray, 
        k_steps: int = 5,
        step_seconds: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Autoregressively rolls forward K future states:
        Ŝ_{t+1}, Ŝ_{t+2}, ..., Ŝ_{t+K}
        Feeding predicted future states recursively back into the input sequence buffer.
        """
        self.eval()
        rollout_results = []
        seq_buffer = np.copy(current_seq) # Shape: [5, 14]
        
        with torch.no_grad():
            for step in range(1, k_steps + 1):
                x_t = torch.tensor(seq_buffer, dtype=torch.float32).unsqueeze(0)
                pred_scaled, _ = self.forward(x_t)
                pred_np = pred_scaled.squeeze(0).cpu().numpy()
                
                # Residual against baseline expectation
                zero_baseline = torch.zeros_like(pred_scaled)
                residual_t = self.compute_residual_error(pred_scaled, zero_baseline)
                residual = float(residual_t.squeeze().cpu().numpy())
                
                infil_prob = float(1.0 - np.exp(-self.gamma * max(0.0, residual)))
                infil_prob = float(np.clip(infil_prob, 0.0, 1.0))
                
                unscaled_pred = pred_np * self.benign_std.cpu().numpy() + self.benign_mean.cpu().numpy()
                pred_stage, stage_probs = profile_mitre_stage(unscaled_pred, infil_prob)
                
                # Roll window forward: drop oldest state, append predicted next state
                seq_buffer = np.vstack([seq_buffer[1:], pred_np])
                
                horizon_sec = step * step_seconds
                rollout_results.append({
                    "step": step,
                    "horizon_seconds": horizon_sec,
                    "horizon_label": f"+{horizon_sec}s Ahead",
                    "predicted_state": unscaled_pred.tolist(),
                    "residual_error": residual,
                    "infiltration_probability": infil_prob,
                    "predicted_stage": pred_stage,
                    "stage_probabilities": stage_probs,
                    "severity": "CRITICAL" if infil_prob >= 0.45 else ("ELEVATED" if infil_prob >= 0.10 else "NOMINAL")
                })
                
        return rollout_results

    def simulate_counterfactual_rollout(
        self, 
        current_seq: np.ndarray, 
        k_steps: int = 5,
        step_seconds: int = 15
    ) -> Dict[str, Any]:
        """
        Simulates Twin Trajectories for Proactive Decision Support:
        1. Status Quo: Unmitigated attack trajectory propagating forward.
        2. Counterfactual SOAR: Active policy mitigation immediately dampens
           anomalous feature spikes towards benign baseline equilibrium.
        """
        status_quo = self.simulate_k_step_rollout(current_seq, k_steps=k_steps, step_seconds=step_seconds)
        
        # Mitigated Counterfactual Simulation
        self.eval()
        mitigated_results = []
        seq_buffer = np.copy(current_seq) # [5, 14]
        
        with torch.no_grad():
            for step in range(1, k_steps + 1):
                x_t = torch.tensor(seq_buffer, dtype=torch.float32).unsqueeze(0)
                pred_scaled, _ = self.forward(x_t)
                pred_np = pred_scaled.squeeze(0).cpu().numpy()
                
                # Apply simulated SOAR dampening: exponential decay of anomaly towards benign zero
                dampen_factor = float(np.exp(-0.85 * step))
                mitigated_pred = pred_np * dampen_factor
                
                zero_baseline = torch.zeros_like(pred_scaled)
                mitigated_t = torch.tensor(mitigated_pred, dtype=torch.float32).unsqueeze(0)
                residual_t = self.compute_residual_error(mitigated_t, zero_baseline)
                residual = float(residual_t.squeeze().cpu().numpy())
                
                infil_prob = float(1.0 - np.exp(-self.gamma * max(0.0, residual)))
                infil_prob = float(np.clip(infil_prob, 0.0, 1.0))
                
                unscaled_pred = mitigated_pred * self.benign_std.cpu().numpy() + self.benign_mean.cpu().numpy()
                pred_stage, stage_probs = profile_mitre_stage(unscaled_pred, infil_prob)
                
                seq_buffer = np.vstack([seq_buffer[1:], mitigated_pred])
                horizon_sec = step * step_seconds
                
                mitigated_results.append({
                    "step": step,
                    "horizon_seconds": horizon_sec,
                    "horizon_label": f"+{horizon_sec}s Ahead",
                    "predicted_state": unscaled_pred.tolist(),
                    "residual_error": residual,
                    "infiltration_probability": infil_prob,
                    "predicted_stage": pred_stage,
                    "stage_probabilities": stage_probs,
                    "severity": "CRITICAL" if infil_prob >= 0.45 else ("ELEVATED" if infil_prob >= 0.10 else "NOMINAL")
                })
                
        initial_risk = status_quo[-1]["infiltration_probability"] if len(status_quo) > 0 else 0.5
        mitigated_final_risk = mitigated_results[-1]["infiltration_probability"] if len(mitigated_results) > 0 else 0.05
        risk_reduction_pct = max(0.0, float((initial_risk - mitigated_final_risk) / (initial_risk + 1e-6) * 100.0))
        
        return {
            "status_quo_trajectory": status_quo,
            "mitigated_trajectory": mitigated_results,
            "initial_unmitigated_risk_pct": round(initial_risk * 100.0, 2),
            "projected_mitigated_risk_pct": round(mitigated_final_risk * 100.0, 2),
            "risk_reduction_efficiency_pct": round(risk_reduction_pct, 1),
            "remediation_verdict": f"SOAR Quarantine achieves {risk_reduction_pct:.1f}% risk reduction within +{k_steps*step_seconds}s."
        }


def profile_mitre_stage(state_vector: np.ndarray, infil_prob: float) -> Tuple[str, List[float]]:
    feat_map = {name: state_vector[i] for i, name in enumerate(FEATURE_NAMES)}
    
    if infil_prob < 0.10:
        return "Normal", [0.85, 0.05, 0.04, 0.03, 0.03]
        
    scores = [0.05, 0.1, 0.1, 0.1, 0.1]
    
    if feat_map.get("dst_port_entropy", 0.0) > 1.2 or feat_map.get("syn_ratio", 0.0) > 0.4:
        scores[1] += 0.55
        
    if feat_map.get("service_remote_ratio", 0.0) > 0.3 or feat_map.get("unallowed_port_ratio", 0.0) > 0.4:
        scores[2] += 0.65
        
    if feat_map.get("service_remote_ratio", 0.0) > 0.5 and feat_map.get("flow_duration_mean", 0.0) > 1000.0:
        scores[3] += 0.70
        
    if feat_map.get("pkt_len_var_mean", 0.0) > 2000.0 or feat_map.get("flow_duration_mean", 0.0) > 5000.0:
        scores[4] += 0.75
        
    probs = np.array(scores) / sum(scores)
    best_idx = int(np.argmax(probs))
    return STAGE_NAMES[best_idx], probs.tolist()


def generate_soar_playbook(
    mitre_stage: str,
    attacker_ip: str = "18.218.115.60",
    victim_subnet: str = "192.168.10.0/24",
    prob: float = 0.95
) -> Dict[str, str]:
    """
    Generates tailored, actionable automated firewall & SOAR remediation commands.
    """
    clean_ip = attacker_ip.strip()
    
    if "impact" in mitre_stage.lower() or "dos" in mitre_stage.lower():
        iptables_cmd = (
            f"# [AEGIS-SOAR] Automated DoS / Slowloris Mitigation\n"
            f"iptables -I INPUT -s {clean_ip}/32 -j DROP\n"
            f"iptables -I FORWARD -s {clean_ip}/32 -d {victim_subnet} -j DROP\n"
            f"iptables -A INPUT -p tcp --dport 80 -m connlimit --connlimit-above 50 -j REJECT --reject-with tcp-reset\n"
            f"sysctl -w net.ipv4.tcp_syncookies=1 > /dev/null"
        )
        aws_sg_cmd = (
            f'aws ec2 revoke-security-group-ingress --group-id sg-0aegis26153 --protocol tcp --port 80 --cidr {clean_ip}/32\n'
            f'aws ec2 authorize-security-group-egress --group-id sg-0aegis26153 --protocol -1 --cidr 0.0.0.0/0'
        )
        cisco_acl_cmd = (
            f"access-list 101 deny tcp host {clean_ip} {victim_subnet} 0.0.0.255 eq 80\n"
            f"access-list 101 permit ip any any\n"
            f"interface GigabitEthernet0/1\n ip access-group 101 in"
        )
    elif "access" in mitre_stage.lower() or "brute" in mitre_stage.lower():
        iptables_cmd = (
            f"# [AEGIS-SOAR] Automated SSH / FTP Brute-Force Blacklist\n"
            f"iptables -I INPUT -p tcp -m multiport --dports 21,22 -s {clean_ip}/32 -j DROP\n"
            f"iptables -I FORWARD -s {clean_ip}/32 -d {victim_subnet} -j DROP\n"
            f"iptables -A INPUT -p tcp --dport 22 -m recent --name SSH_ATTACK --update --seconds 60 --hitcount 4 -j DROP"
        )
        aws_sg_cmd = (
            f'aws ec2 revoke-security-group-ingress --group-id sg-0aegis26153 --protocol tcp --port 22 --cidr {clean_ip}/32\n'
            f'aws wafv2 update-ip-set --name "Aegis-BruteForce-Blocklist" --scope REGIONAL --addresses "{clean_ip}/32"'
        )
        cisco_acl_cmd = (
            f"access-list 101 deny tcp host {clean_ip} {victim_subnet} 0.0.0.255 eq 22\n"
            f"access-list 101 deny tcp host {clean_ip} {victim_subnet} 0.0.0.255 eq 21\n"
            f"access-list 101 permit ip any any"
        )
    elif "control" in mitre_stage.lower() or "botnet" in mitre_stage.lower():
        iptables_cmd = (
            f"# [AEGIS-SOAR] Automated Botnet C2 Isolation & DNS Sinkhole\n"
            f"iptables -I OUTPUT -d {clean_ip}/32 -j REJECT --reject-with icmp-net-unreachable\n"
            f"iptables -I FORWARD -d {clean_ip}/32 -j DROP\n"
            f"iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-ports 5353"
        )
        aws_sg_cmd = (
            f'aws route53resolver create-firewall-rule-group --name "Aegis-C2-Sinkhole"\n'
            f'aws ec2 revoke-security-group-egress --group-id sg-0aegis26153 --protocol -1 --cidr {clean_ip}/32'
        )
        cisco_acl_cmd = (
            f"access-list 101 deny ip {victim_subnet} 0.0.0.255 host {clean_ip}\n"
            f"access-list 101 permit ip any any"
        )
    else:
        iptables_cmd = (
            f"# [AEGIS-SOAR] Automated Quarantine Rule\n"
            f"iptables -I FORWARD -s {clean_ip}/32 -d {victim_subnet} -j DROP\n"
            f"iptables -I INPUT -s {clean_ip}/32 -j LOG --log-prefix '[AEGIS-QUARANTINE] '"
        )
        aws_sg_cmd = f'aws ec2 revoke-security-group-ingress --group-id sg-0aegis26153 --protocol -1 --cidr {clean_ip}/32'
        cisco_acl_cmd = f"access-list 101 deny ip host {clean_ip} any\naccess-list 101 permit ip any any"

    return {
        "iptables": iptables_cmd,
        "aws_cli": aws_sg_cmd,
        "cisco_acl": cisco_acl_cmd,
        "action_summary": f"ISOLATE HOST {clean_ip}/32 FROM {victim_subnet}"
    }


def generate_stix_bundle(
    incident_id: str,
    timestamp: str,
    attacker_ip: str,
    mitre_stage: str,
    risk_score: float,
    soar_playbook: Dict[str, str]
) -> Dict[str, Any]:
    """
    Generates an authentic OASIS STIX 2.1 Threat Intelligence JSON Bundle.
    Includes Indicator, Attack Pattern, Observed Data, and Course of Action.
    """
    clean_ip = attacker_ip.strip()
    bundle_id = f"bundle--{uuid.uuid4()}"
    indicator_id = f"indicator--{uuid.uuid4()}"
    attack_pattern_id = f"attack-pattern--{uuid.uuid4()}"
    coa_id = f"course-of-action--{uuid.uuid4()}"
    obs_id = f"observed-data--{uuid.uuid4()}"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    stage_to_mitre_id = {
        "Reconnaissance": ("T1046", "Network Service Scanning"),
        "Initial Access": ("T1110", "Brute Force"),
        "Lateral Movement": ("T1068", "Exploitation for Privilege Escalation"),
        "Exfiltration": ("T1041", "Exfiltration Over C2 Channel"),
        "Normal": ("T0000", "Baseline Activity")
    }
    tid, tname = stage_to_mitre_id.get(mitre_stage, ("T1190", "Exploit Public-Facing Application"))
    
    return {
        "type": "bundle",
        "id": bundle_id,
        "spec_version": "2.1",
        "objects": [
            {
                "type": "indicator",
                "id": indicator_id,
                "spec_version": "2.1",
                "created": now_iso,
                "modified": now_iso,
                "name": f"AegisDynamics Alert: Malicious IPv4 {clean_ip}",
                "description": f"Continuous World Model detected state deviation in stage {mitre_stage} (Risk: {risk_score*100:.1f}%)",
                "indicator_types": ["malicious-activity", "anomalous-traffic"],
                "pattern": f"[ipv4-addr:value = '{clean_ip}']",
                "pattern_type": "stix",
                "valid_from": now_iso,
                "confidence": int(round(risk_score * 100))
            },
            {
                "type": "attack-pattern",
                "id": attack_pattern_id,
                "spec_version": "2.1",
                "created": now_iso,
                "modified": now_iso,
                "name": tname,
                "description": f"MITRE ATT&CK Phase: {mitre_stage}",
                "external_references": [
                    {
                        "source_name": "mitre-attack",
                        "external_id": tid,
                        "url": f"https://attack.mitre.org/techniques/{tid}"
                    }
                ]
            },
            {
                "type": "course-of-action",
                "id": coa_id,
                "spec_version": "2.1",
                "created": now_iso,
                "modified": now_iso,
                "name": f"Automated Quarantine for {clean_ip}",
                "description": soar_playbook.get("action_summary", f"Isolate {clean_ip}"),
                "action": soar_playbook.get("iptables", "")
            },
            {
                "type": "observed-data",
                "id": obs_id,
                "spec_version": "2.1",
                "created": now_iso,
                "modified": now_iso,
                "first_observed": timestamp,
                "last_observed": timestamp,
                "number_observed": 1,
                "objects": {
                    "0": {
                        "type": "ipv4-addr",
                        "value": clean_ip
                    }
                }
            }
        ]
    }


def generate_sigma_rule(
    incident_id: str,
    mitre_stage: str,
    attacker_ip: str,
    victim_subnet: str = "192.168.10.0/24"
) -> str:
    """
    Synthesizes generic SIEM detection Sigma Rule YAML
    compatible with Splunk, Elastic, Microsoft Sentinel, and QRadar.
    """
    clean_ip = attacker_ip.strip()
    rule_id = str(uuid.uuid4())
    
    stage_to_tag = {
        "Reconnaissance": "attack.discovery, attack.t1046",
        "Initial Access": "attack.initial_access, attack.t1110",
        "Lateral Movement": "attack.lateral_movement, attack.t1068",
        "Exfiltration": "attack.impact, attack.t1498",
        "Normal": "attack.defense_evasion"
    }
    tags = stage_to_tag.get(mitre_stage, "attack.initial_access")
    
    yaml_content = f"""title: AegisDynamics Detected Anomalous Traffic from {clean_ip}
id: {rule_id}
status: experimental
description: Auto-generated Sigma rule from AegisDynamics Self-Supervised World Model for {mitre_stage}
author: AegisDynamics SIH26153 Autonomous SOC
references:
    - https://aegisdynamics.internal/incidents/{incident_id}
date: {datetime.now(timezone.utc).strftime('%Y/%m/%d')}
tags:
    - {tags}
logsource:
    category: firewall
    product: zeek_or_netflow
detection:
    selection:
        src_ip: '{clean_ip}'
        dst_ip|cidr: '{victim_subnet}'
    condition: selection
falsepositives:
    - Highly authorized internal vulnerability assessments
level: high
"""
    return yaml_content


def train_self_supervised_world_model(
    model: SelfSupervisedWorldModel,
    X_train_benign: np.ndarray,
    y_train_benign: np.ndarray,
    epochs: int = 15,
    batch_size: int = 16,
    lr: float = 0.003
) -> Dict[str, List[float]]:
    set_deterministic_seed(42)
    X_t = torch.tensor(X_train_benign, dtype=torch.float32)
    y_t = torch.tensor(y_train_benign, dtype=torch.float32)
    
    dataset = TensorDataset(X_t, y_t)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
    
    criterion = nn.SmoothL1Loss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    
    history = {"loss": []}
    model.train()
    
    for epoch in range(epochs):
        epoch_loss = 0.0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            pred_y, _ = model(batch_x)
            loss = criterion(pred_y, batch_y)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            
        avg_loss = epoch_loss / len(loader)
        history["loss"].append(avg_loss)
        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"[*] Self-Supervised Training Epoch [{epoch+1:02d}/{epochs:02d}] Smooth L1 Loss: {avg_loss:.5f}")
            
    return history


def calibrate_gamma_on_benign_validation(
    model: SelfSupervisedWorldModel,
    X_val_benign: np.ndarray,
    y_val_benign: np.ndarray,
    percentile_target: float = 95.0,
    target_p_infil: float = 0.10
) -> Tuple[float, float]:
    model.eval()
    with torch.no_grad():
        X_t = torch.tensor(X_val_benign, dtype=torch.float32)
        y_t = torch.tensor(y_val_benign, dtype=torch.float32)
        
        preds, _ = model(X_t)
        residuals = model.compute_residual_error(preds, y_t).cpu().numpy()
        
        e_95 = float(np.percentile(residuals, percentile_target))
        if e_95 <= 1e-4:
            e_95 = 0.01
            
        e_90 = float(np.percentile(residuals, 90.0))
        e_99 = float(np.percentile(residuals, 99.0))
        model.conformal_q90 = max(0.01, e_90)
        model.conformal_q99 = max(0.02, e_99)
            
        gamma_calibrated = float(-np.log(1.0 - target_p_infil) / e_95)
        model.gamma = gamma_calibrated
        model.residual_threshold_95 = e_95
        
        print(f"[+] Calibration Complete: Benign Val e_95 = {e_95:.5f} (q90={model.conformal_q90:.4f}, q99={model.conformal_q99:.4f}) | Calibrated Gamma = {gamma_calibrated:.5f}")
        return gamma_calibrated, e_95


def save_models(
    world_model: SelfSupervisedWorldModel, 
    baseline: StaticLogisticRegressionBaseline, 
    save_dir: str = "checkpoints"
):
    os.makedirs(save_dir, exist_ok=True)
    torch.save({
        "state_dict": world_model.state_dict(),
        "gamma": world_model.gamma,
        "e_95": world_model.residual_threshold_95,
        "benign_mean": world_model.benign_mean.cpu(),
        "benign_std": world_model.benign_std.cpu()
    }, os.path.join(save_dir, "world_model.pt"))
    with open(os.path.join(save_dir, "baseline.pkl"), "wb") as f:
        pickle.dump(baseline, f)
    print(f"[+] Models saved successfully to {save_dir}/")


def load_models(
    world_model: SelfSupervisedWorldModel, 
    baseline: StaticLogisticRegressionBaseline, 
    save_dir: str = "checkpoints"
) -> bool:
    wm_path = os.path.join(save_dir, "world_model.pt")
    bl_path = os.path.join(save_dir, "baseline.pkl")
    if os.path.exists(wm_path) and os.path.exists(bl_path):
        ckpt = torch.load(wm_path, map_location="cpu", weights_only=False)
        world_model.load_state_dict(ckpt["state_dict"])
        world_model.gamma = ckpt.get("gamma", 0.1)
        world_model.residual_threshold_95 = ckpt.get("e_95", 1.0)
        world_model.benign_mean.copy_(ckpt["benign_mean"])
        world_model.benign_std.copy_(ckpt["benign_std"])
        with open(bl_path, "rb") as f:
            loaded_bl = pickle.load(f)
            baseline.__dict__.update(loaded_bl.__dict__)
        print(f"[+] Models loaded successfully from {save_dir}/")
        return True
    return False
