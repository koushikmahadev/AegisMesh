import React from 'react';
import { Database, RefreshCw } from 'lucide-react';
import { formatCachedTimestamp } from '../hooks/useDashboardData.js';

/**
 * CachedBanner component
 * Displays a warning when displaying an offline cached snapshot after fetch failure.
 * Never shown alongside live data.
 * Displays HH:MM, plus the date if the snapshot is not from today.
 */
export default function CachedBanner({ isFromCache, cachedAt, onRefresh }) {
  if (!isFromCache || !cachedAt) {
    return null;
  }

  const formattedTime = formatCachedTimestamp(cachedAt);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Offline Cached Data Warning"
      className="p-3 bg-amber-50 border border-amber-600 rounded-card text-xs text-amber-900 flex items-center justify-between gap-3 shadow-xs font-sans"
    >
      <div className="flex items-center space-x-2 min-w-0">
        <Database className="w-4 h-4 text-amber-700 shrink-0" aria-hidden="true" />
        <span className="font-medium">
          Network fetch failed. Showing cached snapshot from {formattedTime}.
        </span>
      </div>

      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          className="text-[11px] font-semibold text-amber-800 hover:text-amber-950 underline shrink-0 inline-flex items-center space-x-1"
        >
          <RefreshCw className="w-3 h-3 mr-1" aria-hidden="true" />
          Retry
        </button>
      )}
    </div>
  );
}
