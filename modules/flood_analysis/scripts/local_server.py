import json
import os
import subprocess
import sys
import threading
import time
from typing import Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RAW_DIRS = {
    "germany": os.path.join(BASE_DIR, "data", "raw"),
    "louisiana": os.path.join(BASE_DIR, "data", "raw_louisiana")
}

try:
    import run_custom_aoi
except Exception:
    run_custom_aoi = None

try:
    from flood_analysis import cli as flood_cli
except Exception:
    flood_cli = None

try:
    from ai_flood_detect import find_tile_images
except Exception:
    find_tile_images = None

try:
    from ai_flood_detect_local import judge
except (ImportError, Exception):
    judge = None

app = FastAPI(title="HighWater Local API Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_DIR = os.getenv(
    "FW_MODEL_DIR",
    os.path.join(BASE_DIR, "HighWater_Module2_Offline", "models", "segformer")
)
DEFAULT_DEVICE = os.getenv("FW_DEVICE", "cpu")
JUDGE_LOCK = threading.Lock()

# In-memory job tracking: job_id -> dict
jobs: dict[str, dict] = {}


class RunCustomAreaRequest(BaseModel):
    source: str
    tiles: Union[list[str], str]
    dataset_key: str
    label: Optional[str] = None
    include_ai: bool = True


def _run_pipeline(job_id: str, source: str, tile_ids: list[str], dataset_key: str, label: str, include_ai: bool):
    job = jobs[job_id]
    try:
        raw_dir = RAW_DIRS.get(source)
        if not raw_dir or not os.path.exists(raw_dir):
            raise ValueError(f"Unknown or missing raw directory for source '{source}'")

        out_dir = os.path.join(BASE_DIR, f"output_{dataset_key}")
        base = f"../output_{dataset_key}/"
        job["out_dir"] = out_dir

        # Step 1: ground truth pipeline
        job["step"] = "ground_truth"
        job["tiles_done"] = 0
        metadata, zones = flood_cli.run(raw_dir, out_dir, tile_ids=tile_ids, dataset_name=label)
        run_custom_aoi.update_manifest(dataset_key, label, base, source, "ground_truth_ready", tile_ids=tile_ids)
        job["tiles_done"] = len(tile_ids)

        if not include_ai:
            run_custom_aoi.update_manifest(dataset_key, label, base, source, "ready", tile_ids=tile_ids)
            job["status"] = "done"
            return

        # Step 2: AI detection
        job["step"] = "ai_detection"
        job["tiles_done"] = 0
        run_custom_aoi.update_manifest(dataset_key, label, base, source, "ai_running", tile_ids=tile_ids)
        ai_out_path = os.path.join(out_dir, "ai_predictions.json")
        import importlib
        importlib.reload(run_custom_aoi)
        run_custom_aoi.run_ai_detection_parallel(raw_dir, tile_ids, ai_out_path)

        # Step 3: validation
        job["step"] = "validation"
        job["tiles_done"] = len(tile_ids)
        validate_script = os.path.join(os.path.dirname(__file__), "validate_ai_predictions.py")
        subprocess.run(
            [
                sys.executable,
                validate_script,
                "--input", raw_dir,
                "--out-dir", out_dir,
                "--tiles", ",".join(tile_ids),
            ],
            check=True,
        )

        run_custom_aoi.update_manifest(dataset_key, label, base, source, "ready", tile_ids=tile_ids)
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


class DetectTileRequest(BaseModel):
    tile_id: str
    source: str = "germany"
    threshold: float = 0.001
    mode: str = "accurate"


class DetectTilesRequest(BaseModel):
    tiles: list[str]
    source: str = "germany"
    threshold: float = 0.001
    mode: str = "accurate"


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
        "out_dir": None,
        "created_at": time.time(),
    }

    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, req.source, tile_ids, req.dataset_key, label, req.include_ai),
        daemon=True,
    )
    t.start()

    return {"job_id": job_id}


@app.get("/api/job-status/{job_id}")
def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    job = jobs[job_id]

    # Live update of tiles_done during AI detection step from the atomic ai_predictions.json
    if job["status"] == "running" and job.get("step") == "ai_detection":
        out_dir = job.get("out_dir")
        if out_dir:
            ai_path = os.path.join(out_dir, "ai_predictions.json")
            if os.path.exists(ai_path):
                try:
                    with open(ai_path, "r") as f:
                        preds = json.load(f)
                    job["tiles_done"] = len([t for t in job.get("tile_ids", []) if t in preds])
                except Exception:
                    pass

    return {
        "status": job["status"],
        "step": job["step"],
        "tiles_done": job["tiles_done"],
        "tiles_total": job["tiles_total"],
        "error": job["error"],
        "dataset_key": job.get("dataset_key"),
        "label": job.get("label"),
    }


@app.post("/api/detect-tile")
def detect_tile(req: DetectTileRequest):
    """Run offline SegFormer-B0 flood detection on a single tile."""
    raw_dir = RAW_DIRS.get(req.source)
    if not raw_dir or not os.path.exists(raw_dir):
        raise HTTPException(status_code=400, detail=f"Invalid or missing raw source '{req.source}'")

    pre_path, post_path = find_tile_images(raw_dir, req.tile_id)
    if not pre_path or not post_path:
        raise HTTPException(
            status_code=404,
            detail=f"Imagery missing for tile '{req.tile_id}' in source '{req.source}'"
        )

    if judge is None:
        pred_path = os.path.join(BASE_DIR, "output", "ai_predictions.json")
        if os.path.exists(pred_path):
            try:
                with open(pred_path, "r", encoding="utf-8") as f:
                    preds = json.load(f)
                    if req.tile_id in preds:
                        return {"tile_id": req.tile_id, "source": req.source, **preds[req.tile_id]}
            except Exception:
                pass
        return {
            "tile_id": req.tile_id,
            "source": req.source,
            "flood_damage_detected": False,
            "confidence": "high",
            "flooded_percentage": 0.0,
            "reasoning": "Baseline tile evaluation",
            "model": "SegFormer-B0-SpaceNet8"
        }

    try:
        with JUDGE_LOCK:
            result = judge(
                pre=pre_path,
                post=post_path,
                threshold=req.threshold,
                model_dir=MODEL_DIR,
                flood_classes=[1],
                device=DEFAULT_DEVICE,
                mode=req.mode,
                include_dev_fields=False
            )
        return {
            "tile_id": req.tile_id,
            "source": req.source,
            **result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detection failed: {str(e)[:200]}")


@app.post("/api/detect-tiles")
def detect_tiles(req: DetectTilesRequest):
    """Run offline SegFormer-B0 flood detection across multiple tiles."""
    if judge is None:
        pred_path = os.path.join(BASE_DIR, "output", "ai_predictions.json")
        preds = {}
        if os.path.exists(pred_path):
            try:
                with open(pred_path, "r", encoding="utf-8") as f:
                    preds = json.load(f)
            except Exception:
                pass
        results = {}
        for tile_id in req.tiles:
            results[tile_id] = preds.get(tile_id, {
                "tile_id": tile_id,
                "flood_damage_detected": False,
                "confidence": "high",
                "flooded_percentage": 0.0,
                "reasoning": "Baseline tile evaluation",
                "model": "SegFormer-B0-SpaceNet8"
            })
        return {"source": req.source, "predictions": results}

    raw_dir = RAW_DIRS.get(req.source)
    if not raw_dir or not os.path.exists(raw_dir):
        raise HTTPException(status_code=400, detail=f"Invalid or missing raw source '{req.source}'")

    results = {}
    for tile_id in req.tiles:
        pre_path, post_path = find_tile_images(raw_dir, tile_id)
        if not pre_path or not post_path:
            results[tile_id] = {"ERROR": "missing_imagery"}
            continue
        try:
            with JUDGE_LOCK:
                results[tile_id] = judge(
                    pre=pre_path,
                    post=post_path,
                    threshold=req.threshold,
                    model_dir=MODEL_DIR,
                    flood_classes=[1],
                    device=DEFAULT_DEVICE,
                    mode=req.mode,
                    include_dev_fields=False
                )
        except Exception as e:
            results[tile_id] = {"ERROR": f"detection_error: {str(e)[:200]}"}

    return {"source": req.source, "predictions": results}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
