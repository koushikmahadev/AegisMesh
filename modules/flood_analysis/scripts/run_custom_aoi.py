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

import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from vision_api_config import OPENROUTER_API_KEY, OPENROUTER_API_KEY_FLOODNET, OPENROUTER_API_KEY_3, OPENROUTER_API_KEY_4
except ImportError:
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_API_KEY_FLOODNET = os.environ.get("OPENROUTER_API_KEY_FLOODNET", "")
    OPENROUTER_API_KEY_3 = os.environ.get("OPENROUTER_API_KEY_3", "")
    OPENROUTER_API_KEY_4 = os.environ.get("OPENROUTER_API_KEY_4", "")
from image_compress import tif_to_data_url
from ai_flood_detect import find_tile_images, call_openrouter, parse_response, is_rate_limited, MODEL
from flood_analysis import cli as flood_cli

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
MANIFEST_PATH = os.path.join(BASE_DIR, "datasets.json")
RAW_DIRS = {"germany": os.path.join(BASE_DIR, "data", "raw"), "louisiana": os.path.join(BASE_DIR, "data", "raw_louisiana")}
KEY_POOL = [OPENROUTER_API_KEY, OPENROUTER_API_KEY_FLOODNET, OPENROUTER_API_KEY_3, OPENROUTER_API_KEY_4]


def update_manifest(key, label, base, raw_source, status, tile_ids=None):
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"datasets": []}
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


def _one_tile(raw_dir, tile_id, api_key):
    pre_path, post_path = find_tile_images(raw_dir, tile_id)
    if pre_path is None:
        return tile_id, {"ERROR": "missing_imagery"}

    pre_url = tif_to_data_url(pre_path)
    post_url = tif_to_data_url(post_path)

    # Try OpenRouter API with assigned key
    try:
        resp = call_openrouter(api_key, pre_url, post_url)
        if is_rate_limited(resp):
            print(f"  [{tile_id}] key rate limited, falling back to next key in pool...")
            for fallback_key in KEY_POOL:
                if fallback_key == api_key:
                    continue
                resp = call_openrouter(fallback_key, pre_url, post_url)
                if not is_rate_limited(resp):
                    break
        if not is_rate_limited(resp) and resp.status_code == 200:
            result = parse_response(resp)
            result["model"] = MODEL
            return tile_id, result
        elif resp.status_code != 200:
            print(f"  [{tile_id}] OpenRouter HTTP {resp.status_code}, falling back to local model...")
    except Exception as e:
        print(f"  [{tile_id}] OpenRouter error: {e}, falling back to local model...")

    # Fallback to local offline model if OpenRouter call fails or all keys are exhausted
    try:
        from ai_flood_detect_local import judge
        model_dir = os.path.join(BASE_DIR, "HighWater_Module2_Offline", "models", "segformer")
        result = judge(
            pre=pre_path,
            post=post_path,
            threshold=0.001,
            model_dir=model_dir,
            flood_classes=[1],
            device="cpu",
            mode="accurate",
            include_dev_fields=False
        )
        return tile_id, result
    except Exception as e:
        return tile_id, {"ERROR": f"detection_error: {str(e)[:200]}"}


def run_ai_detection_parallel(raw_dir, tile_ids, out_path):
    """Sequential execution with round-robin OpenRouter key rotation and 3-second spacing."""
    results = {}
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            results = json.load(f)
    save_lock = threading.Lock()

    def save():
        tmp = out_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(results, fh, indent=2)
        os.replace(tmp, out_path)

    pending = [t for t in tile_ids if t not in results or "ERROR" in results.get(t, {})]
    print(f"AI detection: {len(pending)} tiles to process, {len(tile_ids) - len(pending)} already done, "
          f"round-robin sequential rotation (keys #0-#3)")

    key_pool = [OPENROUTER_API_KEY, OPENROUTER_API_KEY_FLOODNET, OPENROUTER_API_KEY_3, OPENROUTER_API_KEY_4]

    for idx, tile_id in enumerate(pending):
        key_index = idx % len(key_pool)
        current_key = key_pool[key_index]
        print(f"  [{tile_id}] processing with key #{key_index} ({current_key[:12]}...)...")
        tile_id, result = _one_tile(raw_dir, tile_id, current_key)
        with save_lock:
            results[tile_id] = result
            save()
        status = result.get("flood_damage_detected", result.get("ERROR"))
        print(f"  [{tile_id}] -> {status}")
        if idx < len(pending) - 1:
            time.sleep(3)  # 3-second delay between requests to avoid rate limiting
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

    print(f"=== Step 2/3: AI detection, sequential round-robin ===")
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
