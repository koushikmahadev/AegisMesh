import React from 'react';
import { AlertOctagon, AlertCircle, ShieldCheck, HelpCircle } from 'lucide-react';

/**
 * RiskBadge component (design.md Section 4, rules.md)
 * Renders an accessible risk indicator pill with text label and icon.
 * Hard rule: Risk is never conveyed by colour alone.
 * UNKNOWN zones use dashed outline.
 */
export const RISK_CONFIG = {
  CRITICAL: {
    icon: AlertOctagon,
    label: 'CRITICAL',
    className: 'bg-red-100 text-risk-critical border border-risk-critical/40',
  },
  HIGH: {
    icon: AlertOctagon,
    label: 'HIGH',
    className: 'bg-red-50 text-risk-high border border-risk-high/30',
  },
  MEDIUM: {
    icon: AlertCircle,
    label: 'MEDIUM',
    className: 'bg-amber-50 text-amber-900 border border-risk-medium/60',
  },
  LOW: {
    icon: ShieldCheck,
    label: 'LOW',
    className: 'bg-emerald-50 text-risk-low border border-risk-low/30',
  },
  UNKNOWN: {
    icon: HelpCircle,
    label: 'UNKNOWN',
    className: 'bg-gray-100 text-gray-700 border border-dashed border-gray-400',
  },
};

export default function RiskBadge({ level = 'UNKNOWN', size = 'sm' }) {
  const normLevel = (level || 'UNKNOWN').toUpperCase();
  const config = RISK_CONFIG[normLevel] || RISK_CONFIG.UNKNOWN;
  const Icon = config.icon;

  const sizeClasses = size === 'lg'
    ? 'px-2.5 py-1 text-xs gap-1.5'
    : 'px-2 py-0.5 text-[11px] gap-1';

  const iconSizes = size === 'lg' ? 'w-3.5 h-3.5' : 'w-3 h-3';

  return (
    <span
      className={`inline-flex items-center font-bold rounded-badge shrink-0 ${sizeClasses} ${config.className}`}
      role="status"
      aria-label={`Risk level: ${config.label}`}
    >
      <Icon className={`${iconSizes} shrink-0`} aria-hidden="true" />
      <span>{config.label}</span>
    </span>
  );
}
