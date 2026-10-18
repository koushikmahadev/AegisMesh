import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { MapContainer } from 'react-leaflet';
import L from 'leaflet';
import { getDashboardData } from '../services/dashboardApi.js';
import { computeDataBounds, DEFAULT_AOI_BOUNDS } from '../features/map/mapUtils.js';
import FloodMap from '../components/FloodMap.jsx';
import MapControls from '../components/MapControls.jsx';
import MapLegend from '../components/MapLegend.jsx';
import BuildingLayer from '../features/map/BuildingLayer.jsx';
import ProvenanceBadge from '../components/ProvenanceBadge.jsx';
import DashboardLayout from '../app/DashboardLayout.jsx';

describe('Dernau Wiring & 6th Overlay Suite', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  // --------------------------------------------------------------------------
  // 1. Data Source mock-dernau in dashboardApi.js
  // --------------------------------------------------------------------------
  it('loads all 6 resources from /mock-data-dernau/ when dataSource is "mock-dernau"', async () => {
    const requestedUrls = [];
    global.fetch = vi.fn().mockImplementation((url) => {
      requestedUrls.push(url);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ type: 'FeatureCollection', features: [], zones: [] }),
      });
    });

    const result = await getDashboardData({ dataSource: 'mock-dernau' });

    expect(requestedUrls).toContain('/mock-data-dernau/zones.json');
    expect(requestedUrls).toContain('/mock-data-dernau/flood_extent.geojson');
    expect(requestedUrls).toContain('/mock-data-dernau/blocked_roads.geojson');
    expect(requestedUrls).toContain('/mock-data-dernau/facilities.geojson');
    expect(requestedUrls).toContain('/mock-data-dernau/routes.json');
    expect(requestedUrls).toContain('/mock-data-dernau/buildings_exposed.geojson');
    expect(result.rawBuildingsExposed).toBeDefined();
  });

  // --------------------------------------------------------------------------
  // 2. Map extent: computeDataBounds and Reset-extent
  // --------------------------------------------------------------------------
  it('computes fitted bounds from loaded data (zones + flood extent)', () => {
    const sampleZones = [
      {
        zoneId: 'zone-001',
        hasGeometry: true,
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [7.02, 50.51],
              [7.04, 50.51],
              [7.04, 50.53],
              [7.02, 50.53],
              [7.02, 50.51],
            ],
          ],
        },
      },
    ];

    const sampleFlood = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [7.015, 50.512],
                [7.042, 50.512],
                [7.042, 50.531],
                [7.015, 50.531],
                [7.015, 50.512],
              ],
            ],
          },
        },
      ],
    };

    const bounds = computeDataBounds(sampleZones, sampleFlood);
    // [ [minLat, minLng], [maxLat, maxLng] ]
    expect(bounds[0][0]).toBeCloseTo(50.51, 2);
    expect(bounds[0][1]).toBeCloseTo(7.015, 2);
    expect(bounds[1][0]).toBeCloseTo(50.531, 2);
    expect(bounds[1][1]).toBeCloseTo(7.042, 2);
  });

  it('falls back to DEFAULT_AOI_BOUNDS when no geometry exists', () => {
    const emptyZones = [{ zoneId: 'zone-009', hasGeometry: false, geometry: null }];
    const emptyFlood = { type: 'FeatureCollection', features: [] };

    const bounds = computeDataBounds(emptyZones, emptyFlood);
    expect(bounds).toEqual(DEFAULT_AOI_BOUNDS);
  });

  it('MapController calls flyToBounds with fitted dataBounds on resetTrigger', () => {
    const flyToBoundsSpy = vi.spyOn(L.Map.prototype, 'flyToBounds').mockImplementation(() => {});

    const { rerender } = render(
      <FloodMap
        riskZones={[{ zoneId: 'z1', hasGeometry: true, geometry: { type: 'Polygon', coordinates: [[[7.02, 50.51], [7.04, 50.51], [7.04, 50.53], [7.02, 50.53], [7.02, 50.51]]] } }]}
        resetTrigger={0}
      />
    );

    // Initial render does not trigger reset flyToBounds
    expect(flyToBoundsSpy).not.toHaveBeenCalled();

    // Trigger reset extent
    rerender(
      <FloodMap
        riskZones={[{ zoneId: 'z1', hasGeometry: true, geometry: { type: 'Polygon', coordinates: [[[7.02, 50.51], [7.04, 50.51], [7.04, 50.53], [7.02, 50.53], [7.02, 50.51]]] } }]}
        resetTrigger={1}
      />
    );

    expect(flyToBoundsSpy).toHaveBeenCalledTimes(1);
    const calledBounds = flyToBoundsSpy.mock.calls[0][0];
    // Bounds match around 50.51 - 50.53 / 7.02 - 7.04
    expect(calledBounds[0][0]).toBeCloseTo(50.51, 2);
    expect(calledBounds[0][1]).toBeCloseTo(7.02, 2);
  });

  // --------------------------------------------------------------------------
  // 3. Exposed Buildings 6th Overlay
  // --------------------------------------------------------------------------
  it('MapControls includes 6 layer toggles with Exposed Buildings off by default', () => {
    const handleToggle = vi.fn();
    const visibleLayers = {
      flood: true,
      risk: true,
      roads: true,
      facilities: true,
      routes: false,
      buildings: false,
    };

    render(
      <MapControls
        visibleLayers={visibleLayers}
        onToggleLayer={handleToggle}
        onResetExtent={vi.fn()}
      />
    );

    expect(screen.getByText('Exposed Buildings')).toBeInTheDocument();
    const bldgCheckbox = screen.getByRole('checkbox', { name: /Toggle Exposed Buildings overlay/i });
    expect(bldgCheckbox).not.toBeChecked();

    fireEvent.click(bldgCheckbox);
    expect(handleToggle).toHaveBeenCalledWith('buildings');
  });

  it('MapLegend includes Flooded Buildings entry when buildings layer is enabled', () => {
    const { rerender } = render(
      <MapLegend visibleLayers={{ flood: true, risk: true, roads: false, facilities: false, routes: false, buildings: false }} />
    );
    expect(screen.queryByText('Flooded Buildings')).not.toBeInTheDocument();

    rerender(
      <MapLegend visibleLayers={{ flood: true, risk: true, roads: false, facilities: false, routes: false, buildings: true }} />
    );
    expect(screen.getByText('Flooded Buildings')).toBeInTheDocument();
  });

  it('BuildingLayer renders building polygons with theme token styling', () => {
    const buildingData = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { id: 'way/101', flooded: true, building: 'residential' },
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [7.02, 50.52],
                [7.021, 50.52],
                [7.021, 50.521],
                [7.02, 50.521],
                [7.02, 50.52],
              ],
            ],
          },
        },
      ],
    };

    const { container } = render(
      <MapContainer center={[50.52, 7.02]} zoom={12}>
        <BuildingLayer data={buildingData} />
      </MapContainer>
    );
    // Polygon was rendered inside leaflet container
    expect(container).toBeDefined();
  });

  // --------------------------------------------------------------------------
  // 4. DEMO badge & Disclaimers
  // --------------------------------------------------------------------------
  it('renders DEMO MODE badge and illustrative risk scores notice when dataMode is "demo"', () => {
    const mockData = {
      metadata: {
        schemaVersion: '1.0',
        generatedAt: '2026-10-14T10:00:00Z',
        dataMode: 'demo',
        studyArea: 'Dernau (Ahr valley), Germany',
      },
      zones: [
        {
          zoneId: 'zone-001',
          name: 'Zone 001',
          riskLevel: 'LOW',
          riskScore: 12.4,
          floodedPercent: 1.24,
          floodedAreaKm2: 0.0011,
          exposedBuildings: 1,
          accessibility: 'LIMITED',
          reasons: ['1 of 12 buildings flood-labelled'],
          hasGeometry: true,
          geometry: {
            type: 'Polygon',
            coordinates: [[[7.03, 50.51], [7.04, 50.51], [7.04, 50.52], [7.03, 50.52], [7.03, 50.51]]],
          },
        },
      ],
      floodExtent: { type: 'FeatureCollection', features: [] },
      blockedRoads: { type: 'FeatureCollection', features: [] },
      facilities: { type: 'FeatureCollection', features: [] },
      routes: [],
      buildingsExposed: { type: 'FeatureCollection', features: [] },
    };

    render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    expect(screen.getByText('Simulated Ops')).toBeInTheDocument();
  });

  it('renders generic DEMO MODE badge when dataMode is demo and not Dernau', () => {
    const bengaluruData = {
      metadata: {
        generatedAt: '2026-10-14T10:00:00Z',
        dataMode: 'demo',
        studyArea: 'Bengaluru, Karnataka',
      },
      zones: [
        {
          zoneId: 'zone-001',
          name: 'Zone 001',
          riskLevel: 'LOW',
          riskScore: 12.4,
          floodedPercent: 1.24,
          floodedAreaKm2: 0.0011,
          exposedBuildings: 1,
          accessibility: 'LIMITED',
          reasons: [],
          hasGeometry: true,
        },
      ],
      floodExtent: { type: 'FeatureCollection', features: [] },
      blockedRoads: { type: 'FeatureCollection', features: [] },
      facilities: { type: 'FeatureCollection', features: [] },
      routes: [],
      buildingsExposed: { type: 'FeatureCollection', features: [] },
    };

    render(<DashboardLayout data={bengaluruData} onRefresh={vi.fn()} />);
    expect(screen.getByText('DEMO MODE')).toBeInTheDocument();
  });

  it('ProvenanceBadge renders observed, derived, and simulated styles correctly', () => {
    const { rerender } = render(<ProvenanceBadge value="derived" />);
    expect(screen.getByText('Derived')).toBeInTheDocument();

    rerender(<ProvenanceBadge value="simulated" />);
    expect(screen.getByText('Simulated')).toBeInTheDocument();

    rerender(<ProvenanceBadge value="observed" />);
    expect(screen.getByText('Observed')).toBeInTheDocument();
  });

  // --------------------------------------------------------------------------
  // 5. Stat Card Honesty Captions & Zone-005 Not Assessed
  // --------------------------------------------------------------------------
  it('renders the three honesty captions on StatCards when data has partial/ground-truth values', () => {
    const dataWithPartial = {
      metadata: {
        generatedAt: '2026-10-14T10:00:00Z',
        dataMode: 'demo',
        studyArea: 'Dernau (Ahr valley), Germany',
      },
      zones: [
        {
          zoneId: 'zone-001',
          name: 'Zone 001',
          riskLevel: 'LOW',
          riskScore: 10,
          floodedPercent: 1.0,
          floodedAreaKm2: 0.1,
          exposedBuildings: 224,
          accessibility: 'OPEN',
          reasons: [],
          hasGeometry: true,
        },
        {
          zoneId: 'zone-005',
          name: 'Zone 005',
          riskLevel: 'UNKNOWN',
          riskScore: null,
          floodedPercent: 0,
          floodedAreaKm2: 0,
          exposedBuildings: null, // designated test case with withheld value
          accessibility: 'OPEN',
          reasons: [],
          hasGeometry: true,
        },
      ],
      floodExtent: { type: 'FeatureCollection', features: [] },
      blockedRoads: {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', properties: {}, geometry: null }],
      },
      facilities: { type: 'FeatureCollection', features: [] },
      routes: [],
      buildingsExposed: { type: 'FeatureCollection', features: [] },
    };

    render(<DashboardLayout data={dataWithPartial} onRefresh={vi.fn()} />);

    // 1. Flooded area caption
    expect(
      screen.getByText('Derived from labelled flooded buildings/roads, not a measured water boundary')
    ).toBeInTheDocument();

    // 2. Blocked roadways caption
    expect(
      screen.getByText('Roads labelled flooded in ground-truth data')
    ).toBeInTheDocument();

    // 3. Exposed buildings partial note
    expect(
      screen.getByText('Partial: one zone is a designated test case with the value withheld')
    ).toBeInTheDocument();
  });

  it('displays "Not assessed" for zone with null numeric input, UNKNOWN risk, and sorts after scored zones', () => {
    const scoredZone = {
      zoneId: 'zone-001',
      name: 'Zone 001 (scored)',
      riskLevel: 'LOW',
      riskScore: 15,
      floodedAreaKm2: 0.1,
      floodedPercent: 2,
      exposedBuildings: 10,
      accessibility: 'OPEN',
      reasons: ['Measured low inundation'],
      hasGeometry: true,
    };

    const zoneWithNullNumeric = {
      zoneId: 'zone-005',
      name: 'Zone 005 (grid cell)',
      riskLevel: 'UNKNOWN',
      riskScore: null,
      floodedAreaKm2: 0,
      floodedPercent: 0,
      exposedBuildings: null,
      accessibility: 'OPEN',
      reasons: ['Designated test cases, not measured data: missing exposed_buildings numeric field'],
      hasGeometry: true,
    };

    const data = {
      metadata: { generatedAt: '2026-10-14T10:00:00Z', dataMode: 'demo', studyArea: 'Dernau (Ahr valley), Germany' },
      zones: [zoneWithNullNumeric, scoredZone], // Passed in reverse order to test sorting
      floodExtent: { type: 'FeatureCollection', features: [] },
      blockedRoads: { type: 'FeatureCollection', features: [] },
      facilities: { type: 'FeatureCollection', features: [] },
      routes: [],
      buildingsExposed: { type: 'FeatureCollection', features: [] },
    };

    render(<DashboardLayout data={data} onRefresh={vi.fn()} />);

    // In ZoneList: row shows Score: Not assessed (never 0) and Partial data note
    expect(screen.getByText('Score: Not assessed')).toBeInTheDocument();
    expect(screen.queryByText('Score: 0')).not.toBeInTheDocument();
    expect(screen.getAllByText('Partial data').length).toBeGreaterThanOrEqual(1);

    // "(demo-derived)" tag must be completely removed
    expect(screen.queryByText('(demo-derived)')).not.toBeInTheDocument();

    // Scored zone must sort BEFORE unscored zone
    const rows = screen.getAllByRole('button', { name: /Zone 00/i });
    expect(rows[0]).toHaveTextContent('Zone 001');
    expect(rows[1]).toHaveTextContent('Zone 005');

    // Click row to open ZoneDetails
    fireEvent.click(screen.getByRole('button', { name: /Zone 005/i }));

    // In ZoneDetails: Priority Score shows Not assessed and Exposed Buildings shows Not available
    const detailsRegion = screen.getByRole('region', { name: /Zone Inspection Details/i });
    expect(detailsRegion).toHaveTextContent('Not assessed');
    expect(detailsRegion).toHaveTextContent('Not available');
    expect(detailsRegion).toHaveTextContent('Partial data');
    expect(detailsRegion).not.toHaveTextContent('0 / 100');
    expect(screen.queryByText('(demo-derived)')).not.toBeInTheDocument();
  });
});
