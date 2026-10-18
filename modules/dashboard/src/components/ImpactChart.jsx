import React from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  CartesianGrid,
} from 'recharts';
import { THEME } from '../config/theme.js';
import { selectImpactChartData } from '../features/dashboard/dashboardSelectors.js';

function ImpactTooltip({ active, payload, isFloodwatch = false }) {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="bg-card border border-border p-2 rounded shadow-md text-xs font-sans">
        <div className="font-bold text-navy-900">{data.fullName}</div>
        <div className="text-text-muted mt-0.5">
          {isFloodwatch ? 'Observed flooded buildings (labels): ' : 'Exposed Buildings: '}
          <span className="font-semibold text-text">{data.exposedBuildings}</span>
        </div>
        {!isFloodwatch && (
          <div className="text-[11px] text-text-muted mt-0.5">
            Risk Classification: <span className="font-semibold">{data.riskLevel}</span>
          </div>
        )}
      </div>
    );
  }
  return null;
}

/**
 * ImpactChart component (FR-31, T4.9)
 * Renders Recharts horizontal bar chart showing top zones by exposed buildings / observed flooded buildings.
 * Excludes null values and never coerces them to zero (rules.md).
 */
export default function ImpactChart({ zones = [], isFloodwatchMode = false }) {
  const isFloodwatch = isFloodwatchMode || Boolean(zones.length > 0 && zones.some((z) => typeof z.observed_flooded_count === 'number'));
  const data = selectImpactChartData(zones, 5);

  const titleText = isFloodwatch
    ? 'Observed Flooded Buildings per Tile'
    : 'Top Impacted Zones (Exposed Buildings)';

  const emptyText = isFloodwatch
    ? 'No observed building data available'
    : 'No building exposure data available';

  const xAxisLabel = isFloodwatch
    ? 'Observed flooded buildings (labels)'
    : 'Exposed Buildings';

  if (!zones || zones.length === 0 || data.length === 0) {
    return (
      <div className="bg-card border border-border rounded-card p-4 flex flex-col justify-between h-full font-sans">
        <h4 className="text-xs font-bold text-navy-900 mb-2">
          {titleText}
        </h4>
        <div
          className="h-44 bg-surface rounded flex items-center justify-center text-xs text-text-muted border border-dashed border-border"
          role="status"
        >
          {emptyText}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-card p-4 flex flex-col justify-between h-full font-sans shadow-xs">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-bold text-navy-900">
          {titleText}
        </h4>
        <span className="text-[11px] text-text-muted">
          Reporting: {data.length} {isFloodwatch ? 'tiles' : 'zones'}
        </span>
      </div>

      <div
        className="w-full h-44"
        role="img"
        aria-label={isFloodwatch ? 'Horizontal bar chart showing observed flooded buildings per tile' : 'Horizontal bar chart showing top zones by exposed buildings'}
      >
        <ResponsiveContainer width="100%" height="100%" minHeight={160}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 5, right: 20, left: 15, bottom: 20 }}
          >
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={THEME.colors.border} />
            <XAxis
              type="number"
              tick={{ fontSize: 10, fill: THEME.colors['text-muted'] }}
              tickLine={false}
              axisLine={{ stroke: THEME.colors.border }}
              label={{
                value: xAxisLabel,
                position: 'insideBottom',
                offset: -12,
                fontSize: 10,
                fill: THEME.colors['text-muted'],
              }}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 10, fill: THEME.colors['text-muted'] }}
              tickLine={false}
              axisLine={{ stroke: THEME.colors.border }}
              width={75}
            />
            <Tooltip content={<ImpactTooltip isFloodwatch={isFloodwatch} />} />
            <Bar dataKey="exposedBuildings" radius={[0, 4, 4, 0]}>
              {data.map((entry) => (
                <Cell
                  key={entry.zoneId}
                  fill={isFloodwatch ? '#b45309' : (THEME.riskColors[entry.riskLevel] || THEME.colors.flood)}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
