import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import CyberMeshLayer from '../features/map/CyberMeshLayer.jsx';
import { MapContainer } from 'react-leaflet';

describe('CyberMeshLayer Component', () => {
  it('renders nothing when nodes array is empty or undefined', () => {
    const { container } = render(
      <MapContainer center={[50.53, 7.04]} zoom={14}>
        <CyberMeshLayer nodes={[]} />
      </MapContainer>
    );
    expect(container.querySelectorAll('.cyber-mesh-node-marker')).toHaveLength(0);
  });

  it('renders markers for valid nodes with coordinates', () => {
    const mockNodes = [
      {
        id: 'DRONE-RELAY-01',
        name: 'Drone Relay Alpha',
        type: 'drone',
        ip: '192.168.10.101',
        lat: 50.5365,
        lng: 7.0410,
        status: 'HEALTHY',
      },
      {
        id: 'SENSOR-GATEWAY-01',
        name: 'IoT Water Gauge Alpha',
        type: 'sensor',
        ip: '192.168.10.25',
        lat: 50.5320,
        lng: 7.0375,
        status: 'COMPROMISED',
      },
    ];

    const { container } = render(
      <MapContainer center={[50.53, 7.04]} zoom={14}>
        <CyberMeshLayer nodes={mockNodes} />
      </MapContainer>
    );

    expect(container.querySelectorAll('.cyber-mesh-node-marker')).toHaveLength(2);
  });
});
