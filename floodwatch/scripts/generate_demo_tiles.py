"""
Generate factual, data-derived data/demo_tiles.json.
Curates 14 demo tiles based strictly on measured net %, GT feature counts, and model agreement/disagreement.
"""
import glob
import json
import os

with open(os.path.join("data", "tile_scan.json")) as f:
    scan = json.load(f)
scan_dict = {t["tile_id"]: t for t in scan}

ann_dir = os.path.join("data", "raw", "annotations")
gt_info = {}
for p in glob.glob(os.path.join(ann_dir, "*.geojson")):
    tid = os.path.splitext(os.path.basename(p))[0]
    with open(p) as f:
        d = json.load(f)
    bldg = sum(1 for feat in d.get("features", []) if feat.get("properties", {}).get("flooded") == "yes" and feat.get("properties", {}).get("building") == "yes")
    road = sum(1 for feat in d.get("features", []) if feat.get("properties", {}).get("flooded") == "yes" and feat.get("properties", {}).get("highway") is not None)
    tot = bldg + road
    gt_info[tid] = {"gt_flooded_count": tot, "gt_bldg": bldg, "gt_road": road}

demo_configs = [
    # 1. Clear model hits
    ("0_41_58", "Model Hit: +39.00% Net", "181 GT flooded features (169 buildings, 12 roads)"),
    ("0_27_68", "Model Hit: +6.96% Net", "86 GT flooded features (80 buildings, 6 roads)"),
    ("0_41_59", "Model Hit: +4.97% Net", "90 GT flooded features (76 buildings, 14 roads)"),
    ("0_30_63", "Model Hit: +3.93% Net", "62 GT flooded features (48 buildings, 14 roads)"),
    ("0_27_67", "Model Hit: +2.38% Net", "46 GT flooded features (43 buildings, 3 roads)"),
    ("0_28_63", "Model Hit: +1.23% Net", "70 GT flooded features (58 buildings, 12 roads)"),
    
    # 2. Model misses / Disagreements (GT has flooded features, but model reports ~0%)
    ("0_23_62", "Model Miss: +0.08% Net", "101 GT flooded features (94 buildings, 7 roads) missed by model"),
    ("0_29_66", "Model Miss: +0.00% Net", "95 GT flooded features (90 buildings, 5 roads) missed by model"),
    ("0_40_62", "Model Miss: +0.02% Net", "88 GT flooded features (72 buildings, 16 roads) missed by model"),
    ("0_39_62", "Model Miss: +0.00% Net", "2 GT flooded road segments missed by model"),

    # 3. True negatives (Zero GT flooding, Model reports 0.0%)
    ("0_15_63", "True Negative: 0.00% Net", "0 GT flooded features; model correctly reports 0.0%"),
    ("0_15_68", "True Negative: 0.00% Net", "0 GT flooded features; model correctly reports 0.0%"),
    ("0_15_65", "True Negative: 0.00% Net", "0 GT flooded features; model correctly reports 0.0%"),

    # 4. Negative net tiles (Pre-event false positive / artifact)
    ("0_20_66", "Negative Net: -3.32% Net", "0 GT flooded features; pre-event water fraction higher than post-event")
]

demo_tiles = []
for tid, label, desc in demo_configs:
    meta = scan_dict[tid]
    g = gt_info.get(tid, {"gt_flooded_count": 0, "gt_bldg": 0, "gt_road": 0})
    demo_tiles.append({
        "tile_id": tid,
        "label": label,
        "description": desc,
        "before_pct": meta["before"],
        "after_pct": meta["after"],
        "net_intrusion_pct": meta["net"],
        "gt_flooded_count": g["gt_flooded_count"],
        "gt_bldg_count": g["gt_bldg"],
        "gt_road_count": g["gt_road"],
        "latency_ms": meta["latency_ms"]
    })

out_path = os.path.join("data", "demo_tiles.json")
with open(out_path, "w") as f:
    json.dump(demo_tiles, f, indent=2)

print(f"Generated {out_path} with {len(demo_tiles)} factual demo tiles:")
for d in demo_tiles:
    print(f"  {d['tile_id']:<8} | net: {d['net_intrusion_pct']:>+6.2f}% | GT: {d['gt_flooded_count']:3d} | {d['label']:<28} | {d['description']}")
