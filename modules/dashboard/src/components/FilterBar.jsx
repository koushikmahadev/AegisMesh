import React from 'react';
import { Search, X, ArrowUpDown, Filter } from 'lucide-react';

/**
 * FilterBar component (T4.4, FR-22, FR-23)
 * Provides risk classification filter, keyword search, and sorting controls.
 * Shows "Showing N of M zones" when an operational filter is active (T4.8).
 */
export default function FilterBar({
  filters = { search: '', riskLevel: 'ALL' },
  sortBy = 'priority',
  onFilterChange,
  onSortChange,
  totalCount = 0,
  filteredCount = 0,
}) {
  const isFiltered = filters.riskLevel !== 'ALL' || filters.search.trim() !== '';

  const riskOptions = ['ALL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'];

  const sortOptions = [
    { value: 'priority', label: 'Priority' },
    { value: 'score', label: 'Risk Score' },
    { value: 'buildings', label: 'Exposed Buildings' },
    { value: 'name', label: 'Zone Name' },
  ];

  return (
    <div className="bg-card border border-border rounded-card p-3 shadow-sm space-y-3 font-sans">
      {/* Top row: Search input & Sort dropdown */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-stretch sm:items-center justify-between">
        {/* Search Input */}
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-text-muted absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="text"
            placeholder="Search by zone ID or name..."
            value={filters.search}
            onChange={(e) => onFilterChange({ ...filters, search: e.target.value })}
            className="w-full pl-8 pr-8 py-1.5 text-xs bg-surface border border-border rounded-md text-text focus:outline-none focus:ring-2 focus:ring-flood focus:bg-white transition"
            aria-label="Search zones by ID or name"
          />
          {filters.search && (
            <button
              type="button"
              onClick={() => onFilterChange({ ...filters, search: '' })}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text p-0.5"
              aria-label="Clear search keyword"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Sort Selector */}
        <div className="flex items-center space-x-1.5 shrink-0">
          <ArrowUpDown className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
          <span className="text-[11px] text-text-muted font-medium">Sort:</span>
          <select
            value={sortBy}
            onChange={(e) => onSortChange(e.target.value)}
            className="py-1 px-2 text-xs bg-surface border border-border rounded-md text-text focus:outline-none focus:ring-2 focus:ring-flood cursor-pointer"
            aria-label="Sort zones list"
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Bottom row: Risk classification filter pills & Filter Count Status */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border">
        {/* Risk Pills */}
        <div className="flex items-center space-x-1" role="group" aria-label="Filter by Risk Category">
          <Filter className="w-3.5 h-3.5 text-text-muted mr-1 hidden sm:inline" aria-hidden="true" />
          {riskOptions.map((level) => {
            const isSelected = filters.riskLevel === level;
            return (
              <button
                key={level}
                type="button"
                onClick={() => onFilterChange({ ...filters, riskLevel: level })}
                className={`px-2 py-0.5 text-[11px] font-semibold rounded-badge transition ${
                  isSelected
                    ? 'bg-navy-900 text-white shadow-xs'
                    : 'bg-surface text-text-muted hover:bg-slate-200 hover:text-text border border-border/60'
                }`}
                aria-pressed={isSelected}
              >
                {level}
              </button>
            );
          })}
        </div>

        {/* Showing N of M zones Indicator (T4.8) */}
        <div className="text-[11px] text-text-muted font-medium">
          {isFiltered ? (
            <span className="text-navy-900 font-bold bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
              Showing {filteredCount} of {totalCount} zones
            </span>
          ) : (
            <span>All {totalCount} zones</span>
          )}
        </div>
      </div>
    </div>
  );
}
