# AegisDynamics: AI-Based Network Attack Forecasting System
## Technical Architecture & Mathematical Specification Document (SIH26153)

---

### 1. Executive Summary & Problem Formulation
Traditional Network Intrusion Detection Systems (NIDS) evaluate isolated packets or static point-in-time flow snapshots:
$$P(y_t \mid x_t) \quad \text{where } y_t \in \{0, 1\}$$

This reactive paradigm fails against modern Advanced Persistent Threats (APTs) because stealthy reconnaissance, slow brute-force, and low-rate DoS attacks mimic normal background noise. Furthermore, static models have **zero predictive horizon**—triggering only after the breach payload executes ($t \ge t_{\text{exploit}}$).

**AegisDynamics** reformulates enterprise cyber defense as a **Self-Supervised Future State Transition Problem**:
$$\mathcal{M}: [S_{t-k}, \dots, S_t] \longmapsto \hat{S}_{t+1}$$

By training an AI World Model exclusively on benign baseline traffic, the system learns the enterprise network's continuous normal dynamics. When an attack trajectory begins, observed states deviate from the learned manifold, yielding an auto-regressive forecast residual $e(t+1)$ that forecasts the breach across the **MITRE ATT&CK Matrix** ahead of execution.

---

### 2. Topology-Aware Telemetry State Space ($S_t \in \mathbb{R}^{14}$)
Continuous raw flows in sliding window $W_t = [t - \Delta t, t]$ ($\Delta t = 60\text{s}$, stride $= 15\text{s}$) are standardized ($\mu=0, \sigma=1$) across 14 dimensions:

$$\begin{aligned}
S_t = \Big[ & \text{FlowCount}_t, \text{SYN\_Ratio}_t, \text{ACK\_Ratio}_t, \text{FIN\_Ratio}_t, \text{RST\_Ratio}_t, \\
           & \mu(\text{Duration}_t), \max(\text{Duration}_t), \mu(\text{Flow\_IAT}_t), \mu(\text{Pkt\_Len\_Var}_t), \mu(\text{Pkt\_Len}_t), \\
           & \mathcal{H}(\text{Port}_{\text{dst}, t}), \text{Unallowed\_Port\_Ratio}_t, \text{Service\_Web\_Ratio}_t, \text{Service\_Remote\_Ratio}_t \Big]^\top
\end{aligned}$$

Where destination port Shannon entropy is computed as:
$$\mathcal{H}(\text{Port}_{\text{dst}, t}) = - \sum_{p \in \text{Ports}} P(p) \log_2 P(p)$$

And unallowed port ratio measures violation against enterprise baseline $\mathcal{P}_{\text{allowed}} = \{80, 443, 53, 445, 3389\}$:
$$\text{Unallowed\_Port\_Ratio}_t = \frac{1}{N_t} \sum_{i=1}^{N_t} \mathbb{I}(\text{Port}_i \notin \mathcal{P}_{\text{allowed}})$$

---

### 3. Neural World Model Architecture & Huber Training
```
 [S_{t-4}, ..., S_t] ──► [BiLSTM Layer (2x64)] ──► [Temporal Attention] ──► [Decoder MLP] ──► \hat{S}_{t+1}
                                                                                                │
                                          Actual Future Telemetry S_{t+1} ──────────────────────┤
                                                                                                ▼
                                                                                   [Residual e(t+1)]
                                                                                   [Risk P(Infil)]
```

The network optimizes Smooth L1 (Huber) loss over standardized benign sequence lookbacks ($k = 5$):
$$\mathcal{L}_{\text{Huber}}(\theta) = \frac{1}{D} \sum_{d=1}^D \ell_d(\hat{S}_{t+1, d}, S_{t+1, d})$$
$$\ell_d(a, b) = \begin{cases} 0.5(a - b)^2 & \text{if } |a - b| < 1.0 \\ |a - b| - 0.5 & \text{otherwise} \end{cases}$$

---

### 4. Mathematical Gamma ($\gamma$) Calibration & Decision Threshold
The continuous infiltration probability mapping:
$$P(\text{Infiltration}_{t+1}) = 1 - \exp(-\gamma \cdot e(t+1))$$

Is **mathematically calibrated** against the 95th percentile ($e_{95}$) of benign validation residuals:
$$\text{Target: } P(e_{95}) \equiv 0.10 \implies 1 - \exp(-\gamma \cdot e_{95}) = 0.10$$
$$\gamma = \frac{-\ln(0.90)}{e_{95}} = \frac{\ln(10/9)}{e_{95}} \approx \frac{0.1053605}{e_{95}}$$

**Alert Trigger Rule:** An anomaly alarm is flagged when $e(t+1) \ge e_{95} \iff P(\text{Infiltration}_{t+1}) \ge 0.10$. This is mathematically derived from the empirical calibration ceiling rather than an arbitrary constant.

---

### 5. Rigorous Out-of-Time Benchmark Results (CSE-CIC-IDS2018)

Evaluated under strict **chronological out-of-time splits** with standardized features and deterministic seeding:

| Attack Scenario | Metric | Static Baseline | Temporal World Model (Ours) | Delta |
| :--- | :--- | :---: | :---: | :---: |
| **SSH/FTP Brute Force** (`02-14`) | Accuracy | 95.3% | 92.1% | -3.1% |
| *(Initial Access: 104 Atk / 23 Ben)* | Recall | 100.0% | **100.0%** | +0.0% |
| | Precision | 94.5% | 91.2% | -3.3% |
| | F1-Score | 0.972 | 0.954 | -0.018 |
| | FPR | 26.1% (6/23) [95% CI: 12.5%–46.5%] | 43.5% (10/23) [95% CI: 25.6%–63.2%] | +17.4% |
| **DoS GoldenEye/Slowloris** (`02-15`) | Accuracy | 74.0% | **97.1%** | **+23.1%** |
| *(Impact: 240 Atk / 518 Ben)* | Recall | 27.9% | **99.2%** | **+71.2%** |
| | Precision | 73.6% | **92.2%** | **+18.6%** |
| | F1-Score | 0.405 | **0.956** | **+0.551** |
| | FPR | 4.6% | **3.9%** | **-0.8%** |
| **Infiltration & PrivEsc** (`03-01`) | Accuracy | 22.1% | 23.3% | +1.2% |
| *(Stealth PrivEsc: 391 Atk / 1619 Ben)*| Recall | 16.9% | 12.8% | -4.1% |
| | Precision | 5.0% | 4.0% | -1.1% |
| | F1-Score | 0.078 | 0.061 | -0.017 |
| | FPR | 76.7% | **74.2%** | **-2.5%** |
| **Botnet C2 Operations** (`03-02`) | Accuracy | 99.8% | 98.6% | -1.2% |
| *(C2 Infrastructure: 652 Atk / 183 Ben)* | Recall | 99.7% | 99.1% | -0.6% |
| | Precision | 100.0% | 99.1% | -0.9% |
| | F1-Score | 0.998 | 0.991 | -0.008 |
| | FPR | 0.0% | 3.3% | +3.3% |

---

### 6. Acknowledged Technical Limitations & Tradeoffs

1. **Brute Force FPR Sample-Size Caveat**: In the Brute Force test partition, the 43.5% FPR represents **10 false positives out of only 23 benign test windows** (95% Wilson CI: `[25.6%, 63.2%]`). The static baseline's 26.1% FPR (6/23, 95% CI: `[12.5%, 46.5%]`) falls directly within this confidence interval, confirming that the two models are **not statistically distinguishable** at this sample size ($n=23$, a raw difference of only 4 windows).
2. **Infiltration Host-vs-Network Boundary**: Infiltration / Privilege Escalation in CIC-IDS-2018 occurs over legitimate Dropbox/HTTP channels without anomalous volumetric signatures. Both network-flow models struggle on flow-only telemetry (F1 $\approx 0.06–0.08$), reflecting the fundamental boundary where network monitoring must be paired with host/EDR telemetry.
3. **Core Strength (Multi-Stage Temporal Attacks)**: On stealthy, time-accumulative attacks like Slowloris/GoldenEye DoS, the World Model demonstrates massive superiority—achieving **99.2% Recall vs 27.9% Baseline** (+71.2% detection gain).

---

### 7. Explainability & Air-Gapped Deployment
- **SHAP Layer**: Decomposes forecast residual $e(t+1)$, ranking the top-3 telemetry metrics driving each alarm.
- **Air-Gapped Container**: Zero external internet calls, packaged in Docker for offline deployment.
