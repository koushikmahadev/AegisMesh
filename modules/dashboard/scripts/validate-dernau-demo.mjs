import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DIR = path.resolve(__dirname, '../public/mock-data-dernau');
const SAMPLES_DIR = path.resolve(__dirname, '../integration-samples');

let errors = [];
let warnings = [];

function assert(condition, message) {
  if (!condition) {
    errors.push(message);
    console.error(`  FAIL: ${message}`);
  }
}

function isValidLngLat(coord) {
  if (!Array.isArray(coord) || coord.length < 2) return false;
  const [lng, lat] = coord;
  return typeof lng === 'number' && Number.isFinite(lng) && lng >= -180 && lng <= 180 &&
         typeof lat === 'number' && Number.isFinite(lat) && lat >= -90 && lat <= 90;
}

function isClosedRing(ring) {
  if (!Array.isArray(ring) || ring.length < 4) return false;
  const first = ring[0];
  const last = ring[ring.length - 1];
  return first[0] === last[0] && first[1] === last[1];
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function runValidation() {
  console.log('=== HighWater Dernau Demo Dataset Validator ===');
  console.log(`Directory: ${DIR}\n`);

  if (!fs.existsSync(DIR)) {
    console.error(`Target directory does not exist: ${DIR}`);
    process.exit(1);
  }

  const meta = JSON.parse(fs.readFileSync(path.join(SAMPLES_DIR, 'metadata.json'), 'utf8'));
  const aoiBbox = meta.aoi_bbox_lonlat;
  const aoiTolerance = 0.0005;

  // -------------------------------------------------------------------------
  // 1. zones.json validation
  // -------------------------------------------------------------------------
  console.log('1. Validating zones.json...');
  const zonesPath = path.join(DIR, 'zones.json');
  assert(fs.existsSync(zonesPath), 'zones.json exists');
  const zonesData = JSON.parse(fs.readFileSync(zonesPath, 'utf8'));

  assert(zonesData.schema_version === '1.0', 'schema_version is "1.0"');
  assert(zonesData.data_mode === 'demo', 'data_mode is "demo"');
  assert(zonesData.crs === 'EPSG:4326', 'crs is "EPSG:4326"');
  assert(typeof zonesData.generated_at === 'string' && !isNaN(Date.parse(zonesData.generated_at)), 'generated_at is a valid ISO timestamp');
  assert(typeof zonesData.risk_method === 'string' && zonesData.risk_method.includes('0.40'), 'risk_method formula is documented');
  assert(Array.isArray(zonesData.zones), 'zones is an array');
  assert(zonesData.zones.length === 38, `Expected 38 zones, got ${zonesData.zones?.length}`);

  let nullGeomCount = 0;
  let nullNumericCount = 0;
  const nullGeomZoneIds = [];
  const nullNumericZoneIds = [];
  const riskCounts = { HIGH: 0, MEDIUM: 0, LOW: 0, UNKNOWN: 0 };

  zonesData.zones.forEach((z) => {
    assert(typeof z.zone_id === 'string' && z.zone_id.startsWith('zone-'), `${z.zone_id}: valid zone_id format`);
    assert(typeof z.name === 'string' && z.name.length > 0, `${z.zone_id}: name is non-empty string`);
    assert(['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'].includes(z.risk_level), `${z.zone_id}: valid risk_level`);
    riskCounts[z.risk_level] = (riskCounts[z.risk_level] || 0) + 1;

    if (z.risk_level === 'UNKNOWN') {
      assert(z.risk_score === null, `${z.zone_id}: UNKNOWN risk zone must have null risk_score`);
    } else {
      assert(typeof z.risk_score === 'number' && z.risk_score >= 0 && z.risk_score <= 100, `${z.zone_id}: valid risk_score (0-100)`);
    }

    assert(typeof z.flooded_percent === 'number' && z.flooded_percent >= 0, `${z.zone_id}: valid flooded_percent`);
    assert(typeof z.flooded_area_km2 === 'number' && z.flooded_area_km2 >= 0, `${z.zone_id}: valid flooded_area_km2`);
    assert(['OPEN', 'LIMITED', 'BLOCKED', 'UNKNOWN'].includes(z.accessibility), `${z.zone_id}: valid accessibility enum`);
    assert(Array.isArray(z.reasons) && z.reasons.length > 0, `${z.zone_id}: reasons is non-empty array of strings`);

    if (z.zone_id === 'zone-018' || z.zone_id === 'zone-005') {
      const hasDesignatedNote = z.reasons.some((r) => r.toLowerCase().includes('designated test case'));
      assert(hasDesignatedNote, `${z.zone_id}: reasons explicitly marks as designated test case`);
    }

    if (z.exposed_buildings === null) {
      nullNumericCount++;
      nullNumericZoneIds.push(z.zone_id);
    } else {
      assert(typeof z.exposed_buildings === 'number' && z.exposed_buildings >= 0, `${z.zone_id}: exposed_buildings is number or null`);
    }

    if (z.geometry === null) {
      nullGeomCount++;
      nullGeomZoneIds.push(z.zone_id);
      assert(z.risk_level === 'LOW', `${z.zone_id}: null geometry edge case must be a LOW-risk zone`);
    } else {
      assert(z.geometry.type === 'Polygon', `${z.zone_id}: geometry type is Polygon`);
      assert(Array.isArray(z.geometry.coordinates) && z.geometry.coordinates.length === 1, `${z.zone_id}: single ring polygon`);
      const ring = z.geometry.coordinates[0];
      assert(isClosedRing(ring), `${z.zone_id}: polygon ring is closed`);
      assert(ring.length === 5, `${z.zone_id}: rectangle polygon has 5 coordinates`);
      ring.forEach((pt) => {
        assert(isValidLngLat(pt), `${z.zone_id}: valid [lng, lat] coordinate`);
      });
    }
  });

  const zone038 = zonesData.zones.find((z) => z.zone_id === 'zone-038');
  assert(zone038 && zone038.geometry !== null, 'zone-038 has valid geometry and is kept on the map');

  assert(nullGeomCount === 1, `Exactly 1 zone with null geometry (found ${nullGeomCount}: ${nullGeomZoneIds.join(', ')})`);
  assert(nullGeomZoneIds[0] === 'zone-009', `Null geometry zone is zone-009 (found: ${nullGeomZoneIds.join(', ')})`);
  assert(nullNumericCount === 1, `Exactly 1 zone with null numeric field (found ${nullNumericCount}: ${nullNumericZoneIds.join(', ')})`);
  assert(nullNumericZoneIds[0] === 'zone-005', `Null numeric zone is zone-005 (found: ${nullNumericZoneIds.join(', ')})`);
  assert(riskCounts.UNKNOWN >= 1, `At least 1 UNKNOWN risk zone (found ${riskCounts.UNKNOWN})`);
  assert(riskCounts.HIGH >= 1, `At least 1 HIGH risk zone (found ${riskCounts.HIGH})`);
  assert(riskCounts.MEDIUM >= 1, `At least 1 MEDIUM risk zone (found ${riskCounts.MEDIUM})`);
  assert(riskCounts.LOW >= 1, `At least 1 LOW risk zone (found ${riskCounts.LOW})`);

  console.log(`  -> Checked 38 zones: HIGH=${riskCounts.HIGH}, MEDIUM=${riskCounts.MEDIUM}, LOW=${riskCounts.LOW}, UNKNOWN=${riskCounts.UNKNOWN}`);
  console.log(`  -> Null geometry edge case: ${nullGeomZoneIds.join(', ')} (LOW risk)`);
  console.log(`  -> Null numeric field edge case: ${nullNumericZoneIds.join(', ')} (exposed_buildings)`);
  console.log(`  -> zone-038 status: geometry is Polygon (kept on map, risk ${zone038.risk_level})`);

  // -------------------------------------------------------------------------
  // 2. flood_extent.geojson validation (with 0.0005 deg tolerance)
  // -------------------------------------------------------------------------
  console.log('\n2. Validating flood_extent.geojson...');
  const floodPath = path.join(DIR, 'flood_extent.geojson');
  assert(fs.existsSync(floodPath), 'flood_extent.geojson exists');
  const floodData = JSON.parse(fs.readFileSync(floodPath, 'utf8'));

  assert(floodData.type === 'FeatureCollection', 'flood_extent is a FeatureCollection');
  assert(Array.isArray(floodData.features) && floodData.features.length === 196, `Expected exactly 196 features, got ${floodData.features?.length}`);

  let floodBadCoords = 0;
  let floodUnclosedRings = 0;
  let floodInventedZoneIds = 0;

  floodData.features.forEach((feat, idx) => {
    assert(feat.type === 'Feature', `Feature ${idx}: valid type`);
    assert(['Polygon', 'MultiPolygon'].includes(feat.geometry?.type), `Feature ${idx}: geometry is Polygon or MultiPolygon`);
    assert(typeof feat.properties?.feature_id === 'string', `Feature ${idx}: feature_id present`);
    assert(feat.properties?.flood_status === 'flooded', `Feature ${idx}: flood_status is "flooded"`);
    assert(feat.properties?.provenance === 'derived', `Feature ${idx}: provenance is "derived"`);
    if (feat.properties?.zone_id !== undefined) {
      floodInventedZoneIds++;
    }

    const rings = feat.geometry.type === 'Polygon' ? feat.geometry.coordinates : feat.geometry.coordinates.flat(1);
    rings.forEach((ring) => {
      if (!isClosedRing(ring)) floodUnclosedRings++;
      ring.forEach((pt) => {
        if (!isValidLngLat(pt)) floodBadCoords++;
        if (
          pt[0] < aoiBbox[0] - aoiTolerance ||
          pt[0] > aoiBbox[2] + aoiTolerance ||
          pt[1] < aoiBbox[1] - aoiTolerance ||
          pt[1] > aoiBbox[3] + aoiTolerance
        ) {
          floodBadCoords++;
        }
      });
    });
  });

  assert(floodInventedZoneIds === 0, 'No invented zone_id in flood_extent.geojson');
  assert(floodUnclosedRings === 0, 'All flood polygon rings are closed');
  assert(floodBadCoords === 0, 'All flood coordinates are valid [lng, lat] and within AOI bbox (0.0005 deg tolerance)');
  console.log(`  -> Checked ${floodData.features.length} flood polygons: all 196 kept, all rings closed, coordinates within AOI bbox with 0.0005 deg tolerance`);

  // -------------------------------------------------------------------------
  // 3. blocked_roads.geojson validation
  // -------------------------------------------------------------------------
  console.log('\n3. Validating blocked_roads.geojson...');
  const roadsPath = path.join(DIR, 'blocked_roads.geojson');
  assert(fs.existsSync(roadsPath), 'blocked_roads.geojson exists');
  const roadsData = JSON.parse(fs.readFileSync(roadsPath, 'utf8'));

  assert(roadsData.type === 'FeatureCollection', 'blocked_roads is FeatureCollection');
  assert(Array.isArray(roadsData.features) && roadsData.features.length === 45, `Expected 45 blocked roads, got ${roadsData.features?.length}`);

  roadsData.features.forEach((feat, idx) => {
    assert(feat.type === 'Feature', `Road ${idx}: valid type`);
    assert(feat.geometry?.type === 'LineString', `Road ${idx}: geometry is LineString`);
    assert(typeof feat.properties?.road_id === 'string', `Road ${idx}: road_id present`);
    assert(typeof feat.properties?.reason === 'string', `Road ${idx}: reason present`);
    assert(feat.properties?.provenance === 'derived', `Road ${idx}: provenance is "derived"`);
    assert(Array.isArray(feat.geometry.coordinates) && feat.geometry.coordinates.length >= 2, `Road ${idx}: at least 2 points`);
    feat.geometry.coordinates.forEach((pt) => {
      assert(isValidLngLat(pt), `Road ${idx}: valid [lng, lat] coordinate`);
    });
  });
  console.log(`  -> Checked ${roadsData.features.length} blocked road LineStrings: all valid`);

  // -------------------------------------------------------------------------
  // 4. facilities.geojson validation
  // -------------------------------------------------------------------------
  console.log('\n4. Validating facilities.geojson...');
  const facPath = path.join(DIR, 'facilities.geojson');
  assert(fs.existsSync(facPath), 'facilities.geojson exists');
  const facData = JSON.parse(fs.readFileSync(facPath, 'utf8'));

  assert(facData.type === 'FeatureCollection', 'facilities is FeatureCollection');
  assert(Array.isArray(facData.features) && facData.features.length === 3, 'Exactly 3 facilities');

  const facilityTypes = new Set();
  facData.features.forEach((feat, idx) => {
    assert(feat.geometry?.type === 'Point', `Facility ${idx}: geometry is Point`);
    assert(isValidLngLat(feat.geometry.coordinates), `Facility ${idx}: valid Point coordinate`);
    assert(typeof feat.properties?.facility_id === 'string', `Facility ${idx}: facility_id present`);
    assert(typeof feat.properties?.name === 'string', `Facility ${idx}: name present`);
    assert(['hospital', 'shelter', 'depot'].includes(feat.properties?.type), `Facility ${idx}: valid type`);
    assert(feat.properties?.provenance === 'simulated', `Facility ${idx}: provenance is "simulated"`);
    facilityTypes.add(feat.properties?.type);
  });
  assert(facilityTypes.has('hospital') && facilityTypes.has('shelter') && facilityTypes.has('depot'), 'Covers hospital, shelter, and depot');
  console.log(`  -> Checked ${facData.features.length} facilities: hospital, shelter, depot with simulated provenance`);

  // -------------------------------------------------------------------------
  // 5. routes.json validation
  // -------------------------------------------------------------------------
  console.log('\n5. Validating routes.json...');
  const routesPath = path.join(DIR, 'routes.json');
  assert(fs.existsSync(routesPath), 'routes.json exists');
  const routesData = JSON.parse(fs.readFileSync(routesPath, 'utf8'));

  assert(Array.isArray(routesData.routes), 'routes is array');
  assert(routesData.routes.length === 3, 'Exactly 3 routes');

  const okRoutes = routesData.routes.filter((r) => r.status === 'OK');
  const unreachableRoutes = routesData.routes.filter((r) => r.status === 'UNREACHABLE');

  assert(okRoutes.length === 2, `Expected 2 OK routes, got ${okRoutes.length}`);
  assert(unreachableRoutes.length === 1, `Expected 1 UNREACHABLE route, got ${unreachableRoutes.length}`);

  routesData.routes.forEach((r) => {
    assert(typeof r.route_id === 'string', `${r.route_id}: valid route_id`);
    assert(['OK', 'UNREACHABLE', 'UNKNOWN'].includes(r.status), `${r.route_id}: valid status`);
    assert(r.eta_minutes === null, `${r.route_id}: eta_minutes is null (no invented speeds)`);
    assert(r.provenance === 'simulated', `${r.route_id}: provenance is "simulated"`);

    if (r.status === 'OK') {
      assert(typeof r.distance_m === 'number' && r.distance_m > 0, `${r.route_id}: positive distance_m`);
      assert(r.geometry?.type === 'LineString', `${r.route_id}: geometry is LineString`);
      assert(Array.isArray(r.geometry.coordinates) && r.geometry.coordinates.length >= 2, `${r.route_id}: valid coordinates`);
      r.geometry.coordinates.forEach((pt) => {
        assert(isValidLngLat(pt), `${r.route_id}: valid [lng, lat] coordinate`);
      });
    } else if (r.status === 'UNREACHABLE') {
      assert(r.distance_m === null, `${r.route_id}: distance_m is null for UNREACHABLE`);
      assert(r.geometry === null, `${r.route_id}: geometry is null for UNREACHABLE`);
    }
  });
  console.log(`  -> Checked 3 routes: 2 OK with real line geometry & Haversine distance, 1 UNREACHABLE with null geometry`);

  // -------------------------------------------------------------------------
  // 6. buildings_exposed.geojson validation
  // -------------------------------------------------------------------------
  console.log('\n6. Validating buildings_exposed.geojson...');
  const bldgPath = path.join(DIR, 'buildings_exposed.geojson');
  assert(fs.existsSync(bldgPath), 'buildings_exposed.geojson exists');
  const bldgData = JSON.parse(fs.readFileSync(bldgPath, 'utf8'));
  assert(bldgData.type === 'FeatureCollection', 'buildings_exposed is FeatureCollection');
  assert(Array.isArray(bldgData.features) && bldgData.features.length === 759, 'Preserves all 759 building features');
  console.log(`  -> Checked ${bldgData.features.length} building features`);

  // -------------------------------------------------------------------------
  // 7. README.md validation
  // -------------------------------------------------------------------------
  console.log('\n7. Validating README.md...');
  const readmePath = path.join(DIR, 'README.md');
  assert(fs.existsSync(readmePath), 'README.md exists');
  const readmeText = fs.readFileSync(readmePath, 'utf8');

  assert(readmeText.includes('CC BY-SA 4.0'), 'README mentions CC BY-SA 4.0 license');
  assert(readmeText.includes('SpaceNet 8') && readmeText.includes('Maxar'), 'README mentions SpaceNet 8 / Maxar attribution');
  assert(readmeText.includes('unmodified source'), 'README notes integration-samples/ are unmodified source copies');
  assert(readmeText.includes('designated test cases, not measured data'), 'README explicitly marks test cases');
  assert(readmeText.includes('not a measured water boundary') || readmeText.includes('not a flood-extent raster') || readmeText.includes('derived'), 'README notes derived flood extent');
  assert(readmeText.includes('simulated') && readmeText.includes('Member 3'), 'README notes simulated demo values / not Member 3 output');
  assert(readmeText.includes('Dernau') && readmeText.includes('Germany'), 'README notes AOI is Dernau, Germany');
  assert(readmeText.includes('zone-009') && readmeText.includes('zone-005') && readmeText.includes('zone-018'), 'README documents the three edge cases explicitly (zone-009, zone-005, zone-018)');
  console.log('  -> Checked README.md: contains source, license, attribution, unmodified source note, derivation, simulation disclaimer, AOI location, and edge cases');

  // -------------------------------------------------------------------------
  // 8. File sizes report
  // -------------------------------------------------------------------------
  console.log('\n8. File sizes:');
  const files = fs.readdirSync(DIR);
  files.sort().forEach((file) => {
    const stat = fs.statSync(path.join(DIR, file));
    console.log(`  - ${file.padEnd(26)}: ${formatBytes(stat.size)} (${stat.size} bytes)`);
  });

  // Summary
  console.log('\n----------------------------------------');
  if (errors.length === 0) {
    console.log('ALL CHECKS PASSED: Dataset conforms strictly to architecture.md section 5.');
  } else {
    console.error(`FAILED WITH ${errors.length} ERRORS.`);
    process.exit(1);
  }
}

runValidation();
