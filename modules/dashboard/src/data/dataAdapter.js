/**
 * dataAdapter.js
 * Adapter layer mapping raw backend/fixture payloads to the normalised UI model.
 * Per architecture.md and rules.md:
 * - Only dataAdapter.js knows backend field names.
 * - Missing numeric data is never zero and never LOW; unknown risk becomes UNKNOWN.
 * - Non-finite numbers become null.
 * - 0.0 - 1.0 risk scores are normalised to 0 - 100.
 * - Validates coordinates and tracks dropped/invalid features.
 */
import { classifyRiskScore } from '../config/thresholds.js';

/**
 * Normalises a numeric value; non-finite numbers or undefined become null.
 * @param {any} val 
 * @returns {number|null}
 */
export function normalizeNumber(val) {
  if (typeof val === 'number' && Number.isFinite(val)) {
    return val;
  }
  if (typeof val === 'string' && val.trim() !== '') {
    const parsed = Number(val);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Normalises risk level. Anything not strictly HIGH, MEDIUM, LOW becomes UNKNOWN.
 * @param {string} level 
 * @returns {"HIGH"|"MEDIUM"|"LOW"|"UNKNOWN"}
 */
export function normalizeRiskLevel(level) {
  if (typeof level !== 'string') return 'UNKNOWN';
  const upper = level.toUpperCase().trim();
  if (upper === 'HIGH' || upper === 'MEDIUM' || upper === 'LOW') {
    return upper;
  }
  return 'UNKNOWN';
}

/**
 * Normalises risk score to a 0 - 100 scale.
 * If score is on 0.0 - 1.0 scale, converts to 0 - 100.
 * @param {any} rawScore 
 * @returns {{ score: number|null, originalScale?: string }}
 */
export function normalizeRiskScore(rawScore) {
  const num = normalizeNumber(rawScore);
  if (num === null) return { score: null };
  if (num >= 0 && num <= 1.0 && num !== 0 && num !== 1) {
    return {
      score: Math.round(num * 100),
      originalScale: '0-1',
    };
  }
  if (num >= 0 && num <= 100) {
    return {
      score: Math.round(num),
      originalScale: '0-100',
    };
  }
  return { score: null };
}

/**
 * Validates a single [longitude, latitude] coordinate pair.
 * Longitude in [-180, 180], latitude in [-90, 90].
 * @param {number[]} coord 
 * @returns {boolean}
 */
export function isValidLngLat(coord) {
  if (!Array.isArray(coord) || coord.length < 2) return false;
  const [lng, lat] = coord;
  if (typeof lng !== 'number' || !Number.isFinite(lng)) return false;
  if (typeof lat !== 'number' || !Number.isFinite(lat)) return false;
  if (lng < -180 || lng > 180) return false;
  if (lat < -90 || lat > 90) return false;
  return true;
}

/**
 * Validates whether a polygon ring is closed (first point equals last point).
 * @param {number[][]} ring 
 * @returns {boolean}
 */
export function isClosedRing(ring) {
  if (!Array.isArray(ring) || ring.length < 4) return false;
  const first = ring[0];
  const last = ring[ring.length - 1];
  return first[0] === last[0] && first[1] === last[1];
}

/**
 * Normalises raw zones payload.
 * @param {object} rawZonesPayload 
 * @returns {{ metadata: object, zones: Array<object> }}
 */
export function adaptZones(rawZonesPayload) {
  if (!rawZonesPayload || typeof rawZonesPayload !== 'object') {
    throw new Error('Invalid zones payload: expected a top-level object.');
  }

  const rawZones = rawZonesPayload.zones || rawZonesPayload.ranked_zones;
  if (!Array.isArray(rawZones)) {
    throw new Error('Invalid zones payload: missing "zones" array.');
  }

  let studyArea = rawZonesPayload.study_area;
  if (!studyArea) {
    const src = typeof rawZonesPayload.source === 'string' ? rawZonesPayload.source : '';
    if (src.includes('Dernau') || src.includes('SpaceNet') || src.includes('Germany')) {
      studyArea = 'Dernau (Ahr valley), Germany';
    } else if (rawZonesPayload.source) {
      studyArea = rawZonesPayload.source;
    } else {
      studyArea = 'Bengaluru, Karnataka';
    }
  }

  const metadata = {
    schemaVersion: rawZonesPayload.schema_version || '1.0',
    generatedAt: rawZonesPayload.generated_at || null,
    dataMode: (rawZonesPayload.data_mode || 'demo').toLowerCase(),
    studyArea,
    riskMethod: rawZonesPayload.risk_method || null,
    source: rawZonesPayload.source || null,
    dataSource: rawZonesPayload.data_source || null,
  };

  const zones = rawZones.map((z, idx) => {
    const zoneId = z.zone_id || `zone-${idx + 1}`;
    const name = z.name || `Zone ${zoneId}`;
    const floodedPercent = normalizeNumber(z.flooded_percent);
    const floodedAreaKm2 = normalizeNumber(
      z.flooded_area_km2 ?? (z.flooded_area_m2 ? z.flooded_area_m2 / 1000000 : null)
    );
    const exposedBuildings = normalizeNumber(z.exposed_buildings);
    const scoreResult = normalizeRiskScore(z.risk_score ?? z.score);

    const rawRiskScore = (z.risk_score !== undefined && z.risk_score !== null && Number.isFinite(Number(z.risk_score)))
      ? Number(z.risk_score)
      : (z.score !== undefined && z.score !== null && Number.isFinite(Number(z.score)) ? Number(z.score) : null);

    let riskLevel = 'UNKNOWN';
    if (rawRiskScore !== null && scoreResult.score !== null) {
      if (!z.risk_level && !z.priority) {
        riskLevel = classifyRiskScore(rawRiskScore, rawZonesPayload?.priority_thresholds);
      } else {
        const normalizedRisk = normalizeRiskLevel(z.risk_level || z.priority);
        riskLevel = normalizedRisk;
      }
    }

    const riskScore = scoreResult.score;

    const partialData =
      z.flooded_percent === null ||
      z.flooded_area_km2 === null ||
      z.exposed_buildings === null;

    let accessibility = 'UNKNOWN';
    if (typeof z.accessibility === 'string') {
      const acc = z.accessibility.toUpperCase();
      if (['OPEN', 'LIMITED', 'BLOCKED', 'CUT_OFF', 'UNKNOWN', 'ACCESSIBLE', 'PARTIAL'].includes(acc)) {
        if (acc === 'ACCESSIBLE') accessibility = 'OPEN';
        else if (acc === 'PARTIAL') accessibility = 'LIMITED';
        else accessibility = acc;
      }
    }

    const reasons = Array.isArray(z.reasons) ? z.reasons : z.explanation ? [z.explanation] : [];

    // Check geometry or synthesize polygon from bbox [minLon, minLat, maxLon, maxLat]
    let geometry = z.geometry && z.geometry.coordinates ? z.geometry : null;
    if (!geometry && Array.isArray(z.bbox) && z.bbox.length === 4) {
      const [minLon, minLat, maxLon, maxLat] = z.bbox;
      if (isValidLngLat([minLon, minLat]) && isValidLngLat([maxLon, maxLat])) {
        geometry = {
          type: 'Polygon',
          coordinates: [
            [
              [minLon, minLat],
              [maxLon, minLat],
              [maxLon, maxLat],
              [minLon, maxLat],
              [minLon, minLat],
            ],
          ],
        };
      }
    }
    const hasGeometry = Boolean(geometry);

    return {
      zoneId,
      name,
      riskLevel,
      riskScore,
      rawRiskScore,
      floodedPercent,
      floodedAreaKm2,
      exposedBuildings,
      totalBuildings: typeof z.total_buildings === 'number' ? z.total_buildings : null,
      roadLengthM: typeof z.road_length_m === 'number' ? z.road_length_m : (z.isolation?.road_length_m || null),
      floodedRoadLengthM: typeof z.flooded_road_length_m === 'number' ? z.flooded_road_length_m : (z.isolation?.flooded_road_length_m || null),
      accessibility,
      reasons,
      geometry,
      hasGeometry,
      bbox: Array.isArray(z.bbox) ? z.bbox : null,
      centroid: Array.isArray(z.centroid) ? z.centroid : null,
      provenance: z.provenance !== undefined ? z.provenance : null,
      source: z.source !== undefined ? z.source : null,
      confidence: z.confidence !== undefined ? z.confidence : null,
      rank_p10: z.rank_p10 !== undefined ? z.rank_p10 : null,
      rank_p90: z.rank_p90 !== undefined ? z.rank_p90 : null,
      needsSurvey: z.needs_survey === true || Boolean(z.needs_verification),
      partialData,
      observed_flooded_count: typeof z.observed_flooded_count === 'number' ? z.observed_flooded_count : null,
      in_training_pool: z.in_training_pool !== undefined ? Boolean(z.in_training_pool) : null,
    };
  });

  return { metadata, zones };
}

/**
 * Normalises routes payload.
 * @param {object} rawRoutesPayload 
 * @returns {Array<object>}
 */
export function adaptRoutes(rawRoutesPayload) {
  if (!rawRoutesPayload) return [];
  const rawList = Array.isArray(rawRoutesPayload.routes)
    ? rawRoutesPayload.routes
    : rawRoutesPayload.active_routes
    ? Object.entries(rawRoutesPayload.active_routes).map(([zoneId, r]) => ({
        zone_id: zoneId,
        ...(r || { status: 'UNREACHABLE' }),
      }))
    : [];

  return rawList.map((r, idx) => ({
    routeId: r.route_id || r.routeId || `route-${idx + 1}`,
    zoneId: r.zone_id || r.zoneId || null,
    riskLevel: r.risk_level || r.riskLevel || null,
    destination: r.destination || r.destination_name || r.destinationName || null,
    destinationName: r.destination_name || r.destinationName || r.name || null,
    destinationId: r.destination_id || r.destinationId || null,
    destinationCoords: r.destination_coords || r.destinationCoords || null,
    originId: r.origin_id || r.originId || null,
    originCoords: r.origin_coords || r.originCoords || null,
    originType: r.origin_type || r.originType || null,
    status: (r.status || 'UNKNOWN').toUpperCase(),
    distanceM: normalizeNumber(r.distance_m ?? r.distanceM ?? (r.distance_km ? r.distance_km * 1000 : null)),
    lengthKm: normalizeNumber(r.length_km ?? (r.distance_m ? r.distance_m / 1000 : null)),
    etaMinutes: normalizeNumber(r.eta_minutes ?? r.etaMinutes),
    uncertainSegments: normalizeNumber(r.uncertain_segments ?? r.uncertainSegments ?? 0),
    maxWaterDepthM: normalizeNumber(r.max_water_depth_meters ?? r.maxWaterDepthM ?? 0.0),
    dataAgeHours: normalizeNumber(r.data_age_hours ?? r.dataAgeHours),
    vehicleType: r.vehicle_type || r.vehicleType || 'AMBULANCE',
    geometryQuality: r.geometry_quality || r.geometryQuality || (r.vehicle_type === 'HELICOPTER' ? 'AIR_LINE' : (r.vehicle_type === 'RESCUE_BOAT' ? 'WATER_LINE' : 'ROADS')),
    corridorType: r.corridor_type || r.corridorType || (r.geometry_quality === 'AIR_LINE' || r.vehicle_type === 'HELICOPTER' ? 'AIR_LINE' : (r.geometry_quality === 'WATER_LINE' || r.vehicle_type === 'RESCUE_BOAT' ? 'WATER_LINE' : 'ROADS')),
    scenarioId: r.scenario_id || r.scenarioId || null,
    stage: r.stage || 1,
    stageTitle: r.stage_title || r.stageTitle || null,
    fallbackReason: r.fallback_reason || r.fallbackReason || r.reason || null,
    reason: r.reason || null,
    label: r.label || (r.geometry_quality === 'AIR_LINE' || r.vehicle_type === 'HELICOPTER' ? 'Air/boat line, not a road route' : (r.geometry_quality === 'WATER_LINE' || r.vehicle_type === 'RESCUE_BOAT' ? 'Air/boat line, not a road route' : null)),
    wording: r.wording || 'lowest-risk route (model)',
    provenance: r.provenance || 'derived',
    geometry: r.geometry || null,
  }));
}

/**
 * Top-level adapter that transforms all raw module outputs into the unified UI dataset.
 * @param {object} raw 
 * @returns {object}
 */
export function adaptDashboardData(raw) {
  if (!raw || !raw.rawZones) {
    throw new Error('Dashboard adapter requires rawZones payload.');
  }

  const { metadata, zones } = adaptZones(raw.rawZones);
  let droppedFeatureCount = 0;
  const warnings = [];
  const layerErrors = {};

  // Flood extent
  let floodExtent = null;
  if (raw.rawFloodExtent?.error) {
    layerErrors.flood = raw.rawFloodExtent.error;
    floodExtent = { error: raw.rawFloodExtent.error, type: 'FeatureCollection', features: null };
  } else if (raw.rawFloodExtent && Array.isArray(raw.rawFloodExtent.features)) {
    const floodFeatures = raw.rawFloodExtent.features.filter((f) => {
      if (!f.geometry || f.geometry.type !== 'Polygon') return false;
      const ring = f.geometry.coordinates?.[0];
      if (!ring || !isClosedRing(ring)) {
        droppedFeatureCount += 1;
        warnings.push(`Dropped flood feature ${f.properties?.feature_id || 'unknown'}: unclosed polygon.`);
        return false;
      }
      const allValid = ring.every(isValidLngLat);
      if (!allValid) {
        droppedFeatureCount += 1;
        warnings.push(`Dropped flood feature ${f.properties?.feature_id || 'unknown'}: invalid coordinates.`);
        return false;
      }
      return true;
    });
    floodExtent = {
      type: 'FeatureCollection',
      features: floodFeatures,
    };
  } else if (raw.rawFloodExtent === null || raw.rawFloodExtent === undefined) {
    floodExtent = { type: 'FeatureCollection', features: [] };
  } else {
    floodExtent = raw.rawFloodExtent;
  }

  // Blocked roads
  let blockedRoads = null;
  if (raw.rawBlockedRoads?.error) {
    layerErrors.roads = raw.rawBlockedRoads.error;
    blockedRoads = { error: raw.rawBlockedRoads.error, type: 'FeatureCollection', features: null };
  } else if (raw.rawBlockedRoads && Array.isArray(raw.rawBlockedRoads.features)) {
    blockedRoads = raw.rawBlockedRoads;
  } else if (raw.rawBlockedRoads === null || raw.rawBlockedRoads === undefined) {
    blockedRoads = { type: 'FeatureCollection', features: [] };
  } else {
    blockedRoads = raw.rawBlockedRoads;
  }

  // Facilities
  let facilities = null;
  if (raw.rawFacilities?.error) {
    layerErrors.facilities = raw.rawFacilities.error;
    facilities = { error: raw.rawFacilities.error, type: 'FeatureCollection', features: null };
  } else if (raw.rawFacilities && Array.isArray(raw.rawFacilities.features)) {
    facilities = raw.rawFacilities;
  } else if (raw.rawFacilities === null || raw.rawFacilities === undefined) {
    facilities = { type: 'FeatureCollection', features: [] };
  } else {
    facilities = raw.rawFacilities;
  }

  // Routes
  let routes = [];
  if (raw.rawRoutes?.error) {
    layerErrors.routes = raw.rawRoutes.error;
  } else if (raw.rawRoutes) {
    routes = adaptRoutes(raw.rawRoutes);
  }

  // Exposed Buildings
  let buildingsExposed = null;
  if (raw.rawBuildingsExposed?.error) {
    layerErrors.buildings = raw.rawBuildingsExposed.error;
    buildingsExposed = { error: raw.rawBuildingsExposed.error, type: 'FeatureCollection', features: null };
  } else if (raw.rawBuildingsExposed && Array.isArray(raw.rawBuildingsExposed.features)) {
    buildingsExposed = raw.rawBuildingsExposed;
  } else if (raw.rawBuildingsExposed === null || raw.rawBuildingsExposed === undefined) {
    buildingsExposed = { type: 'FeatureCollection', features: [] };
  } else {
    buildingsExposed = raw.rawBuildingsExposed;
  }

  // FloodWatch exported layers (STEP 2)
  let floodGroundTruth = null;
  if (raw.rawGroundTruth?.error) {
    layerErrors.floodGroundTruth = raw.rawGroundTruth.error;
    floodGroundTruth = { error: raw.rawGroundTruth.error, type: 'FeatureCollection', features: null };
  } else if (raw.rawGroundTruth) {
    floodGroundTruth = adaptFloodWatchCollection(raw.rawGroundTruth, (reason) => {
      droppedFeatureCount += 1;
      warnings.push(`Dropped groundtruth feature: ${reason}`);
    }, 'observed');
  }

  let floodPredictedFast = null;
  if (raw.rawPredictedFast?.error) {
    layerErrors.floodPredictedFast = raw.rawPredictedFast.error;
    floodPredictedFast = { error: raw.rawPredictedFast.error, type: 'FeatureCollection', features: null };
  } else if (raw.rawPredictedFast) {
    floodPredictedFast = adaptFloodWatchCollection(raw.rawPredictedFast, (reason) => {
      droppedFeatureCount += 1;
      warnings.push(`Dropped predicted fast feature: ${reason}`);
    }, 'derived');
  }

  let floodPredictedAccurate = null;
  if (raw.rawPredictedAccurate?.error) {
    layerErrors.floodPredictedAccurate = raw.rawPredictedAccurate.error;
    floodPredictedAccurate = { error: raw.rawPredictedAccurate.error, type: 'FeatureCollection', features: null };
  } else if (raw.rawPredictedAccurate) {
    floodPredictedAccurate = adaptFloodWatchCollection(raw.rawPredictedAccurate, (reason) => {
      droppedFeatureCount += 1;
      warnings.push(`Dropped predicted accurate feature: ${reason}`);
    }, 'derived');
  }

  // Merge rawRiskScores if provided (e.g. from Module 3 risk_scores.json)
  if (raw.rawRiskScores && typeof raw.rawRiskScores === 'object') {
    const scoreItems = raw.rawRiskScores.ranked_zones || raw.rawRiskScores.zones || [];
    if (Array.isArray(scoreItems)) {
      const scoreMap = new Map();
      for (const item of scoreItems) {
        if (item.zone_id) scoreMap.set(item.zone_id, item);
      }
      for (const zone of zones) {
        const match = scoreMap.get(zone.zoneId);
        if (match) {
          if (match.score !== undefined && (zone.riskScore === null || zone.riskScore === undefined)) {
            const norm = normalizeRiskScore(match.score);
            zone.riskScore = norm.score;
            zone.rawRiskScore = match.score;
          }
          if (match.priority && (zone.riskLevel === 'UNKNOWN' || !zone.riskLevel)) {
            zone.riskLevel = normalizeRiskLevel(match.priority);
          }
          if (match.confidence && !zone.confidence) {
            zone.confidence = match.confidence;
          }
          if (match.needs_verification !== undefined) {
            zone.needsSurvey = Boolean(match.needs_verification);
          }
          if (match.explanation && (!zone.reasons || zone.reasons.length === 0)) {
            zone.reasons = [match.explanation];
          }
        }
      }
    }
  }

  return {
    metadata,
    zones,
    floodExtent,
    blockedRoads,
    facilities,
    routes,
    buildingsExposed,
    floodGroundTruth,
    floodPredictedFast,
    floodPredictedAccurate,
    layerErrors,
    droppedFeatureCount,
    warnings,
  };
}

/**
 * Adapts a single FloodWatch feature (observed ground truth or predicted flood polygon).
 * Validates coordinates and closed rings using existing helpers.
 * Explicitly passes: provenance, tile_id, mode, mask_pixels, in_training_pool, feature_type.
 * Missing fields remain null (never inferred or defaulted).
 *
 * @param {object} f Raw GeoJSON feature
 * @param {function} [onDropped] Callback invoked when feature is dropped
 * @param {string|null} [defaultProvenance] Fallback provenance if not present on feature
 * @returns {object|null} Adapted feature or null if dropped
 */
export function adaptFloodWatchFeature(f, onDropped = () => {}, defaultProvenance = null) {
  if (!f || typeof f !== 'object' || !f.geometry) {
    onDropped('Missing feature or geometry');
    return null;
  }

  const { type, coordinates } = f.geometry;

  if (type === 'Polygon') {
    const ring = coordinates?.[0];
    if (!ring || !isClosedRing(ring)) {
      onDropped(`Unclosed polygon ring on ${f.properties?.feature_id || 'feature'}`);
      return null;
    }
    if (!ring.every(isValidLngLat)) {
      onDropped(`Invalid polygon coordinates on ${f.properties?.feature_id || 'feature'}`);
      return null;
    }
  } else if (type === 'MultiPolygon') {
    if (!Array.isArray(coordinates) || coordinates.length === 0) {
      onDropped(`Invalid MultiPolygon coordinates on ${f.properties?.feature_id || 'feature'}`);
      return null;
    }
    for (const poly of coordinates) {
      const ring = poly?.[0];
      if (!ring || !isClosedRing(ring)) {
        onDropped(`Unclosed polygon ring on ${f.properties?.feature_id || 'feature'}`);
        return null;
      }
      if (!ring.every(isValidLngLat)) {
        onDropped(`Invalid polygon coordinates on ${f.properties?.feature_id || 'feature'}`);
        return null;
      }
    }
  } else if (type === 'LineString') {
    if (!Array.isArray(coordinates) || coordinates.length < 2) {
      onDropped(`Invalid LineString coordinate array on ${f.properties?.feature_id || 'feature'}`);
      return null;
    }
    if (!coordinates.every(isValidLngLat)) {
      onDropped(`Invalid LineString coordinates on ${f.properties?.feature_id || 'feature'}`);
      return null;
    }
  } else if (type === 'MultiLineString') {
    if (!Array.isArray(coordinates) || coordinates.length === 0) {
      onDropped(`Invalid MultiLineString coordinates on ${f.properties?.feature_id || 'feature'}`);
      return null;
    }
    for (const line of coordinates) {
      if (!Array.isArray(line) || line.length < 2) {
        onDropped(`Invalid MultiLineString line segment on ${f.properties?.feature_id || 'feature'}`);
        return null;
      }
      if (!line.every(isValidLngLat)) {
        onDropped(`Invalid MultiLineString coordinates on ${f.properties?.feature_id || 'feature'}`);
        return null;
      }
    }
  } else {
    onDropped(`Unsupported geometry type ${type} on ${f.properties?.feature_id || 'feature'}`);
    return null;
  }

  const p = f.properties || {};

  return {
    type: 'Feature',
    id: f.id !== undefined ? f.id : (p.feature_id !== undefined ? p.feature_id : null),
    geometry: f.geometry,
    properties: {
      feature_id: p.feature_id !== undefined ? p.feature_id : null,
      provenance: p.provenance !== undefined ? p.provenance : (defaultProvenance || null),
      tile_id: p.tile_id !== undefined ? p.tile_id : null,
      mode: p.mode !== undefined ? p.mode : null,
      mask_pixels: p.mask_pixels !== undefined ? p.mask_pixels : null,
      in_training_pool: p.in_training_pool !== undefined ? p.in_training_pool : null,
      feature_type: p.feature_type !== undefined ? p.feature_type : null,
      source: p.source !== undefined ? p.source : null,
      flooded: p.flooded !== undefined ? p.flooded : null,
      model_class: p.model_class !== undefined ? p.model_class : null,
    },
  };
}

/**
 * Adapts a FloodWatch FeatureCollection.
 * @param {object} fc Raw FeatureCollection
 * @param {function} [onDropped] Callback
 * @param {string|null} [defaultProvenance] Fallback provenance if not present on feature
 * @returns {object}
 */
export function adaptFloodWatchCollection(fc, onDropped = () => {}, defaultProvenance = null) {
  if (!fc) return { type: 'FeatureCollection', features: [] };
  if (fc.error) return { type: 'FeatureCollection', features: null, error: fc.error };
  const rawFeatures = Array.isArray(fc.features) ? fc.features : [];
  const validFeatures = [];

  for (const f of rawFeatures) {
    const adapted = adaptFloodWatchFeature(f, onDropped, defaultProvenance);
    if (adapted) {
      validFeatures.push(adapted);
    }
  }

  return {
    type: 'FeatureCollection',
    features: validFeatures,
  };
}
