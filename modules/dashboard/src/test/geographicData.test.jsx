import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import {
  DEFAULT_MAP_CENTER,
  DEFAULT_AOI_BOUNDS,
  DERNAU_MAP_CENTER,
  DERNAU_AOI_BOUNDS,
  BENGALURU_MAP_CENTER,
  BENGALURU_AOI_BOUNDS,
  computeDataBounds,
  verifyGeographicData,
  areCoordinatesLikelySwapped,
} from '../features/map/mapUtils.js';
import { adaptZones, adaptDashboardData } from '../data/dataAdapter.js';
import FloodMap from '../components/FloodMap.jsx';
import DashboardLayout from '../app/DashboardLayout.jsx';
import Header from '../components/Header.jsx';
import RiskLayer from '../features/map/RiskLayer.jsx';
import { MapContainer } from 'react-leaflet';

describe('Geographic Data Mismatch & Resolution Suite', () => {
  // --------------------------------------------------------------------------
  // 1. Map-Center Selection Tests
  // --------------------------------------------------------------------------
  describe('Map-Center & Extent Selection', () => {
    it('sets default map center and extent to Dernau, Germany (SpaceNet 8), never Bengaluru', () => {
      // Must center in Germany (lat ~50.52, lng ~7.03)
      expect(DEFAULT_MAP_CENTER[0]).toBeCloseTo(50.52, 1);
      expect(DEFAULT_MAP_CENTER[1]).toBeCloseTo(7.03, 1);
      expect(DEFAULT_MAP_CENTER).toEqual(DERNAU_MAP_CENTER);

      // Must NOT be Bengaluru (lat ~12.95, lng ~77.69)
      expect(DEFAULT_MAP_CENTER[0]).not.toBeCloseTo(12.95, 1);
      expect(DEFAULT_MAP_CENTER[1]).not.toBeCloseTo(77.69, 1);

      // Default bounds must encompass Dernau
      expect(DEFAULT_AOI_BOUNDS[0][0]).toBeCloseTo(50.51, 1);
      expect(DEFAULT_AOI_BOUNDS[0][1]).toBeCloseTo(7.01, 1);
      expect(DEFAULT_AOI_BOUNDS).toEqual(DERNAU_AOI_BOUNDS);
    });

    it('computes exact bounding box for SpaceNet 8 Dernau data', () => {
      const dernauZones = [
        {
          zoneId: 'zone-001',
          hasGeometry: true,
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [7.0318, 50.5114],
                [7.0362, 50.5114],
                [7.0362, 50.5142],
                [7.0318, 50.5142],
                [7.0318, 50.5114],
              ],
            ],
          },
        },
      ];

      const bounds = computeDataBounds(dernauZones);
      expect(bounds[0][0]).toBeCloseTo(50.5114, 3);
      expect(bounds[0][1]).toBeCloseTo(7.0318, 3);
      expect(bounds[1][0]).toBeCloseTo(50.5142, 3);
      expect(bounds[1][1]).toBeCloseTo(7.0362, 3);
    });

    it('supports raw Module 2 zones with bbox and centroid when geometry is absent', () => {
      const rawModule2Zones = [
        {
          zoneId: 'zone-001',
          hasGeometry: false,
          bbox: [7.0318, 50.5114, 7.0362, 50.5142],
          centroid: [7.0340, 50.5128],
        },
      ];

      const bounds = computeDataBounds(rawModule2Zones);
      expect(bounds[0][0]).toBeCloseTo(50.5114, 3);
      expect(bounds[0][1]).toBeCloseTo(7.0318, 3);
      expect(bounds[1][0]).toBeCloseTo(50.5142, 3);
      expect(bounds[1][1]).toBeCloseTo(7.0362, 3);
    });

    it('falls back to Bengaluru bounds only when studyArea explicitly requests Bengaluru and no data exists', () => {
      const bounds = computeDataBounds([], null, 'Bengaluru, Karnataka');
      expect(bounds).toEqual(BENGALURU_AOI_BOUNDS);
    });
  });

  // --------------------------------------------------------------------------
  // 2. Zone-to-Coordinate Matching Tests
  // --------------------------------------------------------------------------
  describe('Zone-to-Coordinate Matching', () => {
    it('synthesizes polygon geometry from Module 2 bbox [minLon, minLat, maxLon, maxLat]', () => {
      const rawModule2Payload = {
        source: 'SpaceNet 8 Germany (Dernau)',
        crs: 'EPSG:4326',
        zones: [
          {
            zone_id: 'zone-001',
            bbox: [7.0318, 50.5114, 7.0362, 50.5142],
            centroid: [7.0340, 50.5128],
            flooded_percent: 1.24,
            flooded_area_m2: 1114.4,
            exposed_buildings: 1,
            accessibility: 'PARTIAL',
          },
        ],
      };

      const { metadata, zones } = adaptZones(rawModule2Payload);
      expect(metadata.studyArea).toBe('Dernau (Ahr valley), Germany');
      expect(zones[0].hasGeometry).toBe(true);
      expect(zones[0].geometry.type).toBe('Polygon');
      expect(zones[0].geometry.coordinates[0]).toHaveLength(5);
      expect(zones[0].geometry.coordinates[0][0]).toEqual([7.0318, 50.5114]);
      expect(zones[0].geometry.coordinates[0][2]).toEqual([7.0362, 50.5142]);
      expect(zones[0].floodedAreaKm2).toBeCloseTo(0.0011, 4);
    });

    it('attaches Module 3 risk engine score and priority to matching zone_id', () => {
      const rawModule2Zones = {
        source: 'SpaceNet 8 Germany (Dernau)',
        zones: [
          {
            zone_id: 'zone-036',
            bbox: [7.035, 50.520, 7.040, 50.525],
            accessibility: 'BLOCKED',
          },
        ],
      };

      const rawModule3Output = {
        ranked_zones: [
          {
            zone_id: 'zone-036',
            score: 65.7,
            priority: 'HIGH',
            confidence: 'HIGH',
            explanation: 'High flood exposure along blocked access corridor',
          },
        ],
      };

      const adapted = adaptDashboardData({
        rawZones: rawModule2Zones,
        rawRiskScores: rawModule3Output,
      });

      expect(adapted.zones[0].zoneId).toBe('zone-036');
      expect(adapted.zones[0].riskScore).toBe(66); // Rounded from 65.7
      expect(adapted.zones[0].riskLevel).toBe('HIGH');
      expect(adapted.zones[0].confidence).toBe('HIGH');
      expect(adapted.zones[0].reasons).toContain('High flood exposure along blocked access corridor');
      expect(adapted.zones[0].hasGeometry).toBe(true);
    });

    it('never places flood-risk markers or polygons for non-spatial zones', () => {
      const nonSpatialZone = {
        zoneId: 'zone-009',
        name: 'Zone 009 - Survey Missing',
        riskLevel: 'LOW',
        riskScore: 10,
        hasGeometry: false,
        geometry: null,
      };

      const { container } = render(
        <MapContainer center={[50.52, 7.03]} zoom={14}>
          <RiskLayer zones={[nonSpatialZone]} />
        </MapContainer>
      );

      // No leaflet overlay path / polygon rendered for un-geometried zone
      const overlayPaths = container.querySelectorAll('.leaflet-overlay-pane svg path');
      expect(overlayPaths.length).toBe(0);
    });
  });

  // --------------------------------------------------------------------------
  // 3. Missing Geographic Data Tests
  // --------------------------------------------------------------------------
  describe('Missing Geographic Data Handling', () => {
    it('detects MISSING_GEOGRAPHY when no spatial coordinates exist', () => {
      const result = verifyGeographicData({
        zones: [{ zoneId: 'z1', hasGeometry: false, geometry: null }],
        floodGeoJSON: { type: 'FeatureCollection', features: [] },
        metadata: { studyArea: 'Unknown AOI' },
      });

      expect(result.status).toBe('MISSING_GEOGRAPHY');
      expect(result.isVerified).toBe(false);
      expect(result.warning).toMatch(/No geographic boundary data available/i);
    });

    it('renders geographic warning alert in DashboardLayout when geometry is missing', () => {
      const noGeoData = {
        metadata: {
          studyArea: 'Missing Extent Test',
          generatedAt: '2026-10-14T10:00:00Z',
          dataMode: 'live',
        },
        zones: [
          {
            zoneId: 'z1',
            name: 'No Geo Zone',
            riskLevel: 'HIGH',
            riskScore: 75,
            hasGeometry: false,
          },
        ],
        floodExtent: { type: 'FeatureCollection', features: [] },
        blockedRoads: { type: 'FeatureCollection', features: [] },
        facilities: { type: 'FeatureCollection', features: [] },
        routes: [],
      };

      render(<DashboardLayout data={noGeoData} onRefresh={vi.fn()} />);

      const alertBanner = screen.getByRole('alert', { name: 'Geographic Data Warning' });
      expect(alertBanner).toBeInTheDocument();
      expect(alertBanner).toHaveTextContent(/No geographic boundary data available/i);
    });
  });

  // --------------------------------------------------------------------------
  // 4. Geographic Mismatch Detection Tests
  // --------------------------------------------------------------------------
  describe('Geographic Mismatch Detection', () => {
    it('detects mismatch when coordinates are in Germany but studyArea is labeled Bengaluru', () => {
      const dernauZones = [
        {
          zoneId: 'z1',
          hasGeometry: true,
          geometry: {
            type: 'Polygon',
            coordinates: [[[7.03, 50.51], [7.04, 50.51], [7.04, 50.53], [7.03, 50.53], [7.03, 50.51]]],
          },
        },
      ];

      const result = verifyGeographicData({
        zones: dernauZones,
        floodGeoJSON: null,
        metadata: { studyArea: 'Bengaluru, Karnataka' },
      });

      expect(result.status).toBe('LOCATION_MISMATCH');
      expect(result.isVerified).toBe(false);
      expect(result.warning).toMatch(/Geographic mismatch detected/i);
      expect(result.warning).toMatch(/Dernau, Germany.*Bengaluru/i);
    });

    it('renders geographic mismatch warning in DashboardLayout when mismatch is present', () => {
      const mismatchedData = {
        metadata: {
          studyArea: 'Bengaluru, Karnataka',
          generatedAt: '2026-10-14T10:00:00Z',
          dataMode: 'live',
        },
        zones: [
          {
            zoneId: 'z1',
            name: 'Zone 1',
            riskLevel: 'HIGH',
            riskScore: 80,
            hasGeometry: true,
            geometry: {
              type: 'Polygon',
              coordinates: [[[7.03, 50.51], [7.04, 50.51], [7.04, 50.53], [7.03, 50.53], [7.03, 50.51]]],
            },
          },
        ],
        floodExtent: { type: 'FeatureCollection', features: [] },
        blockedRoads: { type: 'FeatureCollection', features: [] },
        facilities: { type: 'FeatureCollection', features: [] },
        routes: [],
      };

      render(<DashboardLayout data={mismatchedData} onRefresh={vi.fn()} />);

      const alertBanner = screen.getByRole('alert', { name: 'Geographic Data Warning' });
      expect(alertBanner).toBeInTheDocument();
      expect(alertBanner).toHaveTextContent(/Geographic mismatch detected/i);
    });
  });

  // --------------------------------------------------------------------------
  // 5. Historical and Simulated Data Labeling Tests
  // --------------------------------------------------------------------------
  describe('Historical & Simulated Data Labeling', () => {
    it('verifies SpaceNet 8 Dernau data as historical and renders historical event notice (not a live alert)', () => {
      const dernauData = {
        metadata: {
          studyArea: 'Dernau (Ahr valley), Germany',
          source: 'SpaceNet 8 Germany (Dernau)',
          generatedAt: '2026-10-14T10:00:00Z',
          dataMode: 'demo',
        },
        zones: [
          {
            zoneId: 'z1',
            name: 'Zone 1',
            riskLevel: 'LOW',
            riskScore: 12,
            hasGeometry: true,
            geometry: {
              type: 'Polygon',
              coordinates: [[[7.03, 50.51], [7.04, 50.51], [7.04, 50.53], [7.03, 50.53], [7.03, 50.51]]],
            },
          },
        ],
        floodExtent: { type: 'FeatureCollection', features: [] },
        blockedRoads: { type: 'FeatureCollection', features: [] },
        facilities: { type: 'FeatureCollection', features: [] },
        routes: [],
      };

      render(<DashboardLayout data={dernauData} onRefresh={vi.fn()} />);

      const historicalBanner = screen.getByRole('status', { name: 'Historical Event Notice' });
      expect(historicalBanner).toBeInTheDocument();
      expect(historicalBanner).toHaveTextContent(/HISTORICAL FLOOD DATA/i);
      expect(historicalBanner).toHaveTextContent(/not a live flood alert/i);
    });

    it('renders simulated scenario notice when data is synthetic demo data', () => {
      const simulatedData = {
        metadata: {
          studyArea: 'Bengaluru, Karnataka',
          generatedAt: '2026-10-14T10:00:00Z',
          dataMode: 'demo',
        },
        zones: [
          {
            zoneId: 'z1',
            name: 'Zone 1',
            riskLevel: 'MEDIUM',
            riskScore: 50,
            hasGeometry: true,
            geometry: {
              type: 'Polygon',
              coordinates: [[[77.65, 12.92], [77.69, 12.92], [77.69, 12.96], [77.65, 12.96], [77.65, 12.92]]],
            },
          },
        ],
        floodExtent: { type: 'FeatureCollection', features: [] },
        blockedRoads: { type: 'FeatureCollection', features: [] },
        facilities: { type: 'FeatureCollection', features: [] },
        routes: [],
      };

      render(<DashboardLayout data={simulatedData} onRefresh={vi.fn()} />);

      const simulatedBanner = screen.getByRole('status', { name: 'Simulated Scenario Notice' });
      expect(simulatedBanner).toBeInTheDocument();
      expect(simulatedBanner).toHaveTextContent(/SIMULATED SCENARIO/i);
      expect(simulatedBanner).toHaveTextContent(/Not a live flood alert/i);
    });

    it('renders Unverified location badge in Header when studyArea is unverified', () => {
      render(
        <Header
          studyArea="Unverified Study Area"
          dataMode="live"
        />
      );

      expect(screen.getByText('Unverified location')).toBeInTheDocument();
      expect(screen.getByRole('status', { name: 'Unverified location active' })).toBeInTheDocument();
    });
  });

  // --------------------------------------------------------------------------
  // 6. Coordinate Swapping Tests (India & Europe)
  // --------------------------------------------------------------------------
  describe('Coordinate Swapping Validation', () => {
    it('detects swapped coordinates for Western Europe / Germany', () => {
      // Swapped in Germany: lng = 50.51, lat = 7.03
      expect(areCoordinatesLikelySwapped(50.51, 7.03)).toBe(true);
      // Correct in Germany: lng = 7.03, lat = 50.51
      expect(areCoordinatesLikelySwapped(7.03, 50.51)).toBe(false);
    });

    it('detects swapped coordinates for India', () => {
      // Swapped in India: lng = 12.9, lat = 77.6
      expect(areCoordinatesLikelySwapped(12.9, 77.6)).toBe(true);
      // Correct in India: lng = 77.6, lat = 12.9
      expect(areCoordinatesLikelySwapped(77.6, 12.9)).toBe(false);
    });
  });
});
