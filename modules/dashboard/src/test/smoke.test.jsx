import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../app/App.jsx';

describe('Smoke test', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('zones.json')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              schema_version: '1.0',
              data_mode: 'demo',
              study_area: 'Bengaluru, Karnataka',
              zones: [
                {
                  zone_id: 'zone-001',
                  name: 'Zone 001 - Bellandur Basin',
                  risk_level: 'HIGH',
                  risk_score: 82,
                  flooded_percent: 68,
                  flooded_area_km2: 2.4,
                  exposed_buildings: 34,
                },
              ],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ type: 'FeatureCollection', features: [] }),
      });
    }));
  });

  it('renders App component and layout without crashing', async () => {
    render(<App />);
    expect(screen.getByText('HIGHWATER')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('DEMO MODE')).toBeInTheDocument();
      expect(screen.getByText('Flooded area')).toBeInTheDocument();
    });
  });
});
