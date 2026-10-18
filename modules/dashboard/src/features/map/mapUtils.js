/**
 * mapUtils.js
 * Geospatial conversion and validation utilities.
 * Per rules.md:
 * - GeoJSON order is [longitude, latitude].
 * - Leaflet order is [latitude, longitude].
 * - Convert in exactly one tested helper: toLatLng().
 * - Validate every coordinate: lng in [-180, 180], lat in [-90, 90].
 * - Validate closed linear rings for polygons.
 * - Skip and count invalid features.
 */

/**
 * Converts a GeoJSON [longitude, latitude] coordinate pair to Leaflet [latitude, longitude].
 * @param {number[]} coord [lng, lat]
 * @returns {[number, number]} [lat, lng]
 */
export function toLatLng(coord) {
  if (!Array.isArray(coord) || coord.length < 2) {
    throw new Error(`Invalid coordinate array for toLatLng: ${JSON.stringify(coord)}`);
  }
  const [lng, lat] = coord;
  if (!isValidCoordinate(lng, lat)) {
    throw new Error(`Coordinate out of range: lng=${lng}, lat=${lat}`);
  }
  return [lat, lng];
}

/**
 * Validates longitude and latitude bounds.
 * @param {number} lng 
 * @param {number} lat 
 * @returns {boolean}
 */
export function isValidCoordinate(lng, lat) {
  if (typeof lng !== 'number' || !Number.isFinite(lng)) return false;
  if (typeof lat !== 'number' || !Number.isFinite(lat)) return false;
  if (lng < -180 || lng > 180) return false;
  if (lat < -90 || lat > 90) return false;
  return true;
}

/**
 * Checks whether coordinates appear swapped (e.g. latitude looks like a longitude).
 * In southern India / Bengaluru context, lng is ~77 and lat is ~12.
 * @param {number} lng 
 * @param {number} lat 
 * @returns {boolean}
 */
export function areCoordinatesLikelySwapped(lng, lat) {
  // If lat is outside [-90, 90], it's definitely swapped or out of range
  if (Math.abs(lat) > 90) return true;
  // If lng is in [8, 37] and lat is in [68, 98], they are certainly swapped for India
  if (lng >= 8 && lng <= 37 && lat >= 68 && lat <= 98) {
    return true;
  }
  // Western/Central Europe context (e.g. Germany): lat is ~45-56, lng is ~5-16
  // Swapped: lng in [45, 56], lat in [5, 16]
  if (lng >= 45 && lng <= 56 && lat >= 5 && lat <= 16) {
    return true;
  }
  return false;
}

/**
 * Validates that a linear ring has at least 4 coordinates and is closed.
 * @param {number[][]} ring 
 * @returns {boolean}
 */
export function isValidPolygonRing(ring) {
  if (!Array.isArray(ring) || ring.length < 4) return false;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (!Array.isArray(first) || !Array.isArray(last)) return false;
  if (first[0] !== last[0] || first[1] !== last[1]) return false;
  return ring.every(([lng, lat]) => isValidCoordinate(lng, lat));
}

/**
 * Validates a GeoJSON FeatureCollection, dropping invalid features and reporting counts.
 * @param {object} featureCollection 
 * @returns {{ validFeatures: Array<object>, droppedCount: number, warnings: string[] }}
 */
export function validateFeatureCollection(featureCollection) {
  if (!featureCollection || !Array.isArray(featureCollection.features)) {
    return { validFeatures: [], droppedCount: 0, warnings: ['Missing or invalid FeatureCollection'] };
  }

  const validFeatures = [];
  const warnings = [];
  let droppedCount = 0;

  for (const feature of featureCollection.features) {
    const id = feature.id || feature.properties?.feature_id || feature.properties?.road_id || 'unknown';
    const geom = feature.geometry;

    if (!geom || !geom.type || !geom.coordinates) {
      droppedCount += 1;
      warnings.push(`Feature ${id} skipped: missing geometry`);
      continue;
    }

    if (geom.type === 'Polygon') {
      const ring = geom.coordinates[0];
      if (!isValidPolygonRing(ring)) {
        droppedCount += 1;
        warnings.push(`Feature ${id} skipped: unclosed or invalid polygon ring`);
        continue;
      }
    } else if (geom.type === 'LineString') {
      const coords = geom.coordinates;
      if (!Array.isArray(coords) || coords.length < 2 || !coords.every(([lng, lat]) => isValidCoordinate(lng, lat))) {
        droppedCount += 1;
        warnings.push(`Feature ${id} skipped: invalid LineString coordinates`);
        continue;
      }
    } else if (geom.type === 'Point') {
      const [lng, lat] = geom.coordinates;
      if (!isValidCoordinate(lng, lat)) {
        droppedCount += 1;
        warnings.push(`Feature ${id} skipped: invalid Point coordinates`);
        continue;
      }
    }

    validFeatures.push(feature);
  }

  return { validFeatures, droppedCount, warnings };
}

export const VERIFIED_STUDY_AREAS = {
  dernau: {
    id: 'dernau',
    name: 'Dernau (Ahr valley), Germany',
    bounds: [
      [50.5100, 7.0150],
      [50.5510, 7.0450],
    ],
    center: [50.5213, 7.0296],
    zoom: 14,
    isHistorical: true,
    historicalEvent: 'SpaceNet 8 (July 2021 Ahr Valley Flood)',
  },
  bengaluru: {
    id: 'bengaluru',
    name: 'Bengaluru, Karnataka',
    bounds: [
      [12.8800, 77.6000],
      [13.0200, 77.7800],
    ],
    center: [12.9500, 77.6900],
    zoom: 12,
    isHistorical: false,
    isSimulated: true,
    historicalEvent: 'Simulated Demo Scenario (Bellandur / Varthur Basin)',
  },
};

export const DERNAU_AOI_BOUNDS = VERIFIED_STUDY_AREAS.dernau.bounds;
export const DERNAU_MAP_CENTER = VERIFIED_STUDY_AREAS.dernau.center;

export const BENGALURU_AOI_BOUNDS = VERIFIED_STUDY_AREAS.bengaluru.bounds;
export const BENGALURU_MAP_CENTER = VERIFIED_STUDY_AREAS.bengaluru.center;

/**
 * Default extent set to the verified project dataset (SpaceNet 8 Germany / Dernau).
 * Prevents map from defaulting to Bengaluru when real flood data is in Germany.
 */
export const DEFAULT_AOI_BOUNDS = DERNAU_AOI_BOUNDS;
export const DEFAULT_MAP_CENTER = DERNAU_MAP_CENTER;
export const DEFAULT_MAP_ZOOM = 14;

/**
 * Fits bounding box from loaded data (zones + flood extent).
 * Also supports raw Module 2 zones with `bbox` or `centroid`.
 * Falls back to verified study area bounds if no geometry exists.
 * Returns Leaflet bounds: [[minLat, minLng], [maxLat, maxLng]].
 *
 * @param {Array<object>} [zones]
 * @param {object} [floodGeoJSON]
 * @param {string|Array<object>} [extraOrStudyArea]
 * @param {string} [studyAreaArg]
 * @returns {[[number, number], [number, number]]}
 */
export function computeDataBounds(zones = [], floodGeoJSON = null, extraOrStudyArea = null, studyAreaArg = null) {
  const studyArea = typeof extraOrStudyArea === 'string' ? extraOrStudyArea : (typeof studyAreaArg === 'string' ? studyAreaArg : null);
  const extraGeoJSONs = Array.isArray(extraOrStudyArea) ? extraOrStudyArea : [];

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLng = Infinity;
  let maxLng = -Infinity;
  let count = 0;

  const update = (lng, lat) => {
    if (isValidCoordinate(lng, lat)) {
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
      minLng = Math.min(minLng, lng);
      maxLng = Math.max(maxLng, lng);
      count++;
    }
  };

  const processCollection = (fc) => {
    if (!fc || !Array.isArray(fc.features)) return;
    for (const f of fc.features) {
      const geom = f?.geometry;
      if (!geom?.coordinates) continue;
      if (geom.type === 'LineString') {
        for (const pt of geom.coordinates) {
          if (Array.isArray(pt) && pt.length >= 2) update(pt[0], pt[1]);
        }
      } else if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
        const rings = geom.type === 'Polygon' ? geom.coordinates : geom.coordinates.flat(1);
        for (const ring of rings) {
          if (Array.isArray(ring)) {
            for (const pt of ring) {
              if (Array.isArray(pt) && pt.length >= 2) update(pt[0], pt[1]);
            }
          }
        }
      }
    }
  };

  if (Array.isArray(zones)) {
    for (const z of zones) {
      if (z.hasGeometry && z.geometry?.coordinates) {
        const rings = z.geometry.type === 'Polygon' ? z.geometry.coordinates : z.geometry.coordinates.flat(1);
        for (const ring of rings) {
          if (Array.isArray(ring)) {
            for (const pt of ring) {
              if (Array.isArray(pt) && pt.length >= 2) {
                update(pt[0], pt[1]);
              }
            }
          }
        }
      } else if (Array.isArray(z.bbox) && z.bbox.length === 4) {
        update(z.bbox[0], z.bbox[1]);
        update(z.bbox[2], z.bbox[3]);
      } else if (Array.isArray(z.centroid) && z.centroid.length === 2) {
        update(z.centroid[0], z.centroid[1]);
      }
    }
  }

  if (floodGeoJSON) {
    processCollection(floodGeoJSON);
  }

  if (Array.isArray(extraGeoJSONs)) {
    for (const extra of extraGeoJSONs) {
      if (extra) processCollection(extra);
    }
  }

  if (count === 0) {
    if (typeof studyArea === 'string' && studyArea.toLowerCase().includes('bengaluru')) {
      return BENGALURU_AOI_BOUNDS;
    }
    return DEFAULT_AOI_BOUNDS;
  }

  return [
    [minLat, minLng],
    [maxLat, maxLng],
  ];
}

/**
 * Verifies geographic data consistency between feature coordinates and metadata.
 * Detects location mismatches, flags historical vs simulated data, and checks for missing geographic bounds.
 *
 * @param {object} params
 * @param {Array<object>} [params.zones]
 * @param {object} [params.floodGeoJSON]
 * @param {object} [params.metadata]
 * @returns {object}
 */
export function verifyGeographicData({ zones = [], floodGeoJSON = null, metadata = {} } = {}) {
  const hasSpatialZones = Array.isArray(zones) && zones.some((z) => z.hasGeometry || (Array.isArray(z.bbox) && z.bbox.length === 4));
  const hasFloodFeatures = Boolean(floodGeoJSON?.features && floodGeoJSON.features.length > 0);

  const studyAreaStr = (metadata?.studyArea || '').toLowerCase();
  const sourceStr = (metadata?.source || '').toLowerCase();
  const dataMode = (metadata?.dataMode || 'demo').toLowerCase();

  if (!hasSpatialZones && !hasFloodFeatures) {
    return {
      status: 'MISSING_GEOGRAPHY',
      isVerified: false,
      isHistorical: false,
      isSimulated: dataMode === 'demo',
      warning: 'No geographic boundary data available for assessment zones.',
      locationName: metadata?.studyArea || 'Unknown Location',
      bounds: null,
      center: null,
    };
  }

  const bounds = computeDataBounds(zones, floodGeoJSON, metadata?.studyArea);
  const [[minLat, minLng], [maxLat, maxLng]] = bounds;
  const centerLat = (minLat + maxLat) / 2;
  const centerLng = (minLng + maxLng) / 2;

  // Dernau / Ahr Valley bounds: lat ~50.4 - 50.6, lng ~6.9 - 7.2
  const isDernauCoords = centerLat >= 50.4 && centerLat <= 50.6 && centerLng >= 6.9 && centerLng <= 7.2;
  // Bengaluru bounds: lat ~12.7 - 13.2, lng ~77.4 - 77.9
  const isBengaluruCoords = centerLat >= 12.7 && centerLat <= 13.2 && centerLng >= 77.4 && centerLng <= 77.9;

  if (isDernauCoords) {
    if (studyAreaStr.includes('bengaluru')) {
      return {
        status: 'LOCATION_MISMATCH',
        isVerified: false,
        isHistorical: true,
        isSimulated: false,
        warning: 'Geographic mismatch detected: Zone coordinates are located in Dernau, Germany (Ahr Valley), but the study area is labeled as Bengaluru.',
        locationName: 'Dernau (Ahr valley), Germany',
        bounds,
        center: [centerLat, centerLng],
      };
    }
    return {
      status: 'VERIFIED_HISTORICAL',
      isVerified: true,
      isHistorical: true,
      isSimulated: false,
      warning: null,
      locationName: 'Dernau (Ahr valley), Germany',
      eventDescription: 'Historical Event: SpaceNet 8 July 2021 Ahr Valley Flood (Dernau, Germany)',
      bounds,
      center: [centerLat, centerLng],
    };
  }

  if (isBengaluruCoords) {
    if (studyAreaStr.includes('dernau') || sourceStr.includes('spacenet')) {
      return {
        status: 'LOCATION_MISMATCH',
        isVerified: false,
        isHistorical: false,
        isSimulated: true,
        warning: 'Geographic mismatch detected: Zone coordinates are located in Bengaluru, India, but metadata references SpaceNet 8 / Dernau.',
        locationName: 'Bengaluru, Karnataka',
        bounds,
        center: [centerLat, centerLng],
      };
    }
    return {
      status: 'SIMULATED_DEMO',
      isVerified: true,
      isHistorical: false,
      isSimulated: true,
      warning: null,
      locationName: 'Bengaluru, Karnataka',
      eventDescription: 'Simulated Scenario: Demo dataset for Bellandur / Varthur Basin, Bengaluru',
      bounds,
      center: [centerLat, centerLng],
    };
  }

  // Any other location:
  const isKnown = Boolean(studyAreaStr && !studyAreaStr.includes('unverified') && !studyAreaStr.includes('unknown'));
  return {
    status: isKnown ? 'CUSTOM_LOCATION' : 'UNVERIFIED',
    isVerified: isKnown,
    isHistorical: false,
    isSimulated: dataMode === 'demo',
    warning: isKnown ? null : 'Unverified geographic extent: coordinates do not match a verified study area.',
    locationName: metadata?.studyArea || 'Unverified Location',
    bounds,
    center: [centerLat, centerLng],
  };
}

