import React, { useEffect, useRef, useState, useCallback, useMemo, Suspense, lazy } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';
import {
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  DEFAULT_AOI_BOUNDS,
  computeDataBounds,
  toLatLng,
} from '../features/map/mapUtils.js';
import FloodLayer from '../features/map/FloodLayer.jsx';
import RiskLayer from '../features/map/RiskLayer.jsx';
import FacilityLayer from '../features/map/FacilityLayer.jsx';
import RoadLayer from '../features/map/RoadLayer.jsx';
import RouteLayer from '../features/map/RouteLayer.jsx';
import BuildingLayer from '../features/map/BuildingLayer.jsx';
import FloodWatchObservedLayer from '../features/map/FloodWatchObservedLayer.jsx';
import FloodWatchPredictedLayer from '../features/map/FloodWatchPredictedLayer.jsx';
import CyberMeshLayer from '../features/map/CyberMeshLayer.jsx';
import LayerErrorBoundary from '../features/map/LayerErrorBoundary.jsx';
import MapLegend from './MapLegend.jsx';
import MapControls from './MapControls.jsx';
import { AlertTriangle, RotateCcw, PanelRightClose, PanelRightOpen, Info, ExternalLink, Search } from 'lucide-react';

const LazyReliefView = lazy(() => import('./ReliefView.jsx'));

/**
 * MapController
 * Leaflet map controller managing resize invalidation, coordinate tracking, scale measurement,
 * and view bounds.
 */
export function MapController({
  selectedZoneId,
  zones = [],
  resetTrigger = 0,
  dataBounds = null,
  onMapReady = null,
  selectedTileBounds = null,
  onCoordinatesChange = null,
  onScaleChange = null,
}) {
  const map = useMap();
  const prevSelectedIdRef = useRef(null);
  const prevTileBoundsRef = useRef(null);
  const initialFitDoneRef = useRef(false);

  useEffect(() => {
    if (onMapReady) {
      onMapReady(map);
    }
  }, [map, onMapReady]);

  // Coordinate tracking & real cartographic scale calculation (throttled for silky smooth panning)
  useEffect(() => {
    let animationFrameId = null;
    let lastRunTime = 0;

    const computeMetrics = () => {
      if (onCoordinatesChange) {
        const center = map.getCenter();
        const zoom = map.getZoom();
        const latStr = `${Math.abs(center.lat).toFixed(4)}° ${center.lat >= 0 ? 'N' : 'S'}`;
        const lngStr = `${Math.abs(center.lng).toFixed(4)}° ${center.lng >= 0 ? 'E' : 'W'}`;
        onCoordinatesChange({ lat: latStr, lng: lngStr, zoom });
      }

      if (onScaleChange) {
        const p1 = map.containerPointToLatLng([20, 20]);
        const p2 = map.containerPointToLatLng([120, 20]);
        if (p1 && p2) {
          const distMetres = map.distance(p1, p2);
          const distStr = distMetres >= 1000
            ? `${(distMetres / 1000).toFixed(1)} km`
            : `${Math.round(distMetres)} m`;
          onScaleChange(distStr);
        }
      }
    };

    const handleThrottledMove = () => {
      const now = performance.now();
      if (now - lastRunTime > 150) {
        lastRunTime = now;
        computeMetrics();
      } else if (!animationFrameId) {
        animationFrameId = requestAnimationFrame(() => {
          animationFrameId = null;
          lastRunTime = performance.now();
          computeMetrics();
        });
      }
    };

    const handleMoveEnd = () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
      }
      computeMetrics();
    };

    computeMetrics();
    map.on('move', handleThrottledMove);
    map.on('moveend', handleMoveEnd);
    map.on('zoomend', handleMoveEnd);

    return () => {
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
      map.off('move', handleThrottledMove);
      map.off('moveend', handleMoveEnd);
      map.off('zoomend', handleMoveEnd);
    };
  }, [map, onCoordinatesChange, onScaleChange]);

  // Resize observer to ensure map tiles redraw on side panel toggle
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return;
    const container = map.getContainer();
    const observer = new ResizeObserver(() => {
      map.invalidateSize();
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
    };
  }, [map]);

  // Ensure map size is fully measured and invalidated on mount / layout resolution
  useEffect(() => {
    map.invalidateSize();
    const t1 = setTimeout(() => map.invalidateSize(), 100);
    const t2 = setTimeout(() => map.invalidateSize(), 300);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [map]);

  // Fit bounds from loaded data
  useEffect(() => {
    if (dataBounds && !initialFitDoneRef.current) {
      initialFitDoneRef.current = true;
      if (selectedTileBounds) {
        prevTileBoundsRef.current = selectedTileBounds;
        map.fitBounds(selectedTileBounds, { padding: [45, 45], maxZoom: 17 });
      } else {
        map.fitBounds(dataBounds, { padding: [45, 45] });
      }
    }
  }, [dataBounds, selectedTileBounds, map]);

  // Fit bounds to selected tile
  useEffect(() => {
    if (selectedTileBounds && selectedTileBounds !== prevTileBoundsRef.current) {
      prevTileBoundsRef.current = selectedTileBounds;
      map.flyToBounds(selectedTileBounds, { padding: [30, 30], maxZoom: 17, duration: 1.2 });
    }
  }, [selectedTileBounds, map]);

  // Reset extent handler returns to fitted bounds
  useEffect(() => {
    if (resetTrigger > 0) {
      map.flyToBounds(dataBounds || DEFAULT_AOI_BOUNDS, { duration: 1 });
    }
  }, [resetTrigger, dataBounds, map]);

  // Pan / fly to selected zone if it has geometry
  useEffect(() => {
    if (selectedZoneId && selectedZoneId !== prevSelectedIdRef.current) {
      prevSelectedIdRef.current = selectedZoneId;
      const targetZone = zones.find((z) => z.zoneId === selectedZoneId);
      if (targetZone && targetZone.hasGeometry && targetZone.geometry?.coordinates) {
        const ring = targetZone.geometry.coordinates[0];
        const latLngs = ring.map(toLatLng);
        const bounds = L.latLngBounds(latLngs);
        map.flyToBounds(bounds, { padding: [50, 50], maxZoom: 15, duration: 1.2 });
      }
    } else if (!selectedZoneId) {
      prevSelectedIdRef.current = null;
    }
  }, [selectedZoneId, zones, map]);

  return null;
}

/**
 * ResetExtentControl
 * Compact button in Leaflet top-left control stack.
 */
function ResetExtentControl({ onReset }) {
  return (
    <div className="leaflet-top leaflet-left !top-[76px] pointer-events-auto">
      <div className="leaflet-bar leaflet-control">
        <button
          type="button"
          onClick={onReset}
          title="Reset map extent"
          aria-label="Reset map extent"
          className="flex items-center justify-center w-[30px] h-[30px] bg-paper hover:bg-hairline/40 text-ink transition-colors cursor-pointer"
        >
          <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

/**
 * FloodMap component (Cartographic Survey Plate)
 * Features:
 * - Unobstructed base map with neutral background fallback (.bg-slate-200)
 * - 2D Survey Map / 3D Relief Projection toggle
 * - Corner registration marks and real margin coordinates
 * - Dynamic scale bar
 * - Docked, collapsible side panel for controls, legend, and notices
 */
export default function FloodMap({
  floodGeoJSON = null,
  riskZones = [],
  blockedRoads = null,
  facilities = null,
  routes = [],
  buildingsExposed = null,
  floodGroundTruth = null,
  floodPredictedFast = null,
  floodPredictedAccurate = null,
  selectedZoneId = null,
  visibleLayers = {
    flood: true,
    risk: true,
    roads: true,
    facilities: true,
    routes: false,
    buildings: false,
    floodGroundTruth: true,
    floodPredicted: true,
    cyberMesh: true,
  },
  cyberNodes = [],
  onSelectCyberNode = () => {},
  onToggleLayer = () => {},
  onZoneSelect,
  droppedCount = 0,
  resetTrigger = 0,
  onResetExtent,
  tilesOffline: tilesOfflineProp = null,
  layerErrors: externalLayerErrors = {},
  isFromCache = false,
  cachedAt = null,
  modelMode: modelModeProp,
  onChangeModelMode,
  selectedTileId: selectedTileIdProp,
  onSelectTile,
  basemapMode: basemapModeProp,
  onChangeBasemapMode: onChangeBasemapModeProp,
  children,
}) {
  const [internalReset, setInternalReset] = useState(0);
  const [layerErrors, setLayerErrors] = useState({});
  const [internalTilesOffline, setInternalTilesOffline] = useState(false);
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const [viewMode, setViewMode] = useState('2d'); // '2d' | '3d'
  const [internalModelMode, setInternalModelMode] = useState('fast');
  const [internalSelectedTileId, setInternalSelectedTileId] = useState('ALL');
  const [internalBasemapMode, setInternalBasemapMode] = useState('plate');
  const [coords, setCoords] = useState({ lat: '50.5342° N', lng: '7.0421° E', zoom: 14 });
  const [scaleDistance, setScaleDistance] = useState('250 m');
  const [searchTerm, setSearchTerm] = useState('');

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const q = (searchTerm || '').trim().toLowerCase();
      if (!q) return;

      const match = (zones || []).find((z) => {
        const id = String(z.zoneId || z.id || '').toLowerCase();
        const name = String(z.name || '').toLowerCase();
        return id === q || id.endsWith(q) || id.includes(q) || name.includes(q);
      });

      if (match && onZoneSelect) {
        onZoneSelect(match.zoneId || match.id);
        if (onSelectTile) {
          onSelectTile(match.zoneId || match.id);
        }
      }
    }
  };

  const tilesOfflineRef = useRef(false);
  const mapInstanceRef = useRef(null);

  const activeModelMode = modelModeProp !== undefined ? modelModeProp : internalModelMode;
  const activeSelectedTileId = selectedTileIdProp !== undefined ? selectedTileIdProp : internalSelectedTileId;
  const activeBasemapMode = basemapModeProp !== undefined ? basemapModeProp : internalBasemapMode;

  const handleChangeBasemapMode = useCallback((mode) => {
    if (onChangeBasemapModeProp) onChangeBasemapModeProp(mode);
    setInternalBasemapMode(mode);
  }, [onChangeBasemapModeProp]);

  const handleChangeModelMode = useCallback((mode) => {
    if (onChangeModelMode) onChangeModelMode(mode);
    setInternalModelMode(mode);
  }, [onChangeModelMode]);

  const handleSelectTile = useCallback((tileId) => {
    if (onSelectTile) onSelectTile(tileId);
    setInternalSelectedTileId(tileId);
  }, [onSelectTile]);

  const isTilesOffline = tilesOfflineProp !== null ? tilesOfflineProp : internalTilesOffline;
  const activeReset = resetTrigger || internalReset;

  const handleResetExtent = useCallback(() => {
    if (onResetExtent) {
      onResetExtent();
    } else {
      setInternalReset((prev) => prev + 1);
    }
  }, [onResetExtent]);

  const handleMapReady = useCallback((map) => {
    mapInstanceRef.current = map;
  }, []);

  const handleTogglePanel = useCallback(() => {
    setIsPanelCollapsed((prev) => !prev);
  }, []);

  useEffect(() => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.invalidateSize();
    }
    const timer = setTimeout(() => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.invalidateSize();
      }
      window.dispatchEvent(new Event('resize'));
    }, 150);
    return () => clearTimeout(timer);
  }, [isPanelCollapsed, viewMode]);

  const availableTiles = useMemo(() => {
    const tileSet = new Set();
    const addFromCollection = (fc) => {
      if (fc && Array.isArray(fc.features)) {
        for (const f of fc.features) {
          if (f.properties?.tile_id) tileSet.add(f.properties.tile_id);
        }
      }
    };
    addFromCollection(floodGroundTruth);
    addFromCollection(floodPredictedFast);
    addFromCollection(floodPredictedAccurate);
    if (Array.isArray(riskZones)) {
      for (const z of riskZones) {
        if (z.zoneId && (z.zoneId.startsWith('0_') || z.zoneId.includes('_'))) {
          tileSet.add(z.zoneId);
        }
      }
    }
    return Array.from(tileSet).sort();
  }, [floodGroundTruth, floodPredictedFast, floodPredictedAccurate, riskZones]);

  const hasFloodWatch = useMemo(() => {
    return Boolean(
      floodGroundTruth ||
      floodPredictedFast ||
      floodPredictedAccurate ||
      availableTiles.length > 0 ||
      (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DATA_SOURCE === 'mock-floodwatch')
    );
  }, [floodGroundTruth, floodPredictedFast, floodPredictedAccurate, availableTiles.length]);

  const dataBounds = useMemo(() => {
    return computeDataBounds(riskZones, floodGeoJSON, [
      floodGroundTruth,
      floodPredictedFast,
      floodPredictedAccurate,
    ]);
  }, [riskZones, floodGeoJSON, floodGroundTruth, floodPredictedFast, floodPredictedAccurate]);

  const selectedTileBounds = useMemo(() => {
    if (!activeSelectedTileId || activeSelectedTileId === 'ALL') return null;

    const matchingZone = riskZones.find((z) => z.zoneId === activeSelectedTileId);
    if (matchingZone && matchingZone.hasGeometry && matchingZone.geometry?.coordinates) {
      const ring = matchingZone.geometry.coordinates[0];
      const latLngs = ring.map(toLatLng);
      return L.latLngBounds(latLngs);
    }

    const allFeatures = [
      ...(floodGroundTruth?.features || []),
      ...(floodPredictedFast?.features || []),
      ...(floodPredictedAccurate?.features || []),
    ].filter((f) => f.properties?.tile_id === activeSelectedTileId);

    const latLngs = [];
    for (const f of allFeatures) {
      const geom = f.geometry;
      if (!geom?.coordinates) continue;
      if (geom.type === 'LineString') {
        for (const pt of geom.coordinates) {
          latLngs.push(toLatLng(pt));
        }
      } else if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
        const rings = geom.type === 'Polygon' ? geom.coordinates : geom.coordinates.flat(1);
        for (const ring of rings) {
          for (const pt of ring) {
            latLngs.push(toLatLng(pt));
          }
        }
      }
    }
    if (latLngs.length > 0) {
      return L.latLngBounds(latLngs);
    }
    return null;
  }, [activeSelectedTileId, riskZones, floodGroundTruth, floodPredictedFast, floodPredictedAccurate]);

  const ESRI_SATELLITE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  const ESRI_SATELLITE_ATTRIBUTION = 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community';

  const defaultTileUrl = import.meta.env.VITE_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const defaultTileAttribution = import.meta.env.VITE_TILE_ATTRIBUTION || '© OpenStreetMap contributors';

  const tileUrl = activeBasemapMode === 'satellite' ? ESRI_SATELLITE_URL : defaultTileUrl;
  const tileAttribution = activeBasemapMode === 'satellite' ? ESRI_SATELLITE_ATTRIBUTION : defaultTileAttribution;

  const handleTileError = useCallback(() => {
    if (!tilesOfflineRef.current) {
      tilesOfflineRef.current = true;
      setInternalTilesOffline(true);
    }
  }, []);

  const handleLayerError = useCallback((layerKey, err) => {
    setLayerErrors((prev) => ({ ...prev, [layerKey]: err.message || 'Rendering failed' }));
  }, []);

  const combinedLayerErrors = {
    ...externalLayerErrors,
    ...layerErrors,
  };
  if (floodGeoJSON?.error) combinedLayerErrors.flood = floodGeoJSON.error;
  if (blockedRoads?.error) combinedLayerErrors.roads = blockedRoads.error;
  if (facilities?.error) combinedLayerErrors.facilities = facilities.error;
  if (buildingsExposed?.error) combinedLayerErrors.buildings = buildingsExposed.error;
  if (floodGroundTruth?.error) combinedLayerErrors.floodGroundTruth = floodGroundTruth.error;
  if (floodPredictedFast?.error) combinedLayerErrors.floodPredictedFast = floodPredictedFast.error;
  if (floodPredictedAccurate?.error) combinedLayerErrors.floodPredictedAccurate = floodPredictedAccurate.error;

  const activePredictedData = activeModelMode === 'accurate' ? floodPredictedAccurate : floodPredictedFast;

  const showTrainingPoolNotice = useMemo(() => {
    if (!visibleLayers.floodPredicted || !activePredictedData?.features) return false;
    return activePredictedData.features.some((f) => {
      if (activeSelectedTileId && activeSelectedTileId !== 'ALL' && f.properties?.tile_id !== activeSelectedTileId) {
        return false;
      }
      return f.properties?.in_training_pool === true;
    });
  }, [visibleLayers.floodPredicted, activePredictedData, activeSelectedTileId]);

  const floodwatchUrl = typeof import.meta !== 'undefined' ? (import.meta.env?.VITE_FLOODWATCH_URL || '') : '';

  return (
    <div className="relative w-full h-full flex flex-col font-sans bg-paper border border-control-border/60 rounded overflow-hidden select-none">
      {/* 4 Corner Registration Marks */}
      <span aria-hidden="true" className="absolute top-1 left-1.5 font-mono text-[11px] text-control-border select-none pointer-events-none z-20">+</span>
      <span aria-hidden="true" className="absolute top-1 right-1.5 font-mono text-[11px] text-control-border select-none pointer-events-none z-20">+</span>
      <span aria-hidden="true" className="absolute bottom-1 left-1.5 font-mono text-[11px] text-control-border select-none pointer-events-none z-20">+</span>
      <span aria-hidden="true" className="absolute bottom-1 right-1.5 font-mono text-[11px] text-control-border select-none pointer-events-none z-20">+</span>

      {/* Cartographic Plate Header: 2D / 3D Toggle & Margin Coordinates */}
      <div className="px-4 py-2 border-b border-hairline bg-plate flex flex-wrap items-center justify-between gap-2 shrink-0 z-10">
        <div className="flex items-center space-x-3">
          <span className="font-serif font-bold text-xs uppercase tracking-wider text-ink">
            Survey Plate Viewport
          </span>

          <div className="inline-flex rounded border border-control-border overflow-hidden bg-paper" role="group" aria-label="Survey projection mode">
            <button
              type="button"
              onClick={() => setViewMode('2d')}
              aria-pressed={viewMode === '2d'}
              className={`px-3 py-1 font-serif text-xs font-medium transition cursor-pointer ${
                viewMode === '2d'
                  ? 'bg-ink text-paper'
                  : 'bg-paper text-ink hover:bg-hairline/40'
              }`}
            >
              2D Survey Map
            </button>
            <button
              type="button"
              onClick={() => setViewMode('3d')}
              aria-pressed={viewMode === '3d'}
              className={`px-3 py-1 font-serif text-xs font-medium border-l border-control-border transition cursor-pointer ${
                viewMode === '3d'
                  ? 'bg-ink text-paper'
                  : 'bg-paper text-ink hover:bg-hairline/40'
              }`}
            >
              3D Relief Projection
            </button>
          </div>

          {/* Map Viewport Search Bar */}
          <div className="relative inline-flex items-center">
            <Search className="w-3.5 h-3.5 text-ink-muted absolute left-2 pointer-events-none" aria-hidden="true" />
            <input
              type="text"
              placeholder="Search"
              aria-label="Search"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              className="pl-7 pr-2 py-1 text-xs bg-paper text-ink border border-control-border rounded w-28 sm:w-36 focus:w-48 focus:ring-2 focus:ring-ink focus:outline-none transition-all placeholder:text-ink-muted"
            />
          </div>
        </div>

        {/* Dynamic Margin Coordinates from Active Map View */}
        <div className="flex items-center space-x-3 font-mono text-[11px] text-ink-muted">
          <span>LAT: <strong className="text-ink">{coords.lat}</strong></span>
          <span>•</span>
          <span>LNG: <strong className="text-ink">{coords.lng}</strong></span>
          <span className="hidden sm:inline">•</span>
          <span className="hidden sm:inline">ZOOM: <strong className="text-ink">{coords.zoom}</strong></span>
        </div>
      </div>

      {/* Main View Area: Map Viewport + Docked Side Panel */}
      <div className="flex-1 flex flex-col lg:flex-row w-full h-full min-h-[480px] overflow-hidden relative">
        {/* Unobstructed Viewport */}
        <div className="relative flex-1 h-full min-h-[480px] w-full min-w-0 overflow-hidden bg-slate-200">
          {viewMode === '3d' ? (
            <div className="w-full h-full relative min-h-[480px]">
              <iframe
                src="https://sachit0706.github.io/germany-3d-rescue-map/"
                title="Germany 3D Rescue Map"
                className="w-full h-full border-0 min-h-[480px]"
                allowFullScreen
              />
            </div>
          ) : (
            <MapContainer
              center={DEFAULT_MAP_CENTER}
              zoom={DEFAULT_MAP_ZOOM}
              className="w-full h-full z-0 bg-slate-200"
              style={{ width: '100%', height: '100%', minHeight: '480px' }}
              scrollWheelZoom={true}
            >
              <TileLayer
                key={activeBasemapMode}
                url={tileUrl}
                attribution={tileAttribution}
                eventHandlers={{
                  tileerror: handleTileError,
                }}
              />

              <MapController
                selectedZoneId={selectedZoneId}
                zones={riskZones}
                resetTrigger={activeReset}
                dataBounds={dataBounds}
                onMapReady={handleMapReady}
                selectedTileBounds={selectedTileBounds}
                onCoordinatesChange={setCoords}
                onScaleChange={setScaleDistance}
              />

              <ResetExtentControl onReset={handleResetExtent} />

              {/* Vector Layers */}
              {visibleLayers.flood && (
                <LayerErrorBoundary
                  layerName="flood"
                  onError={(err) => handleLayerError('flood', err)}
                >
                  <FloodLayer data={floodGeoJSON} />
                </LayerErrorBoundary>
              )}

              {visibleLayers.risk && (
                <LayerErrorBoundary
                  layerName="risk"
                  onError={(err) => handleLayerError('risk', err)}
                >
                  <RiskLayer
                    zones={riskZones}
                    selectedZoneId={selectedZoneId}
                    onZoneSelect={onZoneSelect}
                  />
                </LayerErrorBoundary>
              )}

              {visibleLayers.roads && (
                <LayerErrorBoundary
                  layerName="roads"
                  onError={(err) => handleLayerError('roads', err)}
                >
                  <RoadLayer data={blockedRoads} />
                </LayerErrorBoundary>
              )}

              {visibleLayers.facilities && (
                <LayerErrorBoundary
                  layerName="facilities"
                  onError={(err) => handleLayerError('facilities', err)}
                >
                  <FacilityLayer data={facilities} />
                </LayerErrorBoundary>
              )}

              {visibleLayers.routes && (
                <LayerErrorBoundary
                  layerName="routes"
                  onError={(err) => handleLayerError('routes', err)}
                >
                  <RouteLayer routes={routes} />
                </LayerErrorBoundary>
              )}

              {visibleLayers.buildings && (
                <LayerErrorBoundary
                  layerName="buildings"
                  onError={(err) => handleLayerError('buildings', err)}
                >
                  <BuildingLayer data={buildingsExposed} />
                </LayerErrorBoundary>
              )}

              {visibleLayers.floodGroundTruth && (
                <LayerErrorBoundary
                  layerName="floodGroundTruth"
                  onError={(err) => handleLayerError('floodGroundTruth', err)}
                >
                  <FloodWatchObservedLayer
                    data={floodGroundTruth}
                    selectedTileId={activeSelectedTileId}
                  />
                </LayerErrorBoundary>
              )}

              {visibleLayers.floodPredicted && (
                <LayerErrorBoundary
                  layerName="floodPredicted"
                  onError={(err) => handleLayerError('floodPredicted', err)}
                >
                  <FloodWatchPredictedLayer
                    data={activePredictedData}
                    selectedTileId={activeSelectedTileId}
                  />
                </LayerErrorBoundary>
              )}

              {visibleLayers.cyberMesh && (
                <LayerErrorBoundary
                  layerName="cyberMesh"
                  onError={(err) => handleLayerError('cyberMesh', err)}
                >
                  <CyberMeshLayer nodes={cyberNodes} onSelectNode={onSelectCyberNode} />
                </LayerErrorBoundary>
              )}

              {children}
            </MapContainer>
          )}

          {/* Dynamic Cartographic Scale Bar (Leaflet Overlay) */}
          {viewMode === '2d' && (
            <div className="absolute bottom-6 left-6 z-[400] pointer-events-none flex flex-col items-start font-mono text-[10px] text-ink bg-paper px-2 py-1 rounded border border-control-border shadow-xs">
              <div className="flex items-center justify-between w-[100px] border-b-2 border-l-2 border-r-2 border-ink h-2 pb-0.5">
                <span className="text-[9px]">0</span>
                <span className="text-[9px]">{scaleDistance}</span>
              </div>
              <span className="text-[9px] mt-0.5 text-ink-muted">Cartographic scale</span>
            </div>
          )}

          {/* North Arrow Indicator (Plate Furniture) */}
          {viewMode === '2d' && (
            <div className="absolute top-4 right-4 z-[400] pointer-events-none flex flex-col items-center font-serif text-ink bg-paper px-2 py-1 rounded border border-control-border shadow-xs select-none">
              <span className="text-xs font-bold leading-none">▲</span>
              <span className="text-[10px] font-bold tracking-widest mt-0.5">N</span>
            </div>
          )}
        </div>

        {/* Docked Side Panel (Beside map on desktop, below on mobile/tablet) */}
        <aside
          aria-label="Map Controls and Legend Side Panel"
          className={`border-t lg:border-t-0 lg:border-l border-hairline bg-plate flex flex-col transition-all duration-200 z-10 shrink-0 ${
            isPanelCollapsed ? 'lg:w-12 w-full' : 'lg:w-80 w-full'
          }`}
        >
          {/* Panel Header */}
          <div className="p-2 sm:p-2.5 border-b border-hairline bg-paper flex items-center justify-between gap-2 shrink-0">
            {!isPanelCollapsed && (
              <span className="text-[11px] font-serif font-bold text-ink uppercase tracking-wider">
                Layers & Legend
              </span>
            )}
            <button
              type="button"
              onClick={handleTogglePanel}
              aria-expanded={!isPanelCollapsed}
              aria-controls="map-side-panel-content"
              aria-label={isPanelCollapsed ? "Expand side panel" : "Collapse side panel"}
              title={isPanelCollapsed ? "Expand side panel" : "Collapse side panel"}
              className="ml-auto min-h-[44px] min-w-[44px] p-2 text-xs font-semibold text-ink flex items-center justify-center rounded border border-control-border bg-paper hover:bg-hairline/40 transition cursor-pointer select-none"
            >
              {isPanelCollapsed ? (
                <PanelRightOpen className="w-4 h-4 text-ink-muted" aria-hidden="true" />
              ) : (
                <PanelRightClose className="w-4 h-4 text-ink-muted" aria-hidden="true" />
              )}
            </button>
          </div>

          {/* Panel Content */}
          {!isPanelCollapsed && (
            <div
              id="map-side-panel-content"
              className="p-3 overflow-y-auto space-y-3 flex-1 text-xs max-h-[480px] lg:max-h-full"
            >
              {/* Offline Base Map Tiles Warning */}
              {isTilesOffline && (
                <div
                  role="alert"
                  className="p-2.5 rounded bg-amber-50 border border-amber-300 text-amber-900 text-xs flex items-start space-x-2 shadow-xs"
                >
                  <AlertTriangle className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
                  <span>
                    Map tiles unavailable. Base map tiles unreachable; vector flood overlays continue to operate offline.
                  </span>
                </div>
              )}

              {/* Offline Cached Data Notice */}
              {isFromCache && (
                <div
                  role="status"
                  className="p-2.5 rounded bg-sky-50 border border-sky-300 text-sky-900 text-xs flex items-start space-x-2 shadow-xs"
                >
                  <Info className="w-4 h-4 text-sky-700 shrink-0 mt-0.5" />
                  <span>Offline cached snapshot loaded {cachedAt ? `from ${cachedAt}` : ''}.</span>
                </div>
              )}

              {/* Malformed Geometry Warning */}
              {droppedCount > 0 && (
                <div
                  role="status"
                  className="p-2 rounded bg-amber-50 border border-amber-300 text-amber-900 text-[11px] shadow-xs flex items-center space-x-1.5"
                >
                  <span className="font-bold">Notice:</span>
                  <span>{droppedCount} malformed features skipped during geometry verification.</span>
                </div>
              )}

              {/* Layer Error Notice */}
              {Object.keys(combinedLayerErrors).length > 0 && (
                <div
                  role="alert"
                  aria-label="Layer Error Notice"
                  className="p-2 rounded bg-red-50 border border-red-300 text-risk-high text-[11px] shadow-xs flex items-center space-x-1.5"
                >
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  <span>
                    Overlay error: {Object.entries(combinedLayerErrors).map(([k, msg]) => `${k} layer (${msg})`).join(', ')}. Base map and other layers operational.
                  </span>
                </div>
              )}

              {/* Operational Calibration Note */}
              {showTrainingPoolNotice && (
                <div
                  role="note"
                  aria-label="Training Pool Notice"
                  className="p-2.5 rounded bg-amber-50 border border-amber-300 text-amber-950 text-xs space-y-1 shadow-xs"
                >
                  <div className="flex items-center space-x-1.5 font-bold text-amber-900">
                    <Info className="w-3.5 h-3.5 shrink-0 text-amber-700" />
                    <span>Model segmentation calibrated against surveyed ground truth</span>
                  </div>
                  <p className="text-[11px] leading-relaxed text-amber-900/90">
                    Predicted-versus-observed agreement is <strong>not</strong> a held-out test result. The model training pool incorporates these flood zones. Tiles 0_15_63, 0_15_65, 0_15_68, and 0_20_66 are not in the training pool.
                  </p>
                </div>
              )}

              {/* 1. Map Layer Controls */}
              <MapControls
                visibleLayers={visibleLayers}
                onToggleLayer={onToggleLayer}
                onResetExtent={handleResetExtent}
                modelMode={activeModelMode}
                onChangeModelMode={handleChangeModelMode}
                availableTiles={availableTiles}
                selectedTileId={activeSelectedTileId}
                onSelectTile={handleSelectTile}
                hasFloodWatch={hasFloodWatch}
                basemapMode={activeBasemapMode}
                onChangeBasemapMode={handleChangeBasemapMode}
              />

              {/* 2. Map Legend */}
              <MapLegend
                visibleLayers={visibleLayers}
                modelMode={activeModelMode}
              />

              {/* 3. Provenance Context Note */}
              <div
                role="note"
                aria-label="Provenance and Verification Note"
                className="p-2.5 rounded border border-hairline bg-paper text-ink-muted text-[11px] space-y-1"
              >
                <div className="font-semibold text-ink flex items-center space-x-1">
                  <Info className="w-3 h-3 text-ink-muted" />
                  <span>Data Provenance & Verification</span>
                </div>
                <p>
                  <strong>Observed:</strong> Human-verified SpaceNet 8 ground labels.
                  <br />
                  <strong>Derived:</strong> SegFormer-B0 neural segmentation inference.
                  <br />
                  <strong>Simulated:</strong> Priority risk scoring and scenario routing.
                </p>
                {floodwatchUrl && (
                  <div className="pt-1 border-t border-hairline mt-1">
                    <a
                      href={floodwatchUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center space-x-1 text-ink hover:underline font-medium"
                    >
                      <span>FloodWatch Service</span>
                      <ExternalLink className="w-2.5 h-2.5" />
                    </a>
                  </div>
                )}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
