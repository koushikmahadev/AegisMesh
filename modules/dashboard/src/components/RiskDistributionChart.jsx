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
import {
  selectRiskDistribution,
  selectObservedFloodedFeaturesChartData,
} from '../features/dashboard/dashboardSelectors.js';

function RiskTooltip({ active, payload }) {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="bg-card border border-border p-2 rounded shadow-md text-xs font-sans">
        <div className="font-bold text-navy-900">{data.level} Risk</div>
        <div className="text-text-muted mt-0.5">
          {data.count} {data.count === 1 ? 'zone' : 'zones'}
        </div>
      </div>
    );
  }
  return null;
}

function FloodWatchTooltip({ active, payload }) {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="bg-card border border-border p-2 rounded shadow-md text-xs font-sans">
        <div className="font-bold text-navy-900">{data.fullName}</div>
        <div className="text-text-muted mt-0.5 font-medium">
          Observed flooded features (labels): <span className="font-bold text-text">{data.count}</span>
        </div>
        <div className="text-[11px] text-text-muted mt-0.5">
          Buildings: <span className="font-semibold text-text">{data.buildings}</span> • Roads: <span className="font-semibold text-text">{data.roads}</span>
        </div>
      </div>
    );
  }
  return null;
}

/**
 * RiskDistributionChart component (FR-30, T4.9)
 * In normal mode: renders Recharts bar chart showing zones by risk category.
 * In mock-floodwatch mode: replaced with a chart of observed flooded features per tile (real counts),
 * with title and axis labels, without inventing risk levels or scores.
 */
export default function RiskDistributionChart({ zones = [], isFloodwatchMode = false }) {
  const isFloodwatch = isFloodwatchMode || Boolean(zones.length > 0 && zones.some((z) => typeof z.observed_flooded_count === 'number'));

  if (isFloodwatch) {
    const data = selectObservedFloodedFeaturesChartData(zones);
    const totalFeatures = data.reduce((sum, item) => sum + item.count, 0);

    if (!zones || zones.length === 0 || data.length === 0) {
      return (
        <div className="bg-card border border-border rounded-card p-4 flex flex-col justify-between h-full font-sans">
          <h4 className="text-xs font-bold text-navy-900 mb-2">
            Observed Flooded Features per Tile
          </h4>
          <div
            className="h-44 bg-surface rounded flex items-center justify-center text-xs text-text-muted border border-dashed border-border"
            role="status"
          >
            No data available
          </div>
        </div>
      );
    }

    return (
      <div className="bg-card border border-border rounded-card p-4 flex flex-col justify-between h-full font-sans shadow-xs">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-bold text-navy-900">
            Observed Flooded Features per Tile
          </h4>
          <span className="text-[11px] text-text-muted">
            Total: {totalFeatures} features
          </span>
        </div>

        <div className="w-full h-44" role="img" aria-label="Bar chart showing observed flooded features per tile">
          <ResponsiveContainer width="100%" height="100%" minHeight={160}>
            <BarChart
              data={data}
              margin={{ top: 10, right: 10, left: -15, bottom: 20 }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={THEME.colors.border} />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 9, fill: THEME.colors['text-muted'] }}
                tickLine={false}
                axisLine={{ stroke: THEME.colors.border }}
                label={{
                  value: 'Tile ID',
                  position: 'insideBottom',
                  offset: -12,
                  fontSize: 10,
                  fill: THEME.colors['text-muted'],
                }}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 10, fill: THEME.colors['text-muted'] }}
                tickLine={false}
                axisLine={{ stroke: THEME.colors.border }}
                label={{
                  value: 'Flooded Features (Labels)',
                  angle: -90,
                  position: 'insideLeft',
                  offset: 25,
                  fontSize: 10,
                  fill: THEME.colors['text-muted'],
                }}
              />
              <Tooltip content={<FloodWatchTooltip />} />
              <Bar dataKey="count" fill="#d97706" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  // Normal risk distribution mode
  const data = selectRiskDistribution(zones);
  const totalZones = data.reduce((sum, item) => sum + item.count, 0);

  if (!zones || zones.length === 0 || totalZones === 0) {
    return (
      <div className="bg-card border border-border rounded-card p-4 flex flex-col justify-between h-full font-sans">
        <h4 className="text-xs font-bold text-navy-900 mb-2">
          Risk Classification Distribution
        </h4>
        <div
          className="h-44 bg-surface rounded flex items-center justify-center text-xs text-text-muted border border-dashed border-border"
          role="status"
        >
          No data available
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-card p-4 flex flex-col justify-between h-full font-sans shadow-xs">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-bold text-navy-900">
          Risk Classification Distribution
        </h4>
        <span className="text-[11px] text-text-muted">
          Total: {totalZones}
        </span>
      </div>

      <div className="w-full h-44" role="img" aria-label="Bar chart showing risk classification distribution">
        <ResponsiveContainer width="100%" height="100%" minHeight={160}>
          <BarChart
            data={data}
            margin={{ top: 10, right: 10, left: -20, bottom: 20 }}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={THEME.colors.border} />
            <XAxis
              dataKey="level"
              tick={{ fontSize: 10, fill: THEME.colors['text-muted'] }}
              tickLine={false}
              axisLine={{ stroke: THEME.colors.border }}
              label={{
                value: 'Risk Level',
                position: 'insideBottom',
                offset: -12,
                fontSize: 10,
                fill: THEME.colors['text-muted'],
              }}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 10, fill: THEME.colors['text-muted'] }}
              tickLine={false}
              axisLine={{ stroke: THEME.colors.border }}
              label={{
                value: 'Zones',
                angle: -90,
                position: 'insideLeft',
                offset: 25,
                fontSize: 10,
                fill: THEME.colors['text-muted'],
              }}
            />
            <Tooltip content={<RiskTooltip />} />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {data.map((entry) => (
                <Cell key={entry.level} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
