import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { detectFloodTiles, DEFAULT_FLOOD_DETECT_URL } from '../services/dashboardApi.js';

describe('detectFloodTiles Integration', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('calls http://localhost:8001/api/detect-tiles with provided tile IDs', async () => {
    const mockResponse = {
      status: 'ok',
      total: 2,
      results: {
        '0_36_59': { flood_damage_detected: false, confidence: 'low' },
        '0_36_62': { flood_damage_detected: true, confidence: 'high' },
      },
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });

    const res = await detectFloodTiles(['0_36_59', '0_36_62']);

    expect(global.fetch).toHaveBeenCalledWith(
      `${DEFAULT_FLOOD_DETECT_URL}/api/detect-tiles`,
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tiles: ['0_36_59', '0_36_62'],
          source: 'germany',
          threshold: 0.001,
          mode: 'fast',
        }),
      })
    );
    expect(res).toEqual(mockResponse);
  });

  it('supports custom baseUrl, threshold, mode, and source options', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok' }),
    });

    await detectFloodTiles(['0_15_65'], {
      baseUrl: 'http://127.0.0.1:8001/',
      source: 'louisiana',
      threshold: 0.05,
      mode: 'accurate',
    });

    expect(global.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8001/api/detect-tiles',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          tiles: ['0_15_65'],
          source: 'louisiana',
          threshold: 0.05,
          mode: 'accurate',
        }),
      })
    );
  });

  it('throws an informative error when the server response is not ok', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({ detail: 'Model failed on GPU memory limit' }),
    });

    await expect(detectFloodTiles(['0_36_59'])).rejects.toThrow(
      'Flood detection API failed: Model failed on GPU memory limit'
    );
  });
});
