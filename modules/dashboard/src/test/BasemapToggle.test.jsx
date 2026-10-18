import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MapControls from '../components/MapControls.jsx';
import FloodMap from '../components/FloodMap.jsx';

describe('Basemap Toggle and Fallback (Plate vs Satellite)', () => {
  it('1. MapControls renders Plate as default active basemap', () => {
    render(
      <MapControls
        visibleLayers={{ flood: true }}
        onToggleLayer={() => {}}
        onResetExtent={() => {}}
        basemapMode="plate"
        onChangeBasemapMode={() => {}}
      />
    );

    const plateBtn = screen.getByRole('button', { name: 'Plate' });
    const satelliteBtn = screen.getByRole('button', { name: 'Satellite' });

    expect(plateBtn).toBeInTheDocument();
    expect(satelliteBtn).toBeInTheDocument();
    expect(plateBtn).toHaveAttribute('aria-pressed', 'true');
    expect(satelliteBtn).toHaveAttribute('aria-pressed', 'false');
  });

  it('2. MapControls triggers onChangeBasemapMode when Satellite is selected', () => {
    const handleChangeBasemap = vi.fn();
    render(
      <MapControls
        visibleLayers={{ flood: true }}
        onToggleLayer={() => {}}
        onResetExtent={() => {}}
        basemapMode="plate"
        onChangeBasemapMode={handleChangeBasemap}
      />
    );

    const satelliteBtn = screen.getByRole('button', { name: 'Satellite' });
    fireEvent.click(satelliteBtn);

    expect(handleChangeBasemap).toHaveBeenCalledWith('satellite');
  });

  it('3. FloodMap renders with Satellite basemap mode and displays Esri attribution', () => {
    const { container } = render(
      <FloodMap
        floodGeoJSON={{ type: 'FeatureCollection', features: [] }}
        riskZones={[]}
        basemapMode="satellite"
      />
    );

    // Map container remains neutral slate-200 base
    const mapContainer = container.querySelector('.leaflet-container');
    expect(mapContainer).toBeInTheDocument();
    expect(mapContainer).toHaveClass('bg-slate-200');

    // Esri attribution is rendered
    expect(screen.getByText(/Esri/i)).toBeInTheDocument();
  });

  it('4. Offline fallback functions cleanly when Satellite tiles are unavailable', () => {
    const sampleZones = [
      {
        zoneId: 'zone-sat-01',
        name: 'Satellite Test Zone',
        riskLevel: 'HIGH',
        riskScore: 92,
        hasGeometry: true,
        geometry: {
          type: 'Polygon',
          coordinates: [[[7.0, 50.5], [7.1, 50.5], [7.1, 50.6], [7.0, 50.6], [7.0, 50.5]]],
        },
      },
    ];

    const { container } = render(
      <FloodMap
        floodGeoJSON={{ type: 'FeatureCollection', features: [] }}
        riskZones={sampleZones}
        basemapMode="satellite"
        tilesOffline={true}
      />
    );

    // Offline alert is displayed
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Map tiles unavailable. Base map tiles unreachable; vector flood overlays continue to operate offline./i)).toBeInTheDocument();

    // Neutral plate container is preserved
    const mapContainer = container.querySelector('.leaflet-container');
    expect(mapContainer).toHaveClass('bg-slate-200');

    // Vector layer (RiskLayer polygon path) is still present and functional
    const paths = container.querySelectorAll('.leaflet-overlay-pane svg path');
    expect(paths.length).toBeGreaterThan(0);
  });
});
