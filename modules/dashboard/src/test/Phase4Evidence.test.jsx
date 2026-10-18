import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import L from 'leaflet';
import DashboardLayout from '../app/DashboardLayout.jsx';
import { toLatLng } from '../features/map/mapUtils.js';

describe('Phase 4 Evidence Tests (Selection, Map Fly-To, and Row Scroll)', () => {
  const mockData = {
    metadata: {
      studyArea: 'Bengaluru Core',
      generatedAt: '2026-10-12T10:00:00Z',
      dataMode: 'demo',
    },
    zones: [
      {
        zoneId: 'zone-001',
        name: 'Zone 001 - Bellandur Basin',
        riskLevel: 'HIGH',
        riskScore: 82,
        floodedAreaKm2: 2.4,
        floodedPercent: 68,
        exposedBuildings: 34,
        accessibility: 'LIMITED',
        reasons: ['Submerged access route'],
        hasGeometry: true,
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [77.655, 12.925],
              [77.690, 12.925],
              [77.690, 12.960],
              [77.655, 12.960],
              [77.655, 12.925],
            ],
          ],
        },
      },
      {
        zoneId: 'zone-009',
        name: 'Zone 009 - Peripheral Staging',
        riskLevel: 'UNKNOWN',
        riskScore: null,
        floodedAreaKm2: null,
        floodedPercent: null,
        exposedBuildings: null,
        accessibility: 'UNKNOWN',
        reasons: [],
        hasGeometry: false,
        geometry: null,
      },
    ],
    floodExtent: { type: 'FeatureCollection', features: [] },
    blockedRoads: { type: 'FeatureCollection', features: [] },
    facilities: { type: 'FeatureCollection', features: [] },
    routes: [],
    droppedFeatureCount: 0,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('Requirement 4: selecting zone-001 from list calls flyToBounds with zone-001 bounds; selecting zone-009 does not', () => {
    const flyToBoundsSpy = vi.spyOn(L.Map.prototype, 'flyToBounds').mockImplementation(() => {});

    render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    // Initially flyToBounds not called for selection
    expect(flyToBoundsSpy).not.toHaveBeenCalled();

    // 1. Select zone-001 from the list (has geometry)
    const zone1Button = screen.getByRole('button', { name: /Zone 001 - Bellandur Basin/i });
    fireEvent.click(zone1Button);

    // flyToBounds was called
    expect(flyToBoundsSpy).toHaveBeenCalledTimes(1);

    // Verify expected bounds passed to flyToBounds
    const expectedLatLngs = mockData.zones[0].geometry.coordinates[0].map(toLatLng);
    const expectedBounds = L.latLngBounds(expectedLatLngs);

    const actualBounds = flyToBoundsSpy.mock.calls[0][0];
    expect(actualBounds.getSouth()).toBeCloseTo(expectedBounds.getSouth(), 4);
    expect(actualBounds.getNorth()).toBeCloseTo(expectedBounds.getNorth(), 4);
    expect(actualBounds.getWest()).toBeCloseTo(expectedBounds.getWest(), 4);
    expect(actualBounds.getEast()).toBeCloseTo(expectedBounds.getEast(), 4);

    // 2. Select zone-009 from the list (has NO geometry)
    const zone9Button = screen.getByRole('button', { name: /Zone 009 - Peripheral Staging/i });
    fireEvent.click(zone9Button);

    // flyToBounds was NOT called again (call count remains 1)
    expect(flyToBoundsSpy).toHaveBeenCalledTimes(1);
  });

  it('Requirement 5: clicking a polygon highlights the matching list row; the selected row scrolls into view', () => {
    const scrollSpy = vi.spyOn(window.HTMLElement.prototype, 'scrollIntoView');

    const { container } = render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    // Locate the RiskLayer polygon path for zone-001
    const paths = container.querySelectorAll('.leaflet-overlay-pane svg path');
    expect(paths.length).toBeGreaterThanOrEqual(1);

    // Prior to click, zone-001 row is not selected
    const zone1Button = screen.getByRole('button', { name: /Zone 001 - Bellandur Basin/i });
    expect(zone1Button).toHaveAttribute('aria-selected', 'false');

    // Click polygon wrapped in act
    act(() => {
      paths[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    // Matching row is now highlighted (aria-selected="true")
    expect(zone1Button).toHaveAttribute('aria-selected', 'true');
    expect(zone1Button).toHaveClass('border-navy-900');

    // Selected row had scrollIntoView invoked
    expect(scrollSpy).toHaveBeenCalled();
  });
});
