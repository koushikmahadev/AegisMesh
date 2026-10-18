import React from 'react';
import { Loader2 } from 'lucide-react';

/**
 * LoadingState component (FR-50, T5.1, design.md Section 4)
 * Renders pulse skeletons for stat cards, map surface, and list, plus "Loading data…"
 */
export default function LoadingState({ message = 'Loading flood response data…' }) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading flood assessment data"
      className="min-h-screen bg-surface flex flex-col font-sans"
    >
      {/* Header Skeleton */}
      <header className="h-14 bg-navy-900 border-b border-navy-700 px-4 md:px-6 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-md bg-flood/20 flex items-center justify-center text-flood font-bold">
            HW
          </div>
          <span className="text-title font-bold tracking-wider text-white">
            HIGHWATER
          </span>
        </div>
        <div className="flex items-center space-x-2 text-slate-300 text-xs">
          <Loader2 className="w-4 h-4 animate-spin text-flood" aria-hidden="true" />
          <span className="font-medium text-white">{message}</span>
        </div>
      </header>

      {/* Main Content Area Skeletons */}
      <main className="flex-1 p-4 lg:p-6 max-w-7xl w-full mx-auto space-y-6">
        {/* Stat Cards Skeletons */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="bg-card border border-border rounded-card p-4 shadow-xs space-y-3"
            >
              <div className="flex justify-between items-start">
                <div className="h-3 w-24 bg-slate-200 rounded animate-pulse" />
                <div className="w-7 h-7 rounded-md bg-slate-200 animate-pulse" />
              </div>
              <div className="h-8 w-20 bg-slate-200 rounded animate-pulse" />
              <div className="h-2.5 w-32 bg-slate-200 rounded animate-pulse" />
            </div>
          ))}
        </div>

        {/* Map and Side Panel Skeletons */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Map Area Skeleton */}
          <div className="lg:col-span-8 bg-card border border-border rounded-card h-[480px] lg:h-[540px] flex flex-col overflow-hidden shadow-xs">
            <div className="p-3 border-b border-border bg-slate-50 flex items-center justify-between">
              <div className="h-4 w-40 bg-slate-200 rounded animate-pulse" />
              <div className="h-4 w-20 bg-slate-200 rounded animate-pulse" />
            </div>
            <div className="flex-1 bg-slate-100 flex flex-col items-center justify-center space-y-3">
              <Loader2 className="w-8 h-8 animate-spin text-flood" aria-hidden="true" />
              <p className="text-xs font-semibold text-text-muted">Initialising geospatial engine…</p>
            </div>
          </div>

          {/* Controls & Details Skeletons */}
          <div className="lg:col-span-4 space-y-4">
            <div className="bg-card border border-border rounded-card p-4 space-y-3 shadow-xs">
              <div className="h-4 w-28 bg-slate-200 rounded animate-pulse" />
              <div className="space-y-2">
                {[1, 2, 3, 4, 5].map((j) => (
                  <div key={j} className="h-6 bg-slate-100 rounded animate-pulse" />
                ))}
              </div>
            </div>
            <div className="bg-card border border-border rounded-card p-6 flex flex-col items-center justify-center space-y-2 h-48 shadow-xs">
              <div className="w-8 h-8 rounded-full bg-slate-200 animate-pulse" />
              <div className="h-3 w-32 bg-slate-200 rounded animate-pulse" />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
