"""Validate FloodNet ai_predictions.json against the real pixel-mask ground truth.

Confidence-aware scoring (same method as the Germany/SpaceNet 8 validation):
a prediction with confidence == 'low' is excluded from accuracy/TP/TN/FP/FN
scoring entirely (treated as an honest "don't know"). Only medium/high
confidence predictions are scored. Both the flat accuracy (all confidences)
and the confidence-aware accuracy are computed and saved side by side.

Run: python scripts/validate_floodnet_predictions.py
"""
import json
import os

BASE = os.path.join(os.path.dirname(__file__), "..")
GROUND_TRUTH_PATH = os.path.join(BASE, "output_floodnet", "ground_truth.json")
PREDICTIONS_PATH = os.path.join(BASE, "output_floodnet", "ai_predictions.json")
OUT_PATH = os.path.join(BASE, "output_floodnet", "validation_summary.json")


def main():
    if not os.path.exists(PREDICTIONS_PATH):
        raise SystemExit(f"No predictions found at {PREDICTIONS_PATH}. Run ai_flood_detect_floodnet.py first.")

    ground_truth = json.load(open(GROUND_TRUTH_PATH))["images"]
    predictions = json.load(open(PREDICTIONS_PATH))

    flat_tp = flat_tn = flat_fp = flat_fn = 0
    conf_tp = conf_tn = conf_fp = conf_fn = 0
    skipped_no_prediction = []
    skipped_error = []
    uncertain_ids = []
    per_image = {}

    for image_id, gt in ground_truth.items():
        truth = gt["flooded"]
        pred_entry = predictions.get(image_id)
        if pred_entry is None:
            skipped_no_prediction.append(image_id)
            continue
        if "ERROR" in pred_entry:
            skipped_error.append(image_id)
            continue

        pred = pred_entry["flood_damage_detected"]
        confidence = pred_entry.get("confidence")
        is_uncertain = confidence == "low"
        category = "UNCERTAIN" if is_uncertain else "CONFIDENT"

        per_image[image_id] = {
            "ground_truth_flooded": truth,
            "ai_predicted_flooded": pred,
            "confidence": confidence,
            "reasoning": pred_entry.get("reasoning"),
            "category": category,
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
            uncertain_ids.append(image_id)
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
        "dataset": "FloodNet (real DJI drone imagery, Hurricane Harvey)",
        "method": (
            "Confidence-aware scoring: predictions with confidence == 'low' excluded as "
            "UNCERTAIN, scored separately from medium/high confidence predictions."
        ),
        "images_total": len(ground_truth),
        "images_compared_flat": n_flat,
        "flat_accuracy": flat_accuracy,
        "flat_confusion": {
            "true_positive_flooded_correctly_caught": flat_tp,
            "true_negative_dry_correctly_identified": flat_tn,
            "false_positive_false_alarm": flat_fp,
            "false_negative_flooded_missed": flat_fn,
        },
        "confident_images_scored": n_conf,
        "confident_accuracy": confident_accuracy,
        "confident_confusion": {
            "true_positive_flooded_correctly_caught": conf_tp,
            "true_negative_dry_correctly_identified": conf_tn,
            "false_positive_false_alarm": conf_fp,
            "false_negative_flooded_missed": conf_fn,
        },
        "uncertain_count": len(uncertain_ids),
        "uncertain_ids": uncertain_ids,
        "skipped_no_prediction": skipped_no_prediction,
        "skipped_error": skipped_error,
        "per_image": per_image,
    }

    with open(OUT_PATH, "w") as fh:
        json.dump(summary, fh, indent=2)

    print(f"Images compared (flat): {n_flat}")
    print(f"Flat accuracy: {flat_accuracy}")
    print(f"Flat TP={flat_tp} TN={flat_tn} FP={flat_fp} FN={flat_fn}")
    print()
    print(f"Confident images scored: {n_conf}")
    print(f"Confident accuracy: {confident_accuracy}")
    print(f"Confident TP={conf_tp} TN={conf_tn} FP={conf_fp} FN={conf_fn}")
    print(f"Uncertain (excluded): {len(uncertain_ids)} -> {uncertain_ids}")
    print(f"Skipped (no prediction): {skipped_no_prediction}")
    print(f"Skipped (error): {skipped_error}")
    print(f"Written to {OUT_PATH}")


if __name__ == "__main__":
    main()
