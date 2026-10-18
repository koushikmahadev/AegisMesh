"""AI flood-damage PREDICTION from PRE/POST SpaceNet 8 imagery via OpenRouter vision API.

This produces a model PREDICTION, compared later against the project's human-labelled
ground truth. It is never a substitute for that ground truth.
Run: python scripts/ai_flood_detect.py
"""
import glob
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from vision_api_config import OPENROUTER_API_KEY
from image_compress import tif_to_data_url

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "output", "ai_predictions.json")
MODEL = "dots-studio/dots-3-note-preview:free"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_DELAY_SECONDS = 4

AOI_TILE_IDS = [f"0_{row}_{col}" for row in range(36, 42) for col in range(59, 63)]

PROMPT = """You are comparing a PRE-event and POST-event satellite image of the same location \
after a flood event. The first image is PRE-event, the second is POST-event.

Determine whether there is visible flood damage or water intrusion in the POST-event image \
that was NOT present in the PRE-event image.

Respond with ONLY a strict JSON object, no other text, in exactly this format:
{"flood_damage_detected": true or false, "confidence": "low" or "medium" or "high", "reasoning": "one short sentence"}
"""


def find_tile_images(tile_id):
    pre = glob.glob(os.path.join(RAW_DIR, "PRE-event", f"*_{tile_id}.tif"))
    post = glob.glob(os.path.join(RAW_DIR, "POST-event", f"*_{tile_id}.tif"))
    if not pre or not post:
        return None, None
    return pre[0], post[0]


def load_results():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as fh:
            return json.load(fh)
    return {}


def save_results(results):
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(results, fh, indent=2)
    os.replace(tmp, OUT_PATH)


def call_openrouter(pre_url, post_url):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": pre_url}},
                    {"type": "image_url", "image_url": {"url": post_url}},
                ],
            }
        ],
        "max_tokens": 3000,
    }
    return requests.post(API_URL, headers=headers, json=body, timeout=90)


def parse_response(resp):
    content = resp.json()["choices"][0]["message"]["content"]
    if content is None:
        raise ValueError("empty content (model returned no content, likely truncated on reasoning)")
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object found in content: {content[:200]!r}")
    parsed = json.loads(content[start:end + 1])
    flood = parsed["flood_damage_detected"]
    if not isinstance(flood, bool):
        raise ValueError(f"flood_damage_detected not boolean: {flood!r}")
    return {
        "flood_damage_detected": flood,
        "confidence": parsed.get("confidence"),
        "reasoning": parsed.get("reasoning"),
    }


def is_rate_limited(resp):
    if resp.status_code == 429:
        return True
    if resp.status_code == 200:
        try:
            return resp.json().get("error", {}).get("code") == 429
        except (ValueError, KeyError):
            return False
    return False


def process_tile(tile_id):
    pre_path, post_path = find_tile_images(tile_id)
    if pre_path is None:
        return {"ERROR": "missing_imagery"}

    pre_url = tif_to_data_url(pre_path)
    post_url = tif_to_data_url(post_path)

    for attempt in range(2):
        try:
            resp = call_openrouter(pre_url, post_url)
        except requests.RequestException as e:
            print(f"  [{tile_id}] network error: {e}")
            return {"ERROR": f"network_error: {e}"}

        if is_rate_limited(resp):
            if attempt == 0:
                print(f"  [{tile_id}] rate limited, waiting 15s and retrying once...")
                time.sleep(15)
                continue
            print(f"  [{tile_id}] still rate limited after retry")
            return {"ERROR": "rate_limited_after_retry"}

        if resp.status_code != 200:
            print(f"  [{tile_id}] HTTP {resp.status_code}: {resp.text[:300]}")
            return {"ERROR": f"http_{resp.status_code}: {resp.text[:200]}"}

        try:
            result = parse_response(resp)
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            print(f"  [{tile_id}] parse error: {e}")
            return {"ERROR": f"parse_error: {e}"}

        result["model"] = MODEL
        return result

    return {"ERROR": "unexpected_retry_exhaustion"}


def main():
    results = load_results()
    processed = 0
    errored = 0

    for tile_id in AOI_TILE_IDS:
        if tile_id in results and "ERROR" not in results.get(tile_id, {}):
            print(f"[{tile_id}] already done, skipping")
            continue

        print(f"[{tile_id}] processing...")
        result = process_tile(tile_id)
        results[tile_id] = result
        save_results(results)

        if "ERROR" in result:
            errored += 1
            print(f"  [{tile_id}] -> ERROR: {result['ERROR']}")
        else:
            processed += 1
            print(f"  [{tile_id}] -> flood_damage_detected={result['flood_damage_detected']} "
                  f"confidence={result['confidence']}")

        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nDone. succeeded={processed} errored={errored}")


if __name__ == "__main__":
    main()
