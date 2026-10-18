import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MapContainer } from 'react-leaflet';
import RiskLayer from '../features/map/RiskLayer.jsx';
import { THEME } from '../config/theme.js';

describe('RiskLayer component tests (T3.4)', () => {
  const zones = [
    {
      zoneId: 'zone-001',
      name: 'Zone 001 - Bellandur',
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
    {
      zoneId: 'zone-002',
      name: 'Zone 002 - Varthur',
      riskLevel: 'MEDIUM',
      riskScore: 54,
      hasGeometry: true,
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [77.705, 12.935],
            [77.745, 12.935],
            [77.745, 12.965],
            [77.705, 12.965],
            [77.705, 12.935],
          ],
        ],
      },
    },
  ];

  it('(a) clicking a RiskLayer polygon calls onZoneSelect with the right zoneId', () => {
    const handleSelect = vi.fn();
    const { container } = render(
      <MapContainer center={[12.95, 77.69]} zoom={12}>
        <RiskLayer zones={zones} selectedZoneId={null} onZoneSelect={handleSelect} />
      </MapContainer>
    );

    const paths = container.querySelectorAll('.leaflet-overlay-pane svg path');
    expect(paths.length).toBe(2);

    paths[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(handleSelect).toHaveBeenCalledWith('zone-001');

    paths[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(handleSelect).toHaveBeenCalledWith('zone-002');
  });

  it('(b) the selected zone gets the thick selected outline', () => {
    const { container, rerender } = render(
      <MapContainer center={[12.95, 77.69]} zoom={12}>
        <RiskLayer zones={zones} selectedZoneId={null} onZoneSelect={() => {}} />
      </MapContainer>
    );

    let paths = container.querySelectorAll('.leaflet-overlay-pane svg path');
    expect(paths[0].getAttribute('stroke')).toBe(THEME.riskColors.HIGH);
    expect(paths[0].getAttribute('stroke-width')).toBe('2');

    rerender(
      <MapContainer center={[12.95, 77.69]} zoom={12}>
        <RiskLayer zones={zones} selectedZoneId="zone-001" onZoneSelect={() => {}} />
      </MapContainer>
    );

    paths = container.querySelectorAll('.leaflet-overlay-pane svg path');
    expect(paths[0].getAttribute('stroke')).toBe(THEME.colors.selected);
    expect(paths[0].getAttribute('stroke-width')).toBe('4');

    expect(paths[1].getAttribute('stroke')).toBe(THEME.riskColors.MEDIUM);
    expect(paths[1].getAttribute('stroke-width')).toBe('2');
  });
});
