import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

/**
 * EmptyState component (FR-50, T5.1, design.md Section 4)
 * Renders when data payload contains no zones or study areas.
 * Hard rule: Never fabricate risk or imply complete safety when zones are missing.
 */
export default function EmptyState({ onRefresh, loading = false }) {
  return (
    <div
      role="region"
      aria-label="Empty Data State"
      className="min-h-[480px] w-full flex flex-col items-center justify-center p-8 text-center bg-card border border-border rounded-card shadow-xs font-sans space-y-4"
    >
      <div className="w-14 h-14 rounded-full bg-slate-100 border border-border flex items-center justify-center text-text-muted">
        <AlertCircle className="w-7 h-7 text-amber-600" aria-hidden="true" />
      </div>

      <div className="space-y-1.5 max-w-md">
        <h3 className="text-heading font-bold text-navy-900">
          No Zones Available
        </h3>
        <p className="text-xs text-text-muted leading-relaxed">
          No flood risk zones or operational sectors are reported for the selected area.
          This does not imply zero risk; assessment data has not yet been submitted or loaded.
        </p>
      </div>

      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex items-center space-x-2 px-3.5 py-2 rounded-md bg-navy-900 hover:bg-navy-700 active:scale-95 text-white text-xs font-semibold transition disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-flood"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          <span>Check for Updates</span>
        </button>
      )}
    </div>
  );
}
