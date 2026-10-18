import React from 'react';

/**
 * StatCard component
 * Displays a single operational metric.
 * Per rules.md:
 * - Missing numeric data renders "Not available", never 0.
 * - Demo values carry an "Illustrative" caption.
 */
export default function StatCard({
  title,
  value,
  unit = '',
  isDemo = true,
  icon: Icon,
  variant = 'default',
  caption,
}) {
  const hasValue = value !== null && value !== undefined && value !== '';
  const displayValue = hasValue ? value : 'Not available';

  // Variant styling for subtle accent border / icon highlight
  const variantStyles = {
    default: 'text-text-muted',
    flood: 'text-flood',
    highRisk: 'text-risk-high',
    warning: 'text-risk-medium',
    lowRisk: 'text-risk-low',
  };

  const iconClass = variantStyles[variant] || variantStyles.default;

  return (
    <div className="bg-card border border-border/80 rounded-card p-4 shadow-xs flex flex-col justify-between transition hover:shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-body font-medium text-text-muted">{title}</span>
        {Icon && (
          <div className={`p-1.5 rounded-md bg-surface ${iconClass}`}>
            <Icon className="w-5 h-5" aria-hidden="true" />
          </div>
        )}
      </div>

      <div className="flex items-baseline space-x-1.5">
        <span className={`text-stat font-bold font-mono tracking-tight ${hasValue ? 'text-text' : 'text-text-muted text-lg font-normal italic'}`}>
          {displayValue}
        </span>
        {hasValue && unit && (
          <span className="text-body font-medium text-text-muted">{unit}</span>
        )}
      </div>

      <div className="mt-2 flex items-center justify-between text-caption text-text-muted pt-2 border-t border-border/50">
        <span>{caption || (isDemo ? 'Simulated data' : 'Verified sensor')}</span>
        {isDemo && (
          <span className="text-[10px] font-semibold tracking-wider uppercase px-1.5 py-0.5 rounded bg-sky-50 text-sky-800 border border-sky-200">
            Simulated
          </span>
        )}
      </div>
    </div>
  );
}
