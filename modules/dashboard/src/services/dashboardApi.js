/**
 * dashboardApi.js
 * Service layer responsible for fetching data payloads.
 * Supports 'mock', 'mock-dernau', 'mock-floodwatch', and 'api' data sources.
 * Components never call fetch directly; all data requests pass through this service.
 *
 * Hard rule: Do NOT guess endpoints or field names.
 * When VITE_DATA_SOURCE=api, VITE_API_BASE_URL and all VITE_API_*_PATH variables must be set.
 */

export const MOCK_RESOURCE_PATHS = {
  zones: '/mock-data/zones.json',
  floodExtent: '/mock-data/flood_extent.geojson',
  blockedRoads: '/mock-data/blocked_roads.geojson',
  facilities: '/mock-data/facilities.geojson',
  routes: '/mock-data/routes.json',
};

export const MOCK_DERNAU_RESOURCE_PATHS = {
  zones: '/mock-data-dernau/zones.json',
  floodExtent: '/mock-data-dernau/flood_extent.geojson',
  blockedRoads: '/mock-data-dernau/blocked_roads.geojson',
  facilities: '/mock-data-dernau/facilities.geojson',
  routes: '/mock-data-dernau/routes.json',
  buildingsExposed: '/mock-data-dernau/buildings_exposed.geojson',
};

export const MOCK_FLOODWATCH_RESOURCE_PATHS = {
  zones: '/mock-data-floodwatch/zones.json',
  floodExtent: '/mock-data-floodwatch/flood_extent_predicted_fast.geojson',
  blockedRoads: '/mock-data/blocked_roads.geojson',
  facilities: '/mock-data/facilities.geojson',
  routes: '/mock-data/routes.json',
  groundTruth: '/mock-data-floodwatch/flood_extent_groundtruth.geojson',
  predictedFast: '/mock-data-floodwatch/flood_extent_predicted_fast.geojson',
  predictedAccurate: '/mock-data-floodwatch/flood_extent_predicted_accurate.geojson',
};

// No guessed default endpoint paths per Phase 6 requirements
export const API_RESOURCE_PATHS = {
  zones: import.meta.env?.VITE_API_ZONES_PATH || '',
  floodExtent: import.meta.env?.VITE_API_FLOOD_PATH || '',
  blockedRoads: import.meta.env?.VITE_API_ROADS_PATH || '',
  facilities: import.meta.env?.VITE_API_FACILITIES_PATH || '',
  routes: import.meta.env?.VITE_API_ROUTES_PATH || '',
};

/**
 * Primary data fetcher for the dashboard.
 * Selects mock, mock-dernau, mock-floodwatch, or live API based on VITE_DATA_SOURCE.
 *
 * @param {Object} options Configuration overrides (useful for testing)
 * @param {'mock'|'mock-dernau'|'mock-floodwatch'|'api'} [options.dataSource] Override data source
 * @param {string} [options.baseUrl] Override API base URL
 * @param {Object} [options.resourcePaths] Override per-resource endpoint paths
 * @returns {Promise<Object>}
 */
export async function getDashboardData(options = {}) {
  const querySource =
    typeof window !== 'undefined' && window.location?.search
      ? new URLSearchParams(window.location.search).get('dataSource') ||
        new URLSearchParams(window.location.search).get('source')
      : null;
  const dataSource = options.dataSource || querySource || import.meta.env?.VITE_DATA_SOURCE || 'mock-dernau';
  const baseUrl = options.baseUrl ?? (import.meta.env?.VITE_API_BASE_URL || '');

  const isApi = dataSource === 'api';
  const isDernau = dataSource === 'mock-dernau';
  const isFloodwatch = dataSource === 'mock-floodwatch';

  const defaultPaths = isApi
    ? API_RESOURCE_PATHS
    : isFloodwatch
    ? MOCK_FLOODWATCH_RESOURCE_PATHS
    : isDernau
    ? MOCK_DERNAU_RESOURCE_PATHS
    : MOCK_RESOURCE_PATHS;

  const paths = { ...defaultPaths, ...options.resourcePaths };

  // Explicit configuration validation for api mode (no guessed endpoints)
  if (isApi) {
    if (!baseUrl || baseUrl.trim() === '') {
      throw new Error(
        'Configuration error: VITE_API_BASE_URL must be specified when VITE_DATA_SOURCE=api.'
      );
    }
    const missingKeys = Object.entries(paths)
      .filter(([_, pathVal]) => !pathVal || pathVal.trim() === '')
      .map(([key]) => `VITE_API_${key.toUpperCase()}_PATH`);

    if (missingKeys.length > 0) {
      throw new Error(
        `Configuration error: Missing endpoint path(s) for ${missingKeys.join(', ')}. Set them in environment configuration when VITE_DATA_SOURCE=api.`
      );
    }
  }

  const getUrl = (resourceKey) => {
    const resourcePath = paths[resourceKey];
    if (!resourcePath) return '';
    if (isApi) {
      const cleanBase = baseUrl.replace(/\/+$/, '');
      const cleanPath = resourcePath.startsWith('/') ? resourcePath : `/${resourcePath}`;
      return `${cleanBase}${cleanPath}`;
    }
    return resourcePath;
  };

  const fetchPromises = [
    fetch(getUrl('zones')),
    fetch(getUrl('floodExtent')),
    fetch(getUrl('blockedRoads')),
    fetch(getUrl('facilities')),
    fetch(getUrl('routes')),
  ];

  const hasBuildings = Boolean(paths.buildingsExposed);
  if (hasBuildings) {
    fetchPromises.push(fetch(getUrl('buildingsExposed')));
  }

  const hasGroundTruth = Boolean(paths.groundTruth);
  if (hasGroundTruth) {
    fetchPromises.push(fetch(getUrl('groundTruth')));
  }

  const hasPredictedFast = Boolean(paths.predictedFast);
  if (hasPredictedFast) {
    fetchPromises.push(fetch(getUrl('predictedFast')));
  }

  const hasPredictedAccurate = Boolean(paths.predictedAccurate);
  if (hasPredictedAccurate) {
    fetchPromises.push(fetch(getUrl('predictedAccurate')));
  }

  const responses = await Promise.all(fetchPromises);
  const zonesRes = responses[0];
  const floodRes = responses[1];
  const roadsRes = responses[2];
  const facilitiesRes = responses[3];
  const routesRes = responses[4];

  let nextIdx = 5;
  const buildingsRes = hasBuildings ? responses[nextIdx++] : null;
  const groundTruthRes = hasGroundTruth ? responses[nextIdx++] : null;
  const predictedFastRes = hasPredictedFast ? responses[nextIdx++] : null;
  const predictedAccurateRes = hasPredictedAccurate ? responses[nextIdx++] : null;

  if (!zonesRes.ok) {
    throw new Error(
      isApi
        ? `API request failed: Failed to load zones from ${getUrl('zones')} (${zonesRes.status} ${zonesRes.statusText})`
        : `Failed to load zones mock data (${zonesRes.statusText})`
    );
  }

  // Failed secondary layers must NOT become empty silently; record error payload for explicit warning
  const [
    zones,
    floodExtent,
    blockedRoads,
    facilities,
    routes,
    buildingsExposed,
    groundTruth,
    predictedFast,
    predictedAccurate,
  ] = await Promise.all([
    zonesRes.json(),
    floodRes.ok
      ? floodRes.json().catch((err) => ({ error: `Malformed flood extent JSON: ${err.message}` }))
      : { error: `Failed to load flood extent (${floodRes.status} ${floodRes.statusText})` },
    roadsRes.ok
      ? roadsRes.json().catch((err) => ({ error: `Malformed blocked roads JSON: ${err.message}` }))
      : { error: `Failed to load blocked roads (${roadsRes.status} ${roadsRes.statusText})` },
    facilitiesRes.ok
      ? facilitiesRes.json().catch((err) => ({ error: `Malformed facilities JSON: ${err.message}` }))
      : { error: `Failed to load facilities (${facilitiesRes.status} ${facilitiesRes.statusText})` },
    routesRes.ok
      ? routesRes.json().catch((err) => ({ error: `Malformed routes JSON: ${err.message}` }))
      : { error: `Failed to load routes (${routesRes.status} ${routesRes.statusText})` },
    buildingsRes
      ? buildingsRes.ok
        ? buildingsRes.json().catch((err) => ({ error: `Malformed buildings exposed JSON: ${err.message}` }))
        : { error: `Failed to load buildings exposed (${buildingsRes.status} ${buildingsRes.statusText})` }
      : null,
    groundTruthRes
      ? groundTruthRes.ok
        ? groundTruthRes.json().catch((err) => ({ error: `Malformed groundtruth JSON: ${err.message}` }))
        : { error: `Failed to load groundtruth (${groundTruthRes.status} ${groundTruthRes.statusText})` }
      : null,
    predictedFastRes
      ? predictedFastRes.ok
        ? predictedFastRes.json().catch((err) => ({ error: `Malformed predicted fast JSON: ${err.message}` }))
        : { error: `Failed to load predicted fast (${predictedFastRes.status} ${predictedFastRes.statusText})` }
      : null,
    predictedAccurateRes
      ? predictedAccurateRes.ok
        ? predictedAccurateRes.json().catch((err) => ({ error: `Malformed predicted accurate JSON: ${err.message}` }))
        : { error: `Failed to load predicted accurate (${predictedAccurateRes.status} ${predictedAccurateRes.statusText})` }
      : null,
  ]);

  if (zones && typeof zones === 'object' && !zones.data_source) {
    zones.data_source = dataSource;
  }

  return {
    rawZones: zones,
    rawFloodExtent: floodExtent,
    rawBlockedRoads: blockedRoads,
    rawFacilities: facilities,
    rawRoutes: routes,
    ...(buildingsExposed ? { rawBuildingsExposed: buildingsExposed } : {}),
    ...(groundTruth ? { rawGroundTruth: groundTruth } : {}),
    ...(predictedFast ? { rawPredictedFast: predictedFast } : {}),
    ...(predictedAccurate ? { rawPredictedAccurate: predictedAccurate } : {}),
  };
}

// Backwards compatibility alias
export const fetchDashboardData = getDashboardData;

export const DEFAULT_FLOOD_DETECT_URL = 'http://localhost:8001';

/**
 * Calls the local SegFormer offline model backend (Module 2) to detect flood damage across tile IDs.
 *
 * @param {string[]} tileIds List of tile IDs (e.g. ['0_36_59', '0_36_62'])
 * @param {Object} [options]
 * @param {string} [options.source='germany'] Imagery dataset source
 * @param {number} [options.threshold=0.001] Flood detection threshold
 * @param {string} [options.mode='fast'] Detection mode ('fast' | 'accurate')
 * @param {string} [options.baseUrl] Backend URL (defaults to import.meta.env?.VITE_FLOOD_DETECT_URL or http://localhost:8001)
 * @returns {Promise<Object>} Results map with predictions and metrics per tile
 */
export async function detectFloodTiles(tileIds, options = {}) {
  const baseUrl = options.baseUrl || import.meta.env?.VITE_FLOOD_DETECT_URL || DEFAULT_FLOOD_DETECT_URL;
  const cleanBase = baseUrl.replace(/\/+$/, '');
  const url = `${cleanBase}/api/detect-tiles`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tiles: tileIds,
      source: options.source || 'germany',
      threshold: options.threshold !== undefined ? options.threshold : 0.001,
      mode: options.mode || 'fast',
    }),
  });

  if (!response.ok) {
    let errDetail = `Server error ${response.status}: ${response.statusText}`;
    try {
      const errJson = await response.json();
      errDetail = errJson.detail || errDetail;
    } catch {
      // ignore
    }
    throw new Error(`Flood detection API failed: ${errDetail}`);
  }

  return await response.json();
}
