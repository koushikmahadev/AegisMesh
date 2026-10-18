import React from 'react';
import { Printer, RefreshCw } from 'lucide-react';

/**
 * Cartographic Title Block (Survey Plate Header)
 * Strictly derives area of interest, timestamps, and data basis from metadata.
 * Free of invented dates, fictitious locations, and promotional copy.
 */
export default function Header({
  studyArea = null,
  timestamp = null,
  dataMode = 'demo',
  dataSource = null,
  source = null,
  onRefresh,
  loading = false,
  lastRefreshedAt = null,
  meshStatus = 'offline',
  meshPeerCount = 0,
}) {
  const activeSource = dataSource || (typeof import.meta !== 'undefined' ? import.meta.env?.VITE_DATA_SOURCE : null);

  const isUnverified =
    typeof studyArea === 'string' &&
    (studyArea.toLowerCase().includes('unverified') || studyArea.toLowerCase().includes('unknown'));

  const isFloodWatch =
    activeSource === 'mock-floodwatch' ||
    (typeof source === 'string' && source.includes('FloodWatch')) ||
    (typeof studyArea === 'string' && studyArea.includes('FloodWatch'));

  const isDernau =
    !isUnverified &&
    !isFloodWatch &&
    dataMode === 'demo' &&
    studyArea &&
    !studyArea.includes('Bengaluru') &&
    (activeSource === 'mock-dernau' ||
      (typeof source === 'string' && source.includes('SpaceNet')) ||
      (typeof studyArea === 'string' && studyArea.includes('Dernau')));

  const isDemo = dataMode === 'demo' && !isDernau && !isFloodWatch && !isUnverified;

  const formatTimestamp = (ts) => {
    if (!ts) return 'Not available';
    try {
      const date = new Date(ts);
      if (isNaN(date.getTime())) return ts;
      return date.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    } catch {
      return ts;
    }
  };

  const formatHHMM = (ts) => {
    if (!ts) return null;
    try {
      const date = new Date(ts);
      if (isNaN(date.getTime())) return null;
      const h = String(date.getHours()).padStart(2, '0');
      const m = String(date.getMinutes()).padStart(2, '0');
      return `${h}:${m}`;
    } catch {
      return null;
    }
  };

  const lastRefreshedTime = formatHHMM(lastRefreshedAt);

  const handlePrint = () => {
    if (typeof window !== 'undefined') {
      window.print();
    }
  };

  return (
    <header className="bg-plate border-b border-hairline px-4 py-3 sm:px-6 flex flex-col md:flex-row md:items-center md:justify-between gap-3 font-sans text-ink shrink-0">
      {/* Title & Archival Registry */}
      <div className="flex items-start sm:items-center space-x-3">
        <div className="border border-control-border px-2 py-1 rounded bg-paper text-ink font-serif font-bold text-xs tracking-wider shrink-0 uppercase">
          Survey Plate
        </div>
        <div>
          <div className="flex items-baseline space-x-2">
            <h1 className="text-lg sm:text-xl font-serif font-bold text-ink tracking-tight">
              HIGHWATER
            </h1>
            <span className="text-xs text-ink-muted font-serif italic">
              Geospatial Flood Assessment
            </span>
          </div>
          <p className="text-[11px] text-ink-muted">
            Data basis: {source || (isFloodWatch ? 'SpaceNet 8 / FloodWatch SegFormer-B0' : 'Hydrological Survey Network')}
          </p>
        </div>
      </div>

      {/* Metadata Indicators: Area of Interest & Timestamps */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        {studyArea && (
          <div className="flex items-center space-x-1.5">
            <span className="font-medium text-ink">Area:</span>
            <span className="font-serif">{studyArea}</span>
          </div>
        )}

        <div className="flex items-center space-x-1.5">
          <span className="font-medium text-ink">Data package generated:</span>
          <span className="font-mono">{formatTimestamp(timestamp)}</span>
        </div>

        {lastRefreshedTime && (
          <div className="flex items-center space-x-1.5">
            <span className="font-medium text-ink">Last refreshed:</span>
            <span className="font-mono">{lastRefreshedTime}</span>
          </div>
        )}
      </div>

      {/* Operational Stamps & Actions */}
      <div className="flex items-center space-x-2.5 shrink-0">
        {/* Archival Status Stamp */}
        {isUnverified ? (
          <div
            className="px-2.5 py-1 rounded border border-control-border bg-paper text-ink font-mono text-[11px] font-semibold tracking-wider uppercase"
            role="status"
            aria-label="Unverified location active"
          >
            Unverified location
          </div>
        ) : isFloodWatch || isDernau ? (
          <div
            className="px-2.5 py-1 rounded border border-control-border bg-paper text-ink font-mono text-[11px] font-semibold tracking-wider uppercase"
            role="status"
            aria-label="Simulated operations environment active"
          >
            Simulated Ops
          </div>
        ) : isDemo ? (
          <div
            className="px-2.5 py-1 rounded border border-notice bg-paper text-notice font-mono text-[11px] font-semibold tracking-wider uppercase"
            role="status"
            aria-label="Demonstration mode active"
          >
            DEMO MODE
          </div>
        ) : (
          <div
            className="px-2.5 py-1 rounded border border-control-border bg-paper text-ink font-mono text-[11px] font-semibold tracking-wider uppercase"
            role="status"
            aria-label="Connected data active"
          >
            Connected data
          </div>
        )}

        {/* Mesh Network Status Badge */}
        <div
          className="px-2.5 py-1 rounded border border-control-border bg-paper text-ink font-mono text-[11px] font-semibold tracking-wider"
          role="status"
          aria-live="polite"
        >
          {meshStatus === 'active'
            ? `Mesh active - ${meshPeerCount} peers connected`
            : 'Mesh offline'}
        </div>

        {/* Print Situation Report Button */}
        <button
          type="button"
          onClick={handlePrint}
          aria-label="Print situation report"
          className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded border border-control-border bg-paper hover:bg-hairline/40 text-ink text-xs font-medium transition cursor-pointer select-none"
        >
          <Printer className="w-3.5 h-3.5 text-ink-muted" aria-hidden="true" />
          <span className="hidden sm:inline">Print Report</span>
        </button>

        {/* Refresh Action Button */}
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          aria-label="Refresh survey data"
          className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded border border-control-border bg-paper hover:bg-hairline/40 text-ink text-xs font-medium transition disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer select-none"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          <span className="hidden sm:inline">Refresh</span>
        </button>
      </div>
    </header>
  );
}
