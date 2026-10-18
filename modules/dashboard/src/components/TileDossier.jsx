import React from 'react';
import ZoneDetails from './ZoneDetails.jsx';
import SurveyNeededList from './SurveyNeededList.jsx';
import { FileText, MapPin, CheckCircle, AlertTriangle } from 'lucide-react';

/**
 * TileDossier (Right Zone of the Survey Plate)
 * Displays in-depth verified dossier for the active tile / sector,
 * training pool provenance, real feature counts, and survey queue.
 */
export default function TileDossier({
  selectedZone = null,
  allZones = [],
  onSelectZone = () => {},
  onClearSelection = () => {},
  timestamp = null,
  isFloodwatchMode = false,
  isTestFixture = false,
}) {
  return (
    <aside
      aria-label="Tile Dossier and Survey Queue"
      className="bg-plate border border-control-border/40 rounded p-4 flex flex-col space-y-4 font-sans text-ink"
    >
      {/* Dossier Header */}
      <div className="border-b border-hairline pb-2.5 flex items-baseline justify-between">
        <div>
          <h2 className="font-serif font-bold text-base text-ink tracking-tight">
            Tile Dossier
          </h2>
          <p className="text-[11px] text-ink-muted">
            {selectedZone ? 'Inspection & ground evidence' : 'Operational survey registry'}
          </p>
        </div>
        {selectedZone && (
          <span className="text-[11px] font-mono px-2 py-0.5 rounded border border-control-border bg-paper text-ink">
            {selectedZone.zoneId}
          </span>
        )}
      </div>

      {/* Selected Tile Inspection Details */}
      {selectedZone ? (
        <div className="space-y-4">
          <ZoneDetails
            zone={selectedZone}
            timestamp={timestamp}
            onClearSelection={onClearSelection}
            isTestFixture={isTestFixture}
          />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="p-3 bg-paper border border-hairline rounded space-y-1 text-center">
            <MapPin className="w-5 h-5 mx-auto text-ink-muted" aria-hidden="true" />
            <h3 className="font-serif font-semibold text-xs text-ink">
              No Tile Selected
            </h3>
            <p className="text-[11px] text-ink-muted max-w-xs mx-auto">
              Select a tile on the survey plate or choose from the verified sector ledger below to inspect damage counts.
            </p>
          </div>

          {/* Aerial Reconnaissance Survey Queue */}
          <SurveyNeededList
            zones={allZones}
            onSelectZone={onSelectZone}
            selectedZoneId={null}
          />

          {/* Survey Tile Register */}
          <div className="space-y-1.5 pt-2 border-t border-hairline">
            <span className="block font-serif font-semibold text-xs text-ink">
              Monitored Survey Tiles ({allZones.length})
            </span>
            <div className="max-h-60 overflow-y-auto space-y-1 pr-1">
              {allZones.map((z) => {
                const count = z.observed_flooded_count !== undefined ? z.observed_flooded_count : z.exposedBuildings || 0;
                return (
                  <button
                    key={z.zoneId}
                    type="button"
                    onClick={() => onSelectZone(z.zoneId)}
                    className="w-full flex items-center justify-between p-2 rounded border border-hairline bg-paper hover:bg-hairline/30 text-left text-xs transition cursor-pointer"
                  >
                    <div>
                      <span className="font-medium text-ink block">{z.name}</span>
                      <span className="text-[10px] text-ink-muted font-mono">{z.zoneId}</span>
                    </div>
                    <div className="text-right">
                      <span className="font-mono text-xs font-semibold text-ink">
                        {count}
                      </span>
                      <span className="block text-[10px] text-ink-muted">features</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
