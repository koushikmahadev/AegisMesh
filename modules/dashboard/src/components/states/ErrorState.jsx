import React from 'react';
import { AlertOctagon, RotateCw } from 'lucide-react';

/**
 * ErrorState component (FR-50, T5.1, design.md Section 4)
 * Displays readable operational error notification with actionable retry button.
 */
export default function ErrorState({
  error = 'Failed to load flood monitoring data.',
  onRetry,
  loading = false,
}) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="p-4 bg-red-50/90 border border-risk-high/40 rounded-card text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs font-sans"
    >
      <div className="flex items-start sm:items-center space-x-2.5 min-w-0">
        <div className="p-1 rounded bg-red-100 text-risk-high shrink-0 mt-0.5 sm:mt-0">
          <AlertOctagon className="w-4 h-4" aria-hidden="true" />
        </div>
        <div>
          <div className="font-bold text-risk-high text-xs">
            Data Synchronization Issue
          </div>
          <div className="text-text text-[11px] mt-0.5">
            {error}
          </div>
        </div>
      </div>

      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={loading}
          className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-risk-high hover:bg-red-800 active:scale-95 text-white rounded font-medium text-xs transition disabled:opacity-50 shrink-0 focus:outline-none focus:ring-2 focus:ring-red-900"
        >
          <RotateCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          <span>Retry</span>
        </button>
      )}
    </div>
  );
}
