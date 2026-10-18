import React from 'react';
import { Layers, RotateCcw, Droplets, ShieldAlert, Ban, Building2, Route, Home } from 'lucide-react';
import ProvenanceBadge from './ProvenanceBadge.jsx';

/**
 * MapControls component (FR-14, FR-15, T3.6)
 * Provides 6 layer overlay switches and reset-extent button.
 * Toggling layers updates visibleLayers only and does NOT reset map viewport.
 */
export default function MapControls({
  visibleLayers = { flood: true, risk: true, roads: true, facilities: true, routes: false, buildings: false },
  onToggleLayer,
  onResetExtent,
  modelMode = 'fast',
  onChangeModelMode = () => {},
  availableTiles = [],
  selectedTileId = 'ALL',
  onSelectTile = () => {},
  hasFloodWatch: hasFloodWatchProp,
  basemapMode = 'plate',
  onChangeBasemapMode = () => {},
}) {
  const isFloodWatchPresent =
    hasFloodWatchProp !== undefined
      ? hasFloodWatchProp
      : visibleLayers.floodGroundTruth !== undefined ||
        visibleLayers.floodPredicted !== undefined ||
        (Array.isArray(availableTiles) && availableTiles.length > 0);

  const layerConfigs = [
    { key: 'flood', label: 'Flood Extent', icon: Droplets, color: 'text-flood', provenance: 'derived' },
    { key: 'risk', label: 'Risk Zones', icon: ShieldAlert, color: 'text-risk-high', provenance: 'derived' },
    { key: 'roads', label: 'Blocked Roads', icon: Ban, color: 'text-risk-high', provenance: 'derived' },
    { key: 'facilities', label: 'Rescue Facilities', icon: Building2, color: 'text-navy-900', provenance: 'simulated' },
    { key: 'routes', label: 'Evacuation Routes', icon: Route, color: 'text-route', provenance: 'simulated' },
    { key: 'buildings', label: 'Exposed Buildings', icon: Home, color: 'text-amber-700', provenance: 'observed' },
    ...(isFloodWatchPresent
      ? [
          { key: 'floodGroundTruth', label: 'Observed flood labels', icon: Home, color: 'text-amber-700', provenance: 'observed' },
          { key: 'floodPredicted', label: 'Model output (derived)', icon: Droplets, color: 'text-sky-600', provenance: 'derived' },
        ]
      : []),
    ...(visibleLayers.cyberMesh !== undefined
      ? [
          { key: 'cyberMesh', label: 'Cyber & Drone Mesh Security', icon: ShieldAlert, color: 'text-emerald-700', provenance: 'aegis' },
        ]
      : []),
  ];

  const enabledCount = Object.values(visibleLayers).filter(Boolean).length;
  const totalCount = layerConfigs.length;

  return (
    <div
      role="region"
      aria-label="Map Layer Controls"
      className="bg-card border border-border rounded-card p-3 shadow-sm space-y-3 font-sans"
    >
      {/* Basemap Selection: Plate (default) vs Satellite */}
      <div className="pb-2 border-b border-border space-y-1.5" role="region" aria-label="Basemap Controls">
        <div className="flex items-center justify-between text-xs">
          <span className="font-semibold text-text">Basemap:</span>
          <div className="inline-flex rounded border border-border overflow-hidden bg-white" role="group" aria-label="Basemap selection">
            <button
              type="button"
              onClick={() => onChangeBasemapMode('plate')}
              className={`px-2.5 py-1 text-xs font-medium transition cursor-pointer ${
                basemapMode === 'plate'
                  ? 'bg-navy-900 text-white font-semibold'
                  : 'bg-white text-text hover:bg-slate-100'
              }`}
              aria-pressed={basemapMode === 'plate'}
            >
              Plate
            </button>
            <button
              type="button"
              onClick={() => onChangeBasemapMode('satellite')}
              className={`px-2.5 py-1 text-xs font-medium border-l border-border transition cursor-pointer ${
                basemapMode === 'satellite'
                  ? 'bg-navy-900 text-white font-semibold'
                  : 'bg-white text-text hover:bg-slate-100'
              }`}
              aria-pressed={basemapMode === 'satellite'}
            >
              Satellite
            </button>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between pb-2 border-b border-border">
        <div className="flex items-center space-x-1.5 text-text font-semibold text-xs">
          <Layers className="w-4 h-4 text-navy-700" aria-hidden="true" />
          <span>Layer Overlays</span>
        </div>
        <span className="text-[11px] text-text-muted font-medium">
          {enabledCount} of {totalCount} Enabled
        </span>
      </div>

      <div className="space-y-1.5">
        {layerConfigs.map(({ key, label, icon: Icon, color, provenance }) => {
          const isChecked = Boolean(visibleLayers[key]);
          return (
            <React.Fragment key={key}>
              <label
                htmlFor={`toggle-${key}`}
                className="flex items-center justify-between p-1.5 rounded hover:bg-surface cursor-pointer transition select-none group"
              >
                <div className="flex items-center space-x-2 text-xs">
                  <Icon className={`w-3.5 h-3.5 ${color}`} aria-hidden="true" />
                  <span className="text-text group-hover:text-navy-900">{label}</span>
                  {provenance && (
                    <ProvenanceBadge value={provenance} className="hidden sm:inline-flex scale-90" />
                  )}
                </div>
                <input
                  id={`toggle-${key}`}
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => onToggleLayer(key)}
                  className="w-4 h-4 rounded text-navy-900 border-border focus:ring-2 focus:ring-flood focus:outline-none transition cursor-pointer"
                  aria-label={`Toggle ${label} overlay`}
                />
              </label>

              {/* Fast / Accurate mode selector right below Model output toggle */}
              {key === 'floodPredicted' && isChecked && (
                <div className="ml-6 pl-2 py-1 flex items-center space-x-2 text-[11px] border-l-2 border-sky-400">
                  <span className="text-text-muted font-medium">Inference:</span>
                  <button
                    type="button"
                    onClick={() => onChangeModelMode('fast')}
                    className={`px-2 py-0.5 rounded font-medium transition cursor-pointer ${
                      modelMode === 'fast'
                        ? 'bg-sky-700 text-white shadow-xs'
                        : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                    }`}
                    aria-pressed={modelMode === 'fast'}
                  >
                    Fast
                  </button>
                  <button
                    type="button"
                    onClick={() => onChangeModelMode('accurate')}
                    className={`px-2 py-0.5 rounded font-medium transition cursor-pointer ${
                      modelMode === 'accurate'
                        ? 'bg-sky-700 text-white shadow-xs'
                        : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                    }`}
                    aria-pressed={modelMode === 'accurate'}
                  >
                    Accurate
                  </button>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Tile selector dropdown for FloodWatch tiles */}
      {availableTiles && availableTiles.length > 0 && (
        <div className="pt-2 border-t border-border space-y-1">
          <label htmlFor="floodwatch-tile-select" className="block text-[11px] font-semibold text-text">
            Filter / Fit to Tile:
          </label>
          <select
            id="floodwatch-tile-select"
            aria-label="Filter or fit map to tile"
            value={selectedTileId || 'ALL'}
            onChange={(e) => onSelectTile(e.target.value)}
            className="w-full text-xs p-1.5 rounded border border-border bg-white text-text focus:ring-2 focus:ring-flood focus:outline-none cursor-pointer"
          >
            <option value="ALL">All Tiles ({availableTiles.length})</option>
            {availableTiles.map((t) => (
              <option key={t} value={t}>
                Tile {t}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="pt-2 border-t border-border">
        <button
          type="button"
          onClick={onResetExtent}
          aria-label="Reset map to study area bounds"
          className="w-full inline-flex items-center justify-center space-x-1.5 px-2.5 py-1.5 rounded bg-surface hover:bg-slate-200 active:scale-95 text-text text-xs font-medium border border-border transition focus:outline-none focus:ring-2 focus:ring-flood"
        >
          <RotateCcw className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
          <span>Reset Map Extent</span>
        </button>
      </div>
    </div>
  );
}
