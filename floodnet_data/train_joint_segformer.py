"""Joint Mixed-Domain SegFormer Training (50% Drone + 50% Satellite).

Trained on NVIDIA RTX 3050 GPU with CUDA Tensor Cores and FP16 Mixed Precision.
In every batch of 8:
  - 4 samples from Drone dataset (FloodNet)
  - 4 samples from Satellite dataset (SpaceNet 8 Germany & Louisiana)

Prevents catastrophic forgetting while expanding the model to orbital satellite scale.
Saves best model to floodnet_data/checkpoints_joint/best.
"""
import argparse
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import SegformerForSemanticSegmentation

DRONE_DIR = Path("floodnet_data/processed")
SAT_DIR = Path("floodnet_data/satellite_processed")
SAVE_DIR = Path("floodnet_data/checkpoints_joint")

NUM_CLASSES = 3
ID2LABEL = {0: "background", 1: "flooded", 2: "natural_water"}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
CLASS_WEIGHTS = [1.0, 3.5, 1.5]

def to_tensor(img_uint8):
    x = (img_uint8.astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(x.transpose(2, 0, 1).copy())

class JointDataset(Dataset):
    def __init__(self, crop=256, length=600):
        self.crop = crop
        self.length = length
        
        # Drone pool
        self.drone_img_dir = DRONE_DIR / "images" / "train"
        self.drone_ann_dir = DRONE_DIR / "annotations" / "train"
        self.drone_names = sorted(p.name for p in self.drone_img_dir.glob("*.png"))
        
        # Satellite pool
        self.sat_img_dir = SAT_DIR / "images"
        self.sat_ann_dir = SAT_DIR / "annotations"
        self.sat_names = sorted(p.name for p in self.sat_img_dir.glob("*.png"))
        
        print(f"Loaded JointDataset: {len(self.drone_names)} drone images | {len(self.sat_names)} satellite tiles")

    def __len__(self):
        return self.length

    def _sample_item(self, img_dir, ann_dir, names):
        n = random.choice(names)
        img = np.array(Image.open(img_dir / n).convert("RGB"))
        lbl = np.array(Image.open(ann_dir / n))
        
        h, w = lbl.shape
        ch, cw = min(self.crop, h), min(self.crop, w)
        y = random.randint(0, h - ch) if h > ch else 0
        x = random.randint(0, w - cw) if w > cw else 0
        
        img = img[y:y + ch, x:x + cw]
        lbl = lbl[y:y + ch, x:x + cw]
        
        # Augmentations
        if random.random() < 0.5:
            img, lbl = img[:, ::-1], lbl[:, ::-1]
        if random.random() < 0.5:
            img, lbl = img[::-1, :], lbl[::-1, :]
        if random.random() < 0.5:
            jitter = random.uniform(0.85, 1.15)
            img = np.clip(img.astype(np.float32) * jitter, 0, 255).astype(np.uint8)
            
        return to_tensor(img), torch.from_numpy(lbl.astype(np.int64).copy())

    def __getitem__(self, idx):
        # Even index -> Drone sample, Odd index -> Satellite sample (50/50 balance)
        if idx % 2 == 0:
            return self._sample_item(self.drone_img_dir, self.drone_ann_dir, self.drone_names)
        else:
            return self._sample_item(self.sat_img_dir, self.sat_ann_dir, self.sat_names)

class DroneValDataset(Dataset):
    def __init__(self, limit=100):
        self.img_dir = DRONE_DIR / "images" / "val"
        self.ann_dir = DRONE_DIR / "annotations" / "val"
        self.names = sorted(p.name for p in self.img_dir.glob("*.png"))[:limit]

    def __len__(self):
        return len(self.names)

    def __getitem__(self, i):
        n = self.names[i]
        img = np.array(Image.open(self.img_dir / n).convert("RGB"))
        lbl = np.array(Image.open(self.ann_dir / n))
        return to_tensor(img), torch.from_numpy(lbl.astype(np.int64).copy())

@torch.no_grad()
def evaluate_drone(model, loader, device):
    model.eval()
    conf = torch.zeros(NUM_CLASSES, NUM_CLASSES, dtype=torch.long)
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        logits = F.interpolate(model(pixel_values=x).logits, size=y.shape[-2:],
                                mode="bilinear", align_corners=False)
        pred = logits.argmax(1)
        valid = y != 255
        idx = y[valid] * NUM_CLASSES + pred[valid]
        conf += torch.bincount(idx, minlength=NUM_CLASSES ** 2).reshape(NUM_CLASSES, NUM_CLASSES).cpu()
    inter = conf.diag().float()
    union = conf.sum(0).float() + conf.sum(1).float() - inter
    iou = inter / union.clamp(min=1)
    return iou.tolist(), iou.mean().item()

def train():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=======================================================")
    print(f"Starting Joint Mixed-Domain Training (50% Drone + 50% Satellite)")
    print(f"Compute Device: {device.upper()}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)} (VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB)")
        print(f"FP16 Mixed Precision Enabled | Batch Size: 8 (4 Drone + 4 Satellite)")
    print(f"=======================================================")

    epochs = 6
    batch_size = 8
    lr = 4e-5
    steps_per_epoch = 150  # 150 * 8 = 1,200 crops per epoch

    train_ds = JointDataset(crop=256, length=steps_per_epoch * batch_size)
    val_ds = DroneValDataset(limit=100)
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=2, pin_memory=(device == "cuda"))
    val_dl = DataLoader(val_ds, batch_size=4, shuffle=False, num_workers=2, pin_memory=(device == "cuda"))

    # Load starting checkpoint from our best full drone model
    start_ckpt = Path("floodnet_data/checkpoints_full/best")
    print(f"Loading initial foundation weights from: {start_ckpt}")
    model = SegformerForSemanticSegmentation.from_pretrained(
        str(start_ckpt),
        num_labels=NUM_CLASSES,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    ).to(device)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    total_steps = epochs * len(train_dl)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=total_steps, eta_min=5e-6)
    weights = torch.tensor(CLASS_WEIGHTS, device=device)
    scaler = torch.amp.GradScaler('cuda', enabled=(device == "cuda"))

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    best_miou = -1.0

    for epoch in range(1, epochs + 1):
        model.train()
        t0 = time.time()
        running_loss = 0.0

        for step, (x, y) in enumerate(train_dl, 1):
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.amp.autocast('cuda', enabled=(device == "cuda")):
                logits = model(pixel_values=x).logits
                logits = F.interpolate(logits, size=y.shape[-2:], mode="bilinear", align_corners=False)
                loss = F.cross_entropy(logits.float(), y, weight=weights, ignore_index=255)

            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            running_loss += loss.item()

            if step % 30 == 0:
                print(f"  Epoch {epoch}/{epochs} | Step {step}/{len(train_dl)} | Loss: {running_loss / step:.4f}")

        epoch_time = time.time() - t0
        iou, miou = evaluate_drone(model, val_dl, device)
        print(f"Epoch {epoch}/{epochs} | Time: {epoch_time:.1f}s | Val Drone IoU -> BG: {iou[0]:.3f}, Flooded: {iou[1]:.3f}, Water: {iou[2]:.3f} | mIoU: {miou:.3f}")

        if miou > best_miou:
            best_miou = miou
            model.save_pretrained(SAVE_DIR / "best")
            print(f"  --> Saved new best Joint Model (mIoU: {best_miou:.3f}) to {SAVE_DIR / 'best'}")

    print(f"\nTraining Complete! Best Joint mIoU: {best_miou:.3f}")
    print(f"Saved to: {SAVE_DIR / 'best'}")

if __name__ == "__main__":
    train()
