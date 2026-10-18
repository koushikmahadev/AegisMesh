import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import FloodMap from '../components/FloodMap.jsx';

describe('Offline Tile Fallback (T5.6, test matrix #19)', () => {
  it('renders neutral background container for base map', () => {
    const { container } = render(
      <FloodMap
        floodGeoJSON={{ type: 'FeatureCollection', features: [] }}
        riskZones={[]}
      />
    );

    const mapContainer = container.querySelector('.leaflet-container');
    expect(mapContainer).toBeInTheDocument();
    expect(mapContainer).toHaveClass('bg-slate-200');
  });

  it('renders offline tile warning notice when tileerror fires or tiles are unreachable', () => {
    const { rerender } = render(
      <FloodMap
        floodGeoJSON={{ type: 'FeatureCollection', features: [] }}
        riskZones={[]}
        tilesOffline={false}
      />
    );

    expect(screen.queryByText(/Base map tiles unreachable/i)).not.toBeInTheDocument();

    // Re-render with tilesOffline = true (simulating tile fetch failure)
    rerender(
      <FloodMap
        floodGeoJSON={{ type: 'FeatureCollection', features: [] }}
        riskZones={[]}
        tilesOffline={true}
      />
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Map tiles unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/Base map tiles unreachable/i)).toBeInTheDocument();
  });

  it('keeps vector layers readable and mounted when map tiles are unavailable', () => {
    const sampleZones = [
      {
        zoneId: 'zone-offline-01',
        name: 'Offline Zone',
        riskLevel: 'HIGH',
        riskScore: 88,
        hasGeometry: true,
        geometry: {
          type: 'Polygon',
          coordinates: [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]],
        },
      },
    ];

    const { container } = render(
      <FloodMap
        floodGeoJSON={{ type: 'FeatureCollection', features: [] }}
        riskZones={sampleZones}
        tilesOffline={true}
      />
    );

    // Vector pane & alert are present and accessible on top of neutral background
    expect(screen.getByRole('alert')).toHaveTextContent(/Map tiles unavailable/i);
    expect(container.querySelector('.leaflet-container')).toHaveClass('bg-slate-200');
    expect(container.querySelector('.leaflet-overlay-pane')).toBeInTheDocument();
  });
});
