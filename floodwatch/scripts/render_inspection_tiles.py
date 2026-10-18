import os
import sys
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.flood_inference import find_tile_paths, analyze_tile, load_rgb

def render_tile_inspection(tile_id):
    out_dir = os.path.join(REPO_ROOT, "docs", "inspection")
    os.makedirs(out_dir, exist_ok=True)
    
    pre_p, post_p = find_tile_paths(tile_id)
    pre_t = load_rgb(pre_p)
    post_t = load_rgb(post_p)
    if pre_t.shape != post_t.shape:
        post_t = F.interpolate(post_t.unsqueeze(0), size=pre_t.shape[-2:], mode="bilinear", align_corners=False)[0]
    
    pre_np = (pre_t.permute(1, 2, 0).numpy() * 255.0).clip(0, 255).astype(np.uint8)
    post_np = (post_t.permute(1, 2, 0).numpy() * 255.0).clip(0, 255).astype(np.uint8)
    
    # Run fast and accurate
    res_fast, pre_m_fast, post_m_fast = analyze_tile(tile_id, return_masks=True, mode="fast")
    res_acc, pre_m_acc, post_m_acc = analyze_tile(tile_id, return_masks=True, mode="accurate")
    
    pre_mf = pre_m_fast.cpu().numpy().astype(bool)
    post_mf = post_m_fast.cpu().numpy().astype(bool)
    pre_ma = pre_m_acc.cpu().numpy().astype(bool)
    post_ma = post_m_acc.cpu().numpy().astype(bool)
    
    def overlay(base_np, mask_bool, color=[0, 240, 255], alpha=0.45):
        img = base_np.astype(float).copy()
        if mask_bool.any():
            for c in range(3):
                img[mask_bool, c] = (1 - alpha) * img[mask_bool, c] + alpha * color[c]
        return Image.fromarray(img.clip(0, 255).astype(np.uint8))
    
    Image.fromarray(pre_np).save(os.path.join(out_dir, f"{tile_id}_pre.jpg"), quality=85)
    Image.fromarray(post_np).save(os.path.join(out_dir, f"{tile_id}_post.jpg"), quality=85)
    
    overlay(pre_np, pre_mf).save(os.path.join(out_dir, f"{tile_id}_pre_fast_mask.jpg"), quality=85)
    overlay(post_np, post_mf).save(os.path.join(out_dir, f"{tile_id}_post_fast_mask.jpg"), quality=85)
    overlay(pre_np, pre_ma).save(os.path.join(out_dir, f"{tile_id}_pre_acc_mask.jpg"), quality=85)
    overlay(post_np, post_ma).save(os.path.join(out_dir, f"{tile_id}_post_acc_mask.jpg"), quality=85)
    
    print(f"Rendered inspection images for {tile_id}:")
    print(f"  Fast:     before={res_fast.before_water_pct}%, after={res_fast.after_water_pct}%, net={res_fast.net_intrusion_pct}%")
    print(f"  Accurate: before={res_acc.before_water_pct}%, after={res_acc.after_water_pct}%, net={res_acc.net_intrusion_pct}%")

if __name__ == "__main__":
    for tid in ["0_38_69", "0_31_69"]:
        render_tile_inspection(tid)
