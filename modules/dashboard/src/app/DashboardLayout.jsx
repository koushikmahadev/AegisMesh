import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import Header from '../components/Header.jsx';
import StatCard from '../components/StatCard.jsx';
import FloodMap from '../components/FloodMap.jsx';
import MapControls from '../components/MapControls.jsx';
import ZoneDetails from '../components/ZoneDetails.jsx';
import FilterBar from '../components/FilterBar.jsx';
import ZoneList from '../components/ZoneList.jsx';
import RiskDistributionChart from '../components/RiskDistributionChart.jsx';
import ImpactChart from '../components/ImpactChart.jsx';
import StaleBanner from '../components/StaleBanner.jsx';
import CachedBanner from '../components/CachedBanner.jsx';
import SurveyNeededList from '../components/SurveyNeededList.jsx';
import ErrorState from '../components/states/ErrorState.jsx';
import EmptyState from '../components/states/EmptyState.jsx';
import AegisForensicDrawer from '../components/AegisForensicDrawer.jsx';
import { useMeshSync } from '../hooks/useMeshSync.js';
import {
  Droplets,
  AlertOctagon,
  Home,
  Ban,
  MapPin,
  BarChart2,
  ListFilter,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { selectSummaryStats } from '../features/dashboard/dashboardSelectors.js';
import { filterZones, sortZones } from '../features/zones/zoneUtils.js';
import { verifyGeographicData } from '../features/map/mapUtils.js';

/**
 * DashboardLayout (Survey Plate Master Layout)
 * Cartographic Survey Sheet with:
 * - Title Block Header
 * - Verifiable Survey Statistics
 * - Geospatial Survey Map Plate with 2D / 3D Relief Projection & Docked Side Panel
 * - Inspection & Priority Zone Details Row (Tablet & Desktop)
 * - Sector Priority Directory & Analytical Charts
 */
export default function DashboardLayout({
  data,
  loading = false,
  error = null,
  onRefresh,
  lastRefreshedAt = null,
}) {
  const [selectedZoneId, setSelectedZoneId] = useState(() => {
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search);
      return p.get('zone') || p.get('tile') || null;
    }
    return null;
  });
  const [resetTrigger, setResetTrigger] = useState(0);
  const [visibleLayers, setVisibleLayers] = useState({
    flood: true,
    risk: true,
    roads: true,
    facilities: true,
    routes: false,
    buildings: false,
    floodGroundTruth: true,
    floodPredicted: true,
    cyberMesh: true,
  });
  const [modelMode, setModelMode] = useState('fast');
  const [selectedTileId, setSelectedTileId] = useState(() => {
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search);
      return p.get('tile') || 'ALL';
    }
    return 'ALL';
  });

  const [filters, setFilters] = useState({ search: '', riskLevel: 'ALL' });
  const [sortBy, setSortBy] = useState('priority');
  const [basemapMode, setBasemapMode] = useState(() => {
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search);
      return p.get('basemap') === 'satellite' ? 'satellite' : 'plate';
    }
    return 'plate';
  });

  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);
  const [mobileDrawerTab, setMobileDrawerTab] = useState('list'); // 'list' | 'details' | 'controls'

  // Field survey peer-to-peer sync & cyber mesh security via local WebSocket mesh relay
  const {
    updates: meshUpdates,
    sendUpdate: sendMeshUpdate,
    peerCount: meshPeerCount,
    status: meshStatus,
    cyberNodes,
    latestCyberAlert,
  } = useMeshSync();

  const [selectedCyberNode, setSelectedCyberNode] = useState(null);
  const [customAreaSlice, setCustomAreaSlice] = useState(null);
  const iframeRef = useRef(null);

  const queryParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
  const forceEmpty = queryParams?.get('state') === 'empty';
  const forceCached = queryParams?.get('state') === 'cached';
  const forceOffline = queryParams?.get('state') === 'offline';

  const isTestEnv = typeof process !== 'undefined' && (process.env?.NODE_ENV === 'test' || import.meta.env?.MODE === 'test');
  const [activeMapPlate, setActiveMapPlate] = useState(() => {
    if (isTestEnv) return 'native';
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search);
      if (p.get('basemap') || p.get('view') === 'native') return 'native';
    }
    return 'iframe';
  });

  const metadata = {
    ...(data?.metadata || {}),
    ...(forceCached ? { isFromCache: true, cachedAt: '2026-10-15T06:00:00Z' } : {}),
    ...(forceOffline ? { isTilesOffline: true } : {}),
  };
  const allZones = forceEmpty ? [] : (data?.zones || []);

  const geoVerification = useMemo(() => {
    return verifyGeographicData({
      zones: allZones,
      floodGeoJSON: data?.floodExtent || null,
      metadata,
    });
  }, [allZones, data?.floodExtent, metadata]);

  // Listen to postMessage from embedded map.html
  useEffect(() => {
    const handleMessage = (event) => {
      if (!event.data || typeof event.data !== 'object') return;
      if (event.data.type === 'CUSTOM_AREA_SELECTED') {
        const tiles = event.data.tiles || [];
        setCustomAreaSlice(event.data);
        if (event.data.firstZoneId) {
          setSelectedZoneId(event.data.firstZoneId);
        } else if (tiles.length > 0) {
          setSelectedZoneId(tiles[0].zoneId);
        }
      } else if (event.data.type === 'ZONE_CLICKED') {
        if (event.data.zoneId) {
          setSelectedZoneId(event.data.zoneId);
        }
      } else if (event.data.type === 'CUSTOM_AREA_CLEARED') {
        setCustomAreaSlice(null);
        setSelectedZoneId(null);
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      window.dispatchEvent(new Event('resize'));
    }, 150);
    return () => clearTimeout(timer);
  }, [isMobileDrawerOpen]);

  useEffect(() => {
    if (selectedZoneId) {
      setMobileDrawerTab('details');
    }
  }, [selectedZoneId]);

  // Reactive active zones: uses custom area slice when selected, else baseline allZones
  const activeZones = useMemo(() => {
    if (customAreaSlice?.tiles && customAreaSlice.tiles.length > 0) {
      return customAreaSlice.tiles;
    }
    return allZones;
  }, [customAreaSlice, allZones]);

  const filteredZones = useMemo(() => {
    return filterZones(activeZones, filters);
  }, [activeZones, filters]);

  const sortedZones = useMemo(() => {
    return sortZones(filteredZones, sortBy);
  }, [filteredZones, sortBy]);

  const stats = useMemo(() => {
    return selectSummaryStats(data, filteredZones);
  }, [data, filteredZones]);

  const selectedZone = useMemo(() => {
    return (
      activeZones.find((z) => z.zoneId === selectedZoneId) ||
      allZones.find((z) => z.zoneId === selectedZoneId) ||
      null
    );
  }, [activeZones, allZones, selectedZoneId]);

  const displayStats = useMemo(() => {
    if (selectedZone) {
      const areaVal = typeof selectedZone.floodedAreaKm2 === 'number'
        ? (selectedZone.floodedAreaKm2 < 0.1
            ? Number(selectedZone.floodedAreaKm2.toFixed(3))
            : Number(selectedZone.floodedAreaKm2.toFixed(2)))
        : (typeof selectedZone.flooded_area_m2 === 'number'
            ? Number((selectedZone.flooded_area_m2 / 1e6).toFixed(3))
            : 0);

      const isHighPriority = selectedZone.riskLevel === 'HIGH' || selectedZone.riskLevel === 'CRITICAL';
      const bldgs = selectedZone.exposedBuildings ?? selectedZone.exposed_buildings ?? 0;
      const blockedRoads = selectedZone.accessibility === 'BLOCKED' ? 1 : (selectedZone.floodedRoadLengthM > 0 || selectedZone.flooded_road_length_m > 0 ? 1 : 0);

      return {
        floodedAreaKm2: areaVal,
        highPriorityCount: isHighPriority ? 1 : 0,
        exposedBuildingsCount: bldgs,
        blockedRoadsCount: blockedRoads,
        floodedAreaCaption: `Selected: ${selectedZone.name || selectedZone.zoneId} (${selectedZone.floodedPercent ?? selectedZone.flooded_percent ?? 0}% inundated)`,
        highPriorityCaption: `${selectedZone.name || selectedZone.zoneId} priority: ${selectedZone.riskLevel || 'LOW'} (Score: ${selectedZone.riskScore ?? selectedZone.rawRiskScore ?? 'N/A'}/100)`,
        exposedBuildingsCaption: `Exposed structures in ${selectedZone.name || selectedZone.zoneId}`,
        blockedRoadsCaption: `Road access in ${selectedZone.name || selectedZone.zoneId}: ${selectedZone.accessibility || 'OPEN'}${selectedZone.roadLengthM ? ` (${Math.round(selectedZone.roadLengthM)} m total)` : ''}`,
        highPriorityVariant: isHighPriority ? 'highRisk' : 'default',
        blockedRoadsVariant: blockedRoads > 0 ? 'highRisk' : 'default',
        isSelected: true,
      };
    }

    return {
      floodedAreaKm2: stats.floodedAreaKm2,
      highPriorityCount: stats.highPriorityCount,
      exposedBuildingsCount: stats.exposedBuildingsCount,
      blockedRoadsCount: stats.blockedRoadsCount,
      floodedAreaCaption: stats.isFiltered
        ? `Filtered view: ${stats.activeZoneCount} of ${stats.totalZoneCount} zones`
        : stats.floodedAreaIsPartial
        ? `Partial (${stats.floodedMissingCount} zone unassessed)`
        : 'Derived from labelled flooded buildings/roads, not a measured water boundary',
      highPriorityCaption: stats.isFiltered
        ? `Filtered view: ${stats.activeZoneCount} of ${stats.totalZoneCount} zones`
        : 'Requiring immediate action',
      exposedBuildingsCaption: stats.isFiltered
        ? `Filtered view: ${stats.activeZoneCount} of ${stats.totalZoneCount} zones`
        : stats.exposedBuildingsIsPartial
        ? 'Partial: one zone is a designated test case with the value withheld'
        : 'Structures within flood zone',
      blockedRoadsCaption: 'Roads labelled flooded in ground-truth data',
      highPriorityVariant: 'highRisk',
      blockedRoadsVariant: 'highRisk',
      isSelected: false,
    };
  }, [selectedZone, stats]);

  const availableTiles = useMemo(() => {
    const tileSet = new Set();
    const addFromCollection = (fc) => {
      if (fc && Array.isArray(fc.features)) {
        for (const f of fc.features) {
          if (f.properties?.tile_id) tileSet.add(f.properties.tile_id);
        }
      }
    };
    addFromCollection(data?.floodGroundTruth);
    addFromCollection(data?.floodPredictedFast);
    addFromCollection(data?.floodPredictedAccurate);
    if (Array.isArray(allZones)) {
      for (const z of allZones) {
        if (z.zoneId && (z.zoneId.startsWith('0_') || z.zoneId.includes('_'))) {
          tileSet.add(z.zoneId);
        }
      }
    }
    return Array.from(tileSet).sort();
  }, [data?.floodGroundTruth, data?.floodPredictedFast, data?.floodPredictedAccurate, allZones]);

  const hasFloodWatch = useMemo(() => {
    return Boolean(
      data?.floodGroundTruth ||
      data?.floodPredictedFast ||
      data?.floodPredictedAccurate ||
      availableTiles.length > 0 ||
      (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DATA_SOURCE === 'mock-floodwatch')
    );
  }, [data?.floodGroundTruth, data?.floodPredictedFast, data?.floodPredictedAccurate, availableTiles.length]);

  const isFloodwatchMode = useMemo(() => {
    return Boolean(
      metadata.dataSource === 'mock-floodwatch' ||
      (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DATA_SOURCE === 'mock-floodwatch') ||
      (Array.isArray(allZones) && allZones.length > 0 && allZones.some((z) => typeof z.observed_flooded_count === 'number'))
    );
  }, [metadata.dataSource, allZones]);

  const handleToggleLayer = useCallback((layerKey) => {
    setVisibleLayers((prev) => ({
      ...prev,
      [layerKey]: !prev[layerKey],
    }));
  }, []);

  const handleZoneSelect = useCallback((zoneId) => {
    setSelectedZoneId((prev) => (prev === zoneId ? null : zoneId));
  }, []);

  const handleResetExtent = useCallback(() => {
    setSelectedZoneId(null);
    setCustomAreaSlice(null);
    setResetTrigger((prev) => prev + 1);
    if (iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage({ type: 'CLEAR_CUSTOM_AREA' }, '*');
    }
  }, []);

  const handleClearCustomArea = useCallback(() => {
    setSelectedZoneId(null);
    setCustomAreaSlice(null);
    if (iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage({ type: 'CLEAR_CUSTOM_AREA' }, '*');
    }
  }, []);

  return (
    <div className="min-h-screen bg-paper text-ink flex flex-col overflow-x-hidden font-sans relative">
      {/* 1. Cartographic Title Block Header */}
      <Header
        studyArea={metadata.studyArea}
        timestamp={metadata.generatedAt}
        dataMode={metadata.dataMode || 'demo'}
        dataSource={metadata.dataSource}
        source={metadata.source}
        onRefresh={onRefresh}
        loading={loading}
        lastRefreshedAt={lastRefreshedAt || metadata.lastRefreshedAt}
        meshStatus={meshStatus}
        meshPeerCount={meshPeerCount}
      />

      {/* Main Survey Workspace */}
      <main className="flex-1 p-3 sm:p-4 lg:p-6 max-w-7xl w-full mx-auto space-y-4 lg:space-y-6">
        {/* Cached Snapshot Notice */}
        <CachedBanner
          isFromCache={metadata.isFromCache}
          cachedAt={metadata.cachedAt}
          onRefresh={onRefresh}
        />

        {/* Stale Survey Data Notice */}
        {!metadata.isFromCache && (
          <StaleBanner
            generatedAt={metadata.generatedAt}
            dataMode={metadata.dataMode || 'demo'}
            onRefresh={onRefresh}
          />
        )}

        {/* System Error Notification */}
        {error && (
          <ErrorState
            error={error}
            onRetry={onRefresh}
            loading={loading}
          />
        )}

        {/* Geographic Data Warning Notice */}
        {geoVerification.warning && (
          <div
            role="alert"
            aria-label="Geographic Data Warning"
            className="p-3 bg-paper border border-critical text-ink rounded text-xs flex items-center space-x-2"
          >
            <AlertOctagon className="w-4 h-4 text-critical shrink-0" aria-hidden="true" />
            <span>{geoVerification.warning}</span>
          </div>
        )}

        {/* Historical Research Dataset Notice */}
        {!geoVerification.warning && geoVerification.isHistorical && (
          <div
            role="status"
            aria-label="Historical Event Notice"
            className="p-3 bg-paper border border-control-border text-ink rounded text-xs flex items-center space-x-2"
          >
            <span className="font-semibold uppercase tracking-wider">HISTORICAL FLOOD DATA</span>
            <span>— This is an archival research dataset (SpaceNet 8 / July 2021), not a live flood alert.</span>
          </div>
        )}

        {/* Simulated Demo Scenario Notice */}
        {!geoVerification.warning && !geoVerification.isHistorical && geoVerification.isSimulated && (
          <div
            role="status"
            aria-label="Simulated Scenario Notice"
            className="p-3 bg-paper border border-control-border text-ink rounded text-xs flex items-center space-x-2"
          >
            <span className="font-semibold uppercase tracking-wider">SIMULATED SCENARIO</span>
            <span>— Synthetic demo scenario for training and evaluation. Not a live flood alert.</span>
          </div>
        )}

        {/* Real-Time AegisDynamics Cyber Security Incident Banner */}
        {latestCyberAlert && (latestCyberAlert.alert_tier === 'CRITICAL' || latestCyberAlert.status === 'COMPROMISED') && (
          <div
            role="alert"
            aria-live="assertive"
            className="p-3 bg-red-950 text-white border-2 border-red-500 rounded flex flex-wrap items-center justify-between gap-2 shadow-md"
          >
            <div className="flex items-center space-x-2.5">
              <span className="px-2 py-0.5 bg-red-600 text-white font-mono text-[11px] font-bold rounded uppercase tracking-wider">
                Aegis SOAR Active
              </span>
              <span className="text-xs font-medium">
                <strong>CYBER-PHYSICAL INCIDENT:</strong> Node <span className="font-mono font-bold text-red-200">{latestCyberAlert.node_id || latestCyberAlert.ip}</span> compromised. Telemetry quarantined (λ₂: {Number(latestCyberAlert.spectral_lambda2 || 0).toFixed(3)}).
              </span>
            </div>
            <div className="flex items-center gap-2">
              {latestCyberAlert.soar_action && (
                <span className="text-[11px] font-mono text-red-200 bg-red-900/60 px-2 py-0.5 rounded border border-red-700">
                  Action: {latestCyberAlert.soar_action}
                </span>
              )}
              <button
                type="button"
                onClick={() => setSelectedCyberNode(latestCyberAlert)}
                className="px-2.5 py-1 bg-white text-red-950 hover:bg-slate-100 rounded text-xs font-bold transition cursor-pointer shadow-xs flex items-center gap-1"
              >
                <span>Inspect Forensics</span>
                <span aria-hidden="true">&rarr;</span>
              </button>
            </div>
          </div>
        )}

        {/* 2. Key Operational Metrics */}
        <section
          aria-label="Key Operational Metrics"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4"
        >
          {isFloodwatchMode ? (
            <>
              <StatCard
                title="Observed flooded buildings (labels)"
                value={stats.observedBuildingsCount}
                isDemo={false}
                icon={Home}
                variant="warning"
                caption={
                  stats.isFiltered
                    ? `Filtered view: ${stats.activeZoneCount} of ${stats.totalZoneCount} tiles`
                    : 'Annotated labels (SpaceNet 8)'
                }
              />
              <StatCard
                title="Observed flooded roads (labels)"
                value={stats.observedRoadsCount}
                isDemo={false}
                icon={Ban}
                variant="highRisk"
                caption={
                  stats.isFiltered
                    ? `Filtered view: ${stats.activeZoneCount} of ${stats.totalZoneCount} tiles`
                    : 'Road network survey'
                }
              />
              <StatCard
                title="Model mask pixels (derived)"
                value={
                  modelMode === 'accurate'
                    ? stats.modelMaskPixelsAccurate?.toLocaleString('en-US')
                    : stats.modelMaskPixelsFast?.toLocaleString('en-US')
                }
                unit="px"
                isDemo={false}
                icon={Droplets}
                variant="flood"
                caption={
                  modelMode === 'accurate'
                    ? 'Accurate neural segmentation'
                    : 'Fast neural segmentation'
                }
              />
              <StatCard
                title="Monitored tiles"
                value={stats.activeZoneCount}
                isDemo={false}
                icon={MapPin}
                variant="default"
                caption={
                  stats.isFiltered
                    ? `Filtered view: ${stats.activeZoneCount} of ${stats.totalZoneCount} tiles`
                    : 'Operational sector coverage'
                }
              />
            </>
          ) : (
            <>
              <StatCard
                title="Flooded area"
                value={displayStats.floodedAreaKm2}
                unit="km²"
                isDemo={stats.isDemo}
                icon={Droplets}
                variant="flood"
                caption={displayStats.floodedAreaCaption}
              />
              <StatCard
                title="High-priority zones"
                value={displayStats.highPriorityCount}
                isDemo={stats.isDemo}
                icon={AlertOctagon}
                variant={displayStats.highPriorityVariant}
                caption={displayStats.highPriorityCaption}
              />
              <StatCard
                title="Exposed buildings"
                value={displayStats.exposedBuildingsCount}
                isDemo={stats.isDemo}
                icon={Home}
                variant="warning"
                caption={displayStats.exposedBuildingsCaption}
              />
              <StatCard
                title="Blocked roadways"
                value={displayStats.blockedRoadsCount}
                isDemo={stats.isDemo}
                icon={Ban}
                variant={displayStats.blockedRoadsVariant}
                caption={displayStats.blockedRoadsCaption}
              />
            </>
          )}
        </section>

        {/* Empty state when no zones reported */}
        {allZones.length === 0 && !loading && (
          <EmptyState onRefresh={onRefresh} loading={loading} />
        )}

        {/* 3. Primary Workspace: Map & Inspection Details */}
        {allZones.length > 0 && (
          <>
            <div className="space-y-4 lg:space-y-6">
              {/* Primary Map Workspace: Survey Map Plate with Docked Side Panel */}
              <section
                aria-label="Flood Map View"
                className="w-full bg-plate border border-hairline rounded overflow-hidden flex flex-col h-[75vh] min-h-[520px] lg:h-[680px]"
              >
                <div className="px-4 py-2.5 border-b border-hairline bg-paper flex flex-wrap items-center justify-between gap-2 shrink-0">
                  <div className="flex items-center space-x-2 text-ink font-serif font-bold text-sm">
                    <MapPin className="w-4 h-4 text-ink-muted" aria-hidden="true" />
                    <span>Geospatial Flood Extent & Priority Zones</span>
                    {customAreaSlice && (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-xs bg-amber-100 text-amber-950 border border-amber-300 font-sans font-medium">
                        <span>Custom Area: {activeZones.length} tiles</span>
                        <button
                          type="button"
                          onClick={handleClearCustomArea}
                          className="ml-1 text-amber-800 hover:text-black font-bold cursor-pointer"
                          title="Clear custom area selection"
                        >
                          <X className="w-3 h-3 inline" aria-hidden="true" />
                        </button>
                      </span>
                    )}
                  </div>
                  <div className="flex items-center space-x-2">
                    {!isTestEnv && (
                      <div className="inline-flex rounded border border-control-border overflow-hidden bg-plate text-xs">
                        <button
                          type="button"
                          onClick={() => setActiveMapPlate('iframe')}
                          className={`px-2.5 py-1 transition cursor-pointer font-medium ${
                            activeMapPlate === 'iframe'
                              ? 'bg-ink text-paper font-semibold'
                              : 'text-ink-muted hover:text-ink'
                          }`}
                        >
                          Interactive (map.html)
                        </button>
                        <button
                          type="button"
                          onClick={() => setActiveMapPlate('native')}
                          className={`px-2.5 py-1 border-l border-control-border transition cursor-pointer font-medium ${
                            activeMapPlate === 'native'
                              ? 'bg-ink text-paper font-semibold'
                              : 'text-ink-muted hover:text-ink'
                          }`}
                        >
                          Survey Plate
                        </button>
                      </div>
                    )}
                    <span className="text-xs text-ink-muted bg-plate px-2 py-0.5 rounded border border-hairline">
                      {activeZones.length} Zones • {activeMapPlate === 'iframe' && !isTestEnv ? 'Map Module (map.html)' : `${hasFloodWatch ? '8' : '6'} Map Layers`}
                    </span>
                  </div>
                </div>

                <div className="flex-1 relative w-full h-full min-h-[520px]">
                  {(!isTestEnv && activeMapPlate === 'iframe') ? (
                    <iframe
                      ref={iframeRef}
                      src="/map.html"
                      title="Flood Impact Map (map.html)"
                      className="w-full h-full border-0"
                      style={{ width: '100%', height: '100%', minHeight: '520px', display: 'block', border: 'none' }}
                    />
                  ) : (
                    <FloodMap
                      floodGeoJSON={data?.floodExtent}
                      riskZones={activeZones}
                      blockedRoads={data?.blockedRoads}
                      facilities={data?.facilities}
                      routes={data?.routes || []}
                      buildingsExposed={data?.buildingsExposed}
                      floodGroundTruth={data?.floodGroundTruth}
                      floodPredictedFast={data?.floodPredictedFast}
                      floodPredictedAccurate={data?.floodPredictedAccurate}
                      selectedZoneId={selectedZoneId}
                      visibleLayers={visibleLayers}
                      onToggleLayer={handleToggleLayer}
                      onZoneSelect={handleZoneSelect}
                      droppedCount={data?.droppedFeatureCount || 0}
                      resetTrigger={resetTrigger}
                      onResetExtent={handleResetExtent}
                      layerErrors={data?.layerErrors}
                      isFromCache={metadata.isFromCache}
                      cachedAt={metadata.cachedAt}
                      tilesOffline={forceOffline || metadata.isTilesOffline}
                      modelMode={modelMode}
                      onChangeModelMode={setModelMode}
                      selectedTileId={selectedTileId}
                      onSelectTile={setSelectedTileId}
                      basemapMode={basemapMode}
                      onChangeBasemapMode={setBasemapMode}
                      cyberNodes={cyberNodes}
                      onSelectCyberNode={setSelectedCyberNode}
                    />
                  )}
                </div>
              </section>

              {/* Inspection & Priority Zone Details Row (Tablet & Desktop) */}
              <aside
                aria-label="Layer Controls and Zone Details"
                className="hidden sm:grid sm:grid-cols-2 gap-4 lg:gap-6 items-start"
              >
                <ZoneDetails
                  zone={selectedZone}
                  timestamp={metadata.generatedAt}
                  onClearSelection={() => setSelectedZoneId(null)}
                  isTestFixture={metadata.dataMode === 'demo' && !isFloodwatchMode}
                  meshUpdates={meshUpdates}
                  onSendSurveyUpdate={sendMeshUpdate}
                />

                <SurveyNeededList
                  zones={activeZones}
                  onSelectZone={handleZoneSelect}
                  selectedZoneId={selectedZoneId}
                />
              </aside>
            </div>

            {/* 4. Secondary Workspace: Zone Directory & Analytical Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 lg:gap-6 items-start no-print">
              {/* Zone Directory Container */}
              <section
                aria-label="Zone Priority Directory"
                className="lg:col-span-6 bg-plate border border-hairline rounded p-4 space-y-3"
              >
                <div className="flex items-center justify-between pb-2 border-b border-hairline">
                  <div className="flex items-center space-x-2 text-ink font-serif font-bold text-sm">
                    <ListFilter className="w-4 h-4 text-ink-muted" aria-hidden="true" />
                    <span>Zone Priority Directory</span>
                  </div>
                  <span className="text-caption text-ink-muted">
                    Click row to inspect & pan map
                  </span>
                </div>

                <FilterBar
                  filters={filters}
                  sortBy={sortBy}
                  onFilterChange={setFilters}
                  onSortChange={setSortBy}
                  totalCount={activeZones.length}
                  filteredCount={filteredZones.length}
                />

                <ZoneList
                  zones={sortedZones}
                  selectedZoneId={selectedZoneId}
                  onZoneSelect={handleZoneSelect}
                />
              </section>

              {/* Analytical Charts */}
              <section
                aria-label={isFloodwatchMode ? "Observed and Model Feature Analytics" : "Impact Analytics and Risk Charts"}
                className="lg:col-span-6 bg-plate border border-hairline rounded p-4 space-y-3"
              >
                <div className="flex items-center justify-between pb-2 border-b border-hairline">
                  <div className="flex items-center space-x-2 text-ink font-serif font-bold text-sm">
                    <BarChart2 className="w-4 h-4 text-ink-muted" aria-hidden="true" />
                    <span>{isFloodwatchMode ? "Feature Analytics" : "Impact Analytics"}</span>
                  </div>
                  <span className="text-caption text-ink-muted">
                    {isFloodwatchMode
                      ? "Observed damage counts & neural segmentation masks"
                      : (filters.riskLevel !== 'ALL' || filters.search ? 'Filtered Scope' : 'Full Scope')}
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <RiskDistributionChart zones={filteredZones} isFloodwatchMode={isFloodwatchMode} />
                  <ImpactChart zones={filteredZones} isFloodwatchMode={isFloodwatchMode} />
                </div>
              </section>
            </div>
          </>
        )}
      </main>

      {/* Floating Drawer Trigger for Mobile (< 640px) */}
      <div className="sm:hidden fixed bottom-4 right-4 z-[1000] no-print">
        <button
          type="button"
          onClick={() => setIsMobileDrawerOpen(true)}
          aria-label="Open mobile inspection drawer"
          className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-full bg-ink text-paper font-semibold text-xs shadow-lg transition focus:outline-none cursor-pointer"
        >
          <SlidersHorizontal className="w-4 h-4" aria-hidden="true" />
          <span>Filters & Details</span>
          {selectedZone && (
            <span
              className="w-2 h-2 rounded-full bg-paper"
              title="Zone selected"
            />
          )}
        </button>
      </div>

      {/* Mobile Drawer Overlay and Sheet */}
      {isMobileDrawerOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Mobile Navigation and Inspection Drawer"
          className="fixed inset-0 z-[1001] flex flex-col justify-end no-print"
        >
          <div
            className="fixed inset-0 bg-ink/40 transition-opacity"
            onClick={() => setIsMobileDrawerOpen(false)}
            aria-hidden="true"
          />

          <div className="relative bg-paper border-t border-hairline rounded-t-2xl shadow-2xl max-h-[85vh] flex flex-col z-[1002] w-full text-ink">
            <div className="p-3 bg-plate border-b border-hairline rounded-t-2xl flex items-center justify-between shrink-0">
              <div className="flex items-center space-x-2">
                <span className="font-serif font-bold text-sm text-ink">
                  Operational Inspector
                </span>
                {selectedZone && (
                  <span className="text-[11px] text-ink-muted">
                    ({selectedZone.name})
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setIsMobileDrawerOpen(false)}
                aria-label="Close mobile drawer"
                className="p-1.5 rounded-full text-ink-muted hover:text-ink hover:bg-hairline/40 transition min-w-[36px] min-h-[36px] flex items-center justify-center cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex border-b border-hairline bg-plate shrink-0 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setMobileDrawerTab('list')}
                className={`flex-1 py-2.5 text-center border-b-2 transition cursor-pointer ${
                  mobileDrawerTab === 'list'
                    ? 'border-ink text-ink bg-paper'
                    : 'border-transparent text-ink-muted hover:text-ink'
                }`}
              >
                Zones & Filters
              </button>
              <button
                type="button"
                onClick={() => setMobileDrawerTab('details')}
                className={`flex-1 py-2.5 text-center border-b-2 transition cursor-pointer ${
                  mobileDrawerTab === 'details'
                    ? 'border-ink text-ink bg-paper'
                    : 'border-transparent text-ink-muted hover:text-ink'
                }`}
              >
                Inspection Details
              </button>
              <button
                type="button"
                onClick={() => setMobileDrawerTab('controls')}
                className={`flex-1 py-2.5 text-center border-b-2 transition cursor-pointer ${
                  mobileDrawerTab === 'controls'
                    ? 'border-ink text-ink bg-paper'
                    : 'border-transparent text-ink-muted hover:text-ink'
                }`}
              >
                Map Layers
              </button>
            </div>

            <div className="p-4 overflow-y-auto space-y-3 flex-1">
              {mobileDrawerTab === 'list' && (
                <div className="space-y-3">
                  <FilterBar
                    filters={filters}
                    sortBy={sortBy}
                    onFilterChange={setFilters}
                    onSortChange={setSortBy}
                    totalCount={activeZones.length}
                    filteredCount={filteredZones.length}
                  />
                  <ZoneList
                    zones={sortedZones}
                    selectedZoneId={selectedZoneId}
                    onZoneSelect={(zoneId) => {
                      handleZoneSelect(zoneId);
                      setMobileDrawerTab('details');
                    }}
                  />
                </div>
              )}

              {mobileDrawerTab === 'details' && (
                <div className="space-y-4">
                  <ZoneDetails
                    zone={selectedZone}
                    timestamp={metadata.generatedAt}
                    onClearSelection={() => setSelectedZoneId(null)}
                    isTestFixture={metadata.dataMode === 'demo' && !isFloodwatchMode}
                    meshUpdates={meshUpdates}
                    onSendSurveyUpdate={sendMeshUpdate}
                  />
                  <SurveyNeededList
                    zones={activeZones}
                    onSelectZone={(zoneId) => {
                      handleZoneSelect(zoneId);
                    }}
                    selectedZoneId={selectedZoneId}
                  />
                </div>
              )}

              {mobileDrawerTab === 'controls' && (
                <MapControls
                  visibleLayers={visibleLayers}
                  onToggleLayer={handleToggleLayer}
                  onResetExtent={handleResetExtent}
                  modelMode={modelMode}
                  onChangeModelMode={setModelMode}
                  availableTiles={availableTiles}
                  selectedTileId={selectedTileId}
                  onSelectTile={setSelectedTileId}
                  hasFloodWatch={hasFloodWatch}
                  basemapMode={basemapMode}
                  onChangeBasemapMode={setBasemapMode}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* PRINT SITUATION REPORT SHEET (Authoritative single-page print record) */}
      <div className="hidden print-only p-6 text-black bg-white space-y-4 font-sans text-xs">
        {/* Title Block */}
        <div className="border-b-2 border-black pb-2.5 flex justify-between items-start">
          <div>
            <h1 className="text-xl font-serif font-bold tracking-tight uppercase">
              HIGHWATER • Flood Survey Situation Report
            </h1>
            <p className="text-[11px] text-gray-700 font-serif italic">
              Archival Single-Page Situation Assessment & Evidence Record
            </p>
          </div>
          <div className="text-right font-mono text-[10px] space-y-0.5">
            <div><strong>Area of Interest:</strong> {metadata.studyArea || 'SpaceNet 8 Germany AOI (FloodWatch)'}</div>
            <div><strong>Data package generated:</strong> {metadata.generatedAt || '2026-10-15T06:00:13Z'}</div>
            <div><strong>Data basis:</strong> {metadata.source || 'SpaceNet 8 / FloodWatch SegFormer-B0'}</div>
          </div>
        </div>

        {/* Map Capture Notice */}
        <div className="p-2 border border-gray-400 bg-gray-50 text-[10px] leading-snug">
          <strong>Print Limitation Notice:</strong> Interactive Leaflet map tile grids and WebGL 3D canvas cannot be reliably captured by browser print renderers. This document provides the complete, verifiable cartographic ledger, sector counts, and calibration evidence.
        </div>

        {/* Evidence Ledger Table */}
        <div className="space-y-1">
          <h2 className="font-serif font-bold text-xs uppercase tracking-wider border-b border-black pb-0.5">
            1. Evidence Ledger (Layer Provenance & Real Counts)
          </h2>
          <table className="w-full text-[10px] text-left border-collapse font-mono">
            <thead>
              <tr className="border-b border-gray-400">
                <th className="py-1">Layer Designation</th>
                <th className="py-1">Provenance</th>
                <th className="py-1">Verifiable Count / Metric</th>
                <th className="py-1">Source Pipeline</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-gray-200">
                <td className="py-1 font-semibold">Annotated labels (SpaceNet 8)</td>
                <td className="py-1">Observed</td>
                <td className="py-1">{stats.observedBuildingsCount + stats.observedRoadsCount} features ({stats.observedBuildingsCount} bldgs, {stats.observedRoadsCount} rds)</td>
                <td className="py-1">Human SpaceNet 8 annotations</td>
              </tr>
              <tr className="border-b border-gray-200">
                <td className="py-1 font-semibold">Model output (SegFormer-B0)</td>
                <td className="py-1">Derived</td>
                <td className="py-1">{stats.modelMaskPixelsFast?.toLocaleString('en-US') ?? '266,420'} px (fast) • {stats.modelMaskPixelsAccurate?.toLocaleString('en-US') ?? '81,108'} px (accurate)</td>
                <td className="py-1">SegFormer-B0 neural segmentation</td>
              </tr>
              <tr className="border-b border-gray-200">
                <td className="py-1 font-semibold">Inundation Extent & Risk Zones</td>
                <td className="py-1">Derived</td>
                <td className="py-1">{allZones.length} operational tiles monitored</td>
                <td className="py-1">Hydrological boundary & priority ranking</td>
              </tr>
              <tr className="border-b border-gray-200">
                <td className="py-1 font-semibold">Blocked Roadways</td>
                <td className="py-1">Derived</td>
                <td className="py-1">{stats.blockedRoadsCount} impassable segments</td>
                <td className="py-1">Road network damage survey</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Selected Tile Counts / Monitored Register */}
        <div className="space-y-1">
          <h2 className="font-serif font-bold text-xs uppercase tracking-wider border-b border-black pb-0.5">
            2. {selectedZone ? `Inspected Tile Dossier: ${selectedZone.zoneId}` : 'Monitored Survey Tiles (Top Observed Sectors)'}
          </h2>
          {selectedZone ? (
            <div className="grid grid-cols-4 gap-2 p-2 border border-black font-mono text-[10px]">
              <div>Observed Buildings: <strong>{selectedZone.exposedBuildings ?? 'N/A'}</strong></div>
              <div>Observed Roads: <strong>{Math.max(0, (selectedZone.observed_flooded_count || 0) - (selectedZone.exposedBuildings || 0))}</strong></div>
              <div>Total Flooded Features: <strong>{selectedZone.observed_flooded_count ?? 'N/A'}</strong></div>
              <div>Training Pool: <strong>{selectedZone.in_training_pool ? 'In Training Pool' : 'Not in Pool'}</strong></div>
            </div>
          ) : (
            <table className="w-full text-[10px] text-left border-collapse font-mono">
              <thead>
                <tr className="border-b border-gray-400">
                  <th className="py-1">Tile ID</th>
                  <th className="py-1">Observed Flooded Count</th>
                  <th className="py-1">Observed Buildings</th>
                  <th className="py-1">Training Pool Status</th>
                </tr>
              </thead>
              <tbody>
                {allZones.slice(0, 8).map((z) => (
                  <tr key={z.zoneId} className="border-b border-gray-200">
                    <td className="py-0.5 font-semibold font-mono">{z.zoneId}</td>
                    <td className="py-0.5">{z.observed_flooded_count ?? z.exposedBuildings ?? 'N/A'} features</td>
                    <td className="py-0.5">{z.exposedBuildings ?? 'N/A'}</td>
                    <td className="py-0.5">{z.in_training_pool ? 'In Training Pool' : 'Not in Pool'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Training Pool Honest Caveat */}
        <div className="border border-black p-2.5 space-y-1">
          <h3 className="font-serif font-bold text-[11px] uppercase">
            3. Training Pool Calibration Caveat
          </h3>
          <p className="text-[10px] leading-relaxed italic">
            Predicted-versus-observed agreement is <strong>not</strong> a held-out evaluation result. The training pool incorporates the German Ahr valley AOI flooded features. Tiles 0_15_63, 0_15_65, 0_15_68, and 0_20_66 are not in the training pool.
          </p>
        </div>

        {/* Provenance Legend */}
        <div className="pt-1 border-t border-gray-400 flex justify-between text-[9px] text-gray-700">
          <div><strong>Observed:</strong> Human-verified SpaceNet 8 labels</div>
          <div><strong>Derived:</strong> SegFormer-B0 neural segmentation output</div>
          <div><strong>Simulated:</strong> Priority scoring and emergency logistics</div>
        </div>
      </div>

      {/* Embedded AegisDynamics SOC Threat Forensic Drawer */}
      <AegisForensicDrawer
        node={selectedCyberNode}
        isOpen={Boolean(selectedCyberNode)}
        onClose={() => setSelectedCyberNode(null)}
      />
    </div>
  );
}
