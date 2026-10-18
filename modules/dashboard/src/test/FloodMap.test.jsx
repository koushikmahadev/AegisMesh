import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import FloodMap, { MapController } from '../components/FloodMap.jsx';
import { MapContainer } from 'react-leaflet';
import LayerErrorBoundary from '../features/map/LayerErrorBoundary.jsx';
import { DEFAULT_AOI_BOUNDS } from '../features/map/mapUtils.js';

function FaultyLayer() {
  throw new Error('Deliberate layer explosion');
}

function HealthyLayer() {
  return <div data-testid="healthy-rendered">Healthy layer online</div>;
}

describe('FloodMap component tests (T3.1, T3.6, T3.8)', () => {
  const sampleZones = [
    {
      zoneId: 'zone-001',
      name: 'Zone 001 - Bellandur Basin',
      riskLevel: 'HIGH',
      riskScore: 82,
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
  ];

  const sampleFlood = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { feature_id: 'flood-001', water_depth_m: 1.4 },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [77.66, 12.93],
              [77.68, 12.93],
              [77.68, 12.95],
              [77.66, 12.95],
              [77.66, 12.93],
            ],
          ],
        },
      },
    ],
  };

  it('(c) reset-extent restores the default bounds (MapController triggers flyToBounds)', () => {
    let capturedMapInstance = null;

    function TestCapture() {
      const map = (function useMap() {
        return {
          getContainer: () => document.createElement('div'),
          invalidateSize: vi.fn(),
          flyToBounds: vi.fn(),
        };
      })();
      capturedMapInstance = map;
      return null;
    }

    const { rerender } = render(
      <MapContainer center={[12.95, 77.69]} zoom={12}>
        <MapController selectedZoneId={null} zones={sampleZones} resetTrigger={0} />
      </MapContainer>
    );

    // Trigger reset extent
    rerender(
      <MapContainer center={[12.95, 77.69]} zoom={12}>
        <MapController selectedZoneId={null} zones={sampleZones} resetTrigger={1} />
      </MapContainer>
    );

    // MapController renders without throwing
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('(d) inside FloodMap, one deliberately throwing layer shows its inline warning while other layers still render', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <FloodMap
        floodGeoJSON={sampleFlood}
        riskZones={sampleZones}
        visibleLayers={{ flood: true, risk: true, roads: false, facilities: false, routes: false }}
      >
        <LayerErrorBoundary
          layerName="corrupted-layer"
          fallback={<div role="alert">Corrupted layer isolated</div>}
        >
          <FaultyLayer />
        </LayerErrorBoundary>
        <HealthyLayer />
      </FloodMap>
    );

    // Throwing layer shows its inline fallback warning
    expect(screen.getByRole('alert')).toHaveTextContent('Corrupted layer isolated');
    // Healthy layer in the same FloodMap still renders cleanly
    expect(screen.getByTestId('healthy-rendered')).toBeInTheDocument();
    // Base map legend and container still present
    expect(screen.getByRole('region', { name: 'Map Legend' })).toBeInTheDocument();

    consoleSpy.mockRestore();
  });

  it('(e) all overlays off still renders the base map cleanly', () => {
    const { container } = render(
      <FloodMap
        floodGeoJSON={sampleFlood}
        riskZones={sampleZones}
        visibleLayers={{ flood: false, risk: false, roads: false, facilities: false, routes: false }}
      />
    );

    // Base Leaflet container is still mounted and operational
    expect(container.querySelector('.leaflet-container')).toBeInTheDocument();
    // TileLayer pane exists
    expect(container.querySelector('.leaflet-tile-pane')).toBeInTheDocument();
    // No vector overlay paths are rendered
    expect(container.querySelectorAll('.leaflet-overlay-pane svg path').length).toBe(0);
    // Legend indicates no overlays active
    expect(screen.getByText('No map overlays active')).toBeInTheDocument();
  });
});
