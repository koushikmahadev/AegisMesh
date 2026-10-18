# AegisDynamics: 2-Minute Demo Video Script (SIH26153)
**Target Duration:** Exactly 120 Seconds (2:00 Minutes)  
**Tone:** Authoritative, Technical, Transparent, Cyber Defense Specialist

---

### [0:00 - 0:20] Hook & Problem Formulation
- **Visual:** Split-screen graphic: Traditional static IDS missing a slow multi-stage DoS/Infiltration attack vs. AegisDynamics forecasting the state transition 5 minutes prior.
- **Narrator (Audio):**  
  *"Traditional intrusion detection systems evaluate isolated single packets, blind to temporal history. They alert only after a server crashes or an exploit executes. For SIH26153, we built AegisDynamics: a Self-Supervised AI World Model that forecasts future network state transitions—P(S_{t+1}|S_t)—predicting attacks across the MITRE ATT&CK matrix ahead of execution."*

---

### [0:20 - 0:45] Architecture & Self-Supervised Benign Learning
- **Visual:** Screen capture of `parser.py` extracting 60-second sliding windows on authentic CSE-CIC-IDS2018 data, followed by the PyTorch BiLSTM + Temporal Attention architecture.
- **Narrator (Audio):**  
  *"Instead of brittle supervised attack classifiers that fail on novel zero-days, AegisDynamics trains self-supervised on benign baseline traffic using outlier-robust Huber loss over standardized 14-D state vectors. It models destination port Shannon entropy and enterprise port compliance for subnet 192.168.10.0/24. Sensitivity constant gamma is mathematically calibrated against the 95th percentile of benign validation residuals."*

---

### [0:45 - 1:15] Live Dashboard & Real-Time Attack Forecasting
- **Visual:** Full-screen walkthrough of the Streamlit Cyber Defense Dashboard (`http://localhost:8501`). Operator selects `02-15-2018.csv` (DoS Slowloris) and moves the playback slider across time.
- **Narrator (Audio):**  
  *"Watch our live SOC dashboard in action. During normal operations, the Infiltration Gauge rests below 10%. As Slowloris begins exhausting web sockets, static single-packet classifiers miss it completely. But our AI World Model tracks cumulative temporal state degradation—its reconstruction residual spikes, instantly forecasting an attack transition with 97% confidence and updating the MITRE ATT&CK timeline."*

---

### [1:15 - 1:35] SHAP Root-Cause Explainability & SOC Alert Log
- **Visual:** Full view of Tab 3 (SHAP Attribution Bar Chart) and Tab 5 (Local SOC Alert Log Table). Highlighting `flow_duration_mean` and `unallowed_port_ratio`.
- **Narrator (Audio):**  
  *"In a mission-critical SOC, black-box predictions are unacceptable. Our SHAP explainability layer decomposes the residual error in real time, proving the alarm was triggered by abnormal flow duration and unallowed port ratios. Timestamped alerts are logged directly to the local SOC console with complete forensic auditability."*

---

### [1:35 - 2:00] Rigorous Out-of-Time Benchmark & Air-Gapped Deployment
- **Visual:** Display Tab 4 Benchmark Comparison chart (World Model 99.2% Recall on DoS vs. Static Baseline 27.9%, and 99.1% Recall on Botnet C2) and terminal showing Docker running with `--network none`.
- **Narrator (Audio):**  
  *"Under strict chronological out-of-time evaluation across CSE-CIC-IDS2018, our World Model achieves 99.2% detection recall on accumulative DoS compared to just 27.9% for static baseline models, and 99.1% recall on Botnet C2 operations. Packaged in a fully air-gapped container with zero cloud dependencies, AegisDynamics transforms reactive security into predictive cyber defense. Thank you."*
