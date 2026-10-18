"""Combined pipeline for a user-drawn custom AOI (map.html "Select Custom Area" mode).

Chains: ground-truth pipeline on the EXACT tiles given (not auto-selected) -> optional
4-way-parallel AI detection on those same tiles -> validation -> datasets.json manifest
update. Static-file-safe: map.html never calls this; a human runs it from the terminal
and the map discovers progress purely by polling plain JSON files (datasets.json,
ai_predictions.json) on an interval.

Run: python scripts/run_custom_aoi.py --source germany --tiles 0_41_58,0_41_59 --dataset-key my_area
Skip AI: add --skip-ai
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vision_api_config import OPENROUTER_API_KEY, OPENROUTER_API_KEY_FLOODNET, OPENROUTER_API_KEY_3, OPENROUTER_API_KEY_4
from image_compress import tif_to_data_url
from ai_flood_detect import find_tile_images, call_openrouter, parse_response, is_rate_limited, MODEL
from flood_analysis import cli as flood_cli

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
MANIFEST_PATH = os.path.join(BASE_DIR, "datasets.json")
RAW_DIRS = {"germany": os.path.join(BASE_DIR, "data", "raw"), "louisiana": os.path.join(BASE_DIR, "data", "raw_louisiana")}
KEY_POOL = [OPENROUTER_API_KEY, OPENROUTER_API_KEY_FLOODNET, OPENROUTER_API_KEY_3, OPENROUTER_API_KEY_4]


def update_manifest(key, label, base, raw_source, status, tile_ids=None):
    manifest = json.load(open(MANIFEST_PATH)) if os.path.exists(MANIFEST_PATH) else {"datasets": []}
    entries = manifest["datasets"]
    existing = next((e for e in entries if e["key"] == key), None)
    entry = {"key": key, "label": label, "base": base, "raw_source": raw_source, "status": status}
    if tile_ids is not None:
        entry["tile_ids"] = tile_ids
    elif existing and "tile_ids" in existing:
        entry["tile_ids"] = existing["tile_ids"]
    if existing:
        existing.update(entry)
    else:
        entries.append(entry)
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(manifest, fh, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def _one_tile(raw_dir, tile_id, start_key_idx):
    pre_path, post_path = find_tile_images(raw_dir, tile_id)
    if pre_path is None:
        return tile_id, {"ERROR": "missing_imagery"}
    pre_url = tif_to_data_url(pre_path)
    post_url = tif_to_data_url(post_path)

    # On a rate limit, actually try a DIFFERENT key from the pool (not the same one
    # again) before declaring all_keys_exhausted — tries every key in the pool once.
    for n in range(len(KEY_POOL)):
        key_idx = (start_key_idx + n) % len(KEY_POOL)
        try:
            resp = call_openrouter(KEY_POOL[key_idx], pre_url, post_url)
        except Exception as e:
            return tile_id, {"ERROR": f"network_error: {e}"}
        if is_rate_limited(resp):
            print(f"  [{tile_id}] key #{key_idx} rate limited, trying next key in pool...")
            continue
        if resp.status_code != 200:
            return tile_id, {"ERROR": f"http_{resp.status_code}: {resp.text[:200]}"}
        try:
            result = parse_response(resp)
        except Exception as e:
            return tile_id, {"ERROR": f"parse_error: {e}"}
        result["model"] = MODEL
        return tile_id, result
    return tile_id, {"ERROR": "all_keys_exhausted"}


def run_ai_detection_parallel(raw_dir, tile_ids, out_path):
    """Real concurrency: ThreadPoolExecutor(max_workers=4), one of the 4 pooled
    OpenRouter keys assigned per tile round-robin, all workers fire their HTTP
    requests independently/simultaneously (not sequential with a label)."""
    results = {}
    if os.path.exists(out_path):
        results = json.load(open(out_path))
    save_lock = threading.Lock()

    def save():
        tmp = out_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(results, fh, indent=2)
        os.replace(tmp, out_path)

    pending = [t for t in tile_ids if t not in results or "ERROR" in results.get(t, {})]
    print(f"AI detection: {len(pending)} tiles to process, {len(tile_ids) - len(pending)} already done, "
          f"4-way parallel pool (keys #0-#3)")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_one_tile, raw_dir, tile_id, i % 4): tile_id
            for i, tile_id in enumerate(pending)
        }
        for fut in concurrent.futures.as_completed(futures):
            tile_id, result = fut.result()
            with save_lock:
                results[tile_id] = result
                save()
            status = result.get("flood_damage_detected", result.get("ERROR"))
            print(f"  [{tile_id}] -> {status}")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=sorted(RAW_DIRS), required=True)
    parser.add_argument("--tiles", required=True, help="Comma-separated tile ids, e.g. 0_41_58,0_41_59")
    parser.add_argument("--dataset-key", required=True, help="Short id for this run, e.g. custom_1699999999")
    parser.add_argument("--label", default=None)
    parser.add_argument("--skip-ai", action="store_true")
    args = parser.parse_args()

    raw_dir = RAW_DIRS[args.source]
    tile_ids = [t for t in args.tiles.split(",") if t]
    out_dir = os.path.join(BASE_DIR, f"output_{args.dataset_key}")
    base = f"../output_{args.dataset_key}/"
    label = args.label or f"Custom area ({args.dataset_key})"

    print(f"=== Step 1/3: ground truth pipeline, {len(tile_ids)} user-selected tiles -> {out_dir} ===")
    metadata, zones = flood_cli.run(raw_dir, out_dir, tile_ids=tile_ids, dataset_name=label)
    print(f"Wrote {len(zones)} zones, {metadata['counts']}")
    update_manifest(args.dataset_key, label, base, args.source, "ground_truth_ready", tile_ids=tile_ids)

    if args.skip_ai:
        update_manifest(args.dataset_key, label, base, args.source, "ready", tile_ids=tile_ids)
        print("=== Done (AI detection skipped via --skip-ai) ===")
        return

    print(f"=== Step 2/3: AI detection, 4-way parallel ===")
    update_manifest(args.dataset_key, label, base, args.source, "ai_running", tile_ids=tile_ids)
    ai_out_path = os.path.join(out_dir, "ai_predictions.json")
    run_ai_detection_parallel(raw_dir, tile_ids, ai_out_path)

    print("=== Step 3/3: validation ===")
    subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "validate_ai_predictions.py"),
         "--input", raw_dir, "--out-dir", out_dir, "--tiles", ",".join(tile_ids)],
        check=True,
    )

    update_manifest(args.dataset_key, label, base, args.source, "ready", tile_ids=tile_ids)
    print(f"=== Done. Dataset '{args.dataset_key}' appended to datasets.json ===")


if __name__ == "__main__":
    main()
