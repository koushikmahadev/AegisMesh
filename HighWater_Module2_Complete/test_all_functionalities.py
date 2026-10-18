import json
import time
import requests

SERVER_8000 = "http://localhost:8000"
SERVER_8001 = "http://localhost:8001"

passed = 0
failed = 0
errors = []

def record(name, success, msg=""):
    global passed, failed
    if success:
        passed += 1
        print(f"[PASS] {name} {msg}")
    else:
        failed += 1
        print(f"[FAIL] {name} {msg}")
        errors.append(f"{name}: {msg}")

print("========================================")
print("TEST 1: Health & Static Web Serving")
print("========================================")

try:
    r = requests.get(f"{SERVER_8000}/map.html")
    record("Map HTML (port 8000)", r.status_code == 200, f"Status: {r.status_code}")
except Exception as e:
    record("Map HTML (port 8000)", False, str(e))

try:
    r = requests.get(f"{SERVER_8001}/api/health")
    record("Local API Health (port 8001)", r.status_code == 200 and r.json().get("status") == "ok")
except Exception as e:
    record("Local API Health (port 8001)", False, str(e))

print("\n========================================")
print("TEST 2: Datasets Manifest & Datasets")
print("========================================")

datasets = []
try:
    r = requests.get(f"{SERVER_8000}/datasets.json")
    if r.status_code == 200:
        manifest = r.json()
        datasets = manifest.get("datasets", [])
        record("Manifest datasets.json", True, f"Found {len(datasets)} datasets")
    else:
        record("Manifest datasets.json", False, f"HTTP {r.status_code}")
except Exception as e:
    record("Manifest datasets.json", False, str(e))

files_to_check = [
    "zones.json",
    "flood_extent.geojson",
    "roads_status.geojson",
    "buildings_exposed.geojson",
    "metadata.json",
]

for ds in datasets:
    key = ds.get("key")
    base = ds.get("base", "")
    # resolve relative base path against SERVER_8000/
    # e.g. "./" -> "http://localhost:8000/"
    # "../output_louisiana/" -> "http://localhost:8000/output_louisiana/"
    cleaned_base = base.replace("../", "").lstrip("./")
    ds_url = f"{SERVER_8000}/{cleaned_base}".rstrip("/") + "/"
    label = ds.get('label', '').encode('ascii', errors='replace').decode('ascii')
    print(f"\nChecking dataset: {key} ({label}) at {ds_url}")

    for fname in files_to_check:
        file_url = f"{ds_url}{fname}"
        try:
            fr = requests.get(file_url, timeout=5)
            if fr.status_code == 200:
                # verify it's valid JSON (not HTML error page)
                data = fr.json()
                record(f"  {key}/{fname}", True, f"(200 OK, JSON parsed)")
            else:
                record(f"  {key}/{fname}", False, f"Status {fr.status_code}")
        except Exception as e:
            record(f"  {key}/{fname}", False, str(e))

print("\n========================================")
print("TEST 3: AI Inference Endpoints")
print("========================================")

try:
    r = requests.post(f"{SERVER_8001}/api/detect-tile", json={"tile_id": "0_41_58", "source": "germany"})
    data = r.json()
    record("Single Tile Detection (/api/detect-tile)", r.status_code == 200 and "flood_damage_detected" in data, f"Result: {data.get('flood_damage_detected')}")
except Exception as e:
    record("Single Tile Detection (/api/detect-tile)", False, str(e))

try:
    r = requests.post(f"{SERVER_8001}/api/detect-tiles", json={"tiles": ["0_41_58", "0_41_59"], "source": "germany"})
    data = r.json()
    record("Batch Tile Detection (/api/detect-tiles)", r.status_code == 200 and data.get("total") == 2, f"Total: {data.get('total')}")
except Exception as e:
    record("Batch Tile Detection (/api/detect-tiles)", False, str(e))

print("\n========================================")
print("TEST 4: Custom Area Generation & Pipeline")
print("========================================")

test_key = f"custom_test_{int(time.time())}"
test_label = f"Automated Test ({test_key})"
test_tiles = ["0_41_58", "0_41_59"]

try:
    req_body = {
        "source": "germany",
        "tiles": test_tiles,
        "dataset_key": test_key,
        "label": test_label,
        "include_ai": True
    }
    r = requests.post(f"{SERVER_8001}/api/run-custom-area", json=req_body)
    job_id = r.json().get("job_id")
    record("Submit Custom Area Job", r.status_code == 200 and job_id is not None, f"job_id: {job_id}")

    # Poll status
    done = False
    for attempt in range(60):
        time.sleep(1)
        sr = requests.get(f"{SERVER_8001}/api/job-status/{job_id}")
        sdata = sr.json()
        print(f"  Poll {attempt+1}: status={sdata.get('status')}, step={sdata.get('step')}, done={sdata.get('tiles_done')}/{sdata.get('tiles_total')}")
        if sdata.get("status") == "done":
            done = True
            break
        elif sdata.get("status") == "error":
            record("Custom Area Job Execution", False, f"Job error: {sdata.get('error')}")
            break

    record("Custom Area Job Completed", done)

    if done:
        # Check generated files
        for fname in files_to_check + ["ai_predictions.json", "ai_validation_summary.json"]:
            file_url = f"{SERVER_8000}/output_{test_key}/{fname}"
            fr = requests.get(file_url, timeout=5)
            if fr.status_code == 200:
                fr.json() # test json
                record(f"Generated {test_key}/{fname}", True, "(200 OK, JSON valid)")
            else:
                record(f"Generated {test_key}/{fname}", False, f"HTTP {fr.status_code}")

except Exception as e:
    record("Custom Area Pipeline", False, str(e))

print("\n========================================")
print(f"SUMMARY: PASSED={passed}, FAILED={failed}")
if errors:
    print("Errors:")
    for err in errors:
        print(f"  - {err}")
print("========================================")
