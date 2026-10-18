import React from 'react';
import DroneIcon from './DroneIcon.jsx';
import RiskBadge from './RiskBadge.jsx';

/**
 * SurveyNeededList component
 * Displays a list of zones flagged for aerial reconnaissance survey.
 * Strictly filters only zones where needsSurvey === true (never derived from confidence).
 * Shows zone name and risk level.
 * Calls onSelectZone(zoneId) on click.
 * Displays "No zones currently flagged for aerial reconnaissance." when none match.
 */
export default function SurveyNeededList({
  zones = [],
  onSelectZone,
  selectedZoneId = null,
}) {
  // Filter ONLY zones where needsSurvey is strictly boolean true (never derived from confidence)
  const surveyZones = Array.isArray(zones)
    ? zones.filter((z) => z && z.needsSurvey === true)
    : [];

  return (
    <section
      aria-label="Aerial Reconnaissance Survey Needed"
      className="bg-card border border-border rounded-card p-4 shadow-xs space-y-3 font-sans"
    >
      <div className="flex items-center justify-between pb-2 border-b border-border">
        <div className="flex items-center space-x-2 text-text font-semibold text-sm">
          <DroneIcon className="w-5 h-4 text-purple-700 shrink-0" aria-hidden="true" />
          <span>Aerial Survey Needed</span>
        </div>
        <span className="text-caption text-text-muted bg-slate-100 px-2 py-0.5 rounded border border-border font-medium">
          {surveyZones.length} {surveyZones.length === 1 ? 'zone' : 'zones'}
        </span>
      </div>

      {surveyZones.length === 0 ? (
        <p className="text-xs text-text-muted py-2">
          No zones currently flagged for aerial reconnaissance.
        </p>
      ) : (
        <ul className="space-y-1.5 max-h-52 overflow-y-auto pr-1" role="list">
          {surveyZones.map((zone) => {
            const isSelected = selectedZoneId === zone.zoneId;
            return (
              <li key={zone.zoneId}>
                <button
                  type="button"
                  onClick={() => onSelectZone && onSelectZone(zone.zoneId)}
                  className={`w-full flex items-center justify-between p-2 rounded text-left text-xs transition border cursor-pointer ${
                    isSelected
                      ? 'bg-slate-100 border-navy-700 font-semibold'
                      : 'border-border/60 hover:bg-slate-50'
                  }`}
                  aria-selected={isSelected}
                >
                  <div className="min-w-0 pr-2">
                    <span className="font-medium text-navy-900 block truncate">
                      {zone.name}
                    </span>
                    <span className="text-[11px] text-text-muted font-mono">
                      {zone.zoneId}
                    </span>
                  </div>
                  <RiskBadge level={zone.riskLevel} size="sm" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
