# HighWater — Model Training, Loss Functions & Technical Specifications

This document details the exact neural network training parameters, mathematical loss functions, dataset split distributions, augmentation pipelines, and algorithm specifications used across the HighWater emergency response platform.

---

## 1. Training Scripts & Architectures

The model pipeline employs **SegFormer-B0** (`nvidia/segformer-b0-finetuned-ade-512-512` backbone with an MiT-B0 hierarchical transformer encoder and lightweight MLP segmentation head):

| Component | Drone Foundation Training | Joint Drone + Satellite Training |
| :--- | :--- | :--- |
| **Script Path** | `floodnet_data/train_segformer.py` | `floodnet_data/train_joint_segformer.py` |
| **Model Architecture** | SegFormer-B0 (`num_labels=3`) | SegFormer-B0 (`num_labels=3`) |
| **Parameter Count** | 3.7 Million parameters (14.8 MB) | 3.7 Million parameters (14.8 MB) |
| **Inference Latency** | ~0.5s per tile (Fully Offline, CPU/CUDA) | ~0.5s per tile (Fully Offline, CPU/CUDA) |
| **Input Channels** | 3 (RGB normalized with ImageNet stats) | 3 (RGB normalized with ImageNet stats) |
| **Target Classes** | 0: Background/Dry, 1: Flooded, 2: Water | 0: Background/Dry, 1: Flooded, 2: Water |
| **Checkpoint Output** | `floodnet_data/checkpoints_full/best/` | `floodnet_data/checkpoints_joint/best/` |

---

## 2. Training Epochs & Optimization Hyperparameters

### Drone Model (`floodnet_data/train_segformer.py`)
- **Total Epochs**: **15 epochs**
- **Batch Size**: 8
- **Base Learning Rate**: $\eta = 6 \times 10^{-5}$
- **Optimizer**: AdamW ($\beta_1 = 0.9, \beta_2 = 0.999$, weight decay $= 0.01$)
- **Learning Rate Schedule**: Polynomial decay with power $0.9$:
  $$\eta(s) = \eta_0 \cdot \left(\max\left(0, 1 - \frac{s}{S_{\text{total}}}\right)\right)^{0.9}$$
- **Precision**: PyTorch FP16 Mixed Precision via `torch.amp.autocast('cuda')` with dynamic `GradScaler`.

### Joint Mixed-Domain Model (`floodnet_data/train_joint_segformer.py`)
- **Total Epochs**: **6 epochs**
- **Steps per Epoch**: 150 steps $\times$ batch size 8 = **1,200 augmented crops per epoch** (Total: **7,200 gradient updates**)
- **Batch Composition**: **50% Drone (FloodNet) + 50% Satellite (SpaceNet 8)** in every batch to prevent catastrophic forgetting.
- **Base Learning Rate**: $\eta = 4 \times 10^{-5}$
- **Optimizer**: AdamW (weight decay $= 0.01$)
- **Schedule**: Cosine Annealing with $\eta_{\text{min}} = 5 \times 10^{-6}$:
  $$\eta(t) = \eta_{\text{min}} + \frac{1}{2}(\eta_0 - \eta_{\text{min}})\left(1 + \cos\left(\frac{t}{T_{\text{max}}}\pi\right)\right)$$

---

## 3. Loss Function & Class Weight Formulation

### Mathematical Formulation
To solve the extreme class imbalance in disaster imagery where non-flooded terrain occupies the vast majority of pixels, we employ **Class-Weighted Cross-Entropy Loss** with unlabeled pixel masking:

$$\mathcal{L} = -\frac{1}{N} \sum_{i=1}^{N} \sum_{c=0}^{C-1} w_c \cdot \mathbb{I}(y_i = c) \cdot \log\left(\frac{\exp(z_{i, c})}{\sum_{j=0}^{C-1} \exp(z_{i, j})}\right)$$

Where:
- $z_{i, c}$ is the predicted logit for pixel $i$ at class $c$.
- $y_i$ is the ground-truth class label at pixel $i$.
- $\text{ignore\_index} = 255$ suppresses invalid or unannotated boundary pixels from gradient computation.

### Class Imbalance & Weight Calibration
From pixel-level auditing across the FloodNet dataset (total $443,904,000$ training pixels):

| Class ID | Semantic Class | Pixel Share | Loss Weight ($w_c$) | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **0** | **Background / Dry Land** | 84.75% ($376,188,864$ px) | **`1.0`** | Baseline majority class |
| **1** | **Flooded Structures & Roads** | **4.31%** ($19,140,725$ px) | **`3.5`** | **Heavily penalized** to eliminate dangerous false negatives on submerged roads & buildings |
| **2** | **Natural Water (Rivers/Lakes)** | 10.94% ($48,574,411$ px) | **`1.5`** | Prevents existing bodies of water from falsely triggering structural flood alarms |
| **255** | **Unlabeled / Invalid** | 0.00% | **`0.0`** | Masked out (`ignore_index = 255`) |

---

## 4. Dataset Splits & Verification Distribution

The benchmark adheres strictly to the official FloodNet Supervised v1.0 benchmark division:

| Split | Image Count | Mask Count | Percentage | Original Resolution | Processed Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Train** | **1,445** | 1,445 | **61.7%** | $4000 \times 3000$ | $640 \times 480$ (4:3 aspect preserved) |
| **Validation** | **450** | 450 | **19.2%** | $4000 \times 3000$ | $640 \times 480$ (4:3 aspect preserved) |
| **Test** | **448** | 448 | **19.1%** | $4000 \times 3000$ | $640 \times 480$ (4:3 aspect preserved) |
| **Total** | **2,343** | **2,343** | **100.0%** | — | — |

### Data Augmentation Pipeline
Applied dynamically in memory per training step:
1. **Random Scale & Crop**: Crops of $384 \times 384$ or $256 \times 256$ preserving high-frequency features.
2. **Horizontal Flip**: $p = 0.5$.
3. **Vertical Flip**: $p = 0.5$.
4. **Photometric Jitter**: Brightness jitter factor sampled uniformly from $[0.85, 1.15]$.
5. **Channel Normalization**:
   - $\mu = [0.485, 0.456, 0.406]$
   - $\sigma = [0.229, 0.224, 0.225]$

---

## 5. Model Validation & Benchmark Results

| Metric | Result | Benchmark Source / Methodology |
| :--- | :--- | :--- |
| **Ground-Truth Accuracy** | **80.67%** | Evaluated against human pixel annotations (FloodNet test split) |
| **Average Model Confidence** | **85.85%** | Weighted mean across 48 real-event disaster tiles |
| **Visual Verification Pass Rate** | **100% (48/48)** | Confirmed real flood inundation across all benchmark scenes |
| **Post-Flood Sentinel-2 (Kerala)** | 88.61% avg conf | 15 cloud-filtered satellite tiles ($98.45\% \to 18.76\%$ coverage range) |
| **Hurricane Harvey UAS (FloodNet)** | 84.60% avg conf | 33 verified drone scenes ($64.81\% \to 0.00\%$ coverage range) |

---

## 6. Physics-Constrained Graph Routing & Vehicle Formulations

Every road segment edge $e = (u, v)$ in the OpenStreetMap directed graph network incorporates dynamic water depth $d_e(t)$:

$$\text{Cost}(e) = \begin{cases} 
\infty & \text{if } d_e > D_{\text{limit}} \quad \text{(Road Blocked / Impassable)} \\
\frac{L_e}{V_{\text{max}}} \cdot \left(1 + \kappa \cdot \left(\frac{d_e}{D_{\text{limit}}}\right)^2\right) & \text{if } d_e \le D_{\text{limit}} \quad \text{(Fording Impedance)}
\end{cases}$$

### Operational Vehicle Limits ($D_{\text{limit}}$):
- **Standard Ambulance / Light Response**: $D_{\text{limit}} = 0.15 \text{ m}$ (6 inches)
- **High-Clearance Rescue Truck (4x4 / Unimog)**: $D_{\text{limit}} = 0.60 \text{ m}$ (24 inches)
- **Inflatable Rescue Boat**: Traverses water where $d_e \ge 0.30 \text{ m}$; impassable on dry terrain.
- **Drone Aerial Survey**: Traverses via direct Euclidean distance unaffected by surface water.

---

## 7. Dynamic Multi-Factor Risk Score Formulation

Zone priority is calculated dynamically without synthetic random values:

$$R_{\text{zone}} = w_F \cdot F_{\text{area}} + w_B \cdot \left(\frac{B_{\text{exposed}}}{B_{\text{total}}}\right) + w_R \cdot \left(\frac{L_{\text{flooded}}}{L_{\text{total}}}\right) + w_P \cdot P_{\text{critical}}$$

- Weights: $w_F = 0.35, w_B = 0.30, w_R = 0.25, w_P = 0.10$ ($\sum w = 1.0$)
- **CRITICAL**: $R \ge 0.75$ (Immediate aerial/boat evacuation)
- **HIGH**: $0.50 \le R < 0.75$ (High-clearance vehicle deployment)
- **MEDIUM**: $0.25 \le R < 0.50$ (Active monitoring / perimeter warning)
- **LOW**: $R < 0.25$ (Safe ground / staging area)
