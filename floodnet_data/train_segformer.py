"""
SegFormer fine-tuning on the processed FloodNet data (3 classes), plus a demo
mode that runs the trained model on any folder of photos (e.g. Kerala).

Run from the project root (the folder that contains floodnet_data/).

  Smoke test (2-3 min, checks everything works):
    python train_segformer.py --limit 40 --epochs 1

  Full training:
    python train_segformer.py --epochs 15

  Predict on Kerala photos:
    python train_segformer.py --predict kerala_photos --out kerala_results

Install once inside floodnet_data/.venv:
    pip install torch torchvision transformers
(Use the CUDA build of torch from pytorch.org if you have an NVIDIA GPU.)
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

ROOT = Path("floodnet_data/processed")
ID2LABEL = {0: "background", 1: "flooded", 2: "natural_water"}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}
NUM_CLASSES = 3
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# Class weights to offset imbalance (train share: bg 84.8%, flooded 4.3%, water 10.9%)
CLASS_WEIGHTS = [1.0, 3.5, 1.5]
COLORS = np.array([[0, 0, 0], [255, 0, 0], [0, 200, 255]], dtype=np.uint8)


def to_tensor(img_uint8):
    x = (img_uint8.astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(x.transpose(2, 0, 1).copy())


class FloodSet(Dataset):
    def __init__(self, split, train, crop=384, limit=None):
        self.img_dir = ROOT / "images" / split
        self.ann_dir = ROOT / "annotations" / split
        self.names = sorted(p.name for p in self.img_dir.glob("*.png"))
        if limit:
            random.Random(0).shuffle(self.names); self.names = self.names[:limit]
        if not self.names:
            raise FileNotFoundError(f"No images found in {self.img_dir}")
        self.train, self.crop = train, crop

    def __len__(self):
        return len(self.names)

    def __getitem__(self, i):
        n = self.names[i]
        img = np.array(Image.open(self.img_dir / n).convert("RGB"))
        lbl = np.array(Image.open(self.ann_dir / n))
        if self.train:
            h, w = lbl.shape
            ch, cw = min(self.crop, h), min(self.crop, w)
            y, x = random.randint(0, h - ch), random.randint(0, w - cw)
            img, lbl = img[y:y + ch, x:x + cw], lbl[y:y + ch, x:x + cw]
            if random.random() < 0.5:  # horizontal flip
                img, lbl = img[:, ::-1], lbl[:, ::-1]
            if random.random() < 0.5:  # brightness jitter
                img = np.clip(img.astype(np.float32) * random.uniform(0.8, 1.2), 0, 255).astype(np.uint8)
        return to_tensor(img), torch.from_numpy(lbl.astype(np.int64).copy())


def build_model(source):
    return SegformerForSemanticSegmentation.from_pretrained(
        source,
        num_labels=NUM_CLASSES,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True,
    )


@torch.no_grad()
def evaluate(model, loader, device):
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


def train(args):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    if device == "cpu":
        print("WARNING: no GPU found. Use --limit 300 --crop 256 --epochs 3 for a CPU demo run.")

    train_ds = FloodSet("train", True, args.crop, args.limit)
    val_ds = FloodSet("val", False, limit=args.limit)
    train_dl = DataLoader(train_ds, batch_size=args.bs, shuffle=True,
                          num_workers=args.workers, drop_last=True)
    val_dl = DataLoader(val_ds, batch_size=4, shuffle=False, num_workers=args.workers)
    print(f"Train images: {len(train_ds)} | Val images: {len(val_ds)}")

    model = build_model(args.model).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    total_steps = args.epochs * len(train_dl)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: max(0.0, 1 - s / total_steps) ** 0.9)
    weights = torch.tensor(CLASS_WEIGHTS, device=device)
    scaler = torch.cuda.amp.GradScaler(enabled=(device == "cuda"))

    out = Path(args.save)
    out.mkdir(parents=True, exist_ok=True)
    best = -1.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        t0, running = time.time(), 0.0
        for step, (x, y) in enumerate(train_dl, 1):
            x, y = x.to(device), y.to(device)
            with torch.autocast(device_type=device, enabled=(device == "cuda")):
                logits = model(pixel_values=x).logits
                logits = F.interpolate(logits, size=y.shape[-2:], mode="bilinear", align_corners=False)
                loss = F.cross_entropy(logits.float(), y, weight=weights, ignore_index=255)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            running += loss.item()
            if step % 20 == 0:
                print(f"  epoch {epoch} step {step}/{len(train_dl)} loss {running / step:.4f}")
        iou, miou = evaluate(model, val_dl, device)
        print(f"Epoch {epoch}/{args.epochs} | {time.time() - t0:.0f}s | "
              f"val IoU bg {iou[0]:.3f} flooded {iou[1]:.3f} water {iou[2]:.3f} | mIoU {miou:.3f}")
        if miou > best:
            best = miou
            model.save_pretrained(out / "best")
            print(f"  saved new best (mIoU {best:.3f}) -> {out / 'best'}")
    print(f"Done. Best val mIoU: {best:.3f}")


@torch.no_grad()
def predict(args):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SegformerForSemanticSegmentation.from_pretrained(Path(args.save) / "best").to(device).eval()
    in_dir, out_dir = Path(args.predict), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in sorted(in_dir.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    print(f"Found {len(files)} images in {in_dir}")
    for p in files:
        img = Image.open(p).convert("RGB")
        scale = 640 / max(img.size)  # long side -> 640, like the training images
        w, h = max(32, int(img.width * scale) // 32 * 32), max(32, int(img.height * scale) // 32 * 32)
        img = img.resize((w, h), Image.Resampling.BILINEAR)
        arr = np.array(img)
        logits = model(pixel_values=to_tensor(arr).unsqueeze(0).to(device)).logits
        pred = F.interpolate(logits, size=(h, w), mode="bilinear", align_corners=False).argmax(1)[0].cpu().numpy()
        overlay = (0.55 * arr + 0.45 * COLORS[pred]).astype(np.uint8)
        overlay[pred == 0] = arr[pred == 0]
        Image.fromarray(np.concatenate([arr, overlay], axis=1)).save(out_dir / f"{p.stem}_result.png")
        flooded = 100 * (pred == 1).mean()
        water = 100 * (pred == 2).mean()
        print(f"{p.name}: flooded {flooded:.1f}% | natural water {water:.1f}%")
    print(f"Saved side-by-side results to {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--bs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=6e-5)
    ap.add_argument("--crop", type=int, default=384, help="training crop size (smaller = faster)")
    ap.add_argument("--limit", type=int, default=None, help="use only N images (smoke test)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--model", default="nvidia/segformer-b0-finetuned-ade-512-512")
    ap.add_argument("--save", default="floodnet_data/checkpoints")
    ap.add_argument("--predict", default=None, help="folder of photos to segment")
    ap.add_argument("--out", default="kerala_results")
    a = ap.parse_args()
    predict(a) if a.predict else train(a)
