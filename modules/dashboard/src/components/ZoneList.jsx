import React, { useEffect, useRef } from 'react';
import RiskBadge from './RiskBadge.jsx';
import { MapPinOff, Building2 } from 'lucide-react';

/**
 * ZoneListRow component
 * Individual row in the priority zone directory.
 * Attaches a ref to scroll into view when selected.
 */
function ZoneListRow({
  zone,
  rank,
  isSelected,
  onSelect,
}) {
  const rowRef = useRef(null);

  // Auto-scroll selected row into view (design.md Section 4, T4.3)
  useEffect(() => {
    if (isSelected && rowRef.current && typeof rowRef.current.scrollIntoView === 'function') {
      rowRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
      });
    }
  }, [isSelected]);

  const isPartial = Boolean(
    zone.partialData ||
    zone.exposedBuildings === null ||
    zone.floodedAreaKm2 === null ||
    zone.floodedPercent === null
  );

  const scoreText = zone.riskScore !== null ? zone.riskScore : 'Not assessed';
  const bldgText = zone.exposedBuildings !== null ? `${zone.exposedBuildings} bldgs` : 'Bldgs: Not available';

  return (
    <button
      ref={rowRef}
      type="button"
      aria-selected={isSelected}
      onClick={() => onSelect(zone.zoneId)}
      className={`w-full text-left p-3 rounded-card border transition flex items-center justify-between gap-3 focus:outline-none focus:ring-2 focus:ring-navy-900 ${
        isSelected
          ? 'bg-slate-50 border-navy-900 ring-2 ring-navy-900/25 shadow-xs'
          : 'bg-white border-border hover:border-slate-400 hover:bg-slate-50/50'
      }`}
    >
      {/* Left: Rank, Risk Badge, Name & No map shape / Partial data flags */}
      <div className="flex items-center space-x-3 min-w-0">
        <span className="text-xs font-bold text-text-muted w-6 text-center shrink-0">
          #{rank}
        </span>

        <RiskBadge level={zone.riskLevel} size="sm" />

        <div className="min-w-0 truncate">
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-text text-xs truncate">
              {zone.name}
            </span>
            {!zone.hasGeometry && (
              <span
                className="inline-flex items-center space-x-0.5 px-1.5 py-0.2 text-[10px] font-semibold text-amber-800 bg-amber-50 border border-amber-300 rounded shrink-0"
                title="Non-spatial staging area without polygon boundary"
              >
                <MapPinOff className="w-2.5 h-2.5 mr-0.5" aria-hidden="true" />
                <span>No map shape</span>
              </span>
            )}
            {isPartial && (
              <span
                className="inline-flex items-center px-1.5 py-0.2 text-[10px] font-medium text-amber-800 bg-amber-50 border border-amber-300 rounded shrink-0"
                title="Zone contains partial data"
              >
                Partial data
              </span>
            )}
            {zone.needsSurvey === true && (
              <span
                className="inline-flex items-center px-1.5 py-0.2 text-[10px] font-medium text-purple-800 bg-purple-50 border border-purple-300 rounded shrink-0"
                title="Ground reconnaissance survey needed"
              >
                Needs survey
              </span>
            )}
          </div>
          <div className="text-[11px] text-text-muted">
            ID: {zone.zoneId}
          </div>
        </div>
      </div>

      {/* Right: Risk Score & Exposed Buildings */}
      <div className="text-right shrink-0 space-y-0.5">
        <div className="text-xs font-bold text-navy-900">
          <span className={zone.riskScore === null ? 'text-text-muted font-normal' : ''}>
            Score: {scoreText}
          </span>
        </div>
        <div className="text-[11px] text-text-muted flex items-center justify-end space-x-1">
          <Building2 className="w-3 h-3 text-text-muted" aria-hidden="true" />
          <span>{bldgText}</span>
        </div>
      </div>
    </button>
  );
}

/**
 * ZoneList component (FR-22, FR-23, FR-26, T4.4, T4.6)
 * Renders ranked list of zones with risk badges, scores, exposed buildings,
 * and handles "No map shape" indicator.
 */
export default function ZoneList({
  zones = [],
  selectedZoneId = null,
  onZoneSelect,
}) {
  if (!zones || zones.length === 0) {
    return (
      <div
        className="p-8 text-center text-xs text-text-muted bg-surface rounded-card border border-dashed border-border"
        role="status"
      >
        No zones match the current search or filter criteria.
      </div>
    );
  }

  return (
    <div
      className="space-y-2 max-h-[380px] overflow-y-auto pr-1"
      role="region"
      aria-label="Prioritised Zone Directory"
    >
      {zones.map((zone, index) => (
        <ZoneListRow
          key={zone.zoneId}
          zone={zone}
          rank={index + 1}
          isSelected={zone.zoneId === selectedZoneId}
          onSelect={onZoneSelect}
        />
      ))}
    </div>
  );
}
