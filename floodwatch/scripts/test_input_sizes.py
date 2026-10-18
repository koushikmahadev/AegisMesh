"""
Test different INPUT_SIZE values (384, 512, 768, native) on the top 5 highest-net tiles.
"""
import time
import torch
import torch.nn.functional as F
import numpy as np
from src.flood_inference import find_tile_paths, load_rgb, get_model, MEAN, STD, DEVICE, USE_FP16, WATER_CLASS, water_pct

TOP5_TILES = ["0_41_58", "0_41_59", "0_27_68", "0_30_63", "0_37_61"]
SIZES = [384, 512, 768, "native"]

def segment_at_size(images, size, model):
    sizes = [img.shape[-2:] for img in images]
    if size == "native":
        target_size = sizes[0]
        batch = torch.stack([
            F.interpolate(img.unsqueeze(0), size=target_size, mode="bilinear", align_corners=False)[0]
            if img.shape[-2:] != target_size else img
            for img in images
        ])
    else:
        batch = torch.stack([
            F.interpolate(img.unsqueeze(0), size=(size, size), mode="bilinear", align_corners=False)[0]
            for img in images
        ])
    
    batch = (batch - MEAN) / STD
    batch = batch.to(DEVICE, dtype=torch.float16 if USE_FP16 else torch.float32)

    logits = model(pixel_values=batch).logits

    masks = []
    for i, orig_size in enumerate(sizes):
        up = F.interpolate(logits[i:i + 1].float(), size=orig_size, mode="bilinear", align_corners=False)
        masks.append((up.argmax(dim=1)[0] == WATER_CLASS).cpu())
    return masks

def run_experiment():
    model = get_model()
    print("Testing INPUT_SIZE = 384, 512, 768, native on Top 5 Tiles\n")
    
    results = {}
    for tile_id in TOP5_TILES:
        pre_p, post_p = find_tile_paths(tile_id)
        pre, post = load_rgb(pre_p), load_rgb(post_p)
        print(f"================ TILE {tile_id} (orig size: pre={pre.shape[-2:]}, post={post.shape[-2:]}) ================")
        results[tile_id] = {}

        for sz in SIZES:
            t0 = time.perf_counter()
            try:
                with torch.no_grad():
                    pre_m, post_m = segment_at_size([pre, post], sz, model)
                b_pct = water_pct(pre_m)
                a_pct = water_pct(post_m)
                net = round(a_pct - b_pct, 2)
                dt = int((time.perf_counter() - t0) * 1000)
                results[tile_id][sz] = {"before": b_pct, "after": a_pct, "net": net, "ms": dt}
                print(f"  size={str(sz):<7} | before={b_pct:5.2f}% | after={a_pct:5.2f}% | net={net:+5.2f}% | lat={dt:3d}ms")
            except Exception as e:
                print(f"  size={str(sz):<7} | FAILED: {e}")
                results[tile_id][sz] = {"error": str(e)}

    # Compute mask IoU overlap compared to default (512)
    print("\n=== MASK IoU OVERLAP COMPARED TO DEFAULT (512) ===")
    for tile_id in TOP5_TILES:
        pre_p, post_p = find_tile_paths(tile_id)
        pre, post = load_rgb(pre_p), load_rgb(post_p)
        with torch.no_grad():
            _, base_post = segment_at_size([pre, post], 512, model)
        base_bool = base_post.bool()
        
        print(f"Tile {tile_id}:")
        for sz in [384, 768]:
            with torch.no_grad():
                _, test_post = segment_at_size([pre, post], sz, model)
            test_bool = test_post.bool()
            inter = (base_bool & test_bool).sum().item()
            union = (base_bool | test_bool).sum().item()
            iou = (inter / union * 100) if union > 0 else 100.0
            print(f"  Overlap (512 vs {sz}): IoU = {iou:.1f}% (inter={inter}, union={union})")

if __name__ == "__main__":
    run_experiment()
