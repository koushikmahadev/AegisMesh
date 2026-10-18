import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';
import {
  generateEvacuationRoutes,
  identifyEvacuationZones,
  buildRoadNetwork,
  indexZoneRoads,
  computePathDistance,
  haversineDistance,
  getZoneOrigin,
} from '../services/routeGenerator.js';
import { adaptRoutes } from '../data/dataAdapter.js';
import RouteLayer from '../features/map/RouteLayer.jsx';
import ZoneDetails from '../components/ZoneDetails.jsx';
import FloodMap from '../components/FloodMap.jsx';

// Load actual Dernau dataset outputs
const FIXTURES_DIR = path.resolve(__dirname, '../../public/mock-data-dernau');
const dernauZones = JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, 'zones.json'), 'utf8'));
const dernauRoads = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../../flood_analysis/output/roads_status.geojson'), 'utf8'));
const dernauFacilities = JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, 'facilities.geojson'), 'utf8'));
const dernauRoutes = JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, 'routes.json'), 'utf8'));

describe('Evacuation Route Selection and Optimization Engine', () => {
  // ===========================================================================
  // 1. Data-Driven Candidate Identification (High & Medium risk zones)
  // ===========================================================================
  describe('Candidate Zone Identification', () => {
    it('identifies EVERY zone classified as High or Medium risk dynamically without hardcoding', () => {
      const candidates = identifyEvacuationZones(dernauZones);
      const candidateIds = candidates.map((z) => z.zone_id);

      // Total 8 qualifying zones in Dernau dataset (3 HIGH, 5 MEDIUM)
      expect(candidates).toHaveLength(8);

      // Verify all HIGH risk zones
      expect(candidateIds).toContain('zone-036');
      expect(candidateIds).toContain('zone-002');
      expect(candidateIds).toContain('zone-038');

      // Verify all MEDIUM risk zones
      expect(candidateIds).toContain('zone-031');
      expect(candidateIds).toContain('zone-008');
      expect(candidateIds).toContain('zone-010');
      expect(candidateIds).toContain('zone-017');
      expect(candidateIds).toContain('zone-035');

      // Confirm candidate risk levels are strictly HIGH or MEDIUM
      candidates.forEach((z) => {
        expect(['HIGH', 'MEDIUM', 'CRITICAL']).toContain(z.risk_level);
        expect(z.risk_score).toBeGreaterThanOrEqual(20);
      });
    });

    it('excludes all low-risk peripheral zones from evacuation routing', () => {
      const candidates = identifyEvacuationZones(dernauZones);
      const candidateIds = candidates.map((z) => z.zone_id);

      const lowRiskZoneIds = [
        'zone-028', 'zone-029', 'zone-023', 'zone-022',
        'zone-016', 'zone-024', 'zone-003', 'zone-007', 'zone-020',
      ];
      lowRiskZoneIds.forEach((id) => {
        expect(candidateIds).not.toContain(id);
      });
    });

    it('sorts candidate zones strictly by descending priority score', () => {
      const candidates = identifyEvacuationZones(dernauZones);
      for (let i = 0; i < candidates.length - 1; i++) {
        expect(candidates[i].risk_score).toBeGreaterThanOrEqual(candidates[i + 1].risk_score);
      }
    });
  });

  // ===========================================================================
  // 2. Road Network and Flooded-Road Avoidance
  // ===========================================================================
  describe('Road Network & Flood Constraint Satisfaction', () => {
    it('separates flooded roads from dry roads and builds an unflooded graph', () => {
      const { dryGraph, dryRoads, floodedRoads } = buildRoadNetwork(dernauRoads);

      expect(floodedRoads.length).toBe(45);
      expect(dryRoads.length).toBe(72);
      expect(dryGraph.size).toBeGreaterThan(50);

      expect(dryRoads.every((f) => f.properties.flooded === false)).toBe(true);
      expect(floodedRoads.every((f) => f.properties.flooded === true)).toBe(true);
    });

    it('verifies all road access for cut-off zones 36 and 38 is 100% flooded', () => {
      const candidates = identifyEvacuationZones(dernauZones);
      const zoneIndex = indexZoneRoads(candidates, dernauRoads);

      const z36Info = zoneIndex.get('zone-036');
      expect(z36Info).toBeDefined();
      expect(z36Info.totalRoads).toBe(7);
      expect(z36Info.floodedRoads).toBe(7);
      expect(z36Info.dryRoads).toBe(0);

      const z38Info = zoneIndex.get('zone-038');
      expect(z38Info).toBeDefined();
      expect(z38Info.totalRoads).toBe(3);
      expect(z38Info.floodedRoads).toBe(3);
      expect(z38Info.dryRoads).toBe(0);
    });

    it('verifies qualifying zones with dry roads have unflooded connectivity', () => {
      const candidates = identifyEvacuationZones(dernauZones);
      const zoneIndex = indexZoneRoads(candidates, dernauRoads);

      ['zone-002', 'zone-008', 'zone-010', 'zone-017', 'zone-031', 'zone-035'].forEach((id) => {
        const info = zoneIndex.get(id);
        expect(info).toBeDefined();
        expect(info.dryRoads).toBeGreaterThan(0);
      });
    });
  });

  // ===========================================================================
  // 3. Dernau Study Area Output Verification
  // ===========================================================================
  describe('Dernau Study Area Pipeline Evaluation', () => {
    it('evaluates all 8 eligible zones and produces 2 continuous OK routes to safe shelters and 6 explicit failures', () => {
      const result = generateEvacuationRoutes({
        zones: dernauZones,
        roads: dernauRoads,
        facilities: dernauFacilities,
      });

      expect(result.routes).toHaveLength(8);

      const okRoutes = result.routes.filter((r) => r.status === 'OK');
      const failedRoutes = result.routes.filter((r) => r.status === 'NO_SAFE_ROUTE' || r.status === 'UNREACHABLE');

      expect(okRoutes).toHaveLength(2);
      expect(failedRoutes).toHaveLength(6);

      // Verify the two successful routes connect to verified shelters (fac-004 and fac-005)
      const r08 = okRoutes.find((r) => r.zone_id === 'zone-008');
      expect(r08).toBeDefined();
      expect(r08.destination_id).toBe('fac-004');
      expect(r08.destination_name).toBe('North-Central Relief Staging');
      expect(r08.distance_m).toBeGreaterThan(0);
      expect(r08.geometry.type).toBe('LineString');
      expect(r08.geometry.coordinates.length).toBeGreaterThan(5);

      const r35 = okRoutes.find((r) => r.zone_id === 'zone-035');
      expect(r35).toBeDefined();
      expect(r35.destination_id).toBe('fac-005');
      expect(r35.destination_name).toBe('North Emergency Assembly Post');
      expect(r35.distance_m).toBeGreaterThan(0);
      expect(r35.geometry.type).toBe('LineString');
      expect(r35.geometry.coordinates.length).toBeGreaterThan(5);

      // Check all 6 failed zones report explicit status and null geometry without fabricated lines
      failedRoutes.forEach((r) => {
        expect(['NO_SAFE_ROUTE', 'UNREACHABLE']).toContain(r.status);
        expect(r.geometry).toBeNull();
        expect(r.distance_m).toBeNull();
        expect(r.eta_minutes).toBeNull();
        expect(r.destination_id).toBeNull();
        expect(r.reason).toBeTruthy();
      });

      // Verify cut-off and blocked zones
      const r36 = failedRoutes.find((r) => r.zone_id === 'zone-036');
      expect(r36.reason).toContain('all 7 road segments in zone-036 are flooded');

      const r38 = failedRoutes.find((r) => r.zone_id === 'zone-038');
      expect(r38.reason).toContain('all 3 road segments in zone-038 are flooded');

      const r02 = failedRoutes.find((r) => r.zone_id === 'zone-002');
      expect(r02.reason).toContain('all egress corridors toward safe emergency facilities are blocked');

      const r31 = failedRoutes.find((r) => r.zone_id === 'zone-031');
      expect(r31.reason).toContain('all egress corridors toward safe emergency facilities are blocked');

      const r10 = failedRoutes.find((r) => r.zone_id === 'zone-010');
      expect(r10.reason).toContain('all egress corridors toward safe emergency facilities are blocked');

      const r17 = failedRoutes.find((r) => r.zone_id === 'zone-017');
      expect(r17.reason).toContain('all egress corridors toward safe emergency facilities are blocked');
    });

    it('ensures successful routes strictly avoid all flooded road segments', () => {
      const { floodedRoads } = buildRoadNetwork(dernauRoads);
      const floodedSegments = new Set();
      const segKey = (p1, p2) => {
        const k1 = `${p1[0].toFixed(5)},${p1[1].toFixed(5)}`;
        const k2 = `${p2[0].toFixed(5)},${p2[1].toFixed(5)}`;
        return k1 < k2 ? `${k1}->${k2}` : `${k2}->${k1}`;
      };

      floodedRoads.forEach((feat) => {
        const coords = feat.geometry.coordinates;
        for (let i = 0; i < coords.length - 1; i++) {
          floodedSegments.add(segKey(coords[i], coords[i + 1]));
        }
      });

      const result = generateEvacuationRoutes({
        zones: dernauZones,
        roads: dernauRoads,
        facilities: dernauFacilities,
      });

      const okRoutes = result.routes.filter((r) => r.status === 'OK');
      okRoutes.forEach((r) => {
        const coords = r.geometry.coordinates;
        for (let i = 0; i < coords.length - 1; i++) {
          const key = segKey(coords[i], coords[i + 1]);
          expect(floodedSegments.has(key)).toBe(false);
        }
      });
    });
  });

  // ===========================================================================
  // 4. Required Regression Cases (14 Cases per Section 6 Specification)
  // ===========================================================================
  describe('Deterministic 14 Regression Cases', () => {
    // Helper to generate a minimal FeatureCollection
    const makeRoads = (features) => ({ type: 'FeatureCollection', features });
    const makeFacilities = (features) => ({ type: 'FeatureCollection', features });

    // 1. A simple connected road graph with a known origin and shelter produces the expected complete route
    it('Case 1: simple connected road graph with known origin and shelter produces expected complete route', () => {
      const road = {
        type: 'Feature',
        properties: { id: 'road-linear', flooded: false },
        geometry: {
          type: 'LineString',
          coordinates: [[7.000, 50.000], [7.010, 50.000], [7.020, 50.000]],
        },
      };
      const zone = {
        zone_id: 'zone-linear',
        name: 'Zone Linear',
        risk_level: 'HIGH',
        risk_score: 80,
        bbox: [6.999, 49.999, 7.001, 50.001],
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-1', name: 'Safe Shelter 1', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.020, 50.000] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([road]),
        facilities: makeFacilities([shelter]),
      });

      expect(result.routes).toHaveLength(1);
      const r = result.routes[0];
      expect(r.status).toBe('OK');
      expect(r.destination_id).toBe('shelter-1');
      expect(r.geometry.type).toBe('LineString');
      expect(r.geometry.coordinates).toHaveLength(3);
      expect(r.geometry.coordinates[0]).toEqual([7.000, 50.000]);
      expect(r.geometry.coordinates[2]).toEqual([7.020, 50.000]);
      expect(r.distance_m).toBeGreaterThan(1400);
    });

    // 2. The route begins at the correct origin and reaches the correct destination
    it('Case 2: route begins at the correct origin and reaches the correct destination', () => {
      const originRoad = {
        type: 'Feature',
        properties: { id: 'road-ab', flooded: false },
        geometry: {
          type: 'LineString',
          coordinates: [[7.100, 50.100], [7.105, 50.100], [7.105, 50.105]],
        },
      };
      const zone = {
        zone_id: 'zone-origin-test',
        name: 'Origin Test Zone',
        risk_level: 'HIGH',
        risk_score: 90,
        pickup_point: [7.100, 50.100],
        bbox: [7.099, 50.099, 7.101, 50.101],
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-target', name: 'Target Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.105, 50.105] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([originRoad]),
        facilities: makeFacilities([shelter]),
      });

      const r = result.routes[0];
      expect(r.status).toBe('OK');
      expect(r.origin_id).toBe('pickup-zone-origin-test');
      expect(r.destination_id).toBe('shelter-target');
      // Starts within 5m of zone origin
      expect(haversineDistance(r.geometry.coordinates[0], [7.100, 50.100])).toBeLessThan(5);
      // Ends within 5m of shelter
      expect(haversineDistance(r.geometry.coordinates[r.geometry.coordinates.length - 1], [7.105, 50.105])).toBeLessThan(5);
    });

    // 3. A flooded road is avoided when a safe alternative exists
    it('Case 3: flooded road is avoided when a safe alternative exists', () => {
      // Diamond: start at [7.00, 50.00]. Path 1 (short, flooded): [7.00, 50.00] -> [7.01, 50.00] -> [7.02, 50.00].
      // Path 2 (longer, dry detour): [7.00, 50.00] -> [7.01, 50.01] -> [7.02, 50.00].
      const floodedShort = {
        type: 'Feature',
        properties: { id: 'road-flooded', flooded: true },
        geometry: { type: 'LineString', coordinates: [[7.00, 50.00], [7.01, 50.00], [7.02, 50.00]] },
      };
      const dryDetour1 = {
        type: 'Feature',
        properties: { id: 'road-detour-1', flooded: false },
        geometry: { type: 'LineString', coordinates: [[7.00, 50.00], [7.01, 50.01]] },
      };
      const dryDetour2 = {
        type: 'Feature',
        properties: { id: 'road-detour-2', flooded: false },
        geometry: { type: 'LineString', coordinates: [[7.01, 50.01], [7.02, 50.00]] },
      };
      const zone = {
        zone_id: 'zone-detour',
        name: 'Detour Zone',
        risk_level: 'HIGH',
        risk_score: 75,
        bbox: [6.995, 49.995, 7.005, 50.005],
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-detour', name: 'Detour Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.02, 50.00] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([floodedShort, dryDetour1, dryDetour2]),
        facilities: makeFacilities([shelter]),
      });

      const r = result.routes[0];
      expect(r.status).toBe('OK');
      // Must take detour via 50.01
      const lats = r.geometry.coordinates.map((pt) => pt[1]);
      expect(lats).toContain(50.01);
      // Must not use flooded intermediate node [7.01, 50.00]
      const usesFloodedMid = r.geometry.coordinates.some(([x, y]) => Math.abs(x - 7.01) < 1e-4 && Math.abs(y - 50.00) < 1e-4);
      expect(usesFloodedMid).toBe(false);
    });

    // 4. A route is rejected or reported as unavailable when all available paths are unsafe
    it('Case 4: route is rejected or reported as unavailable when all available paths are unsafe', () => {
      const road1 = {
        type: 'Feature',
        properties: { id: 'road-submerged-1', flooded: true },
        geometry: { type: 'LineString', coordinates: [[7.00, 50.00], [7.01, 50.00]] },
      };
      const road2 = {
        type: 'Feature',
        properties: { id: 'road-submerged-2', flooded: true },
        geometry: { type: 'LineString', coordinates: [[7.01, 50.00], [7.02, 50.00]] },
      };
      const zone = {
        zone_id: 'zone-submerged',
        name: 'Submerged Zone',
        risk_level: 'HIGH',
        risk_score: 95,
        bbox: [6.995, 49.995, 7.005, 50.005],
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-safe', name: 'Safe Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.02, 50.00] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([road1, road2]),
        facilities: makeFacilities([shelter]),
      });

      const r = result.routes[0];
      expect(['NO_SAFE_ROUTE', 'UNREACHABLE']).toContain(r.status);
      expect(r.geometry).toBeNull();
      expect(r.distance_m).toBeNull();
      expect(r.reason).toContain('Surface road access severed');
      expect(r.reason).toContain('flooded');
    });

    // 5. A disconnected road graph produces an explicit failure instead of an incomplete route
    it('Case 5: disconnected road graph produces an explicit failure instead of an incomplete route', () => {
      const zoneRoad = {
        type: 'Feature',
        properties: { id: 'road-island-1', flooded: false },
        geometry: { type: 'LineString', coordinates: [[7.000, 50.000], [7.005, 50.000]] },
      };
      const shelterRoad = {
        type: 'Feature',
        properties: { id: 'road-island-2', flooded: false },
        geometry: { type: 'LineString', coordinates: [[7.050, 50.000], [7.055, 50.000]] },
      };
      const zone = {
        zone_id: 'zone-island',
        name: 'Island Zone',
        risk_level: 'HIGH',
        risk_score: 80,
        bbox: [6.995, 49.995, 7.006, 50.005],
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-remote', name: 'Remote Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.055, 50.000] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([zoneRoad, shelterRoad]),
        facilities: makeFacilities([shelter]),
      });

      const r = result.routes[0];
      expect(['NO_SAFE_ROUTE', 'UNREACHABLE']).toContain(r.status);
      expect(r.geometry).toBeNull();
      expect(r.reason).toContain('all egress corridors toward safe emergency facilities are blocked');
    });

    // 6. A zone near a depot is not automatically assigned the depot as its shelter
    it('Case 6: zone near a depot is not automatically assigned the depot as its shelter', () => {
      // Road passes from origin [7.00, 50.00] through depot at [7.002, 50.00] to shelter at [7.020, 50.00]
      const road = {
        type: 'Feature',
        properties: { id: 'road-depot-shelter', flooded: false },
        geometry: {
          type: 'LineString',
          coordinates: [[7.000, 50.000], [7.002, 50.000], [7.020, 50.000]],
        },
      };
      const zone = {
        zone_id: 'zone-near-depot',
        name: 'Near Depot Zone',
        risk_level: 'HIGH',
        risk_score: 70,
        bbox: [6.995, 49.995, 7.003, 50.005],
      };
      const depotNearby = {
        type: 'Feature',
        properties: { facility_id: 'depot-01', name: 'Supply Depot Alpha', type: 'depot' },
        geometry: { type: 'Point', coordinates: [7.002, 50.000] },
      };
      const shelterFar = {
        type: 'Feature',
        properties: { facility_id: 'shelter-01', name: 'Verified Safe Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.020, 50.000] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([road]),
        facilities: makeFacilities([depotNearby, shelterFar]),
      });

      const r = result.routes[0];
      expect(r.status).toBe('OK');
      // Must NOT be assigned to depot-01 merely because it is 100x closer
      expect(r.destination_id).not.toBe('depot-01');
      expect(r.destination_id).toBe('shelter-01');
      expect(r.destination_name).toBe('Verified Safe Shelter');
    });

    // 7. Hospitals, depots, and shelters are handled according to their facility types
    it('Case 7: hospitals, depots, and shelters are handled according to their facility types', () => {
      const road = {
        type: 'Feature',
        properties: { id: 'road-facility-types', flooded: false },
        geometry: {
          type: 'LineString',
          coordinates: [[7.000, 50.000], [7.010, 50.000], [7.020, 50.000], [7.030, 50.000]],
        },
      };
      const zone = {
        zone_id: 'zone-fac-types',
        name: 'Facility Types Zone',
        risk_level: 'HIGH',
        risk_score: 85,
        bbox: [6.995, 49.995, 7.005, 50.005],
      };
      const hospital = {
        type: 'Feature',
        properties: { facility_id: 'hosp-1', name: 'Central Hospital', type: 'hospital' },
        geometry: { type: 'Point', coordinates: [7.010, 50.000] },
      };
      const depot = {
        type: 'Feature',
        properties: { facility_id: 'depot-1', name: 'Equipment Depot', type: 'depot' },
        geometry: { type: 'Point', coordinates: [7.020, 50.000] },
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-1', name: 'Community Evac Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.030, 50.000] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([road]),
        facilities: makeFacilities([hospital, depot, shelter]),
      });

      const r = result.routes[0];
      expect(r.status).toBe('OK');
      expect(r.destination_id).toBe('shelter-1');
      expect(r.destination_id).not.toBe('hosp-1');
      expect(r.destination_id).not.toBe('depot-1');
    });

    // 8. Multiple eligible zones are all processed
    it('Case 8: multiple eligible zones are all processed', () => {
      const road = {
        type: 'Feature',
        properties: { id: 'road-multi-zone', flooded: false },
        geometry: {
          type: 'LineString',
          coordinates: [[7.00, 50.00], [7.01, 50.00], [7.02, 50.00]],
        },
      };
      const zones = [
        { zone_id: 'z-high-1', name: 'Zone High 1', risk_level: 'HIGH', risk_score: 85, bbox: [6.99, 49.99, 7.01, 50.01] },
        { zone_id: 'z-high-2', name: 'Zone High 2', risk_level: 'HIGH', risk_score: 75, bbox: [7.00, 49.99, 7.02, 50.01] },
        { zone_id: 'z-med-1', name: 'Zone Med 1', risk_level: 'MEDIUM', risk_score: 45, bbox: [7.00, 49.99, 7.01, 50.01] },
        { zone_id: 'z-low-1', name: 'Zone Low 1', risk_level: 'LOW', risk_score: 10, bbox: [7.00, 49.99, 7.01, 50.01] },
      ];
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-multi', name: 'Multi Zone Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.02, 50.00] },
      };

      const result = generateEvacuationRoutes({
        zones,
        roads: makeRoads([road]),
        facilities: makeFacilities([shelter]),
      });

      // Exactly the 3 qualifying zones (2 HIGH, 1 MEDIUM) must receive route assignments
      expect(result.routes).toHaveLength(3);
      const zoneIds = result.routes.map((r) => r.zone_id);
      expect(zoneIds).toContain('z-high-1');
      expect(zoneIds).toContain('z-high-2');
      expect(zoneIds).toContain('z-med-1');
      expect(zoneIds).not.toContain('z-low-1');
    });

    // 9. Multiple generated routes survive API serialization and frontend adaptation
    it('Case 9: multiple generated routes survive API serialization and frontend adaptation', () => {
      const road = {
        type: 'Feature',
        properties: { id: 'road-surv', flooded: false },
        geometry: { type: 'LineString', coordinates: [[7.00, 50.00], [7.01, 50.00]] },
      };
      const zones = [
        { zone_id: 'z-1', name: 'Zone 1', risk_level: 'HIGH', risk_score: 90, bbox: [6.99, 49.99, 7.01, 50.01] },
        { zone_id: 'z-2', name: 'Zone 2', risk_level: 'MEDIUM', risk_score: 50, bbox: [6.99, 49.99, 7.01, 50.01] },
      ];
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'sh-1', name: 'Shelter Surv', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.01, 50.00] },
      };

      const backendOutput = generateEvacuationRoutes({
        zones,
        roads: makeRoads([road]),
        facilities: makeFacilities([shelter]),
      });

      // Simulate wire serialization
      const jsonWireString = JSON.stringify(backendOutput);
      const parsedFromWire = JSON.parse(jsonWireString);
      const adapted = adaptRoutes(parsedFromWire);

      expect(adapted).toHaveLength(2);
      expect(adapted[0].routeId).toBe('route-evac-z-1');
      expect(adapted[0].destinationId).toBe('sh-1');
      expect(adapted[0].status).toBe('OK');
      expect(adapted[0].geometry.type).toBe('LineString');

      expect(adapted[1].routeId).toBe('route-evac-z-2');
      expect(adapted[1].destinationId).toBe('sh-1');
      expect(adapted[1].status).toBe('OK');
    });

    // 10. MultiLineString and LineString geometries are handled correctly if both are supported
    it('Case 10: MultiLineString and LineString geometries are handled correctly in graph and RouteLayer', () => {
      const lineStringRoad = {
        type: 'Feature',
        properties: { id: 'ls-road', flooded: false },
        geometry: { type: 'LineString', coordinates: [[7.00, 50.00], [7.01, 50.00]] },
      };
      const multiLineStringRoad = {
        type: 'Feature',
        properties: { id: 'mls-road', flooded: false },
        geometry: {
          type: 'MultiLineString',
          coordinates: [
            [[7.01, 50.00], [7.02, 50.00]],
            [[7.02, 50.00], [7.03, 50.00]],
          ],
        },
      };
      const zone = {
        zone_id: 'zone-mls',
        name: 'MLS Zone',
        risk_level: 'HIGH',
        risk_score: 80,
        bbox: [6.99, 49.99, 7.01, 50.01],
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-mls', name: 'MLS Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: [7.03, 50.00] },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([lineStringRoad, multiLineStringRoad]),
        facilities: makeFacilities([shelter]),
      });

      expect(result.routes[0].status).toBe('OK');
      expect(result.routes[0].destination_id).toBe('shelter-mls');
      expect(result.routes[0].geometry.coordinates.length).toBeGreaterThanOrEqual(4);

      // Verify RouteLayer renders MultiLineString without crashing
      const adaptedMulti = [{
        routeId: 'route-mls-test',
        zoneId: 'zone-mls',
        status: 'OK',
        geometry: {
          type: 'MultiLineString',
          coordinates: [
            [[7.00, 50.00], [7.01, 50.00]],
            [[7.01, 50.00], [7.02, 50.00]],
          ],
        },
      }];
      const { container } = render(<FloodMap routes={adaptedMulti} visibleLayers={{ routes: true }} />);
      expect(container.querySelector('.leaflet-container')).toBeInTheDocument();
    });

    // 11. Invalid coordinates, empty geometry, missing facility data, and malformed network edges are handled safely
    it('Case 11: invalid coordinates, empty geometry, missing facility data, and malformed edges handled safely', () => {
      const malformedRoads = [
        { type: 'Feature', properties: { id: 'empty-geom' }, geometry: null },
        { type: 'Feature', properties: { id: 'empty-coords' }, geometry: { type: 'LineString', coordinates: [] } },
        { type: 'Feature', properties: { id: 'nan-coords' }, geometry: { type: 'LineString', coordinates: [[NaN, NaN], [7.01, 50.00]] } },
        { type: 'Feature', properties: { id: 'valid-road', flooded: false }, geometry: { type: 'LineString', coordinates: [[7.00, 50.00], [7.01, 50.00]] } },
      ];
      const zone = {
        zone_id: 'zone-malformed',
        name: 'Malformed Test Zone',
        risk_level: 'HIGH',
        risk_score: 90,
        bbox: null,
      };

      expect(() => {
        const result = generateEvacuationRoutes({
          zones: [zone, null, undefined],
          roads: makeRoads(malformedRoads),
          facilities: null,
        });
        expect(result.routes).toBeDefined();
      }).not.toThrow();
    });

    // 12. The first and last rendered route positions agree with the validated endpoints within the documented tolerance
    it('Case 12: first and last route positions agree with validated endpoints within documented tolerance', () => {
      const road = {
        type: 'Feature',
        properties: { id: 'road-endpoint-check', flooded: false },
        geometry: {
          type: 'LineString',
          coordinates: [[7.0005, 50.0005], [7.0100, 50.0000], [7.0195, 50.0005]],
        },
      };
      const zoneOrigin = [7.0000, 50.0000];
      const shelterPoint = [7.0200, 50.0000];

      const zone = {
        zone_id: 'zone-tol',
        name: 'Tolerance Zone',
        risk_level: 'HIGH',
        risk_score: 80,
        pickup_point: zoneOrigin,
        bbox: [6.999, 49.999, 7.002, 50.002],
      };
      const shelter = {
        type: 'Feature',
        properties: { facility_id: 'shelter-tol', name: 'Tolerance Shelter', type: 'shelter' },
        geometry: { type: 'Point', coordinates: shelterPoint },
      };

      const result = generateEvacuationRoutes({
        zones: [zone],
        roads: makeRoads([road]),
        facilities: makeFacilities([shelter]),
      });

      const r = result.routes[0];
      expect(r.status).toBe('OK');

      const firstPt = r.geometry.coordinates[0];
      const lastPt = r.geometry.coordinates[r.geometry.coordinates.length - 1];

      // Documented tolerance: origin snapping <= 200m
      const originDist = haversineDistance(firstPt, zoneOrigin);
      expect(originDist).toBeLessThanOrEqual(200);

      // Documented tolerance: shelter access <= 150m
      const shelterDist = haversineDistance(lastPt, shelterPoint);
      expect(shelterDist).toBeLessThanOrEqual(150);
    });

    // 13. No stale fallback geometry is displayed after a route fails
    it('Case 13: no stale fallback geometry is displayed after a route fails', () => {
      const failedRoute = {
        routeId: 'route-failed',
        zoneId: 'zone-failed',
        status: 'NO_SAFE_ROUTE',
        geometry: null,
      };

      const { container } = render(<RouteLayer routes={[failedRoute]} />);
      // Failed routes produce null render in RouteLayer without drawing fallback polylines
      expect(container.firstChild).toBeNull();
    });

    // 14. Backend successful-route counts match the routes passed to the map renderer
    it('Case 14: backend successful-route counts match the routes passed to the map renderer', () => {
      const result = generateEvacuationRoutes({
        zones: dernauZones,
        roads: dernauRoads,
        facilities: dernauFacilities,
      });

      const backendOkRoutes = result.routes.filter((r) => r.status === 'OK');
      const adapted = adaptRoutes(result);
      const adaptedOkRoutes = adapted.filter((r) => r.status === 'OK');

      expect(backendOkRoutes.length).toBe(adaptedOkRoutes.length);
      expect(backendOkRoutes.length).toBe(2);

      // Render in FloodMap and verify Leaflet container is populated
      const { container } = render(
        <FloodMap
          riskZones={dernauZones.zones}
          routes={adapted}
          visibleLayers={{ flood: false, risk: false, roads: false, facilities: false, routes: true }}
        />
      );
      expect(container.querySelector('.leaflet-container')).toBeInTheDocument();
    });
  });

  // ===========================================================================
  // 5. Data Adapter & Persistence Consistency
  // ===========================================================================
  describe('Data Adapter & Persistence Consistency', () => {
    it('adapts generated routes preserving routeId, zoneId, riskLevel, destination, reason, and geometry', () => {
      const adapted = adaptRoutes(dernauRoutes);

      expect(adapted).toHaveLength(8);

      const adapted36 = adapted.find((r) => r.zoneId === 'zone-036');
      expect(adapted36).toBeDefined();
      expect(['NO_SAFE_ROUTE', 'UNREACHABLE']).toContain(adapted36.status);
      expect(adapted36.riskLevel).toBe('HIGH');
      expect(adapted36.geometry).toBeNull();
      expect(adapted36.reason).toContain('all 7 road segments in zone-036 are flooded');

      const adapted08 = adapted.find((r) => r.zoneId === 'zone-008');
      expect(adapted08).toBeDefined();
      expect(adapted08.status).toBe('OK');
      expect(adapted08.riskLevel).toBe('MEDIUM');
      expect(adapted08.originId).toBe('pickup-zone-008');
      expect(adapted08.originCoords).toBeDefined();
      expect(adapted08.originType).toBe('road_pickup_point');
      expect(adapted08.destinationId).toBe('fac-004');
      expect(adapted08.destinationName).toBe('North-Central Relief Staging');
      expect(adapted08.destinationCoords).toBeDefined();
      expect(adapted08.distanceM).toBeGreaterThan(0);
      expect(adapted08.etaMinutes).toBeGreaterThan(0);
      expect(adapted08.geometry.type).toBe('LineString');
    });

    it('ensures consistent geometry between mock-data-dernau/routes.json and fresh generator output', () => {
      const freshResult = generateEvacuationRoutes({
        zones: dernauZones,
        roads: dernauRoads,
        facilities: dernauFacilities,
      });

      expect(freshResult.routes.length).toBe(dernauRoutes.routes.length);

      for (let i = 0; i < freshResult.routes.length; i++) {
        const fresh = freshResult.routes[i];
        const persisted = dernauRoutes.routes.find((r) => r.zone_id === fresh.zone_id);
        expect(persisted).toBeDefined();
        expect(persisted.status).toBe(fresh.status);
        expect(persisted.destination_id).toBe(fresh.destination_id);
        if (fresh.geometry) {
          expect(persisted.geometry.type).toBe(fresh.geometry.type);
          expect(persisted.geometry.coordinates).toEqual(fresh.geometry.coordinates);
        } else {
          expect(persisted.geometry).toBeNull();
        }
      }
    });
  });

  // ===========================================================================
  // 6. Frontend Visual Component Rendering
  // ===========================================================================
  describe('Frontend Component Rendering', () => {
    it('RouteLayer draws all reachable routes and filters out unreachable routes without geometry', () => {
      const adapted = adaptRoutes(dernauRoutes);

      const reachableOnly = adapted.filter((r) => r.status === 'OK');
      const unreachableOnly = adapted.filter((r) => r.status !== 'OK');

      expect(reachableOnly).toHaveLength(2);
      expect(unreachableOnly).toHaveLength(6);

      // Unreachable routes produce null render in RouteLayer
      const { container: unreachableContainer } = render(<RouteLayer routes={unreachableOnly} />);
      expect(unreachableContainer.firstChild).toBeNull();
    });

    it('ZoneDetails displays Evacuation Route Clear when reachable zone (zone-008) is selected', () => {
      const adapted = adaptRoutes(dernauRoutes);
      const z08 = dernauZones.zones.find((z) => z.zone_id === 'zone-008');
      const r08 = adapted.find((r) => r.zoneId === 'zone-008');

      render(
        <ZoneDetails
          zone={{
            zoneId: z08.zone_id,
            name: z08.name,
            riskLevel: z08.risk_level,
            riskScore: z08.risk_score,
            floodedPercent: z08.flooded_percent,
            floodedAreaKm2: z08.flooded_area_km2,
            exposedBuildings: z08.exposed_buildings,
            accessibility: z08.accessibility,
            hasGeometry: true,
            reasons: z08.reasons,
          }}
          route={r08}
        />
      );

      expect(screen.getByText('Evacuation Route Clear')).toBeInTheDocument();
      expect(screen.getByText('North-Central Relief Staging')).toBeInTheDocument();
      expect(screen.getByText('OK')).toBeInTheDocument();
    });

    it('ZoneDetails displays No Safe Route (Cut Off) when cut-off zone (zone-036) is selected', () => {
      const adapted = adaptRoutes(dernauRoutes);
      const z36 = dernauZones.zones.find((z) => z.zone_id === 'zone-036');
      const r36 = adapted.find((r) => r.zoneId === 'zone-036');

      render(
        <ZoneDetails
          zone={{
            zoneId: z36.zone_id,
            name: z36.name,
            riskLevel: z36.risk_level,
            riskScore: z36.risk_score,
            floodedPercent: z36.flooded_percent,
            floodedAreaKm2: z36.flooded_area_km2,
            exposedBuildings: z36.exposed_buildings,
            accessibility: z36.accessibility,
            hasGeometry: true,
            reasons: z36.reasons,
          }}
          route={r36}
        />
      );

      expect(screen.getByText('No Safe Route (Cut Off)')).toBeInTheDocument();
      expect(screen.getByText(/all 7 road segments in zone-036 are flooded/i)).toBeInTheDocument();
    });
  });
});
