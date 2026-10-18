# AegisDynamics // SIH Grand Finale Judge Q&A Defense Guide
## Anticipated Technical & Mathematical Defense Responses

---

### Q1: Why self-supervised world modeling instead of supervised classification (e.g., Random Forest, XGBoost)?
**Defense**:
1. **Zero Day & Novel Threat Immunity**: Supervised models learn specific class boundaries of historical attacks. When an attacker alters evasion techniques (e.g. rate-throttled Slowloris, living-off-the-land PowerShell), supervised models fail.
2. **Benign Physics Discipline**: Our World Model trains exclusively on uncompromised benign traffic. Any deviation from physical network conservation laws generates a high prediction residual $e(t+1)$, detecting zero-days without prior attack signatures.
3. **No Attack Label Dependence**: Real enterprise SOCs have millions of unlabeled flows. Supervised learning requires manual labeling; self-supervised learning trains continuously on baseline telemetry.

---

### Q2: Why did you choose Huber Smooth L1 Loss over Mean Squared Error (MSE)?
**Defense**:
* Network traffic exhibits high natural burstiness (e.g., occasional batch backups or large file transfers).
* Quadratic MSE loss disproportionately penalizes benign spikes, causing loss spikes that distort weights.
* Huber loss provides quadratic precision for subtle gradient signals ($|e| < 1.0$) while switching to robust linear penalties for extreme bursts ($|e| \ge 1.0$), ensuring stable convergence.

---

### Q3: How does your Spectral Graph Channel handle dynamic IP address allocations (DHCP)?
**Defense**:
* Our Graph Laplacian operates on normalized structural connectivity rather than hardcoded static IP strings.
* Algebraic connectivity ($\lambda_2$) and spectral dispersion ($\lambda_n - \lambda_2$) measure global cluster density, bipartite deformation, and communication entropy across the enterprise subnet.
* Whether host IPs shift or remain static, structural anomalies (such as fan-out port scans or centralized C2 star topologies) fundamentally distort the Laplacian eigenvalue spectrum.

---

### Q4: How does Gated Entropy Memory (GEM) solve the "Boiling Frog" baseline poisoning attack?
**Defense**:
* In rolling adaptive systems, slow persistent beaconing gradually pollutes trailing FIFO buffers.
* GEM places an admission gate on memory ingestion: if Spatiotemporal Risk $\text{Risk}_{ST} > 0.15$, the rolling memory is frozen.
* The system continues scoring against the pristine pre-attack baseline, preserving detection recall ($59.0\%$ vs $21.1\%$ un-gated) and preventing false normalization.

---

### Q5: How do you guarantee the system can run in air-gapped defense networks?
**Defense**:
* Zero external cloud APIs, zero remote LLM inference calls, and zero external telemetry reporting.
* SHAP explanations are computed via our embedded local KernelExplainer.
* Graph Laplacians are solved via local SciPy sparse eigensolvers.
* All REST APIs, WebSockets, and dashboard assets (Lucide SVG, HTML5 Canvas) are bundled directly inside the local runtime container.
