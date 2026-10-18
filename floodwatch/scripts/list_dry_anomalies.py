import json

with open("data/accurate_dry_benchmark.json", "r", encoding="utf-8") as f:
    d = json.load(f)

print("=== 8 Dry Tiles with Accurate after > 0.1% ===")
after_gt = sorted([t for t in d["tiles"] if t["accurate_after"] > 0.1], key=lambda x: x["accurate_after"], reverse=True)
for t in after_gt:
    print(f"{t['tile_id']}: Accurate after={t['accurate_after']}%, before={t['accurate_before']}%, net={t['accurate_net']}% | Fast after={t['fast_after']}%, before={t['fast_before']}%, net={t['fast_net']}%")

print("\n=== 5 Dry Tiles with Accurate before > 0.1% ===")
before_gt = sorted([t for t in d["tiles"] if t["accurate_before"] > 0.1], key=lambda x: x["accurate_before"], reverse=True)
for t in before_gt:
    print(f"{t['tile_id']}: Accurate before={t['accurate_before']}%, after={t['accurate_after']}%, net={t['accurate_net']}% | Fast before={t['fast_before']}%, after={t['fast_after']}%, net={t['fast_net']}%")
