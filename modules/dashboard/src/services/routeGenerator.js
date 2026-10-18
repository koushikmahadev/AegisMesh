/**
 * routeGenerator.js
 * HighWater Evacuation Route Selection & Optimization Engine
 *
 * Implements data-driven evaluation of affected zones, road network graph
 * construction, constraint-satisfaction (avoiding submerged/flooded corridors),
 * and route generation towards verified safe emergency facilities.
 *
 * When terrestrial access is completely cut off by floodwaters, the engine
 * reports status: 'UNREACHABLE' with explanatory diagnostic reasons rather
 * than inventing non-existent overland paths.
 */

/**
 * Computes Haversine distance in meters between two [lon, lat] coordinates.
 * @param {[number, number]} c1 
 * @param {[number, number]} c2 
 * @returns {number}
 */
export function haversineDistance(c1, c2) {
  if (!c1 || !c2 || !Number.isFinite(c1[0]) || !Number.isFinite(c1[1]) || !Number.isFinite(c2[0]) || !Number.isFinite(c2[1])) {
    return 0;
  }
  const R = 6371000; // Earth's mean radius in meters
  const dLat = ((c2[1] - c1[1]) * Math.PI) / 180;
  const dLon = ((c2[0] - c1[0]) * Math.PI) / 180;
  const lat1 = (c1[1] * Math.PI) / 180;
  const lat2 = (c2[1] * Math.PI) / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * Computes cumulative path distance along a coordinate array in meters.
 * @param {Array<[number, number]>} coords 
 * @returns {number}
 */
export function computePathDistance(coords) {
  if (!Array.isArray(coords) || coords.length < 2) return 0;
  let dist = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    dist += haversineDistance(coords[i], coords[i + 1]);
  }
  return Math.round(dist);
}

/**
 * Quantizes node coordinates for topological graph joining.
 * @param {[number, number]} pt 
 * @returns {string}
 */
export function nodeKey(pt) {
  if (!pt || !Number.isFinite(pt[0]) || !Number.isFinite(pt[1])) return '0.000000,0.000000';
  return `${pt[0].toFixed(6)},${pt[1].toFixed(6)}`;
}

/**
 * Extracts coordinate line sequences from a GeoJSON LineString or MultiLineString feature.
 * @param {object} feat 
 * @returns {Array<Array<[number, number]>>}
 */
export function getLineStringsFromFeature(feat) {
  if (!feat || !feat.geometry) return [];
  if (feat.geometry.type === 'LineString' && Array.isArray(feat.geometry.coordinates)) {
    return [feat.geometry.coordinates];
  }
  if (feat.geometry.type === 'MultiLineString' && Array.isArray(feat.geometry.coordinates)) {
    return feat.geometry.coordinates.filter(Array.isArray);
  }
  return [];
}

/**
 * Computes bounding box [minLon, minLat, maxLon, maxLat] for a zone.
 * @param {object} zone 
 * @returns {[number, number, number, number]|null}
 */
export function getZoneBBox(zone) {
  if (!zone) return null;
  if (Array.isArray(zone.bbox) && zone.bbox.length === 4 && zone.bbox.every(Number.isFinite)) {
    return zone.bbox;
  }
  if (zone.geometry && zone.geometry.coordinates) {
    const raw = zone.geometry.type === 'Polygon'
      ? zone.geometry.coordinates[0]
      : zone.geometry.coordinates.flat(1);
    if (Array.isArray(raw) && raw.length > 0) {
      const validPoints = raw.filter((p) => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]));
      if (validPoints.length > 0) {
        const lons = validPoints.map((p) => p[0]);
        const lats = validPoints.map((p) => p[1]);
        return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
      }
    }
  }
  return null;
}

/**
 * Identifies zones requiring evacuation routing using data-driven criteria.
 * Zones classified as HIGH or MEDIUM risk, or exceeding hazard thresholds, qualify.
 * Unaffected peripheral zones (LOW risk with no significant flood exposure) are excluded.
 *
 * @param {Array<object>|object} zonesData 
 * @param {object} options 
 * @returns {Array<object>} Filtered and sorted candidate zones (highest priority first).
 */
export function identifyEvacuationZones(zonesData, options = {}) {
  const list = Array.isArray(zonesData)
    ? zonesData
    : Array.isArray(zonesData?.zones)
    ? zonesData.zones
    : [];

  const allowedRiskLevels = options.allowedRiskLevels || ['HIGH', 'MEDIUM', 'CRITICAL'];
  const minFloodedPercent = typeof options.minFloodedPercent === 'number' ? options.minFloodedPercent : 4.0;
  const minExposedBuildings = typeof options.minExposedBuildings === 'number' ? options.minExposedBuildings : 10;
  const riskScoreThreshold = typeof options.riskScoreThreshold === 'number' ? options.riskScoreThreshold : 20.0;

  const candidates = list.filter((z) => {
    if (!z || typeof z !== 'object') return false;

    const riskLevel = (z.risk_level || z.riskLevel || '').toUpperCase();
    if (riskLevel) {
      return allowedRiskLevels.includes(riskLevel);
    }

    const score = typeof z.risk_score === 'number'
      ? z.risk_score
      : typeof z.riskScore === 'number'
      ? z.riskScore
      : null;
    return score !== null && score >= riskScoreThreshold;
  });

  // Sort candidates strictly descending by priority: risk score, then flooded percent
  return candidates.sort((a, b) => {
    const scoreA = a.risk_score ?? a.riskScore ?? 0;
    const scoreB = b.risk_score ?? b.riskScore ?? 0;
    if (scoreB !== scoreA) return scoreB - scoreA;
    const floodA = a.flooded_percent ?? a.floodedPercent ?? 0;
    const floodB = b.flooded_percent ?? b.floodedPercent ?? 0;
    return floodB - floodA;
  });
}

/**
 * Builds an adjacency network graph from road features, separating unflooded roads
 * from flooded (submerged) corridors. Consecutive polyline segments are stored
 * so intermediate T-junctions and crossings connect topologically.
 *
 * @param {object} roadsGeoJSON GeoJSON FeatureCollection
 * @param {object} options
 * @returns {{
 *   dryGraph: Map<string, Array<{ to: string, dist: number, wayId: string, coords: Array<[number, number]> }>>,
 *   dryRoads: Array<object>,
 *   floodedRoads: Array<object>
 * }}
 */
export function buildRoadNetwork(roadsGeoJSON, options = {}) {
  const dryGraph = new Map();
  const dryRoads = [];
  const floodedRoads = [];

  const features = Array.isArray(roadsGeoJSON?.features) ? roadsGeoJSON.features : [];
  const snapTolerance = typeof options.snappingToleranceM === 'number' ? options.snappingToleranceM : 15.0;

  features.forEach((feat) => {
    const isFlooded = Boolean(feat.properties?.flooded);
    const lines = getLineStringsFromFeature(feat);
    const wayId = feat.properties?.id || 'way-unidentified';

    if (isFlooded) {
      floodedRoads.push(feat);
    } else {
      dryRoads.push(feat);
      lines.forEach((coords) => {
        if (coords.length < 2) return;
        for (let i = 0; i < coords.length - 1; i++) {
          const u = nodeKey(coords[i]);
          const v = nodeKey(coords[i + 1]);
          const dist = haversineDistance(coords[i], coords[i + 1]);

          if (!dryGraph.has(u)) dryGraph.set(u, []);
          if (!dryGraph.has(v)) dryGraph.set(v, []);

          dryGraph.get(u).push({ to: v, dist, wayId, coords: [coords[i], coords[i + 1]] });
          dryGraph.get(v).push({ to: u, dist, wayId, coords: [coords[i + 1], coords[i]] });
        }
      });
    }
  });

  // Snap proximate unflooded road endpoints/junctions across tile seams
  if (snapTolerance > 0 && dryGraph.size > 0) {
    const allNodes = [...dryGraph.keys()];
    const allCoords = allNodes.map((k) => k.split(',').map(Number));
    for (let i = 0; i < allNodes.length; i++) {
      for (let j = i + 1; j < allNodes.length; j++) {
        const d = haversineDistance(allCoords[i], allCoords[j]);
        if (d > 0 && d <= snapTolerance) {
          dryGraph.get(allNodes[i]).push({ to: allNodes[j], dist: d, wayId: 'junction-snap', coords: [allCoords[i], allCoords[j]] });
          dryGraph.get(allNodes[j]).push({ to: allNodes[i], dist: d, wayId: 'junction-snap', coords: [allCoords[j], allCoords[i]] });
        }
      }
    }
  }

  return { dryGraph, dryRoads, floodedRoads };
}

/**
 * Indexes road network segments that touch or pass through each candidate zone.
 *
 * @param {Array<object>} zones 
 * @param {object} roadsGeoJSON 
 * @returns {Map<string, { totalRoads: number, floodedRoads: number, dryRoads: number, dryWays: Array<object>, floodedWays: Array<object> }>}
 */
export function indexZoneRoads(zones, roadsGeoJSON) {
  const zoneIndex = new Map();
  const features = Array.isArray(roadsGeoJSON?.features) ? roadsGeoJSON.features : [];

  zones.forEach((zone) => {
    const zoneId = zone.zone_id || zone.zoneId;
    const bbox = getZoneBBox(zone);

    if (!bbox) {
      zoneIndex.set(zoneId, {
        totalRoads: 0,
        floodedRoads: 0,
        dryRoads: 0,
        dryWays: [],
        floodedWays: [],
      });
      return;
    }

    const dryWays = [];
    const floodedWays = [];

    features.forEach((feat) => {
      const lines = getLineStringsFromFeature(feat);
      const touches = lines.some((coords) =>
        coords.some(([x, y]) => x >= bbox[0] && x <= bbox[2] && y >= bbox[1] && y <= bbox[3])
      );

      if (touches) {
        if (feat.properties?.flooded) {
          floodedWays.push(feat);
        } else {
          dryWays.push(feat);
        }
      }
    });

    zoneIndex.set(zoneId, {
      totalRoads: dryWays.length + floodedWays.length,
      floodedRoads: floodedWays.length,
      dryRoads: dryWays.length,
      dryWays,
      floodedWays,
    });
  });

  return zoneIndex;
}

/**
 * Shortest path search across unflooded network using Dijkstra algorithm.
 *
 * @param {Array<string>} startNodes 
 * @param {Map<string, object>} targetNodeMap 
 * @param {Map<string, Array<object>>} dryGraph 
 * @returns {{ dist: number, pathEdges: Array<object>, endNode: string, targetInfo: object }|null}
 */
export function dijkstra(startNodes, targetNodeMap, dryGraph) {
  if (!startNodes || startNodes.length === 0 || !targetNodeMap || targetNodeMap.size === 0) {
    return null;
  }

  const dist = new Map();
  const prev = new Map();
  const pq = [];

  startNodes.forEach((s) => {
    dist.set(s, 0);
    pq.push({ node: s, d: 0 });
  });

  let reachedTarget = null;

  while (pq.length > 0) {
    pq.sort((a, b) => a.d - b.d);
    const { node: curr, d } = pq.shift();

    if (targetNodeMap.has(curr)) {
      reachedTarget = curr;
      break;
    }

    if (d > (dist.get(curr) ?? Infinity)) continue;

    for (const edge of (dryGraph.get(curr) || [])) {
      const nextD = d + edge.dist;
      if (nextD < (dist.get(edge.to) ?? Infinity)) {
        dist.set(edge.to, nextD);
        prev.set(edge.to, { from: curr, edge });
        pq.push({ node: edge.to, d: nextD });
      }
    }
  }

  if (!reachedTarget) return null;

  const pathEdges = [];
  let curr = reachedTarget;
  while (prev.has(curr)) {
    const { from, edge } = prev.get(curr);
    pathEdges.unshift(edge);
    curr = from;
  }

  return {
    dist: dist.get(reachedTarget),
    pathEdges,
    endNode: reachedTarget,
    targetInfo: targetNodeMap.get(reachedTarget),
  };
}
/**
 * Computes or retrieves designated origin/pickup point for an evacuation zone.
 * @param {object} zone 
 * @returns {[number, number]}
 */
export function getZoneOrigin(zone) {
  if (!zone) return [0, 0];
  if (Array.isArray(zone.pickup_point) && zone.pickup_point.length >= 2 && Number.isFinite(zone.pickup_point[0]) && Number.isFinite(zone.pickup_point[1])) {
    return [zone.pickup_point[0], zone.pickup_point[1]];
  }
  if (Array.isArray(zone.origin) && zone.origin.length >= 2 && Number.isFinite(zone.origin[0]) && Number.isFinite(zone.origin[1])) {
    return [zone.origin[0], zone.origin[1]];
  }
  if (Array.isArray(zone.centroid) && zone.centroid.length >= 2 && Number.isFinite(zone.centroid[0]) && Number.isFinite(zone.centroid[1])) {
    return [zone.centroid[0], zone.centroid[1]];
  }
  const bbox = getZoneBBox(zone);
  if (bbox) {
    return [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2];
  }
  return [0, 0];
}

/**
 * Core Evacuation Route Generator.
 * Evaluates candidate affected zones (High & Medium risk), traverses only unflooded
 * road network graph, discovers reachability to verified safe facilities, and produces
 * consistent schema-compliant route objects.
 *
 * @param {{
 *   zones: Array<object>|object,
 *   roads: object,
 *   facilities: object,
 *   options?: object
 * }} param0
 * @returns {{ schema_version: string, generated_at: string, routes: Array<object> }}
 */
export function generateEvacuationRoutes({ zones, roads, facilities, options = {} }) {
  const candidateZones = identifyEvacuationZones(zones, options);
  const { dryGraph, dryRoads } = buildRoadNetwork(roads, options);
  const zoneRoadIndex = indexZoneRoads(candidateZones, roads);

  const maxFacilityAccessDistanceM = typeof options.maxFacilityAccessDistanceM === 'number'
    ? options.maxFacilityAccessDistanceM
    : 150.0;
  const maxOriginSnappingToleranceM = typeof options.maxOriginSnappingToleranceM === 'number'
    ? options.maxOriginSnappingToleranceM
    : 200.0;
  const failureStatus = options.failureStatus || 'NO_SAFE_ROUTE';

  // Evacuation destinations MUST be verified safe shelters.
  // Depots and hospitals are strictly rejected as evacuation shelters.
  const allowedFacilityTypes = (options.allowedFacilityTypes || ['shelter']).map((t) => String(t).toLowerCase());
  const facFeatures = Array.isArray(facilities?.features)
    ? facilities.features.filter((f) => allowedFacilityTypes.includes((f.properties?.type || '').toLowerCase()))
    : [];

  const targetNodeMap = new Map();

  facFeatures.forEach((fac) => {
    const facId = fac.properties?.facility_id || fac.properties?.id;
    const facName = fac.properties?.name || `Facility ${facId}`;
    const facCoords = fac.geometry?.coordinates;
    if (!facCoords || !Array.isArray(facCoords) || facCoords.length < 2) return;
    if (!Number.isFinite(facCoords[0]) || !Number.isFinite(facCoords[1])) return;

    let bestNode = null;
    let bestDist = Infinity;

    for (const n of dryGraph.keys()) {
      const [x, y] = n.split(',').map(Number);
      const d = haversineDistance(facCoords, [x, y]);
      if (d < bestDist) {
        bestDist = d;
        bestNode = n;
      }
    }

    // Facility must be accessible from an unflooded road within documented tolerance
    if (bestNode && bestDist <= maxFacilityAccessDistanceM) {
      targetNodeMap.set(bestNode, {
        facilityId: facId,
        facilityName: facName,
        facilityCoords: [facCoords[0], facCoords[1]],
        accessDist: bestDist,
      });
    }
  });

  const routes = [];

  candidateZones.forEach((zone) => {
    const zoneId = zone.zone_id || zone.zoneId;
    const zoneName = zone.name || `Zone ${zoneId}`;
    const riskLevel = zone.risk_level || zone.riskLevel || 'UNKNOWN';
    const zoneInfo = zoneRoadIndex.get(zoneId) || {
      totalRoads: 0,
      floodedRoads: 0,
      dryRoads: 0,
      dryWays: [],
      floodedWays: [],
    };
    const routeId = `route-evac-${zoneId}`;
    const originCoords = getZoneOrigin(zone);

    // Condition A: No road network data available
    if (zoneInfo.totalRoads === 0 && dryRoads.length === 0) {
      routes.push({
        route_id: routeId,
        zone_id: zoneId,
        zone_name: zoneName,
        risk_level: riskLevel,
        origin_id: `pickup-${zoneId}`,
        origin_coords: originCoords,
        origin_type: 'zone_origin',
        destination_id: null,
        destination_name: null,
        destination_coords: null,
        status: failureStatus,
        distance_m: null,
        eta_minutes: null,
        provenance: 'derived',
        reason: `No road network data available for ${zoneId} to compute evacuation routing.`,
        geometry: null,
      });
      return;
    }

    // Condition B: 100% of connecting roads are flooded (Surface access completely severed)
    if (zoneInfo.dryRoads === 0) {
      routes.push({
        route_id: routeId,
        zone_id: zoneId,
        zone_name: zoneName,
        risk_level: riskLevel,
        origin_id: `pickup-${zoneId}`,
        origin_coords: originCoords,
        origin_type: 'zone_origin',
        destination_id: null,
        destination_name: null,
        destination_coords: null,
        status: failureStatus,
        distance_m: null,
        eta_minutes: null,
        provenance: 'derived',
        reason: zoneInfo.totalRoads > 0
          ? `Surface road access severed: all ${zoneInfo.totalRoads} road segments in ${zoneId} are flooded. Overland vehicle evacuation is impossible.`
          : `No road infrastructure found in ${zoneId} to establish an egress route.`,
        geometry: null,
      });
      return;
    }

    // Condition C: No designated safe destination facilities
    if (targetNodeMap.size === 0) {
      routes.push({
        route_id: routeId,
        zone_id: zoneId,
        zone_name: zoneName,
        risk_level: riskLevel,
        origin_id: `pickup-${zoneId}`,
        origin_coords: originCoords,
        origin_type: 'zone_origin',
        destination_id: null,
        destination_name: null,
        destination_coords: null,
        status: failureStatus,
        distance_m: null,
        eta_minutes: null,
        provenance: 'derived',
        reason: 'No verified safe destination shelters designated within unflooded territory.',
        geometry: null,
      });
      return;
    }

    // Condition D: Collect unflooded road network nodes touching this zone
    const dryNodes = [];
    zoneInfo.dryWays.forEach((feat) => {
      getLineStringsFromFeature(feat).forEach((coords) => {
        coords.forEach((pt) => {
          if (Array.isArray(pt) && pt.length >= 2 && Number.isFinite(pt[0]) && Number.isFinite(pt[1])) {
            const k = nodeKey(pt);
            if (dryGraph.has(k)) {
              dryNodes.push({ key: k, pt: [pt[0], pt[1]] });
            }
          }
        });
      });
    });

    const uniqueCandidateNodes = [];
    const seenKeys = new Set();
    dryNodes.forEach((n) => {
      if (!seenKeys.has(n.key)) {
        seenKeys.add(n.key);
        uniqueCandidateNodes.push(n);
      }
    });

    if (uniqueCandidateNodes.length === 0) {
      routes.push({
        route_id: routeId,
        zone_id: zoneId,
        zone_name: zoneName,
        risk_level: riskLevel,
        origin_id: `pickup-${zoneId}`,
        origin_coords: originCoords,
        origin_type: 'zone_origin',
        destination_id: null,
        destination_name: null,
        destination_coords: null,
        status: failureStatus,
        distance_m: null,
        eta_minutes: null,
        provenance: 'derived',
        reason: `No passable road nodes found within ${zoneId} to establish an egress route.`,
        geometry: null,
      });
      return;
    }

    // Evaluate candidate origin nodes to find shortest safe egress corridor
    let bestPath = null;
    let bestOrigin = null;
    let minOriginDist = Infinity;

    for (const cand of uniqueCandidateNodes) {
      const res = dijkstra([cand.key], targetNodeMap, dryGraph);
      if (res) {
        const dToOrigin = haversineDistance(originCoords, cand.pt);
        if (dToOrigin <= maxOriginSnappingToleranceM) {
          if (dToOrigin < minOriginDist - 1 || (Math.abs(dToOrigin - minOriginDist) <= 1 && res.dist < (bestPath?.dist ?? Infinity))) {
            minOriginDist = dToOrigin;
            bestPath = res;
            bestOrigin = cand;
          }
        }
      }
    }

    if (!bestPath || !bestOrigin) {
      // Disconnected dry pocket cut off by surrounding flood barriers or no shelter reachable
      routes.push({
        route_id: routeId,
        zone_id: zoneId,
        zone_name: zoneName,
        risk_level: riskLevel,
        origin_id: `pickup-${zoneId}`,
        origin_coords: originCoords,
        origin_type: 'zone_origin',
        destination_id: null,
        destination_name: null,
        destination_coords: null,
        status: failureStatus,
        distance_m: null,
        eta_minutes: null,
        provenance: 'derived',
        reason: `Overland evacuation blocked: dry road segments exist within ${zoneId}, but all egress corridors toward safe emergency facilities are blocked by floodwaters.`,
        geometry: null,
      });
      return;
    }

    // Assemble continuous coordinates strictly following connected road network edges
    const lineCoords = [bestOrigin.pt];
    bestPath.pathEdges.forEach((edge) => {
      const c = edge.coords;
      const last = lineCoords[lineCoords.length - 1];
      if (haversineDistance(last, c[0]) < 1e-3) {
        lineCoords.push(c[1]);
      } else if (haversineDistance(last, c[1]) < 1e-3) {
        lineCoords.push(c[0]);
      } else {
        lineCoords.push(c[0], c[1]);
      }
    });

    // Connect final access leg to shelter marker within documented tolerance
    if (bestPath.targetInfo?.facilityCoords) {
      const facPt = bestPath.targetInfo.facilityCoords;
      const last = lineCoords[lineCoords.length - 1];
      const shelterAccessDist = haversineDistance(last, facPt);
      if (shelterAccessDist > 0.01 && shelterAccessDist <= maxFacilityAccessDistanceM) {
        lineCoords.push(facPt);
      }
    }

    let totalDistance = 0;
    for (let i = 0; i < lineCoords.length - 1; i++) {
      totalDistance += haversineDistance(lineCoords[i], lineCoords[i + 1]);
    }
    totalDistance = Math.round(totalDistance);
    // Assume 30 km/h emergency transit speed (~500 m/min)
    const etaMinutes = Math.max(1, Math.round(totalDistance / 500));

    routes.push({
      route_id: routeId,
      zone_id: zoneId,
      zone_name: zoneName,
      risk_level: riskLevel,
      origin_id: `pickup-${zoneId}`,
      origin_coords: bestOrigin.pt,
      origin_type: 'road_pickup_point',
      destination_id: bestPath.targetInfo?.facilityId || 'safe-haven',
      destination_name: bestPath.targetInfo?.facilityName || 'Safe Emergency Facility',
      destination_coords: bestPath.targetInfo?.facilityCoords || null,
      status: 'OK',
      distance_m: totalDistance,
      eta_minutes: etaMinutes,
      provenance: 'derived',
      reason: `Continuous evacuation corridor via unflooded road network to ${bestPath.targetInfo?.facilityName}.`,
      geometry: {
        type: 'LineString',
        coordinates: lineCoords,
      },
    });
  });

  return {
    schema_version: '1.0',
    generated_at: new Date().toISOString(),
    routes,
  };
}
