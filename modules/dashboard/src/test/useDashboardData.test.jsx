import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import {
  useDashboardData,
  getActiveCacheKey,
  formatCachedTimestamp,
} from '../hooks/useDashboardData.js';
import * as dashboardApi from '../services/dashboardApi.js';

describe('useDashboardData hook (T4.2, test matrix #18)', () => {
  const dummyPayload = {
    rawZones: {
      schema_version: '1.0',
      data_mode: 'demo',
      study_area: 'Test Area',
      zones: [
        {
          zone_id: 'zone-001',
          name: 'Test Zone',
          risk_level: 'HIGH',
          risk_score: 80,
        },
      ],
    },
    rawFloodExtent: { type: 'FeatureCollection', features: [] },
    rawBlockedRoads: { type: 'FeatureCollection', features: [] },
    rawFacilities: { type: 'FeatureCollection', features: [] },
    rawRoutes: { schema_version: '1.0', data_mode: 'demo', routes: [] },
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  describe('getActiveCacheKey and formatCachedTimestamp helpers', () => {
    it('keys cache by active VITE_DATA_SOURCE or provided parameter', () => {
      expect(getActiveCacheKey('mock-dernau')).toBe('highwater_cache_mock-dernau');
      expect(getActiveCacheKey('api')).toBe('highwater_cache_api');
      expect(getActiveCacheKey()).toMatch(/^highwater_cache_/);
    });

    it('formats timestamp as HH:MM when snapshot is from today', () => {
      const todayFixed = new Date('2026-10-14T10:30:00.000Z');
      const nowSameDay = new Date('2026-10-14T15:00:00.000Z');
      const formatted = formatCachedTimestamp(todayFixed.toISOString(), nowSameDay);
      const hours = String(todayFixed.getHours()).padStart(2, '0');
      const minutes = String(todayFixed.getMinutes()).padStart(2, '0');
      expect(formatted).toBe(`${hours}:${minutes}`);
    });

    it('formats timestamp as HH:MM, YYYY-MM-DD when snapshot is not from today', () => {
      const pastDate = new Date('2026-10-12T08:15:00.000Z');
      const now = new Date('2026-10-14T15:00:00.000Z');
      const formatted = formatCachedTimestamp(pastDate.toISOString(), now);
      const hours = String(pastDate.getHours()).padStart(2, '0');
      const minutes = String(pastDate.getMinutes()).padStart(2, '0');
      const year = pastDate.getFullYear();
      const month = String(pastDate.getMonth() + 1).padStart(2, '0');
      const day = String(pastDate.getDate()).padStart(2, '0');
      expect(formatted).toBe(`${hours}:${minutes}, ${year}-${month}-${day}`);
    });
  });

  it('loads dashboard fixtures and sets data correctly', async () => {
    vi.spyOn(dashboardApi, 'fetchDashboardData').mockResolvedValue(dummyPayload);

    const { result } = renderHook(() => useDashboardData());

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).not.toBeNull();
    expect(result.current.data.zones).toHaveLength(1);
    expect(result.current.data.zones[0].zoneId).toBe('zone-001');
    expect(result.current.data.metadata.isFromCache).toBe(false);
    expect(result.current.data.metadata.cachedAt).toBeNull();
    expect(result.current.lastRefreshedAt).not.toBeNull();
    expect(result.current.data.metadata.lastRefreshedAt).not.toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('prevents duplicate in-flight requests when refresh is called repeatedly (test matrix #18)', async () => {
    let resolveFirst;
    const pendingPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    const mockFetch = vi.spyOn(dashboardApi, 'fetchDashboardData').mockImplementation(() => pendingPromise);

    const { result } = renderHook(() => useDashboardData());

    // Initially called on mount (1st call)
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(true);

    // Call refresh multiple times while initial request is still in-flight
    act(() => {
      result.current.refresh();
      result.current.refresh();
      result.current.refresh();
    });

    // In-flight guard should prevent duplicate requests
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Now resolve the in-flight request
    await act(async () => {
      resolveFirst(dummyPayload);
      await pendingPromise;
    });

    expect(result.current.loading).toBe(false);

    // Subsequent refresh after completion is now permitted
    await act(async () => {
      mockFetch.mockResolvedValueOnce(dummyPayload);
      await result.current.refresh();
    });

    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('stores successful fetch in localStorage with ISO timestamp and sets isFromCache to false', async () => {
    const cacheKey = getActiveCacheKey('mock');
    vi.spyOn(dashboardApi, 'fetchDashboardData').mockResolvedValue(dummyPayload);

    const { result } = renderHook(() => useDashboardData({ dataSource: 'mock' }));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data.metadata.isFromCache).toBe(false);
    const storedStr = localStorage.getItem(cacheKey);
    expect(storedStr).not.toBeNull();
    const parsed = JSON.parse(storedStr);
    expect(parsed.raw).toEqual(dummyPayload);
    expect(typeof parsed.cachedAt).toBe('string');
    expect(!isNaN(new Date(parsed.cachedAt).getTime())).toBe(true);
  });

  it('uses cached snapshot only when fetch fails and sets isFromCache and cachedAt', async () => {
    const cacheKey = getActiveCacheKey('mock');
    const cachedIso = '2026-10-14T09:00:00.000Z';
    localStorage.setItem(
      cacheKey,
      JSON.stringify({
        raw: dummyPayload,
        cachedAt: cachedIso,
      })
    );

    // Network fetch fails
    vi.spyOn(dashboardApi, 'fetchDashboardData').mockRejectedValue(new Error('Network offline'));

    const { result } = renderHook(() => useDashboardData({ dataSource: 'mock' }));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBeNull();
    expect(result.current.data).not.toBeNull();
    expect(result.current.data.metadata.isFromCache).toBe(true);
    expect(result.current.data.metadata.cachedAt).toBe(cachedIso);
  });

  it('never shows cached banner alongside live data, clearing isFromCache and replacing cache on next successful fetch', async () => {
    const cacheKey = getActiveCacheKey('mock');
    const oldCachedIso = '2026-10-13T09:00:00.000Z';
    localStorage.setItem(
      cacheKey,
      JSON.stringify({
        raw: dummyPayload,
        cachedAt: oldCachedIso,
      })
    );

    // Initial fetch fails -> falls back to cache
    const mockFetch = vi.spyOn(dashboardApi, 'fetchDashboardData').mockRejectedValueOnce(new Error('Connection error'));

    const { result } = renderHook(() => useDashboardData({ dataSource: 'mock' }));

    await waitFor(() => {
      expect(result.current.data?.metadata?.isFromCache).toBe(true);
    });
    expect(result.current.data.metadata.cachedAt).toBe(oldCachedIso);

    // Next fetch succeeds -> live data replaces cached state
    mockFetch.mockResolvedValueOnce({
      ...dummyPayload,
      rawZones: {
        ...dummyPayload.rawZones,
        zones: [
          {
            zone_id: 'zone-002',
            name: 'Updated Live Zone',
            risk_level: 'LOW',
            risk_score: 20,
          },
        ],
      },
    });

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.data.metadata.isFromCache).toBe(false);
    expect(result.current.data.metadata.cachedAt).toBeNull();
    expect(result.current.data.zones[0].zoneId).toBe('zone-002');

    // Stored cache in localStorage is also replaced with new ISO timestamp
    const updatedCache = JSON.parse(localStorage.getItem(cacheKey));
    expect(updatedCache.raw.rawZones.zones[0].zone_id).toBe('zone-002');
    expect(updatedCache.cachedAt).not.toBe(oldCachedIso);
  });

  it('sets error and data remains null if fetch fails and no cache exists', async () => {
    vi.spyOn(dashboardApi, 'fetchDashboardData').mockRejectedValue(new Error('Server unavailable'));

    const { result } = renderHook(() => useDashboardData({ dataSource: 'api' }));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe('Server unavailable');
  });
});
