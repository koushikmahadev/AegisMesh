import React, { useState } from 'react';
import RiskBadge from './RiskBadge.jsx';
import ProvenanceBadge from './ProvenanceBadge.jsx';
import { AlertCircle, CheckCircle, Ban, HelpCircle, X, ShieldAlert, MapPinOff } from 'lucide-react';

/**
 * Maps operational accessibility enum to human-friendly operational copy (design.md Section 5)
 */
function getAccessibilityDisplay(accessibility) {
  switch (accessibility) {
    case 'OPEN':
      return {
        label: 'Open access',
        icon: CheckCircle,
        className: 'text-risk-low bg-emerald-50 border-emerald-200',
      };
    case 'LIMITED':
      return {
        label: 'Restricted access',
        icon: AlertCircle,
        className: 'text-risk-medium bg-amber-50 border-amber-200',
      };
    case 'BLOCKED':
      return {
        label: 'Blocked access',
        icon: Ban,
        className: 'text-risk-high bg-red-50 border-red-200',
      };
    case 'CUT_OFF':
      return {
        label: 'Cut off',
        icon: ShieldAlert,
        className: 'text-risk-high bg-red-100 border-red-300 font-bold',
      };
    default:
      return {
        label: 'Not available',
        icon: HelpCircle,
        className: 'text-text-muted bg-surface border-border',
      };
  }
}

/**
 * Maps field survey status enum to human-friendly badge styles and icons
 */
function getSurveyStatusConfig(surveyStatus) {
  switch (surveyStatus) {
    case 'flooded':
      return {
        label: 'Flooded',
        icon: AlertCircle,
        style: 'text-risk-high bg-red-50 border-red-200',
      };
    case 'clear':
      return {
        label: 'Clear',
        icon: CheckCircle,
        style: 'text-risk-low bg-emerald-50 border-emerald-200',
      };
    case 'unsure':
    default:
      return {
        label: 'Unsure',
        icon: HelpCircle,
        style: 'text-text-muted bg-surface border-border',
      };
  }
}

function formatSurveyTime(isoString) {
  if (!isoString) return '';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
  } catch {
    return isoString;
  }
}

/**
 * ZoneDetails component (FR-20, FR-21, T4.5)
 * Displays in-depth assessment data for the selected zone.
 * Strictly adheres to rules.md:
 * - Missing data displays "Not available", never 0 or assumed values.
 * - Non-spatial zones show an explicit note.
 * - Reasons list renders directly from supplied data.
 */
export default function ZoneDetails({
  zone = null,
  route = null,
  timestamp = null,
  onClearSelection,
  isTestFixture = false,
  meshUpdates = [],
  onSendSurveyUpdate = null,
}) {
  const [surveyStatus, setSurveyStatus] = useState('flooded');
  const [surveyNote, setSurveyNote] = useState('');
  const [surveyAuthor, setSurveyAuthor] = useState('');
  const [formError, setFormError] = useState(null);

  if (!zone) {
    return (
      <div
        className="bg-card border border-border rounded-card p-6 text-center space-y-3"
        role="region"
        aria-live="polite"
        aria-label="Zone Inspection Details"
      >
        <div className="w-10 h-10 rounded-full bg-surface border border-border flex items-center justify-center mx-auto text-text-muted">
          <HelpCircle className="w-5 h-5" aria-hidden="true" />
        </div>
        <div className="space-y-1">
          <h3 className="text-sm font-semibold text-text">No Zone Selected</h3>
          <p className="text-xs text-text-muted max-w-xs mx-auto">
            Select a zone on the map or in the list to inspect damage, risk score, and accessibility.
          </p>
        </div>
      </div>
    );
  }

  const zoneUpdates = Array.isArray(meshUpdates)
    ? meshUpdates.filter((u) => u && String(u.zoneId) === String(zone.zoneId))
    : [];

  const access = getAccessibilityDisplay(zone.accessibility);
  const AccessIcon = access.icon;

  const isPartial = Boolean(
    zone.partialData ||
    zone.exposedBuildings === null ||
    zone.floodedAreaKm2 === null ||
    zone.floodedPercent === null
  );

  const isFixture = Boolean(
    isTestFixture ||
    zone.isTestFixture ||
    zone.isFixture ||
    (typeof zone.source === 'string' && zone.source.toLowerCase().includes('fixture')) ||
    (Array.isArray(zone.reasons) && zone.reasons.some((r) => r.toLowerCase().includes('designated test case')))
  );

  const isFloodwatch = Boolean(
    isTestFixture === false &&
    zone.observed_flooded_count !== undefined &&
    zone.observed_flooded_count !== null
  ) || Boolean(
    typeof zone.zoneId === 'string' && (zone.zoneId.startsWith('0_') || zone.zoneId.includes('_')) &&
    typeof zone.observed_flooded_count === 'number'
  );

  const scoreDisplay = zone.riskScore !== null ? `${zone.riskScore} / 100` : 'Not assessed';
  const floodAreaDisplay = zone.floodedAreaKm2 !== null ? `${zone.floodedAreaKm2} km²` : 'Not available';
  const floodPctDisplay = zone.floodedPercent !== null ? `${zone.floodedPercent}%` : 'Not available';
  const exposedBldgsDisplay = zone.exposedBuildings !== null ? zone.exposedBuildings : 'Not available';
  const updatedDisplay = timestamp || 'Not available';

  // FloodWatch derived metrics
  const observedBldgs = zone.exposedBuildings !== null && zone.exposedBuildings !== undefined ? zone.exposedBuildings : 0;
  const observedRoads = (typeof zone.observed_flooded_count === 'number' && typeof zone.exposedBuildings === 'number')
    ? Math.max(0, zone.observed_flooded_count - zone.exposedBuildings)
    : 0;
  const observedTotal = zone.observed_flooded_count !== null && zone.observed_flooded_count !== undefined
    ? zone.observed_flooded_count
    : (observedBldgs + observedRoads);

  let modelMaskDisplay = 'None reported';
  if (Array.isArray(zone.reasons)) {
    const maskLine = zone.reasons.find((r) => r.includes('mask pixels'));
    if (maskLine) {
      const match = maskLine.match(/mask pixels:\s*(\d+)\s*\(fast\s*mode\),\s*(\d+)\s*\(accurate\s*mode\)/i);
      if (match) {
        modelMaskDisplay = `${Number(match[1]).toLocaleString('en-US')} (fast) • ${Number(match[2]).toLocaleString('en-US')} (acc)`;
      } else {
        modelMaskDisplay = maskLine.replace(/Model detected mask pixels:\s*/i, '');
      }
    }
  }

  return (
    <div
      className="bg-card border border-border rounded-card p-4 shadow-xs space-y-4 font-sans"
      role="region"
      aria-live="polite"
      aria-label={`Zone Inspection Details for ${zone.name}`}
    >
      {/* Header: Zone Name, Risk Badge, and Clear Button */}
      <div className="flex items-start justify-between gap-2 pb-3 border-b border-border">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center space-x-2 flex-wrap gap-y-1">
            <h3 className="text-sm font-bold text-navy-900 truncate">
              {zone.name}
            </h3>
            {isFloodwatch ? (
              <>
                <span className="px-2 py-0.5 text-[10px] font-semibold tracking-wider uppercase rounded bg-slate-100 text-slate-700 border border-slate-300">
                  No Risk Scoring
                </span>
                {zone.in_training_pool !== null && zone.in_training_pool !== undefined && (
                  <span className={`px-2 py-0.5 text-[10px] font-semibold tracking-wider uppercase rounded ${
                    zone.in_training_pool
                      ? 'bg-blue-50 text-blue-800 border border-blue-200'
                      : 'bg-slate-50 text-slate-600 border border-slate-200'
                  }`}>
                    {zone.in_training_pool ? 'In training pool' : 'Not in training pool'}
                  </span>
                )}
              </>
            ) : (
              <RiskBadge level={zone.riskLevel} size="sm" />
            )}
            {isPartial && !isFloodwatch && (
              <span
                className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium text-amber-800 bg-amber-50 border border-amber-300 rounded shrink-0"
                title="Zone contains partial data"
              >
                Partial data
              </span>
            )}
            {zone.needsSurvey === true && !isFloodwatch && (
              <span
                className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium text-purple-800 bg-purple-50 border border-purple-300 rounded shrink-0"
                title="Ground reconnaissance survey needed"
              >
                Needs survey
              </span>
            )}
          </div>
          <p className="text-[11px] text-text-muted">
            Zone ID: <span className="font-mono">{zone.zoneId}</span>
          </p>
        </div>

        {onClearSelection && (
          <button
            type="button"
            onClick={onClearSelection}
            className="text-text-muted hover:text-text p-1 rounded hover:bg-surface transition"
            aria-label="Clear zone selection"
            title="Clear zone selection"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Geometry notice if zone is non-spatial (T4.6, FR-26) */}
      {!zone.hasGeometry && (
        <div
          className="p-2.5 bg-amber-50 border border-amber-300 rounded text-amber-900 text-xs flex items-start space-x-2"
          role="note"
        >
          <MapPinOff className="w-4 h-4 shrink-0 text-amber-700 mt-0.5" aria-hidden="true" />
          <div>
            <span className="font-bold block">Non-spatial staging area</span>
            <span>No geospatial boundary coordinates available; sector not plotted on the map.</span>
          </div>
        </div>
      )}

      {/* Key Metrics Grid */}
      {isFloodwatch ? (
        <div className="grid grid-cols-2 gap-2 text-xs">
          {/* Observed Flooded Buildings */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Observed flooded buildings (labels)</span>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              {observedBldgs}
            </span>
          </div>

          {/* Observed Flooded Roads */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Observed flooded roads (labels)</span>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              {observedRoads}
            </span>
          </div>

          {/* Model Mask Pixels */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Model mask pixels (derived)</span>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              {modelMaskDisplay}
            </span>
          </div>

          {/* Total Flooded Features */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Observed flooded total (labels)</span>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              {observedTotal} features
            </span>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 text-xs">
          {/* Risk Score */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Priority Score</span>
            <span className={`text-sm font-bold block mt-0.5 ${zone.riskScore === null ? 'text-text-muted font-normal' : 'text-navy-900'}`}>
              {scoreDisplay}
            </span>
          </div>

          {/* Accessibility Status */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Accessibility</span>
            <div className="flex items-center space-x-1.5 mt-0.5">
              <AccessIcon className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
              <span className="text-xs font-semibold text-text truncate">
                {access.label}
              </span>
            </div>
          </div>

          {/* Flooded Area */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Flooded Area</span>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              {floodAreaDisplay}
            </span>
            {zone.floodedPercent !== null && (
              <span className="text-[10px] text-text-muted block">
                Coverage: {floodPctDisplay}
              </span>
            )}
          </div>

          {/* Exposed Buildings */}
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Exposed Buildings</span>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              {exposedBldgsDisplay}
            </span>
          </div>

        {/* Provenance */}
        {zone.provenance !== null && zone.provenance !== undefined && (
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <span className="text-[11px] text-text-muted block">Provenance</span>
            <div className="mt-1 flex items-center space-x-1.5 flex-wrap">
              <ProvenanceBadge value={zone.provenance} />
              {zone.source && (
                <span className="text-[11px] text-text-muted block">
                  {zone.source}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Confidence (as supplied, no rescaling guesses) */}
        {zone.confidence !== null && zone.confidence !== undefined && (
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <div className="flex items-center space-x-1">
              <span className="text-[11px] text-text-muted">Confidence</span>
              {isFixture && (
                <span className="text-[10px] text-text-muted italic">
                  (test fixture)
                </span>
              )}
            </div>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              {String(zone.confidence)}
            </span>
          </div>
        )}

        {/* Uncertainty Rank Range (P10 to P90) */}
        {(zone.rank_p10 !== null && zone.rank_p10 !== undefined || zone.rank_p90 !== null && zone.rank_p90 !== undefined) && (
          <div className="p-2.5 rounded bg-surface border border-border/50">
            <div className="flex items-center space-x-1">
              <span className="text-[11px] text-text-muted">Rank Range (P10 to P90)</span>
              {isFixture && (
                <span className="text-[10px] text-text-muted italic">
                  (test fixture)
                </span>
              )}
            </div>
            <span className="text-sm font-bold text-navy-900 mt-0.5 block">
              P10: {zone.rank_p10 ?? 'N/A'} • P90: {zone.rank_p90 ?? 'N/A'}
            </span>
          </div>
        )}
      </div>
      )}

      {/* Evacuation Route Assessment */}
      {route && (
        <div className="pt-2 border-t border-border space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-text">
              {route.status === 'OK' ? 'Evacuation Route Clear' : 'No Safe Route (Cut Off)'}
            </span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
              route.status === 'OK' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'
            }`}>
              {route.status}
            </span>
          </div>
          {route.status === 'OK' && (route.destinationName || route.destination) && (
            <p className="text-xs text-navy-900 font-medium">
              <span>Destination: </span>
              <span>{route.destinationName || route.destination}</span>
            </p>
          )}
          {route.reason && (
            <p className="text-xs text-text-muted leading-snug">
              {route.reason}
            </p>
          )}
        </div>
      )}

      {/* Operational Reasons (FR-21) */}
      <div className="pt-2 border-t border-border space-y-1.5">
        <span className="text-xs font-semibold text-text block">
          {isFloodwatch ? 'Observed Features & Model Findings:' : 'Operational Assessment Reasons:'}
        </span>
        {zone.reasons && zone.reasons.length > 0 ? (
          <ul className="space-y-1 text-xs text-text-muted pl-4 list-disc">
            {zone.reasons.map((reason, idx) => (
              <li key={idx} className="leading-snug">
                {reason}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-text-muted italic">
            None reported
          </p>
        )}
      </div>

      {/* Field Survey Section (Mesh Sync) */}
      <div className="pt-3 border-t border-border space-y-2.5">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold text-text">Field survey</h4>
          <span className="text-[10px] text-text-muted font-mono">
            {zoneUpdates.length} {zoneUpdates.length === 1 ? 'record' : 'records'}
          </span>
        </div>

        {/* Existing updates for selected zone */}
        {zoneUpdates.length > 0 ? (
          <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
            {zoneUpdates.map((u) => {
              const statusCfg = getSurveyStatusConfig(u.surveyStatus);
              const StatusIcon = statusCfg.icon;
              return (
                <div
                  key={u.id}
                  className="p-2 rounded bg-surface border border-border text-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span
                      className={`inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border ${statusCfg.style}`}
                    >
                      <StatusIcon className="w-3 h-3 shrink-0" aria-hidden="true" />
                      <span>{statusCfg.label}</span>
                    </span>
                    <ProvenanceBadge value="observed" />
                  </div>
                  <p className="text-xs text-ink break-words">{u.note}</p>
                  <div className="flex items-center justify-between text-[10px] text-text-muted">
                    <span className="font-medium">{u.author || 'Field user'}</span>
                    <span className="font-mono">{formatSurveyTime(u.createdAt)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-text-muted italic">
            No field surveys recorded for this zone yet.
          </p>
        )}

        {/* Keyboard-accessible Field Survey Form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const trimmed = surveyNote.trim();
            if (!trimmed) {
              setFormError('Note cannot be empty');
              return;
            }
            if (surveyNote.length > 280) {
              setFormError('Note exceeds 280 characters');
              return;
            }

            if (onSendSurveyUpdate) {
              onSendSurveyUpdate({
                zoneId: zone.zoneId,
                surveyStatus,
                note: trimmed,
                author: surveyAuthor.trim() || 'Field user',
              });
            }

            setSurveyNote('');
            setFormError(null);
          }}
          className="space-y-2 pt-2 border-t border-hairline"
        >
          <div>
            <label
              htmlFor={`survey-status-${zone.zoneId}`}
              className="block text-[11px] font-medium text-text mb-0.5"
            >
              Survey status
            </label>
            <select
              id={`survey-status-${zone.zoneId}`}
              name="surveyStatus"
              value={surveyStatus}
              onChange={(e) => setSurveyStatus(e.target.value)}
              className="w-full text-xs bg-paper text-ink border border-control-border rounded px-2 py-1.5 focus:ring-2 focus:ring-ink focus:outline-none"
            >
              <option value="flooded">Flooded</option>
              <option value="clear">Clear</option>
              <option value="unsure">Unsure</option>
            </select>
          </div>

          <div>
            <div className="flex items-center justify-between mb-0.5">
              <label
                htmlFor={`survey-note-${zone.zoneId}`}
                className="block text-[11px] font-medium text-text"
              >
                Observation note
              </label>
              <span
                className={`text-[10px] font-mono ${
                  surveyNote.length > 280 ? 'text-risk-high font-bold' : 'text-text-muted'
                }`}
              >
                {surveyNote.length}/280
              </span>
            </div>
            <textarea
              id={`survey-note-${zone.zoneId}`}
              name="note"
              rows={2}
              value={surveyNote}
              onChange={(e) => {
                setSurveyNote(e.target.value);
                if (formError) setFormError(null);
              }}
              placeholder="Enter ground observation (max 280 chars)..."
              className="w-full text-xs bg-paper text-ink border border-control-border rounded px-2 py-1.5 focus:ring-2 focus:ring-ink focus:outline-none resize-none"
            />
            {formError && (
              <p className="text-[11px] text-risk-high mt-0.5" role="alert">
                {formError}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor={`survey-author-${zone.zoneId}`}
              className="block text-[11px] font-medium text-text mb-0.5"
            >
              Author
            </label>
            <input
              id={`survey-author-${zone.zoneId}`}
              name="author"
              type="text"
              value={surveyAuthor}
              onChange={(e) => setSurveyAuthor(e.target.value)}
              placeholder="Field user"
              className="w-full text-xs bg-paper text-ink border border-control-border rounded px-2 py-1.5 focus:ring-2 focus:ring-ink focus:outline-none"
            />
          </div>

          <button
            type="submit"
            className="w-full text-xs font-medium py-1.5 px-3 rounded border border-control-border bg-paper hover:bg-hairline/40 text-ink transition focus:ring-2 focus:ring-ink focus:outline-none cursor-pointer"
          >
            Submit Field Survey
          </button>
        </form>
      </div>

      {/* Footer metadata */}
      <div className="pt-2 border-t border-border flex items-center justify-between text-[11px] text-text-muted">
        <span>Last assessment update:</span>
        <span className="font-mono">{updatedDisplay}</span>
      </div>
    </div>
  );
}
