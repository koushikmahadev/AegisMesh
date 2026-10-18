import React from 'react';
import { AlertTriangle, Clock } from 'lucide-react';

/**
 * Checks whether data is stale based on generatedAt timestamp and threshold.
 * @param {string} generatedAt ISO 8601 timestamp
 * @param {number} staleMinutes Threshold in minutes
 * @returns {boolean}
 */
export function isDataStale(generatedAt, staleMinutes = null) {
  if (!generatedAt) return false;
  const threshold = staleMinutes !== null
    ? staleMinutes
    : Number(import.meta.env?.VITE_STALE_MINUTES || 60);

  const genTime = new Date(generatedAt).getTime();
  if (Number.isNaN(genTime)) return false;

  const diffMs = Date.now() - genTime;
  const diffMinutes = diffMs / (1000 * 60);
  return diffMinutes > threshold;
}

/**
 * StaleBanner component (FR-51, T5.2, design.md Section 4)
 * Renders an amber banner warning the operator when data exceeds stale threshold.
 */
export default function StaleBanner({
  generatedAt,
  staleMinutes = null,
  onRefresh = null,
  dataMode = 'live',
}) {
  // Suppress stale warning while data_mode is "demo" (the DEMO badge already warns the operator)
  if (dataMode === 'demo') {
    return null;
  }

  const stale = isDataStale(generatedAt, staleMinutes);

  if (!stale) return null;

  let timeString = 'recently';
  try {
    const d = new Date(generatedAt);
    if (!Number.isNaN(d.getTime())) {
      timeString = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
  } catch {}

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Stale Data Warning"
      className="p-3 bg-amber-50 border border-amber-600 rounded-card text-xs text-amber-900 flex items-center justify-between gap-3 shadow-xs font-sans"
    >
      <div className="flex items-center space-x-2 min-w-0">
        <AlertTriangle className="w-4 h-4 text-amber-700 shrink-0" aria-hidden="true" />
        <span className="font-medium">
          Data last updated {timeString}. This may be out of date.
        </span>
      </div>

      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          className="text-[11px] font-semibold text-amber-800 hover:text-amber-950 underline shrink-0"
        >
          Refresh now
        </button>
      )}
    </div>
  );
}
