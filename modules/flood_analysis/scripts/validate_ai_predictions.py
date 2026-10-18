"""Validate ai_predictions.json against the SN8 human-labelled ground truth.

Ground-truth method (documented): for each AOI tile, load its raw annotation
geojson (data/raw/annotations/{tile_id}.geojson), the same source the main
processor pipeline uses. A tile's ground-truth label is "flooded" if ANY
labelled building or road feature in that tile has flooded == 'yes'
(majority-style tile aggregation: one of the labelled flooded features present
is enough to call the tile flooded, since most tiles have very few flooded
features total). Tiles with zero building/road features are excluded.

Confidence-aware scoring: a tile whose AI prediction has confidence == 'low'
is excluded from accuracy/TP/TN/FP/FN scoring entirely (treated as an honest
"don't know", not right or wrong). Only medium/high confidence predictions
are scored. Both the original flat accuracy (all tiles, any confidence) and
the confidence-aware accuracy are computed and saved side by side.

Tile bbox (for map rendering) is the bounding box of that tile's own labelled
building/road features from data/raw/annotations/{tile}.geojson — the same
source geometry already used elsewhere in this module, not invented.

Run: python scripts/validate_ai_predictions.py
"""
import json
import os

from shapely.geometry import shape
from shapely.ops import unary_union

BASE = os.path.join(os.path.dirname(__file__), "..")
ANNOTATIONS_DIR = os.path.join(BASE, "data", "raw", "annotations")
PREDICTIONS_PATH = os.path.join(BASE, "output", "ai_predictions.json")
OUT_PATH = os.path.join(BASE, "output", "ai_validation_summary.json")

AOI_TILE_IDS = [f"0_{row}_{col}" for row in range(36, 42) for col in range(59, 63)]


def tile_features(tile_id):
    fp = os.path.join(ANNOTATIONS_DIR, f"{tile_id}.geojson")
    if not os.path.exists(fp):
        return None
    d = json.load(open(fp))
    return [
        f for f in d["features"]
        if f["properties"].get("building") is not None or f["properties"].get("highway") is not None
    ]


def tile_ground_truth(features):
    if not features:
        return None
    return any(f["properties"].get("flooded") == "yes" for f in features)


def tile_bbox(features):
    if not features:
        return None
    geoms = [shape(f["geometry"]) for f in features]
    minx, miny, maxx, maxy = unary_union(geoms).bounds
    return [minx, miny, maxx, maxy]


def main():
    if not os.path.exists(PREDICTIONS_PATH):
        raise SystemExit(f"No predictions found at {PREDICTIONS_PATH}. Run ai_flood_detect.py first.")

    predictions = json.load(open(PREDICTIONS_PATH))

    # Flat (original) scoring: every tile with a real prediction + ground truth, any confidence.
    flat_tp = flat_tn = flat_fp = flat_fn = 0
    # Confidence-aware scoring: medium/high confidence only.
    conf_tp = conf_tn = conf_fp = conf_fn = 0

    skipped_no_truth = []
    skipped_no_prediction = []
    skipped_error = []
    uncertain_tile_ids = []
    per_tile = {}

    for tile_id in AOI_TILE_IDS:
        features = tile_features(tile_id)
        truth = tile_ground_truth(features)
        bbox = tile_bbox(features)

        if truth is None:
            skipped_no_truth.append(tile_id)
            continue

        pred_entry = predictions.get(tile_id)
        if pred_entry is None:
            skipped_no_prediction.append(tile_id)
            continue
        if "ERROR" in pred_entry:
            skipped_error.append(tile_id)
            continue

        pred = pred_entry["flood_damage_detected"]
        confidence = pred_entry.get("confidence")
        is_uncertain = confidence == "low"
        category = "UNCERTAIN" if is_uncertain else "CONFIDENT"

        per_tile[tile_id] = {
            "ground_truth_flooded": truth,
            "ai_predicted_flooded": pred,
            "confidence": confidence,
            "reasoning": pred_entry.get("reasoning"),
            "category": category,
            "bbox": bbox,
        }

        if truth and pred:
            flat_tp += 1
        elif (not truth) and (not pred):
            flat_tn += 1
        elif (not truth) and pred:
            flat_fp += 1
        elif truth and (not pred):
            flat_fn += 1

        if is_uncertain:
            uncertain_tile_ids.append(tile_id)
            continue

        if truth and pred:
            conf_tp += 1
        elif (not truth) and (not pred):
            conf_tn += 1
        elif (not truth) and pred:
            conf_fp += 1
        elif truth and (not pred):
            conf_fn += 1

    n_flat = flat_tp + flat_tn + flat_fp + flat_fn
    flat_accuracy = (flat_tp + flat_tn) / n_flat if n_flat else None

    n_conf = conf_tp + conf_tn + conf_fp + conf_fn
    confident_accuracy = (conf_tp + conf_tn) / n_conf if n_conf else None

    summary = {
        "method": (
            "Ground truth per tile = any labelled building/road feature in that tile has "
            "flooded == 'yes' (from data/raw/annotations/{tile}.geojson, same source as the "
            "main processor pipeline). Tiles with no building/road features are excluded. "
            "Confidence-aware scoring: tiles where the AI reported confidence == 'low' are "
            "excluded from accuracy/TP/TN/FP/FN as an honest 'uncertain', scored separately."
        ),
        "tiles_total_in_aoi": len(AOI_TILE_IDS),
        "tiles_compared": n_flat,
        "tiles_skipped_no_ground_truth_features": skipped_no_truth,
        "tiles_skipped_no_prediction": skipped_no_prediction,
        "tiles_skipped_prediction_error": skipped_error,

        "accuracy": flat_accuracy,
        "confusion": {
            "true_positive_flooded_correctly_caught": flat_tp,
            "true_negative_dry_correctly_identified": flat_tn,
            "false_positive_false_alarm": flat_fp,
            "false_negative_flooded_missed": flat_fn,
        },

        "flat_accuracy": flat_accuracy,
        "flat_confusion": {
            "true_positive_flooded_correctly_caught": flat_tp,
            "true_negative_dry_correctly_identified": flat_tn,
            "false_positive_false_alarm": flat_fp,
            "false_negative_flooded_missed": flat_fn,
        },

        "confident_tiles_scored": n_conf,
        "confident_accuracy": confident_accuracy,
        "confident_confusion": {
            "true_positive_flooded_correctly_caught": conf_tp,
            "true_negative_dry_correctly_identified": conf_tn,
            "false_positive_false_alarm": conf_fp,
            "false_negative_flooded_missed": conf_fn,
        },
        "uncertain_tile_count": len(uncertain_tile_ids),
        "uncertain_tile_ids": uncertain_tile_ids,

        "per_tile": per_tile,
    }

    with open(OUT_PATH, "w") as fh:
        json.dump(summary, fh, indent=2)

    print(f"Tiles compared (flat, all confidence): {n_flat}")
    print(f"Flat accuracy: {flat_accuracy}")
    print(f"Flat TP={flat_tp} TN={flat_tn} FP={flat_fp} FN={flat_fn}")
    print()
    print(f"Confident tiles scored (medium/high only): {n_conf}")
    print(f"Confident accuracy: {confident_accuracy}")
    print(f"Confident TP={conf_tp} TN={conf_tn} FP={conf_fp} FN={conf_fn}")
    print(f"Uncertain (low confidence, excluded) tiles: {len(uncertain_tile_ids)} -> {uncertain_tile_ids}")
    print()
    print(f"Skipped (no ground-truth features): {skipped_no_truth}")
    print(f"Skipped (no prediction yet): {skipped_no_prediction}")
    print(f"Skipped (prediction error): {skipped_error}")
    print(f"Written to {OUT_PATH}")


if __name__ == "__main__":
    main()
