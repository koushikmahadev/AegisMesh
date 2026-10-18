import React, { useEffect, useRef, useState, useMemo } from 'react';
import * as THREE from 'three';
import { RotateCw, RotateCcw, RefreshCcw, Box, Eye, Layers } from 'lucide-react';

/**
 * ReliefView (3D Relief Projection of Survey Tiles)
 * Honest 3D cartographic visualization where column heights strictly represent
 * real event counts in abstract "scene units" (never physical metres).
 */
export default function ReliefView({
  zones = [],
  selectedZoneId = null,
  onSelectZone = () => {},
  groundTruthData = null,
  modelMode = 'fast',
}) {
  const mountRef = useRef(null);
  const [metric, setMetric] = useState('observed_features'); // 'observed_features' | 'observed_buildings' | 'model_pixels'
  const [hoveredTile, setHoveredTile] = useState(null);
  const [cameraAzimuth, setCameraAzimuth] = useState(45); // Degrees
  const [cameraPolar, setCameraPolar] = useState(55); // Degrees

  // Scene references
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const rendererRef = useRef(null);
  const meshMapRef = useRef(new Map());
  const reqIdRef = useRef(null);

  // Filter valid zones with geometry
  const validZones = useMemo(() => {
    return zones.filter((z) => z.geometry && z.geometry.coordinates);
  }, [zones]);

  // Compute spatial bounding center
  const centerCoords = useMemo(() => {
    if (validZones.length === 0) return { lng: 7.04, lat: 50.53 };
    let sumLng = 0;
    let sumLat = 0;
    let count = 0;
    for (const z of validZones) {
      const ring = z.geometry.coordinates[0];
      if (Array.isArray(ring)) {
        for (const pt of ring) {
          sumLng += pt[0];
          sumLat += pt[1];
          count++;
        }
      }
    }
    return count > 0 ? { lng: sumLng / count, lat: sumLat / count } : { lng: 7.04, lat: 50.53 };
  }, [validZones]);

  // Extract count for selected metric
  const getMetricValue = (zone, m) => {
    if (m === 'observed_buildings') {
      return typeof zone.exposedBuildings === 'number' ? zone.exposedBuildings : 0;
    }
    if (m === 'model_pixels') {
      if (Array.isArray(zone.reasons)) {
        const maskLine = zone.reasons.find((r) => r.includes('mask pixels'));
        if (maskLine) {
          const match = maskLine.match(/mask pixels:\s*(\d+)\s*\(fast\s*mode\),\s*(\d+)\s*\(accurate\s*mode\)/i);
          if (match) {
            return modelMode === 'accurate' ? Number(match[2]) : Number(match[1]);
          }
        }
      }
      return 0;
    }
    // Default: observed features
    if (typeof zone.observed_flooded_count === 'number') return zone.observed_flooded_count;
    return typeof zone.exposedBuildings === 'number' ? zone.exposedBuildings : 0;
  };

  const metricLabel = useMemo(() => {
    if (metric === 'observed_buildings') return 'Observed flooded buildings (labels)';
    if (metric === 'model_pixels') return `Model mask pixels (${modelMode} mode)`;
    return 'Observed flooded features (labels)';
  }, [metric, modelMode]);

  const maxVal = useMemo(() => {
    let m = 1;
    for (const z of validZones) {
      const v = getMetricValue(z, metric);
      if (v > m) m = v;
    }
    return m;
  }, [validZones, metric, modelMode]);

  // Initialize Three.js scene
  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    const width = container.clientWidth || 600;
    const height = container.clientHeight || 450;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#F6F3ED'); // Cartographic paper color
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(40, width / height, 1, 1000);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    rendererRef.current = renderer;

    container.innerHTML = '';
    container.appendChild(renderer.domElement);

    // Directional and ambient cartographic illumination
    const ambientLight = new THREE.AmbientLight(0xFFFFFF, 0.7);
    scene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight(0xFFFBF0, 0.8);
    sunLight.position.set(50, 80, 40);
    scene.add(sunLight);

    // Ground plane reference grid (subtle cartographic hairline)
    const gridHelper = new THREE.GridHelper(120, 24, 0xDCD6CA, 0xEBE6DC);
    gridHelper.position.y = -0.1;
    scene.add(gridHelper);

    // Update camera position from polar coordinates
    const updateCameraPos = (azimuthDeg, polarDeg) => {
      const radius = 90;
      const phi = (polarDeg * Math.PI) / 180;
      const theta = (azimuthDeg * Math.PI) / 180;
      camera.position.x = radius * Math.sin(phi) * Math.sin(theta);
      camera.position.y = radius * Math.cos(phi);
      camera.position.z = radius * Math.sin(phi) * Math.cos(theta);
      camera.lookAt(0, 4, 0);
    };

    updateCameraPos(cameraAzimuth, cameraPolar);

    // Mouse drag interaction
    let isDragging = false;
    let prevMouseX = 0;
    let prevMouseY = 0;

    const onMouseDown = (e) => {
      isDragging = true;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;
    };

    const onMouseMove = (e) => {
      if (!isDragging) {
        // Raycasting for hover tooltip
        const rect = renderer.domElement.getBoundingClientRect();
        const mouse = new THREE.Vector2(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          -((e.clientY - rect.top) / rect.height) * 2 + 1
        );
        const raycaster = new THREE.Raycaster();
        raycaster.setFromCamera(mouse, camera);

        const meshes = Array.from(meshMapRef.current.values());
        const intersects = raycaster.intersectObjects(meshes, true);
        if (intersects.length > 0) {
          const hit = intersects[0].object;
          if (hit.userData && hit.userData.zoneId) {
            setHoveredTile({
              zoneId: hit.userData.zoneId,
              name: hit.userData.name,
              value: hit.userData.value,
              heightUnits: hit.userData.heightUnits,
              inTrainingPool: hit.userData.inTrainingPool,
              x: e.clientX - rect.left,
              y: e.clientY - rect.top,
            });
            return;
          }
        }
        setHoveredTile(null);
        return;
      }

      const deltaX = e.clientX - prevMouseX;
      const deltaY = e.clientY - prevMouseY;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;

      setCameraAzimuth((prev) => (prev + deltaX * 0.5) % 360);
      setCameraPolar((prev) => Math.max(15, Math.min(85, prev - deltaY * 0.5)));
    };

    const onMouseUp = () => {
      isDragging = false;
    };

    const onClick = (e) => {
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(mouse, camera);

      const meshes = Array.from(meshMapRef.current.values());
      const intersects = raycaster.intersectObjects(meshes, true);
      if (intersects.length > 0) {
        const hit = intersects[0].object;
        if (hit.userData && hit.userData.zoneId) {
          onSelectZone(hit.userData.zoneId);
        }
      }
    };

    const dom = renderer.domElement;
    dom.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    dom.addEventListener('click', onClick);

    // Animation render loop
    const animate = () => {
      reqIdRef.current = requestAnimationFrame(animate);
      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      if (!container || !renderer || !camera) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      if (reqIdRef.current) cancelAnimationFrame(reqIdRef.current);
      dom.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      dom.removeEventListener('click', onClick);
      window.removeEventListener('resize', handleResize);
      renderer.dispose();
    };
  }, []);

  // Update camera on azimuth / polar state change
  useEffect(() => {
    if (!cameraRef.current) return;
    const radius = 90;
    const phi = (cameraPolar * Math.PI) / 180;
    const theta = (cameraAzimuth * Math.PI) / 180;
    cameraRef.current.position.x = radius * Math.sin(phi) * Math.sin(theta);
    cameraRef.current.position.y = radius * Math.cos(phi);
    cameraRef.current.position.z = radius * Math.sin(phi) * Math.cos(theta);
    cameraRef.current.lookAt(0, 4, 0);
  }, [cameraAzimuth, cameraPolar]);

  // Build / update 3D Tile Slabs & Columns
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    // Clear existing objects
    meshMapRef.current.forEach((obj) => scene.remove(obj));
    meshMapRef.current.clear();

    const group = new THREE.Group();

    validZones.forEach((z) => {
      const ring = z.geometry.coordinates[0];
      if (!Array.isArray(ring) || ring.length === 0) return;

      // Calculate centroid in local coordinates
      let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
      ring.forEach(([lng, lat]) => {
        if (lng < minLng) minLng = lng;
        if (lng > maxLng) maxLng = lng;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
      });

      const centerLng = (minLng + maxLng) / 2;
      const centerLat = (minLat + maxLat) / 2;

      // Project degrees to local scene units (scaled to fit ~80 units viewport)
      const scaleCoord = 5000;
      const x = (centerLng - centerCoords.lng) * scaleCoord;
      const zPos = -(centerLat - centerCoords.lat) * scaleCoord;
      const slabW = Math.max(3, (maxLng - minLng) * scaleCoord);
      const slabD = Math.max(3, (maxLat - minLat) * scaleCoord);

      const val = getMetricValue(z, metric);
      // Normalized height strictly in scene units (max 18 scene units)
      const heightUnits = Math.max(0.4, Number(((val / (maxVal || 1)) * 18).toFixed(1)));

      const isSelected = z.zoneId === selectedZoneId;

      // 1. Tile Base Slab
      const slabGeo = new THREE.BoxGeometry(slabW, 0.4, slabD);
      const slabMat = new THREE.MeshLambertMaterial({
        color: isSelected ? 0xDCD6CA : 0xEDE8DC,
      });
      const slabMesh = new THREE.Mesh(slabGeo, slabMat);
      slabMesh.position.set(x, 0.2, zPos);
      slabMesh.userData = { zoneId: z.zoneId, name: z.name, value: val, heightUnits, inTrainingPool: z.in_training_pool };

      // 2. Vertical Column Encoding Metric in Scene Units
      const colGeo = new THREE.BoxGeometry(slabW * 0.5, heightUnits, slabD * 0.5);
      const colColor = metric === 'model_pixels'
        ? (isSelected ? 0x1E3A8A : 0x2563EB)
        : (isSelected ? 0x9A3412 : 0xC2410C);

      const colMat = new THREE.MeshLambertMaterial({ color: colColor });
      const colMesh = new THREE.Mesh(colGeo, colMat);
      colMesh.position.set(x, 0.4 + heightUnits / 2, zPos);
      colMesh.userData = { zoneId: z.zoneId, name: z.name, value: val, heightUnits, inTrainingPool: z.in_training_pool };

      // Add to group & mapping
      group.add(slabMesh);
      group.add(colMesh);
      meshMapRef.current.set(`${z.zoneId}-slab`, slabMesh);
      meshMapRef.current.set(`${z.zoneId}-col`, colMesh);
    });

    scene.add(group);

    return () => {
      scene.remove(group);
    };
  }, [validZones, centerCoords, metric, modelMode, maxVal, selectedZoneId]);

  return (
    <div className="relative w-full h-full flex flex-col font-sans select-none bg-paper">
      {/* 3D Viewport Controls & Legend Bar */}
      <div className="p-3 border-b border-hairline bg-plate flex flex-wrap items-center justify-between gap-2.5 text-xs">
        {/* Metric Selector */}
        <div className="flex items-center space-x-2">
          <span className="font-serif font-semibold text-ink">Encoding:</span>
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            aria-label="Select metric to encode as column height"
            className="p-1.5 rounded border border-control-border bg-paper text-ink text-xs focus:outline-none cursor-pointer"
          >
            <option value="observed_features">Observed Flooded Features (Labels)</option>
            <option value="observed_buildings">Observed Flooded Buildings</option>
            <option value="model_pixels">Model Mask Pixels ({modelMode})</option>
          </select>
        </div>

        {/* Camera Rotation Controls */}
        <div className="flex items-center space-x-1.5">
          <button
            type="button"
            onClick={() => setCameraAzimuth((prev) => (prev - 30) % 360)}
            title="Rotate projection 30° left"
            aria-label="Rotate projection 30° left"
            className="p-1.5 rounded border border-control-border bg-paper hover:bg-hairline/40 text-ink cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setCameraAzimuth((prev) => (prev + 30) % 360)}
            title="Rotate projection 30° right"
            aria-label="Rotate projection 30° right"
            className="p-1.5 rounded border border-control-border bg-paper hover:bg-hairline/40 text-ink cursor-pointer"
          >
            <RotateCw className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              setCameraAzimuth(45);
              setCameraPolar(55);
            }}
            title="Reset projection angle"
            aria-label="Reset projection angle"
            className="p-1.5 rounded border border-control-border bg-paper hover:bg-hairline/40 text-ink cursor-pointer"
          >
            <RefreshCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* WebGL Canvas Container */}
      <div className="relative flex-1 w-full min-h-[380px] overflow-hidden" ref={mountRef}>
        {/* Interactive Hover Tooltip */}
        {hoveredTile && (
          <div
            className="absolute z-20 pointer-events-none p-2 rounded bg-ink text-paper text-xs shadow-md space-y-0.5"
            style={{
              left: `${Math.min(hoveredTile.x + 12, (mountRef.current?.clientWidth || 500) - 220)}px`,
              top: `${Math.max(hoveredTile.y - 45, 10)}px`,
            }}
          >
            <span className="font-serif font-bold block">{hoveredTile.name}</span>
            <span className="block text-[11px] font-mono">
              Count: {hoveredTile.value.toLocaleString('en-US')}
            </span>
            <span className="block text-[10px] text-paper/80 italic">
              Height: {hoveredTile.heightUnits} scene units (not metres)
            </span>
            {hoveredTile.inTrainingPool !== undefined && (
              <span className="block text-[10px] text-paper/70">
                {hoveredTile.inTrainingPool ? '• In training pool' : '• Not in training pool'}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Cartographic Relief Legend Block */}
      <div className="p-2.5 bg-plate border-t border-hairline flex flex-wrap items-center justify-between text-[11px] text-ink-muted gap-2">
        <div className="flex items-center space-x-2">
          <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: metric === 'model_pixels' ? '#1E3A8A' : '#9A3412' }} />
          <span>
            Column height encodes <strong className="text-ink font-medium">{metricLabel}</strong> in <em>scene units</em> (1 to 18 units max).
          </span>
        </div>
        <span className="font-mono text-[10px]">
          Units do NOT represent physical elevation metres.
        </span>
      </div>

      {/* Screen-reader Accessible Data Summary Table */}
      <div className="sr-only">
        <table>
          <caption>3D Relief Projection Survey Tiles Data</caption>
          <thead>
            <tr>
              <th scope="col">Tile</th>
              <th scope="col">Observed Flooded Count</th>
              <th scope="col">Column Height (Scene Units)</th>
              <th scope="col">Training Pool Status</th>
            </tr>
          </thead>
          <tbody>
            {validZones.map((z) => (
              <tr key={z.zoneId}>
                <td>{z.name}</td>
                <td>{getMetricValue(z, metric)}</td>
                <td>{((getMetricValue(z, metric) / (maxVal || 1)) * 18).toFixed(1)}</td>
                <td>{z.in_training_pool ? 'In pool' : 'Not in pool'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
