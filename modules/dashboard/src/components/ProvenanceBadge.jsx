import React from 'react';

/**
 * ProvenanceBadge component (FR-43, FR-60, design.md section 4)
 * Displays data origin status: Observed (solid navy), Derived (outlined navy), or Simulated (dashed amber).
 *
 * @param {Object} props
 * @param {'observed'|'derived'|'simulated'|string} props.value
 * @param {string} [props.className]
 */
export default function ProvenanceBadge({ value, className = '' }) {
  if (!value || typeof value !== 'string') return null;

  const normalized = value.toLowerCase().trim();

  let label = 'Observed';
  let badgeStyle = 'bg-navy-900 text-white border-transparent';

  if (normalized === 'derived') {
    label = 'Derived';
    badgeStyle = 'bg-transparent text-navy-700 border border-navy-700';
  } else if (normalized === 'simulated') {
    label = 'Simulated';
    badgeStyle = 'bg-amber-50 text-amber-800 border border-dashed border-amber-600';
  } else if (normalized === 'observed') {
    label = 'Observed';
    badgeStyle = 'bg-navy-900 text-white border-transparent';
  } else {
    label = value;
    badgeStyle = 'bg-slate-100 text-slate-700 border border-slate-300';
  }

  return (
    <span
      aria-label={`Data provenance: ${label}`}
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide uppercase select-none ${badgeStyle} ${className}`}
    >
      {label}
    </span>
  );
}
