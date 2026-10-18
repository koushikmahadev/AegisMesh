import { describe, it, expect } from 'vitest';
import { filterZones, sortZones } from '../features/zones/zoneUtils.js';

describe('zoneUtils (T4.4, test matrix #4, #5, #6)', () => {
  const sampleZones = [
    { zoneId: 'zone-001', name: 'Alpha Basin', riskLevel: 'HIGH', riskScore: 85, exposedBuildings: 40 },
    { zoneId: 'zone-002', name: 'Beta Ridge', riskLevel: 'MEDIUM', riskScore: 60, exposedBuildings: 25 },
    { zoneId: 'zone-003', name: 'Gamma Valley', riskLevel: 'LOW', riskScore: 30, exposedBuildings: 10 },
    { zoneId: 'zone-004', name: 'Delta Heights', riskLevel: 'UNKNOWN', riskScore: null, exposedBuildings: null },
    { zoneId: 'zone-005', name: 'Epsilon Park', riskLevel: 'HIGH', riskScore: 92, exposedBuildings: null },
  ];

  describe('filterZones (FR-22, FR-23, test matrix #4, #5)', () => {
    it('returns all zones when filter is ALL and search is empty', () => {
      const result = filterZones(sampleZones, { riskLevel: 'ALL', search: '' });
      expect(result).toHaveLength(5);
    });

    it('filters strictly by risk level (test matrix #4)', () => {
      const highOnly = filterZones(sampleZones, { riskLevel: 'HIGH' });
      expect(highOnly).toHaveLength(2);
      expect(highOnly.map((z) => z.zoneId)).toEqual(['zone-001', 'zone-005']);

      const unknownOnly = filterZones(sampleZones, { riskLevel: 'UNKNOWN' });
      expect(unknownOnly).toHaveLength(1);
      expect(unknownOnly[0].zoneId).toBe('zone-004');
    });

    it('filters by search keyword matching zoneId or name (test matrix #5)', () => {
      const byName = filterZones(sampleZones, { search: 'beta' });
      expect(byName).toHaveLength(1);
      expect(byName[0].zoneId).toBe('zone-002');

      const byId = filterZones(sampleZones, { search: '003' });
      expect(byId).toHaveLength(1);
      expect(byId[0].zoneId).toBe('zone-003');
    });

    it('combines risk level and search keyword correctly', () => {
      const combined = filterZones(sampleZones, { riskLevel: 'HIGH', search: 'Alpha' });
      expect(combined).toHaveLength(1);
      expect(combined[0].zoneId).toBe('zone-001');

      const noMatch = filterZones(sampleZones, { riskLevel: 'LOW', search: 'Alpha' });
      expect(noMatch).toHaveLength(0);
    });

    it('handles null, undefined or non-array gracefully', () => {
      expect(filterZones(null)).toEqual([]);
      expect(filterZones(undefined)).toEqual([]);
      expect(filterZones([])).toEqual([]);
    });
  });

  describe('sortZones (FR-22, test matrix #6)', () => {
    it('sorts by score descending and puts null scores last (test matrix #6)', () => {
      const sorted = sortZones(sampleZones, 'score');
      const scores = sorted.map((z) => z.riskScore);
      expect(scores).toEqual([92, 85, 60, 30, null]);
    });

    it('sorts by exposed buildings descending and puts null values last', () => {
      const sorted = sortZones(sampleZones, 'buildings');
      const bldgs = sorted.map((z) => z.exposedBuildings);
      expect(bldgs.slice(0, 3)).toEqual([40, 25, 10]);
      // The last two should be null
      expect(bldgs[3]).toBeNull();
      expect(bldgs[4]).toBeNull();
    });

    it('sorts by priority (HIGH > MEDIUM > LOW > UNKNOWN, tie-break score)', () => {
      const sorted = sortZones(sampleZones, 'priority');
      expect(sorted[0].zoneId).toBe('zone-005'); // HIGH (score 92)
      expect(sorted[1].zoneId).toBe('zone-001'); // HIGH (score 85)
      expect(sorted[2].zoneId).toBe('zone-002'); // MEDIUM (score 60)
      expect(sorted[3].zoneId).toBe('zone-003'); // LOW (score 30)
      expect(sorted[4].zoneId).toBe('zone-004'); // UNKNOWN
    });

    it('sorts by name alphabetically', () => {
      const sorted = sortZones(sampleZones, 'name');
      const names = sorted.map((z) => z.name);
      expect(names).toEqual([
        'Alpha Basin',
        'Beta Ridge',
        'Delta Heights',
        'Epsilon Park',
        'Gamma Valley',
      ]);
    });

    it('handles non-array input safely', () => {
      expect(sortZones(null)).toEqual([]);
      expect(sortZones(undefined)).toEqual([]);
    });
  });
});
