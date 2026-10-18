import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const fixturesDir = path.resolve(__dirname, '../../public/mock-data');

function readJsonFixture(filename) {
  const filePath = path.join(fixturesDir, filename);
  const content = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(content);
}

describe('Fixture Validation against architecture.md section 5', () => {
  const zonesData = readJsonFixture('zones.json');
  const floodData = readJsonFixture('flood_extent.geojson');
  const roadsData = readJsonFixture('blocked_roads.geojson');
  const facilitiesData = readJsonFixture('facilities.geojson');
  const routesData = readJsonFixture('routes.json');

  it('validates zones.json has data_mode = "demo"', () => {
    expect(zonesData.data_mode).toBe('demo');
  });

  it('proves zones.json contains at least one HIGH, MEDIUM, LOW, and UNKNOWN zone', () => {
    const riskLevels = zonesData.zones.map((z) => z.risk_level);
    expect(riskLevels).toContain('HIGH');
    expect(riskLevels).toContain('MEDIUM');
    expect(riskLevels).toContain('LOW');
    expect(riskLevels).toContain('UNKNOWN');

    const highZones = zonesData.zones.filter((z) => z.risk_level === 'HIGH');
    const medZones = zonesData.zones.filter((z) => z.risk_level === 'MEDIUM');
    const lowZones = zonesData.zones.filter((z) => z.risk_level === 'LOW');
    const unkZones = zonesData.zones.filter((z) => z.risk_level === 'UNKNOWN');

    expect(highZones.length).toBeGreaterThanOrEqual(1);
    expect(medZones.length).toBeGreaterThanOrEqual(1);
    expect(lowZones.length).toBeGreaterThanOrEqual(1);
    expect(unkZones.length).toBeGreaterThanOrEqual(1);
  });

  it('proves zones.json contains at least one zone with no geometry (zone-009)', () => {
    const noGeomZones = zonesData.zones.filter((z) => z.geometry === null);
    expect(noGeomZones.length).toBeGreaterThanOrEqual(1);
    const nonSpatial = zonesData.zones.find((z) => z.zone_id === 'zone-009');
    expect(nonSpatial).toBeDefined();
    expect(nonSpatial.geometry).toBeNull();
  });

  it('proves zones.json contains at least one zone with missing numeric fields (zone-004)', () => {
    const missingNumeric = zonesData.zones.find((z) => z.zone_id === 'zone-004');
    expect(missingNumeric).toBeDefined();
    expect(missingNumeric.risk_score).toBeNull();
    expect(missingNumeric.flooded_percent).toBeNull();
    expect(missingNumeric.flooded_area_km2).toBeNull();
    expect(missingNumeric.exposed_buildings).toBeNull();
  });

  it('proves all polygon rings in zones.json are closed and in [lng, lat] order', () => {
    const spatialZones = zonesData.zones.filter((z) => z.geometry !== null);
    expect(spatialZones.length).toBeGreaterThan(0);

    for (const zone of spatialZones) {
      expect(zone.geometry.type).toBe('Polygon');
      for (const ring of zone.geometry.coordinates) {
        expect(ring.length).toBeGreaterThanOrEqual(4);
        const first = ring[0];
        const last = ring[ring.length - 1];
        // Closed ring check
        expect(first[0]).toBe(last[0]);
        expect(first[1]).toBe(last[1]);

        // [lng, lat] coordinate limits and Bengaluru ordering (lng ~77.6, lat ~12.9)
        for (const [lng, lat] of ring) {
          expect(lng).toBeGreaterThanOrEqual(-180);
          expect(lng).toBeLessThanOrEqual(180);
          expect(lat).toBeGreaterThanOrEqual(-90);
          expect(lat).toBeLessThanOrEqual(90);
          expect(lng).toBeGreaterThan(70); // Bengaluru longitude is ~77
          expect(lat).toBeLessThan(20);    // Bengaluru latitude is ~12-13
        }
      }
    }
  });

  it('proves flood_extent.geojson features are closed polygons in [lng, lat] order', () => {
    expect(floodData.type).toBe('FeatureCollection');
    expect(floodData.features.length).toBeGreaterThan(0);

    for (const feature of floodData.features) {
      expect(feature.geometry.type).toBe('Polygon');
      for (const ring of feature.geometry.coordinates) {
        expect(ring.length).toBeGreaterThanOrEqual(4);
        const first = ring[0];
        const last = ring[ring.length - 1];
        expect(first[0]).toBe(last[0]);
        expect(first[1]).toBe(last[1]);
        for (const [lng, lat] of ring) {
          expect(lng).toBeGreaterThan(70);
          expect(lat).toBeLessThan(20);
        }
      }
    }
  });

  it('proves blocked_roads.geojson features are LineStrings in [lng, lat] order', () => {
    expect(roadsData.type).toBe('FeatureCollection');
    expect(roadsData.features.length).toBeGreaterThan(0);

    for (const feature of roadsData.features) {
      expect(feature.geometry.type).toBe('LineString');
      for (const [lng, lat] of feature.geometry.coordinates) {
        expect(lng).toBeGreaterThan(70);
        expect(lat).toBeLessThan(20);
      }
    }
  });

  it('proves facilities.geojson features are Points in [lng, lat] order', () => {
    expect(facilitiesData.type).toBe('FeatureCollection');
    expect(facilitiesData.features.length).toBeGreaterThan(0);

    for (const feature of facilitiesData.features) {
      expect(feature.geometry.type).toBe('Point');
      const [lng, lat] = feature.geometry.coordinates;
      expect(lng).toBeGreaterThan(70);
      expect(lat).toBeLessThan(20);
    }
  });

  it('proves routes.json contains valid routes and handles unreachable status', () => {
    expect(Array.isArray(routesData.routes)).toBe(true);
    expect(routesData.routes.length).toBeGreaterThan(0);

    const reachable = routesData.routes.find((r) => r.status === 'OK');
    expect(reachable).toBeDefined();
    expect(reachable.geometry.type).toBe('LineString');
    for (const [lng, lat] of reachable.geometry.coordinates) {
      expect(lng).toBeGreaterThan(70);
      expect(lat).toBeLessThan(20);
    }

    const unreachable = routesData.routes.find((r) => r.status === 'UNREACHABLE');
    expect(unreachable).toBeDefined();
    expect(unreachable.geometry).toBeNull();
  });
});
