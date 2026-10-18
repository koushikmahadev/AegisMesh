import { describe, it, expect } from 'vitest';
import { selectSummaryStats } from '../features/dashboard/dashboardSelectors.js';

describe('dashboardSelectors', () => {
  it('correctly calculates summary metrics from normalised zones', () => {
    const mockData = {
      metadata: { dataMode: 'demo' },
      zones: [
        { zoneId: 'z1', riskLevel: 'HIGH', floodedAreaKm2: 2.4, exposedBuildings: 30 },
        { zoneId: 'z2', riskLevel: 'MEDIUM', floodedAreaKm2: 1.1, exposedBuildings: 10 },
        { zoneId: 'z3', riskLevel: 'HIGH', floodedAreaKm2: 3.8, exposedBuildings: 60 },
        { zoneId: 'z4', riskLevel: 'UNKNOWN', floodedAreaKm2: null, exposedBuildings: null },
      ],
      blockedRoads: {
        features: [{ id: 'r1' }, { id: 'r2' }, { id: 'r3' }],
      },
    };

    const stats = selectSummaryStats(mockData);

    expect(stats.floodedAreaKm2).toBe(7.3); // 2.4 + 1.1 + 3.8
    expect(stats.highPriorityCount).toBe(2); // 2 HIGH zones
    expect(stats.exposedBuildingsCount).toBe(100); // 30 + 10 + 60
    expect(stats.blockedRoadsCount).toBe(3);
    expect(stats.isDemo).toBe(true);
    expect(stats.floodedAreaIsPartial).toBe(true);
    expect(stats.floodedMissingCount).toBe(1);
  });

  it('proves that null or missing numeric fields are never summed as 0 when all zones lack data', () => {
    const emptyNumericData = {
      metadata: { dataMode: 'demo' },
      zones: [
        { zoneId: 'z1', riskLevel: 'UNKNOWN', floodedAreaKm2: null, exposedBuildings: null },
        { zoneId: 'z2', riskLevel: 'UNKNOWN', floodedAreaKm2: null, exposedBuildings: null },
      ],
      blockedRoads: { features: [] },
    };

    const stats = selectSummaryStats(emptyNumericData);
    expect(stats.floodedAreaKm2).toBeNull();
    expect(stats.exposedBuildingsCount).toBeNull();
    // Must never return 0
    expect(stats.floodedAreaKm2).not.toBe(0);
    expect(stats.exposedBuildingsCount).not.toBe(0);
  });

  it('proves partial datasets calculate verified sum and flag missing zones without treating null as 0', () => {
    const partialData = {
      metadata: { dataMode: 'demo' },
      zones: [
        { zoneId: 'z1', riskLevel: 'HIGH', floodedAreaKm2: 2.0, exposedBuildings: 10 },
        { zoneId: 'z2', riskLevel: 'UNKNOWN', floodedAreaKm2: null, exposedBuildings: null },
        { zoneId: 'z3', riskLevel: 'UNKNOWN', floodedAreaKm2: null, exposedBuildings: null },
      ],
      blockedRoads: { features: [] },
    };

    const stats = selectSummaryStats(partialData);
    expect(stats.floodedAreaKm2).toBe(2.0);
    expect(stats.floodedAreaIsPartial).toBe(true);
    expect(stats.floodedMissingCount).toBe(2);
    expect(stats.exposedBuildingsCount).toBe(10);
    expect(stats.exposedBuildingsIsPartial).toBe(true);
    expect(stats.bldgsMissingCount).toBe(2);
  });

  it('returns nulls when dataset is empty or undefined', () => {
    const nullStats = selectSummaryStats(null);
    expect(nullStats.floodedAreaKm2).toBeNull();
    expect(nullStats.highPriorityCount).toBeNull();
    expect(nullStats.exposedBuildingsCount).toBeNull();
    expect(nullStats.blockedRoadsCount).toBeNull();

    const emptyStats = selectSummaryStats({ zones: [] });
    expect(emptyStats.floodedAreaKm2).toBeNull();
    expect(emptyStats.highPriorityCount).toBeNull();
  });

  it('correctly calculates FloodWatch observed and derived counts and chart data', () => {
    const floodwatchData = {
      metadata: { dataSource: 'mock-floodwatch', dataMode: 'demo' },
      zones: [
        { zoneId: '0_41_58', name: 'Tile 0_41_58', riskLevel: 'UNKNOWN', exposedBuildings: 169, observed_flooded_count: 181 },
        { zoneId: '0_23_62', name: 'Tile 0_23_62', riskLevel: 'UNKNOWN', exposedBuildings: 94, observed_flooded_count: 101 },
      ],
      floodPredictedFast: {
        features: [
          { properties: { tile_id: '0_41_58', mask_pixels: 5000 } },
          { properties: { tile_id: '0_23_62', mask_pixels: 1200 } },
        ],
      },
      floodPredictedAccurate: {
        features: [
          { properties: { tile_id: '0_41_58', mask_pixels: 6000 } },
          { properties: { tile_id: '0_23_62', mask_pixels: 1500 } },
        ],
      },
    };

    const stats = selectSummaryStats(floodwatchData);
    expect(stats.observedBuildingsCount).toBe(263); // 169 + 94
    expect(stats.observedRoadsCount).toBe(19); // (181 - 169) + (101 - 94) = 12 + 7
    expect(stats.modelMaskPixelsFast).toBe(6200); // 5000 + 1200
    expect(stats.modelMaskPixelsAccurate).toBe(7500); // 6000 + 1500
  });
});
