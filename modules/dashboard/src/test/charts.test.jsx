import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import RiskDistributionChart from '../components/RiskDistributionChart.jsx';
import ImpactChart from '../components/ImpactChart.jsx';

describe('Charts (T4.9, FR-30, FR-31)', () => {
  const sampleZones = [
    { zoneId: 'zone-001', name: 'Alpha Basin', riskLevel: 'HIGH', exposedBuildings: 40 },
    { zoneId: 'zone-002', name: 'Beta Ridge', riskLevel: 'MEDIUM', exposedBuildings: 25 },
    { zoneId: 'zone-003', name: 'Gamma Valley', riskLevel: 'LOW', exposedBuildings: 10 },
    { zoneId: 'zone-004', name: 'Delta Heights', riskLevel: 'UNKNOWN', exposedBuildings: null },
  ];

  describe('RiskDistributionChart', () => {
    it('renders chart title, total count, and container', () => {
      render(<RiskDistributionChart zones={sampleZones} />);

      expect(screen.getByText('Risk Classification Distribution')).toBeInTheDocument();
      expect(screen.getByText('Total: 4')).toBeInTheDocument();
      expect(screen.getByRole('img', { name: /Bar chart showing risk classification distribution/i })).toBeInTheDocument();
    });

    it('renders "No data available" when zones list is empty', () => {
      render(<RiskDistributionChart zones={[]} />);

      expect(screen.getByText('Risk Classification Distribution')).toBeInTheDocument();
      expect(screen.getByText('No data available')).toBeInTheDocument();
    });
  });

  describe('ImpactChart', () => {
    it('renders chart title, reporting count, and excludes null values', () => {
      render(<ImpactChart zones={sampleZones} />);

      expect(screen.getByText('Top Impacted Zones (Exposed Buildings)')).toBeInTheDocument();
      // Only 3 zones have non-null exposedBuildings
      expect(screen.getByText('Reporting: 3 zones')).toBeInTheDocument();
      expect(screen.getByRole('img', { name: /Horizontal bar chart showing top zones by exposed buildings/i })).toBeInTheDocument();
    });

    it('renders "No building exposure data available" when no zones have exposed building data', () => {
      const nullOnlyZones = [
        { zoneId: 'zone-004', name: 'Delta Heights', riskLevel: 'UNKNOWN', exposedBuildings: null },
      ];
      render(<ImpactChart zones={nullOnlyZones} />);

      expect(screen.getByText('Top Impacted Zones (Exposed Buildings)')).toBeInTheDocument();
      expect(screen.getByText('No building exposure data available')).toBeInTheDocument();
    });

    it('renders relabeled "Observed Flooded Buildings per Tile" in mock-floodwatch mode', () => {
      const floodwatchZones = [
        { zoneId: '0_41_58', name: 'Tile 0_41_58', riskLevel: 'UNKNOWN', exposedBuildings: 169, observed_flooded_count: 181 },
        { zoneId: '0_23_62', name: 'Tile 0_23_62', riskLevel: 'UNKNOWN', exposedBuildings: 94, observed_flooded_count: 101 },
      ];
      render(<ImpactChart zones={floodwatchZones} isFloodwatchMode={true} />);

      expect(screen.getByText('Observed Flooded Buildings per Tile')).toBeInTheDocument();
      expect(screen.getByText('Reporting: 2 tiles')).toBeInTheDocument();
      expect(screen.getByRole('img', { name: /Horizontal bar chart showing observed flooded buildings per tile/i })).toBeInTheDocument();
    });
  });

  describe('FloodWatch Mode Charts (Real counts, zero risk inference)', () => {
    const floodwatchZones = [
      { zoneId: '0_41_58', name: 'Tile 0_41_58', riskLevel: 'UNKNOWN', exposedBuildings: 169, observed_flooded_count: 181 },
      { zoneId: '0_23_62', name: 'Tile 0_23_62', riskLevel: 'UNKNOWN', exposedBuildings: 94, observed_flooded_count: 101 },
    ];

    it('renders "Observed Flooded Features per Tile" with axis labels and real counts', () => {
      render(<RiskDistributionChart zones={floodwatchZones} isFloodwatchMode={true} />);

      expect(screen.getByText('Observed Flooded Features per Tile')).toBeInTheDocument();
      expect(screen.getByText('Total: 282 features')).toBeInTheDocument();
      expect(screen.getByRole('img', { name: /Bar chart showing observed flooded features per tile/i })).toBeInTheDocument();
      // Should NOT contain risk classification labels
      expect(screen.queryByText('Risk Classification Distribution')).not.toBeInTheDocument();
    });
  });
});
