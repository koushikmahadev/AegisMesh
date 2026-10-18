"""
AegisDynamics - Synthetic CIC-IDS-2018 Flow Generator
Generates realistic multi-stage network attack scenario data.
Stages: Normal -> Reconnaissance -> Initial Access -> Lateral Movement -> Exfiltration
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_mock_cic_dataset(num_records: int = 1200, output_file: str = "mock_cic_ids_2018.csv") -> pd.DataFrame:
    np.random.seed(42)
    start_time = datetime(2026, 8, 24, 9, 0, 0)
    
    timestamps = []
    src_ips = []
    dst_ips = []
    src_ports = []
    dst_ports = []
    protocols = []
    flow_durations = []
    flow_iat_means = []
    pkt_len_vars = []
    syn_flags = []
    ack_flags = []
    fin_flags = []
    labels = []
    mitre_stages = []
    
    internal_ips = [f"192.168.1.{i}" for i in range(10, 50)]
    server_ips = ["192.168.1.5", "192.168.1.6", "10.0.0.100"]
    external_attacker = "203.0.113.42"
    
    # 5 attack phases across time sequence:
    # Phase 0 (0-25%): Normal baseline traffic
    # Phase 1 (25-45%): Reconnaissance (Port scanning, rapid SYN packets, high port entropy)
    # Phase 2 (45-65%): Initial Access (Brute force / exploit, abnormal payload variance, high IAT)
    # Phase 3 (65-85%): Lateral Movement (Internal pivot, SMB/RDP flows, SYN+ACK anomalies)
    # Phase 4 (85-100%): Data Exfiltration (High flow duration, high packet length, abnormal egress)
    
    current_time = start_time
    for i in range(num_records):
        current_time += timedelta(seconds=float(np.random.exponential(scale=2.5)))
        phase_ratio = i / float(num_records)
        
        if phase_ratio < 0.25:
            # Normal / Benign
            stage = "Normal"
            label = "Benign"
            s_ip = np.random.choice(internal_ips)
            d_ip = np.random.choice(server_ips)
            s_port = int(np.random.randint(49152, 65535))
            d_port = int(np.random.choice([80, 443, 53, 22]))
            proto = 6 if d_port in [80, 443, 22] else 17
            duration = float(np.random.gamma(shape=2.0, scale=500.0))
            iat_mean = float(np.random.normal(loc=120.0, scale=30.0))
            pkt_var = float(np.random.normal(loc=450.0, scale=80.0))
            syn = int(np.random.choice([0, 1], p=[0.85, 0.15]))
            ack = int(np.random.choice([0, 1], p=[0.2, 0.8]))
            fin = int(np.random.choice([0, 1], p=[0.8, 0.2]))
            
        elif phase_ratio < 0.45:
            # Reconnaissance (Recon)
            stage = "Reconnaissance"
            label = "PortScan"
            s_ip = external_attacker
            d_ip = np.random.choice(server_ips)
            s_port = int(np.random.randint(40000, 60000))
            # Scanning broad range of ports
            d_port = int(np.random.randint(1, 1024))
            proto = 6
            duration = float(np.random.uniform(5.0, 50.0)) # fast probes
            iat_mean = float(np.random.uniform(2.0, 15.0)) # rapid burst
            pkt_var = float(np.random.uniform(10.0, 60.0)) # uniform small probe packets
            syn = 1
            ack = int(np.random.choice([0, 1], p=[0.9, 0.1]))
            fin = 0
            
        elif phase_ratio < 0.65:
            # Initial Access
            stage = "Initial Access"
            label = "BruteForce-SSH/WebExploit"
            s_ip = external_attacker
            d_ip = "192.168.1.5" # primary DMZ server
            s_port = int(np.random.randint(50000, 60000))
            d_port = int(np.random.choice([22, 443, 8080]))
            proto = 6
            duration = float(np.random.uniform(800.0, 3000.0))
            iat_mean = float(np.random.uniform(40.0, 90.0))
            pkt_var = float(np.random.uniform(1200.0, 3500.0)) # high variance in login attempts & payloads
            syn = int(np.random.choice([0, 1], p=[0.4, 0.6]))
            ack = 1
            fin = int(np.random.choice([0, 1], p=[0.7, 0.3]))
            
        elif phase_ratio < 0.85:
            # Lateral Movement
            stage = "Lateral Movement"
            label = "Infiltration-InternalPivot"
            s_ip = "192.168.1.5" # compromised host pivoting internally
            d_ip = np.random.choice(["192.168.1.20", "192.168.1.35", "10.0.0.100"])
            s_port = int(np.random.randint(49152, 65535))
            d_port = int(np.random.choice([445, 139, 3389, 22])) # SMB, RDP, SSH
            proto = 6
            duration = float(np.random.uniform(1500.0, 5000.0))
            iat_mean = float(np.random.uniform(20.0, 70.0))
            pkt_var = float(np.random.uniform(800.0, 2200.0))
            syn = int(np.random.choice([0, 1], p=[0.3, 0.7]))
            ack = 1
            fin = int(np.random.choice([0, 1], p=[0.6, 0.4]))
            
        else:
            # Data Exfiltration
            stage = "Exfiltration"
            label = "DataExfiltration-Encrypted"
            s_ip = "10.0.0.100" # Core database/internal server
            d_ip = external_attacker
            s_port = int(np.random.randint(49152, 65535))
            d_port = 443
            proto = 6
            duration = float(np.random.uniform(4000.0, 12000.0))
            iat_mean = float(np.random.uniform(5.0, 25.0)) # continuous bulk transfer
            pkt_var = float(np.random.uniform(4000.0, 9500.0)) # maximum payload packet variance
            syn = 0
            ack = 1
            fin = int(np.random.choice([0, 1], p=[0.9, 0.1]))
            
        timestamps.append(current_time.strftime("%Y-%m-%d %H:%M:%S"))
        src_ips.append(s_ip)
        dst_ips.append(d_ip)
        src_ports.append(s_port)
        dst_ports.append(d_port)
        protocols.append(proto)
        flow_durations.append(max(0.1, duration))
        flow_iat_means.append(max(0.1, iat_mean))
        pkt_len_vars.append(max(0.1, pkt_var))
        syn_flags.append(syn)
        ack_flags.append(ack)
        fin_flags.append(fin)
        labels.append(label)
        mitre_stages.append(stage)
        
    df = pd.DataFrame({
        "Timestamp": timestamps,
        "Src_IP": src_ips,
        "Dst_IP": dst_ips,
        "Src_Port": src_ports,
        "Dst_Port": dst_ports,
        "Protocol": protocols,
        "Flow_Duration": flow_durations,
        "Flow_IAT_Mean": flow_iat_means,
        "Pkt_Len_Var": pkt_len_vars,
        "SYN_Flag_Cnt": syn_flags,
        "ACK_Flag_Cnt": ack_flags,
        "FIN_Flag_Cnt": fin_flags,
        "Label": labels,
        "Stage": mitre_stages
    })
    
    if output_file:
        df.to_csv(output_file, index=False)
        print(f"[+] Successfully generated synthetic CIC-IDS-2018 mock dataset with {len(df)} flows at: {output_file}")
        
    return df

if __name__ == "__main__":
    generate_mock_cic_dataset(1500, "AegisDynamics/mock_cic_ids_2018.csv")
