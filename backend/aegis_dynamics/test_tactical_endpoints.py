import sys
import os

sys.path.insert(0, r"C:\Users\Koushik\farlands\backend\aegis_dynamics")
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)

print("\n" + "="*80)
print("TESTING ATAK / CURSOR-ON-TARGET (CoT) & TACTICAL VOICE COPILOT ENDPOINTS")
print("="*80)

# 1. Test ATAK CoT XML bundle
r1 = client.get("/api/v1/atak/cot")
print(f"1. GET /api/v1/atak/cot -> Status: {r1.status_code}")
assert r1.status_code == 200
assert "<events" in r1.text and "<event" in r1.text
print(f"   CoT XML snippet:\n{r1.text[:280]}...\n")

# 2. Test ATAK GeoJSON FeatureCollection
r2 = client.get("/api/v1/atak/geojson")
print(f"2. GET /api/v1/atak/geojson -> Status: {r2.status_code}")
assert r2.status_code == 200
geo_data = r2.json()
print(f"   Returned {len(geo_data.get('features', []))} tactical features for ATAK Data Package.\n")

# 3. Test ATAK UDP Broadcast
r3 = client.post("/api/v1/atak/broadcast?target_ip=127.0.0.1&port=4242")
print(f"3. POST /api/v1/atak/broadcast -> Status: {r3.status_code}")
assert r3.status_code == 200
print(f"   Broadcast result: {r3.json()}\n")

# 4. Test Tactical Copilot Suggestions
r4 = client.get("/api/v1/copilot/suggestions")
print(f"4. GET /api/v1/copilot/suggestions -> Status: {r4.status_code}")
assert r4.status_code == 200
print(f"   Suggestions: {r4.json()}\n")

# 5. Test Tactical Copilot Query (Dynamic Reroute)
r5 = client.post("/api/v1/copilot/query", json={"query": "Aegis, calculate alternate route to Sector 4 avoiding unverified depth sensors.", "window_index": 58})
print(f"5. POST /api/v1/copilot/query (Route) -> Status: {r5.status_code}")
assert r5.status_code == 200
data5 = r5.json()
print(f"   Spoken Response: {data5.get('spoken_response')}")
print(f"   Action: {data5.get('action')}\n")

# 6. Test Tactical Copilot Query (SOAR Quarantine)
r6 = client.post("/api/v1/copilot/query", json={"query": "Aegis, quarantine attacker IP immediately.", "window_index": 58})
print(f"6. POST /api/v1/copilot/query (Quarantine) -> Status: {r6.status_code}")
assert r6.status_code == 200
data6 = r6.json()
print(f"   Spoken Response: {data6.get('spoken_response')}")
print(f"   Action: {data6.get('action')}\n")

print("="*80)
print("ALL ATAK & TACTICAL VOICE COPILOT TESTS PASSED PERFECTLY!")
print("="*80)
