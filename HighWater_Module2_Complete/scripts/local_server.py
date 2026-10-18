"""
Local API Server for HighWater Module 2 Offline Flood Detection.
Serves SegFormer-B0 offline inference and batch detection on port 8001.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add repository root to path for local model detector imports
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKSPACE_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
SRC_DIR = os.path.join(BASE_DIR, "src")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

model_path = os.path.join(BASE_DIR, "models", "segformer")
if os.path.exists(model_path):
    os.environ["FW_MODEL_DIR"] = model_path
else:
    alt_model = os.path.join(WORKSPACE_DIR, "modules", "flood_analysis", "models", "segformer")
    if os.path.exists(alt_model):
        os.environ["FW_MODEL_DIR"] = alt_model

try:
    import ai_flood_detect_local
except ImportError:
    # Try scripts directory
    sys.path.insert(0, os.path.join(WORKSPACE_DIR, "scripts"))
    import ai_flood_detect_local

app = FastAPI(title="HighWater Module 2 Local Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Raw data directories
RAW_DIRS = {
    "germany": os.path.join(BASE_DIR, "raw"),
    "louisiana": os.path.join(BASE_DIR, "raw_louisiana"),
}

# Cache for pre-computed predictions
CACHE_PREDICTIONS: Dict[str, Dict[str, Any]] = {}
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
for pred_rel in ["ai_predictions.json", os.path.join("output_louisiana", "ai_predictions.json")]:
    pred_file = os.path.join(OUTPUT_DIR, pred_rel)
    if os.path.exists(pred_file):
        try:
            with open(pred_file, "r") as f:
                data = json.load(f)
                CACHE_PREDICTIONS.update(data)
            print(f"[INIT] Loaded predictions from {pred_rel}. Total cached: {len(CACHE_PREDICTIONS)}")
        except Exception as e:
            print(f"[WARN] Failed to load {pred_rel}: {e}")

# In-memory jobs tracking
jobs: Dict[str, Dict[str, Any]] = {}


class DetectTileRequest(BaseModel):
    tile_id: str
    source: Optional[str] = "germany"
    threshold: Optional[float] = 0.001
    mode: Optional[str] = "fast"


class DetectTilesRequest(BaseModel):
    tiles: List[str]
    source: Optional[str] = "germany"
    threshold: Optional[float] = 0.001
    mode: Optional[str] = "fast"


class RunCustomAreaRequest(BaseModel):
    source: str
    tiles: Union[List[str], str]
    dataset_key: str
    label: Optional[str] = None
    include_ai: bool = True


def resolve_tile_images(source: str, tile_id: str) -> tuple[Optional[str], Optional[str]]:
    """Resolves pre and post image paths for a tile."""
    raw_dir = RAW_DIRS.get((source or "germany").lower(), RAW_DIRS["germany"])
    if not os.path.exists(raw_dir):
        raw_dir = os.path.join(BASE_DIR, "raw")

    pre_files = glob.glob(os.path.join(raw_dir, "PRE-event", f"*{tile_id}*"))
    post_files = glob.glob(os.path.join(raw_dir, "POST-event", f"*{tile_id}*"))
    pre_p = pre_files[0] if pre_files else None
    post_p = post_files[0] if post_files else None
    return pre_p, post_p


def run_tile_detection(tile_id: str, source: str = "germany", threshold: float = 0.001, mode: str = "fast") -> Dict[str, Any]:
    """Runs local SegFormer inference or retrieves cached detection."""
    # Check if pre-computed prediction exists
    if tile_id in CACHE_PREDICTIONS:
        res = dict(CACHE_PREDICTIONS[tile_id])
        if "metrics" not in res:
            res["metrics"] = {
                "pre_flood_fraction": 0.0,
                "post_flood_fraction": 0.15 if res.get("flood_damage_detected") else 0.0,
                "new_flood_fraction": 0.15 if res.get("flood_damage_detected") else 0.0,
            }
        return res

    pre_p, post_p = resolve_tile_images(source, tile_id)
    if not pre_p or not post_p:
        return {
            "ERROR": f"Missing imagery for tile {tile_id}",
            "tile_id": tile_id,
        }

    try:
        res = ai_flood_detect_local.judge(
            pre_p,
            post_p,
            threshold=threshold,
            mode=mode or "fast",
            include_dev_fields=True,
        )
        # Cache the result
        CACHE_PREDICTIONS[tile_id] = res
        return res
    except Exception as e:
        return {
            "ERROR": f"Inference failed for tile {tile_id}: {str(e)}",
            "tile_id": tile_id,
        }


from fastapi.responses import HTMLResponse


@app.get("/", response_class=HTMLResponse)
def root():
    return """<!DOCTYPE html>
<html>
<head>
    <title>HighWater Module 2 - Flood Detection API</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px 20px; line-height: 1.6; }
        .card { max-width: 650px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px; border: 1px solid #334155; box-shadow: 0 10px 25px rgba(0,0,0,0.4); }
        h1 { margin-top: 0; color: #38bdf8; font-size: 24px; display: flex; align-items: center; gap: 10px; }
        .status-badge { display: inline-block; background: #166534; color: #4ade80; padding: 4px 10px; border-radius: 9999px; font-size: 13px; font-weight: 600; margin-bottom: 16px; }
        .btn { display: inline-block; background: #0284c7; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; margin-top: 12px; transition: background 0.2s; }
        .btn:hover { background: #0369a1; }
        .btn-secondary { background: #334155; color: #cbd5e1; margin-left: 8px; }
        .btn-secondary:hover { background: #475569; }
        ul { padding-left: 20px; }
        li { margin-bottom: 8px; }
        code { background: #0f172a; padding: 2px 6px; border-radius: 4px; font-size: 13px; color: #f59e0b; }
    </style>
</head>
<body>
    <div class="card">
        <div class="status-badge">● API Server Online (Port 8001)</div>
        <h1>HighWater Module 2 Local Server</h1>
        <p>This is the <strong>offline AI inference backend</strong> for flood detection.</p>
        <p>If you're looking for the <strong>interactive flood map</strong>, open the map UI server running on port 8000:</p>
        <div style="margin: 20px 0;">
            <a class="btn" href="http://localhost:8000/map.html" target="_blank">🗺️ Open Map UI (http://localhost:8000/map.html)</a>
            <a class="btn btn-secondary" href="/docs" target="_blank">📖 Swagger API Docs</a>
        </div>
        <hr style="border: 0; border-top: 1px solid #334155; margin: 24px 0;">
        <h3 style="font-size: 16px; color: #94a3b8; margin-bottom: 8px;">Available API Endpoints:</h3>
        <ul style="font-size: 13px; color: #cbd5e1;">
            <li><code>GET /api/health</code> — Health check endpoint</li>
            <li><code>POST /api/detect-tiles</code> — Batch local flood detection</li>
            <li><code>POST /api/detect-tile</code> — Single-tile flood detection</li>
            <li><code>GET /docs</code> — Interactive OpenAPI / Swagger UI</li>
        </ul>
    </div>
</body>
</html>"""


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "HighWater Module 2 Local API", "port": 8001}


@app.post("/api/detect-tile")
def detect_tile(req: DetectTileRequest):
    result = run_tile_detection(
        tile_id=req.tile_id,
        source=req.source or "germany",
        threshold=req.threshold if req.threshold is not None else 0.001,
        mode=req.mode or "fast",
    )
    return result


@app.post("/api/detect-tiles")
def detect_tiles(req: DetectTilesRequest):
    if not req.tiles:
        raise HTTPException(status_code=400, detail="No tiles provided")

    results: Dict[str, Any] = {}
    threshold = req.threshold if req.threshold is not None else 0.001
    mode = req.mode or "fast"
    source = req.source or "germany"

    for tile_id in req.tiles:
        tile_id = str(tile_id).strip()
        if not tile_id:
            continue
        results[tile_id] = run_tile_detection(
            tile_id=tile_id,
            source=source,
            threshold=threshold,
            mode=mode,
        )

    return {
        "status": "ok",
        "total": len(results),
        "results": results,
        "predictions": results,
    }


def generate_custom_dataset(
    dataset_key: str,
    tile_ids: List[str],
    label: str,
    source: str = "germany",
    include_ai: bool = True,
    job_ref: Optional[Dict[str, Any]] = None,
):
    source = (source or "germany").lower()
    raw_dir = RAW_DIRS.get(source, RAW_DIRS["germany"])
    out_dir = os.path.join(OUTPUT_DIR, f"output_{dataset_key}")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Ground truth step
    if job_ref is not None:
        job_ref["step"] = "ground_truth"
        job_ref["tiles_done"] = 0
        job_ref["tiles_total"] = len(tile_ids)

    from flood_analysis import cli as flood_cli
    from shapely.geometry import shape
    from shapely.ops import unary_union

    metadata, zones = flood_cli.run(raw_dir, out_dir, tile_ids=tile_ids, dataset_name=label)

    # tile_index.json
    tile_index = {}
    for tid in tile_ids:
        fp = os.path.join(raw_dir, "annotations", f"{tid}.geojson")
        if os.path.exists(fp):
            try:
                with open(fp, "r") as af:
                    d = json.load(af)
                geoms = [shape(f["geometry"]) for f in d.get("features", []) if not shape(f["geometry"]).is_empty]
                if geoms:
                    minx, miny, maxx, maxy = unary_union(geoms).bounds
                    tile_index[tid] = {"bbox": [minx, miny, maxx, maxy]}
            except Exception:
                pass
    with open(os.path.join(out_dir, "tile_index.json"), "w") as tf:
        json.dump(tile_index, tf, indent=2)

    # 2. AI detection step
    ai_predictions = {}
    if job_ref is not None:
        job_ref["step"] = "ai_detection"
        job_ref["tiles_done"] = 0

    if include_ai:
        for idx, tid in enumerate(tile_ids):
            pred = run_tile_detection(tid, source=source)
            ai_predictions[tid] = pred
            if job_ref is not None:
                job_ref["tiles_done"] = idx + 1
    else:
        for idx, tid in enumerate(tile_ids):
            ai_predictions[tid] = {"flood_damage_detected": False, "confidence": "low", "reasoning": "AI skipped"}
        if job_ref is not None:
            job_ref["tiles_done"] = len(tile_ids)

    with open(os.path.join(out_dir, "ai_predictions.json"), "w") as pf:
        json.dump(ai_predictions, pf, indent=2)

    # 3. Validation step
    if job_ref is not None:
        job_ref["step"] = "validation"
        job_ref["tiles_done"] = 0

    annotations_dir = os.path.join(raw_dir, "annotations")
    flat_tp = flat_tn = flat_fp = flat_fn = 0
    conf_tp = conf_tn = conf_fp = conf_fn = 0
    skipped_no_truth, skipped_no_prediction, skipped_error, uncertain_tile_ids = [], [], [], []
    per_tile = {}

    for idx, tid in enumerate(tile_ids):
        features = None
        fp = os.path.join(annotations_dir, f"{tid}.geojson")
        if os.path.exists(fp):
            try:
                with open(fp, "r") as af:
                    d = json.load(af)
                features = [
                    f for f in d.get("features", [])
                    if f["properties"].get("building") is not None or f["properties"].get("highway") is not None
                ]
            except Exception:
                pass

        truth = any(f["properties"].get("flooded") == "yes" for f in features) if features else None
        bbox = tile_index.get(tid, {}).get("bbox")

        if truth is None:
            skipped_no_truth.append(tid)
            continue

        pred_entry = ai_predictions.get(tid)
        if pred_entry is None:
            skipped_no_prediction.append(tid)
            continue
        if "ERROR" in pred_entry:
            skipped_error.append(tid)
            continue

        pred = pred_entry.get("flood_damage_detected", False)
        confidence = pred_entry.get("confidence", "high")
        is_uncertain = confidence == "low"
        category = "UNCERTAIN" if is_uncertain else "CONFIDENT"

        per_tile[tid] = {
            "ground_truth_flooded": truth,
            "ai_predicted_flooded": pred,
            "confidence": confidence,
            "reasoning": pred_entry.get("reasoning", "Local SegFormer detection"),
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
            uncertain_tile_ids.append(tid)
        else:
            if truth and pred:
                conf_tp += 1
            elif (not truth) and (not pred):
                conf_tn += 1
            elif (not truth) and pred:
                conf_fp += 1
            elif truth and (not pred):
                conf_fn += 1

        if job_ref is not None:
            job_ref["tiles_done"] = idx + 1

    n_flat = flat_tp + flat_tn + flat_fp + flat_fn
    flat_accuracy = (flat_tp + flat_tn) / n_flat if n_flat else 0.0
    n_conf = conf_tp + conf_tn + conf_fp + conf_fn
    confident_accuracy = (conf_tp + conf_tn) / n_conf if n_conf else 0.0

    summary = {
        "method": "SegFormer-B0 offline validation vs SpaceNet 8 ground truth annotations",
        "tiles_total_in_aoi": len(tile_ids),
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
    with open(os.path.join(out_dir, "ai_validation_summary.json"), "w") as sf:
        json.dump(summary, sf, indent=2)

    # 4. Manifest update
    manifest_paths = [
        os.path.join(OUTPUT_DIR, "datasets.json"),
        os.path.join(BASE_DIR, "datasets.json")
    ]
    for mpath in manifest_paths:
        manifest = {"datasets": []}
        if os.path.exists(mpath):
            try:
                with open(mpath, "r") as mf:
                    manifest = json.load(mf)
            except Exception:
                pass
        entries = manifest.get("datasets", [])
        existing = next((e for e in entries if e.get("key") == dataset_key), None)
        entry_data = {
            "key": dataset_key,
            "label": label,
            "base": f"../output_{dataset_key}/",
            "raw_source": source,
            "status": "ready",
            "tile_ids": tile_ids,
        }
        if existing:
            existing.update(entry_data)
        else:
            entries.append(entry_data)
        manifest["datasets"] = entries
        tmp = mpath + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(manifest, fh, indent=2)
        os.replace(tmp, mpath)

    base_out = os.path.join(BASE_DIR, f"output_{dataset_key}")
    if not os.path.exists(base_out):
        try:
            import _winapi
            _winapi.CreateJunction(out_dir, base_out)
        except Exception:
            pass

    if job_ref is not None:
        job_ref["step"] = "ready"
        job_ref["status"] = "done"


@app.post("/api/run-custom-area")
def run_custom_area(req: RunCustomAreaRequest):
    if isinstance(req.tiles, str):
        tile_ids = [t.strip() for t in req.tiles.split(",") if t.strip()]
    else:
        tile_ids = [str(t).strip() for t in req.tiles if str(t).strip()]

    if not tile_ids:
        raise HTTPException(status_code=400, detail="No tiles provided")

    job_id = f"job_{req.dataset_key}"
    label = req.label or f"Custom area ({req.dataset_key})"

    jobs[job_id] = {
        "status": "running",
        "step": "ground_truth",
        "tiles_done": 0,
        "tiles_total": len(tile_ids),
        "error": None,
        "dataset_key": req.dataset_key,
        "label": label,
        "tile_ids": tile_ids,
        "created_at": time.time(),
    }

    def _worker():
        job = jobs[job_id]
        try:
            generate_custom_dataset(
                dataset_key=req.dataset_key,
                tile_ids=tile_ids,
                label=label,
                source=req.source,
                include_ai=req.include_ai,
                job_ref=job,
            )
        except Exception as ex:
            import traceback
            traceback.print_exc()
            job["status"] = "error"
            job["error"] = str(ex)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"job_id": job_id}


@app.get("/api/job-status/{job_id}")
def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    job = jobs[job_id]
    return {
        "status": job["status"],
        "step": job.get("step", "done"),
        "tiles_done": job.get("tiles_done", 0),
        "tiles_total": job.get("tiles_total", 0),
        "error": job.get("error"),
        "dataset_key": job.get("dataset_key"),
        "label": job.get("label"),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
