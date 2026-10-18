import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { getDashboardData } from '../services/dashboardApi.js';
import { adaptDashboardData } from '../data/dataAdapter.js';
import DashboardLayout from '../app/DashboardLayout.jsx';

describe('Real-Fetch Integration & Failure Tests (T6.2, T6.5)', () => {
  const originalFetch = global.fetch;
  const mockResourcePaths = {
    zones: '/api/v1/zones',
    floodExtent: '/api/v1/flood-extent',
    blockedRoads: '/api/v1/blocked-roads',
    facilities: '/api/v1/facilities',
    routes: '/api/v1/routes',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('throws clear configuration error if VITE_DATA_SOURCE="api" and baseUrl or paths are unset (Requirement 2)', async () => {
    // 1. Missing baseUrl
    await expect(
      getDashboardData({
        dataSource: 'api',
        baseUrl: '',
        resourcePaths: mockResourcePaths,
      })
    ).rejects.toThrow(/Configuration error: VITE_API_BASE_URL must be specified when VITE_DATA_SOURCE=api/);

    // 2. Missing endpoint paths (no guessed defaults allowed)
    await expect(
      getDashboardData({
        dataSource: 'api',
        baseUrl: 'https://api.highwater.org',
        resourcePaths: {
          zones: '/api/v1/zones',
          floodExtent: '',
          blockedRoads: '',
          facilities: '',
          routes: '',
        },
      })
    ).rejects.toThrow(/Configuration error: Missing endpoint path\(s\) for VITE_API_FLOODEXTENT_PATH/);
  });

  it('fetches from explicitly configured API endpoints when dataSource is "api"', async () => {
    const requestedUrls = [];
    global.fetch = vi.fn().mockImplementation((url) => {
      requestedUrls.push(url);
      if (url.includes('/api/v1/zones')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              schema_version: '1.0',
              data_mode: 'live',
              study_area: 'Live City Center',
              generated_at: new Date().toISOString(),
              zones: [
                {
                  zone_id: 'zone-live-01',
                  name: 'Live Core Zone',
                  risk_level: 'HIGH',
                  risk_score: 92,
                  flooded_area_km2: 4.5,
                  flooded_percent: 75,
                  exposed_buildings: 110,
                  geometry: {
                    type: 'Polygon',
                    coordinates: [
                      [
                        [77.5, 12.9],
                        [77.6, 12.9],
                        [77.6, 13.0],
                        [77.5, 13.0],
                        [77.5, 12.9],
                      ],
                    ],
                  },
                },
              ],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ type: 'FeatureCollection', features: [] }),
      });
    });

    const baseUrl = 'https://api.highwater.org';
    const raw = await getDashboardData({
      dataSource: 'api',
      baseUrl,
      resourcePaths: mockResourcePaths,
    });

    expect(requestedUrls).toContain(`${baseUrl}${mockResourcePaths.zones}`);
    expect(requestedUrls).toContain(`${baseUrl}${mockResourcePaths.floodExtent}`);
    expect(requestedUrls).toContain(`${baseUrl}${mockResourcePaths.blockedRoads}`);
    expect(requestedUrls).toContain(`${baseUrl}${mockResourcePaths.facilities}`);
    expect(requestedUrls).toContain(`${baseUrl}${mockResourcePaths.routes}`);

    // Verify adapter consumes API payload without component changes
    const adapted = adaptDashboardData(raw);
    expect(adapted.metadata.studyArea).toBe('Live City Center');
    expect(adapted.metadata.dataMode).toBe('live');
    expect(adapted.zones).toHaveLength(1);
    expect(adapted.zones[0].zoneId).toBe('zone-live-01');
    expect(adapted.zones[0].riskScore).toBe(92);

    // Verify layout renders live data seamlessly without component modification
    render(<DashboardLayout data={adapted} onRefresh={vi.fn()} />);
    expect(screen.getByText('Live Core Zone')).toBeInTheDocument();
  });

  it('handles failed API response with clear error (T6.5, test matrix #17)', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/api/v1/zones')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: 'Internal Server Error',
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await expect(
      getDashboardData({
        dataSource: 'api',
        baseUrl: 'https://api.highwater.org',
        resourcePaths: mockResourcePaths,
      })
    ).rejects.toThrow(/API request failed: Failed to load zones from https:\/\/api.highwater.org\/api\/v1\/zones \(500 Internal Server Error\)/);
  });

  it('handles empty API response cleanly, rendering EmptyState without crashing (T6.5, test matrix #7)', async () => {
    global.fetch = vi.fn().mockImplementation(() => {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            schema_version: '1.0',
            data_mode: 'live',
            study_area: 'Zero Inundation Zone',
            generated_at: new Date().toISOString(),
            zones: [],
          }),
      });
    });

    const raw = await getDashboardData({
      dataSource: 'api',
      baseUrl: 'https://api.highwater.org',
      resourcePaths: mockResourcePaths,
    });

    const adapted = adaptDashboardData(raw);
    expect(adapted.zones).toHaveLength(0);

    // Render DashboardLayout with empty API zones
    render(<DashboardLayout data={adapted} onRefresh={vi.fn()} />);
    expect(screen.getByText('No Zones Available')).toBeInTheDocument();
    expect(screen.getByText(/No flood risk zones or operational sectors are reported/i)).toBeInTheDocument();
  });

  it('failed or malformed secondary layers must NOT become empty silently: shows inline warning and dependent stats show "Not available" (Requirement 1 & T6.5)', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('/api/v1/zones')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              schema_version: '1.0',
              data_mode: 'live',
              zones: [
                {
                  zone_id: 'zone-01',
                  name: 'Safe Staging',
                  risk_level: 'LOW',
                  risk_score: 15,
                  has_geometry: false,
                },
              ],
            }),
        });
      }
      if (url.includes('/api/v1/flood-extent')) {
        // Return 502 Bad Gateway for flood layer
        return Promise.resolve({
          ok: false,
          status: 502,
          statusText: 'Bad Gateway',
        });
      }
      if (url.includes('/api/v1/blocked-roads')) {
        // Return malformed JSON for roads layer
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.reject(new SyntaxError('Unexpected token < in JSON at position 0')),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ type: 'FeatureCollection', features: [] }),
      });
    });

    const raw = await getDashboardData({
      dataSource: 'api',
      baseUrl: 'https://api.highwater.org',
      resourcePaths: mockResourcePaths,
    });

    // 1. Verify errors are recorded explicitly, NOT silently empty
    expect(raw.rawFloodExtent.error).toContain('Failed to load flood extent (502 Bad Gateway)');
    expect(raw.rawBlockedRoads.error).toContain('Malformed blocked roads JSON');

    const adapted = adaptDashboardData(raw);
    expect(adapted.layerErrors.flood).toBeDefined();
    expect(adapted.layerErrors.roads).toBeDefined();

    // 2. Render UI
    render(<DashboardLayout data={adapted} onRefresh={vi.fn()} />);

    // 3. Verify dependent stat card: "Blocked roadways" must show "Not available", NEVER 0
    const blockedRoadsCard = screen.getByText('Blocked roadways').closest('.rounded-card');
    expect(within(blockedRoadsCard).getByText('Not available')).toBeInTheDocument();
    expect(within(blockedRoadsCard).queryByText('0')).not.toBeInTheDocument();

    // 4. Verify inline layer warning notice is prominently rendered on map
    const layerNotice = screen.getByRole('alert', { name: 'Layer Error Notice' });
    expect(layerNotice).toBeInTheDocument();
    expect(layerNotice).toHaveTextContent(/Overlay error:/i);
    expect(layerNotice).toHaveTextContent(/roads layer/i);
    expect(layerNotice).toHaveTextContent(/flood layer/i);
  });
});
