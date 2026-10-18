"""AI flood-damage PREDICTION on single FloodNet drone photos via OpenRouter vision API.

Unlike the SpaceNet 8 Germany pipeline (PRE/POST pair), FloodNet has a single
post-disaster photo per case — the model judges flood damage from one image.
This produces a model PREDICTION, compared later against the real pixel-mask
ground truth. It is never a substitute for that ground truth.
Run: python scripts/ai_flood_detect_floodnet.py
"""
import glob
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from vision_api_config import OPENROUTER_API_KEY_FLOODNET
from image_compress import tif_to_data_url
from ai_flood_detect import MODEL  # reuse the same model id used for Germany

BASE = os.path.join(os.path.dirname(__file__), "..")
IMG_DIR = os.path.join(BASE, "data", "raw_floodnet", "test-org-img")
OUT_PATH = os.path.join(BASE, "output_floodnet", "ai_predictions.json")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_DELAY_SECONDS = 4

PROMPT = """You are looking at a single aerial drone photo taken after a flood disaster \
(Hurricane Harvey). Determine whether there is visible flood damage in this image: \
standing water, flood debris, or submerged/water-damaged structures or roads.

Respond with ONLY a strict JSON object, no other text, in exactly this format:
{"flood_damage_detected": true or false, "confidence": "low" or "medium" or "high", "reasoning": "one short sentence"}
"""


def find_image_ids():
    files = sorted(glob.glob(os.path.join(IMG_DIR, "*.jpg")))
    return [os.path.basename(f).replace(".jpg", "") for f in files]


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


def call_openrouter(image_url):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY_FLOODNET}", "Content-Type": "application/json"}
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": image_url}},
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


def process_image(image_id):
    img_path = os.path.join(IMG_DIR, f"{image_id}.jpg")
    if not os.path.exists(img_path):
        return {"ERROR": "missing_imagery"}

    image_url = tif_to_data_url(img_path)

    for attempt in range(2):
        try:
            resp = call_openrouter(image_url)
        except requests.RequestException as e:
            print(f"  [{image_id}] network error: {e}")
            return {"ERROR": f"network_error: {e}"}

        if is_rate_limited(resp):
            if attempt == 0:
                print(f"  [{image_id}] rate limited, waiting 15s and retrying once...")
                time.sleep(15)
                continue
            print(f"  [{image_id}] still rate limited after retry")
            return {"ERROR": "rate_limited_after_retry"}

        if resp.status_code != 200:
            print(f"  [{image_id}] HTTP {resp.status_code}: {resp.text[:300]}")
            return {"ERROR": f"http_{resp.status_code}: {resp.text[:200]}"}

        try:
            result = parse_response(resp)
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            print(f"  [{image_id}] parse error: {e}")
            return {"ERROR": f"parse_error: {e}"}

        result["model"] = MODEL
        return result

    return {"ERROR": "unexpected_retry_exhaustion"}


def main():
    results = load_results()
    processed = 0
    errored = 0

    for image_id in find_image_ids():
        if image_id in results and "ERROR" not in results.get(image_id, {}):
            print(f"[{image_id}] already done, skipping")
            continue

        print(f"[{image_id}] processing...")
        result = process_image(image_id)
        results[image_id] = result
        save_results(results)

        if "ERROR" in result:
            errored += 1
            print(f"  [{image_id}] -> ERROR: {result['ERROR']}")
        else:
            processed += 1
            print(f"  [{image_id}] -> flood_damage_detected={result['flood_damage_detected']} "
                  f"confidence={result['confidence']}")

        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nDone. succeeded={processed} errored={errored}")


if __name__ == "__main__":
    main()
