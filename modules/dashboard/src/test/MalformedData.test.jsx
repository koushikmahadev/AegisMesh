import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import FloodMap from '../components/FloodMap.jsx';
import { adaptDashboardData } from '../data/dataAdapter.js';

describe('Malformed Data Handling (T5.3, FR-53, test matrix #11, #12, #13)', () => {
  it('skips unclosed polygon rings and invalid coordinates without throwing or crashing', () => {
    const rawWithMalformed = {
      rawZones: {
        schema_version: '1.0',
        zones: [
          {
            zone_id: 'zone-001',
            name: 'Valid Zone',
            risk_level: 'HIGH',
            risk_score: 80,
          },
        ],
      },
      rawFloodExtent: {
        type: 'FeatureCollection',
        features: [
          // 1. Valid closed polygon
          {
            type: 'Feature',
            properties: { feature_id: 'valid-flood' },
            geometry: {
              type: 'Polygon',
              coordinates: [
                [[77.6, 12.9], [77.7, 12.9], [77.7, 13.0], [77.6, 13.0], [77.6, 12.9]],
              ],
            },
          },
          // 2. Unclosed ring (first != last)
          {
            type: 'Feature',
            properties: { feature_id: 'bad-ring' },
            geometry: {
              type: 'Polygon',
              coordinates: [
                [[77.6, 12.9], [77.7, 12.9], [77.7, 13.0], [77.6, 13.0]],
              ],
            },
          },
          // 3. Invalid latitude (> 90)
          {
            type: 'Feature',
            properties: { feature_id: 'bad-lat' },
            geometry: {
              type: 'Polygon',
              coordinates: [
                [[77.6, 95.0], [77.7, 95.0], [77.7, 96.0], [77.6, 96.0], [77.6, 95.0]],
              ],
            },
          },
        ],
      },
      rawBlockedRoads: { type: 'FeatureCollection', features: [] },
      rawFacilities: { type: 'FeatureCollection', features: [] },
      rawRoutes: { routes: [] },
    };

    const adapted = adaptDashboardData(rawWithMalformed);

    // 2 features dropped, 1 kept
    expect(adapted.droppedFeatureCount).toBe(2);
    expect(adapted.floodExtent.features).toHaveLength(1);
    expect(adapted.floodExtent.features[0].properties.feature_id).toBe('valid-flood');
    expect(adapted.warnings.length).toBe(2);
  });

  it('renders readable notice in FloodMap when features were dropped, avoiding blank page', () => {
    const { container } = render(
      <FloodMap
        floodGeoJSON={{ type: 'FeatureCollection', features: [] }}
        riskZones={[]}
        droppedCount={2}
      />
    );

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText(/2 malformed features skipped during geometry verification/i)).toBeInTheDocument();
    // Map container remains mounted and functional
    expect(container.querySelector('.leaflet-container')).toBeInTheDocument();
  });
});
