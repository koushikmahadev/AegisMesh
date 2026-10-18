import { describe, it, expect } from 'vitest';
import {
  normalizeNumber,
  normalizeRiskLevel,
  normalizeRiskScore,
  isValidLngLat,
  isClosedRing,
  adaptZones,
  adaptDashboardData,
  adaptFloodWatchFeature,
  adaptFloodWatchCollection,
} from '../data/dataAdapter.js';

describe('dataAdapter', () => {
  describe('normalizeNumber', () => {
    it('returns finite numbers unchanged', () => {
      expect(normalizeNumber(42)).toBe(42);
      expect(normalizeNumber(0)).toBe(0);
      expect(normalizeNumber(-3.14)).toBe(-3.14);
    });

    it('parses valid numeric strings', () => {
      expect(normalizeNumber('12.4')).toBe(12.4);
    });

    it('returns null for non-finite values and non-numbers', () => {
      expect(normalizeNumber(NaN)).toBeNull();
      expect(normalizeNumber(Infinity)).toBeNull();
      expect(normalizeNumber(undefined)).toBeNull();
      expect(normalizeNumber(null)).toBeNull();
      expect(normalizeNumber('invalid')).toBeNull();
    });
  });

  describe('normalizeRiskLevel', () => {
    it('preserves HIGH, MEDIUM, LOW', () => {
      expect(normalizeRiskLevel('HIGH')).toBe('HIGH');
      expect(normalizeRiskLevel('medium')).toBe('MEDIUM');
      expect(normalizeRiskLevel('low ')).toBe('LOW');
    });

    it('converts unknown or missing risk to UNKNOWN (never LOW)', () => {
      expect(normalizeRiskLevel('CRITICAL')).toBe('UNKNOWN');
      expect(normalizeRiskLevel('')).toBe('UNKNOWN');
      expect(normalizeRiskLevel(null)).toBe('UNKNOWN');
      expect(normalizeRiskLevel(undefined)).toBe('UNKNOWN');
      expect(normalizeRiskLevel(123)).toBe('UNKNOWN');
    });
  });

  describe('normalizeRiskScore', () => {
    it('normalises 0.0 - 1.0 scale to 0 - 100', () => {
      expect(normalizeRiskScore(0.85)).toEqual({ score: 85, originalScale: '0-1' });
      expect(normalizeRiskScore(0.32)).toEqual({ score: 32, originalScale: '0-1' });
    });

    it('preserves 0 - 100 scores', () => {
      expect(normalizeRiskScore(82)).toEqual({ score: 82, originalScale: '0-100' });
      expect(normalizeRiskScore(0)).toEqual({ score: 0, originalScale: '0-100' });
      expect(normalizeRiskScore(100)).toEqual({ score: 100, originalScale: '0-100' });
    });

    it('returns null for missing or invalid scores', () => {
      expect(normalizeRiskScore(null)).toEqual({ score: null });
      expect(normalizeRiskScore(undefined)).toEqual({ score: null });
      expect(normalizeRiskScore('bad')).toEqual({ score: null });
      expect(normalizeRiskScore(150)).toEqual({ score: null });
    });
  });

  describe('Geospatial validations', () => {
    it('validates [lng, lat] coordinate limits', () => {
      expect(isValidLngLat([77.6, 12.9])).toBe(true);
      expect(isValidLngLat([181, 12.9])).toBe(false);
      expect(isValidLngLat([77.6, 95])).toBe(false);
      expect(isValidLngLat(['bad', 12.9])).toBe(false);
    });

    it('verifies closed polygon linear rings', () => {
      const closed = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]];
      const open = [[0, 0], [1, 0], [1, 1], [0, 1]];
      expect(isClosedRing(closed)).toBe(true);
      expect(isClosedRing(open)).toBe(false);
    });
  });

  describe('adaptZones & adaptDashboardData', () => {
    it('throws descriptive error on malformed payload', () => {
      expect(() => adaptZones(null)).toThrow('Invalid zones payload');
      expect(() => adaptZones({})).toThrow('missing "zones" array');
    });

    it('adapts zones with missing fields and non-spatial zones', () => {
      const rawPayload = {
        schema_version: '1.0',
        data_mode: 'demo',
        study_area: 'Bengaluru',
        zones: [
          {
            zone_id: 'z1',
            name: 'Spatial High',
            risk_level: 'HIGH',
            risk_score: 82,
            flooded_percent: 68,
            geometry: {
              type: 'Polygon',
              coordinates: [[[77.6, 12.9], [77.7, 12.9], [77.7, 13.0], [77.6, 13.0], [77.6, 12.9]]],
            },
          },
          {
            zone_id: 'z2',
            name: 'Non-spatial Missing Numeric',
            risk_level: 'UNKNOWN',
            risk_score: null,
            flooded_percent: null,
            geometry: null,
          },
        ],
      };

      const { metadata, zones } = adaptZones(rawPayload);
      expect(metadata.dataMode).toBe('demo');
      expect(zones).toHaveLength(2);

      expect(zones[0].hasGeometry).toBe(true);
      expect(zones[0].riskLevel).toBe('HIGH');
      expect(zones[0].riskScore).toBe(82);

      expect(zones[1].hasGeometry).toBe(false);
      expect(zones[1].riskLevel).toBe('UNKNOWN');
      expect(zones[1].riskScore).toBeNull();
      expect(zones[1].floodedPercent).toBeNull();
      expect(zones[1].partialData).toBe(true);
    });

    it('keeps risk level and sets partialData flag when risk_level is supplied but other numeric fields are null', () => {
      const payload = {
        schema_version: '1.0',
        data_mode: 'demo',
        zones: [
          {
            zone_id: 'z-partial',
            name: 'High Risk Partial',
            risk_level: 'HIGH',
            risk_score: 91,
            flooded_percent: 45.2,
            flooded_area_km2: 1.2,
            exposed_buildings: null, // one numeric field null
          },
          {
            zone_id: 'z-missing-score',
            name: 'Supplied Risk but Missing Score',
            risk_level: 'MEDIUM',
            risk_score: null,
            flooded_percent: 20.0,
            flooded_area_km2: 0.5,
            exposed_buildings: 10,
          },
          {
            zone_id: 'z-invalid-risk',
            name: 'Invalid Risk Level',
            risk_level: 'CRITICAL', // invalid level
            risk_score: 85,
            flooded_percent: 50.0,
            flooded_area_km2: 1.0,
            exposed_buildings: 25,
          },
          {
            zone_id: 'z-complete',
            name: 'Complete Data',
            risk_level: 'LOW',
            risk_score: 25,
            flooded_percent: 5.0,
            flooded_area_km2: 0.1,
            exposed_buildings: 3,
          },
        ],
      };

      const { zones } = adaptZones(payload);

      // z-partial keeps HIGH risk_level and 91 score, but has partialData flag true
      expect(zones[0].riskLevel).toBe('HIGH');
      expect(zones[0].riskScore).toBe(91);
      expect(zones[0].partialData).toBe(true);

      // z-missing-score has missing score -> forces UNKNOWN and riskScore null
      expect(zones[1].riskLevel).toBe('UNKNOWN');
      expect(zones[1].riskScore).toBeNull();

      // z-invalid-risk has invalid risk level -> forces UNKNOWN
      expect(zones[2].riskLevel).toBe('UNKNOWN');
      expect(zones[2].riskScore).toBe(85);

      // z-complete has all fields present -> partialData is false
      expect(zones[3].riskLevel).toBe('LOW');
      expect(zones[3].riskScore).toBe(25);
      expect(zones[3].partialData).toBe(false);
    });

    it('treats only boolean true as needsSurvey and passes confidence, provenance, rank_p10, rank_p90 through explicitly', () => {
      const payload = {
        schema_version: '1.0',
        data_mode: 'demo',
        zones: [
          {
            zone_id: 'z-strict-true',
            risk_level: 'HIGH',
            risk_score: 80,
            needs_survey: true,
            confidence: 0.942, // as supplied, no rescaling
            provenance: 'observed',
            rank_p10: 2,
            rank_p90: 8,
          },
          {
            zone_id: 'z-string-coercion',
            risk_level: 'HIGH',
            risk_score: 80,
            needs_survey: 'true', // string must NOT coerce to true
            confidence: 0.1, // low confidence must NOT derive needsSurvey
          },
          {
            zone_id: 'z-number-coercion',
            risk_level: 'HIGH',
            risk_score: 80,
            needs_survey: 1, // number 1 must NOT coerce to true
          },
          {
            zone_id: 'z-missing-fields',
            risk_level: 'LOW',
            risk_score: 20,
            // confidence, provenance, rank_p10, rank_p90, needs_survey omitted
          },
        ],
      };

      const { zones } = adaptZones(payload);

      // z-strict-true
      expect(zones[0].needsSurvey).toBe(true);
      expect(zones[0].confidence).toBe(0.942); // exact pass-through, no rescaling
      expect(zones[0].provenance).toBe('observed');
      expect(zones[0].rank_p10).toBe(2);
      expect(zones[0].rank_p90).toBe(8);

      // z-string-coercion
      expect(zones[1].needsSurvey).toBe(false);
      expect(zones[1].confidence).toBe(0.1);

      // z-number-coercion
      expect(zones[2].needsSurvey).toBe(false);

      // z-missing-fields: missing values are null, not defaulted or inferred
      expect(zones[3].needsSurvey).toBe(false);
      expect(zones[3].confidence).toBeNull();
      expect(zones[3].provenance).toBeNull();
      expect(zones[3].rank_p10).toBeNull();
      expect(zones[3].rank_p90).toBeNull();
    });
  });

  describe('FloodWatch Adapters', () => {
    it('validates polygon coordinates and ring closure', () => {
      const validPolygon = {
        type: 'Feature',
        id: 'poly-1',
        properties: {
          tile_id: '0_41_58',
          mode: 'accurate',
          provenance: 'derived',
          mask_pixels: 450,
          in_training_pool: true,
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[[7.0, 50.5], [7.1, 50.5], [7.1, 50.6], [7.0, 50.6], [7.0, 50.5]]],
        },
      };

      const dropped = [];
      const adapted = adaptFloodWatchFeature(validPolygon, (msg) => dropped.push(msg));
      expect(adapted).not.toBeNull();
      expect(adapted.id).toBe('poly-1');
      expect(adapted.properties.tile_id).toBe('0_41_58');
      expect(adapted.properties.mode).toBe('accurate');
      expect(adapted.properties.provenance).toBe('derived');
      expect(adapted.properties.mask_pixels).toBe(450);
      expect(adapted.properties.in_training_pool).toBe(true);
      expect(adapted.properties.feature_type).toBeNull(); // missing stays null
      expect(dropped).toHaveLength(0);
    });

    it('validates LineString coordinates and passes observed provenance', () => {
      const validLine = {
        type: 'Feature',
        id: 'line-1',
        properties: {
          tile_id: '0_41_58',
          feature_type: 'road',
          provenance: 'observed',
          flooded: 'yes',
          in_training_pool: true,
        },
        geometry: {
          type: 'LineString',
          coordinates: [[7.0, 50.5], [7.05, 50.55]],
        },
      };

      const dropped = [];
      const adapted = adaptFloodWatchFeature(validLine, (msg) => dropped.push(msg));
      expect(adapted).not.toBeNull();
      expect(adapted.id).toBe('line-1');
      expect(adapted.properties.feature_type).toBe('road');
      expect(adapted.properties.provenance).toBe('observed');
      expect(adapted.properties.mode).toBeNull(); // missing stays null
      expect(adapted.properties.mask_pixels).toBeNull(); // missing stays null
      expect(dropped).toHaveLength(0);
    });

    it('drops invalid geometries and records reasons', () => {
      const dropped = [];
      const onDrop = (reason) => dropped.push(reason);

      // Unclosed ring
      const unclosed = {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [[[7.0, 50.5], [7.1, 50.5], [7.1, 50.6]]],
        },
      };
      expect(adaptFloodWatchFeature(unclosed, onDrop)).toBeNull();

      // Invalid coordinates
      const badCoords = {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [[[200.0, 50.5], [7.1, 50.5], [7.1, 50.6], [7.0, 50.6], [200.0, 50.5]]],
        },
      };
      expect(adaptFloodWatchFeature(badCoords, onDrop)).toBeNull();

      // Unsupported geometry type
      const point = {
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: [7.0, 50.5],
        },
      };
      expect(adaptFloodWatchFeature(point, onDrop)).toBeNull();

      expect(dropped).toHaveLength(3);
    });

    it('adapts valid MultiPolygon and MultiLineString geometries without dropping', () => {
      const dropped = [];
      const onDrop = (reason) => dropped.push(reason);

      const multiPolygon = {
        type: 'Feature',
        id: 'mp1',
        properties: { tile_id: '0_41_58', feature_type: 'building' },
        geometry: {
          type: 'MultiPolygon',
          coordinates: [
            [[[7.0, 50.5], [7.1, 50.5], [7.1, 50.6], [7.0, 50.6], [7.0, 50.5]]],
            [[[7.2, 50.5], [7.3, 50.5], [7.3, 50.6], [7.2, 50.6], [7.2, 50.5]]],
          ],
        },
      };

      const multiLineString = {
        type: 'Feature',
        id: 'mls1',
        properties: { tile_id: '0_41_58', feature_type: 'road' },
        geometry: {
          type: 'MultiLineString',
          coordinates: [
            [[7.0, 50.5], [7.1, 50.5]],
            [[7.2, 50.6], [7.3, 50.6], [7.4, 50.7]],
          ],
        },
      };

      const adaptedMP = adaptFloodWatchFeature(multiPolygon, onDrop, 'observed');
      expect(adaptedMP).not.toBeNull();
      expect(adaptedMP.geometry.type).toBe('MultiPolygon');
      expect(adaptedMP.properties.feature_type).toBe('building');

      const adaptedMLS = adaptFloodWatchFeature(multiLineString, onDrop, 'observed');
      expect(adaptedMLS).not.toBeNull();
      expect(adaptedMLS.geometry.type).toBe('MultiLineString');
      expect(adaptedMLS.properties.feature_type).toBe('road');

      expect(dropped).toHaveLength(0);
    });

    it('drops invalid MultiPolygon and MultiLineString geometries', () => {
      const dropped = [];
      const onDrop = (reason) => dropped.push(reason);

      const badMPUnclosed = {
        type: 'Feature',
        id: 'bad-mp',
        geometry: {
          type: 'MultiPolygon',
          coordinates: [
            [[[7.0, 50.5], [7.1, 50.5], [7.1, 50.6]]],
          ],
        },
      };
      expect(adaptFloodWatchFeature(badMPUnclosed, onDrop)).toBeNull();

      const badMLSShort = {
        type: 'Feature',
        id: 'bad-mls',
        geometry: {
          type: 'MultiLineString',
          coordinates: [
            [[7.0, 50.5]], // only 1 point
          ],
        },
      };
      expect(adaptFloodWatchFeature(badMLSShort, onDrop)).toBeNull();

      expect(dropped).toHaveLength(2);
    });

    it('uses defaultProvenance fallback only when provenance is undefined', () => {
      const featureWithoutProvenance = {
        type: 'Feature',
        properties: { tile_id: '0_15_63' },
        geometry: {
          type: 'Polygon',
          coordinates: [[[7.0, 50.5], [7.1, 50.5], [7.1, 50.6], [7.0, 50.6], [7.0, 50.5]]],
        },
      };

      const adaptedObserved = adaptFloodWatchFeature(featureWithoutProvenance, () => {}, 'observed');
      expect(adaptedObserved.properties.provenance).toBe('observed');

      const adaptedDerived = adaptFloodWatchFeature(featureWithoutProvenance, () => {}, 'derived');
      expect(adaptedDerived.properties.provenance).toBe('derived');
    });

    it('adaptFloodWatchCollection adapts collection, ignores invalid features and counts dropped', () => {
      const rawCollection = {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            id: 'f1',
            properties: { tile_id: '0_41_58' },
            geometry: {
              type: 'Polygon',
              coordinates: [[[7.0, 50.5], [7.1, 50.5], [7.1, 50.6], [7.0, 50.6], [7.0, 50.5]]],
            },
          },
          {
            type: 'Feature',
            id: 'bad',
            geometry: {
              type: 'Polygon',
              coordinates: [[[7.0, 50.5], [7.1, 50.5]]], // unclosed / invalid
            },
          },
        ],
      };

      let dropCount = 0;
      const res = adaptFloodWatchCollection(rawCollection, () => { dropCount += 1; }, 'derived');
      expect(res.type).toBe('FeatureCollection');
      expect(res.features).toHaveLength(1);
      expect(res.features[0].id).toBe('f1');
      expect(dropCount).toBe(1);
    });
  });
});
