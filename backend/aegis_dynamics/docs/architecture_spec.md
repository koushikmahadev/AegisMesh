# AegisDynamics Architectural Specification
## Continuous-Time Cyber Defense World Model (SIH26153)

---

### 1. Architectural Overview
AegisDynamics decouples threat hunting from brittle signature matching and static classification. It operates as a continuous state-space observer modeling enterprise network dynamics through dual-channel spatiotemporal momentum.

```
+-----------------------------------------------------------------------------------+
|                           ENTERPRISE NETWORK FLOWS                                |
|             (CIC-IDS2018 / PCAP / NetFlow / IPFIX Telemetry Stream)               |
+-----------------------------------------+-----------------------------------------+
                                          |
                   [Sliding Window State Extraction: W=60s, S=15s]
                                          |
                 +------------------------+------------------------+
                 |                                                 |
                 v                                                 v
    +-------------------------+                       +-------------------------+
    |   TEMPORAL CHANNEL      |                       |    GRAPH CHANNEL        |
    |  Huber World Model      |                       |  Spectral Graph L_t     |
    |  S_t -> S_{t+1} State   |                       |  Algebraic Conn. λ_2    |
    |  Prediction Residual e_T|                       |  Spectral Gap (λ_n-λ_2) |
    +------------+------------+                       +------------+------------+
                 |                                                 |
                 |      +-----------------------------------+      |
                 +----->|  SPATIOTEMPORAL CROSS-MOMENTUM    |<-----+
                        |             (STCM)                |
                        | M_ST = e_T * (1 + 5*v_topo)^2.0   |
                        +-----------------+-----------------+
                                          |
                                          v
                        +-----------------------------------+
                        |   GATED ENTROPY MEMORY (GEM)      |
                        | Freeze buffer if Risk_ST > 0.15   |
                        +-----------------+-----------------+
                                          |
                 +------------------------+------------------------+
                 |                                                 |
                 v                                                 v
    +-------------------------+                       +-------------------------+
    |   ANALYST EXPLAINABILITY|                       |  AUTONOMOUS SOAR ENGINE |
    |   - True SHAP Values    |                       |  - AWS WAF / Security Gr|
    |   - +75s K-Step Rollout |                       |  - Cisco Hardware ACL   |
    |   - MITRE ATT&CK Phase  |                       |  - Linux iptables Drop  |
    +-------------------------+                       +-------------------------+
```

---

### 2. Mathematics of Detection Layers

#### Layer 1: Self-Supervised Temporal World Model
* **Input**: 5-step historical lookback sequence $X_t \in \mathbb{R}^{5 \times 14}$.
* **Objective Function**: Smooth L1 (Huber) Loss:
  $$\mathcal{L}(y, \hat{y}) = \begin{cases} 0.5(y - \hat{y})^2 & \text{if } |y - \hat{y}| < 1.0 \\ |y - \hat{y}| - 0.5 & \text{otherwise} \end{cases}$$
* **Residual Error**: $e_T(t) = \|\hat{S}_{t+1} - S_{t+1}\|_1$.

#### Layer 2: Spectral Graph Topology Engine
* **Graph Laplacian**: $L_t = D_t - A_t$.
* **Algebraic Connectivity ($\lambda_2$)**: Second smallest eigenvalue of normalized Laplacian, measuring global network interconnectivity.
* **Topological Velocity ($v_{\text{topo}}$)**:
  $$v_{\text{topo}}(t) = \left| \ln \left( \frac{\lambda_2(t) + 10^{-7}}{\lambda_2(t-1) + 10^{-7}} \right) \right|$$

#### Layer 3: Spatiotemporal Cross-Momentum (STCM)
$$\mathcal{M}_{ST}(t) = e_T(t) \cdot \Big(1.0 + \kappa \cdot v_{\text{topo}}(t)\Big)^\zeta \quad (\kappa = 5.0, \, \zeta = 2.0)$$
$$\text{Risk}_{ST}(t) = 1.0 - \exp\big(-\gamma_T \cdot \mathcal{M}_{ST}(t)\big)$$

#### Layer 4: Gated Entropy Memory (GEM)
$$\text{FIFO\_Buffer} \leftarrow (X_t, y_{t+1}) \iff \text{Risk}_{ST}(t) \le 0.15$$
Frozen memory protects online rolling baselines against baseline poisoning during sustained low-and-slow campaigns.
