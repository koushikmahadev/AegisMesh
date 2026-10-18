import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ZoneDetails from '../components/ZoneDetails.jsx';

describe('ZoneDetails component (T4.5, FR-20, FR-21)', () => {
  const completeZone = {
    zoneId: 'zone-001',
    name: 'Bellandur Basin',
    riskLevel: 'HIGH',
    riskScore: 82,
    floodedAreaKm2: 2.4,
    floodedPercent: 68,
    exposedBuildings: 34,
    accessibility: 'LIMITED',
    reasons: ['Critical stormwater drainage blockage', 'Submerged access routes'],
    hasGeometry: true,
  };

  const missingDataZone = {
    zoneId: 'zone-009',
    name: 'Peripheral Relief Staging',
    riskLevel: 'UNKNOWN',
    riskScore: null,
    floodedAreaKm2: null,
    floodedPercent: null,
    exposedBuildings: null,
    accessibility: 'UNKNOWN',
    reasons: [],
    hasGeometry: false,
  };

  it('renders complete zone details with metrics, risk badge, and reasons', () => {
    render(
      <ZoneDetails
        zone={completeZone}
        timestamp="2026-10-12T10:00:00Z"
        onClearSelection={vi.fn()}
      />
    );

    expect(screen.getByText('Bellandur Basin')).toBeInTheDocument();
    expect(screen.getByText('Zone ID:')).toBeInTheDocument();
    expect(screen.getByText('zone-001')).toBeInTheDocument();
    expect(screen.getByText('82 / 100')).toBeInTheDocument();
    expect(screen.getByText('2.4 km²')).toBeInTheDocument();
    expect(screen.getByText('Coverage: 68%')).toBeInTheDocument();
    expect(screen.getByText('34')).toBeInTheDocument();
    expect(screen.getByText('Restricted access')).toBeInTheDocument();
    expect(screen.getByText('Critical stormwater drainage blockage')).toBeInTheDocument();
    expect(screen.getByText('Submerged access routes')).toBeInTheDocument();
    expect(screen.getByText('2026-10-12T10:00:00Z')).toBeInTheDocument();
  });

  it('renders "Not available" for missing fields and never coerces to 0 (T4.5, test matrix #8)', () => {
    render(
      <ZoneDetails
        zone={missingDataZone}
        timestamp={null}
        onClearSelection={vi.fn()}
      />
    );

    expect(screen.getByText('Peripheral Relief Staging')).toBeInTheDocument();
    expect(screen.getByText('Not assessed')).toBeInTheDocument();
    expect(screen.getAllByText('Not available').length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText('None reported')).toBeInTheDocument();
    expect(screen.getByText('Non-spatial staging area')).toBeInTheDocument();
    expect(screen.getByText('Partial data')).toBeInTheDocument();
  });

  it('renders "Partial data" note and preserves risk level when risk_level is supplied but other fields are null', () => {
    const partialZone = {
      zoneId: 'zone-partial',
      name: 'Partial High Zone',
      riskLevel: 'HIGH',
      riskScore: 92,
      floodedAreaKm2: 1.5,
      floodedPercent: 25,
      exposedBuildings: null, // missing numeric
      accessibility: 'OPEN',
      reasons: ['High flood impact'],
      hasGeometry: true,
      partialData: true,
    };

    render(<ZoneDetails zone={partialZone} onClearSelection={vi.fn()} />);

    expect(screen.getByText('Partial High Zone')).toBeInTheDocument();
    expect(screen.getByText('HIGH')).toBeInTheDocument();
    expect(screen.getByText('92 / 100')).toBeInTheDocument();
    expect(screen.getByText('Partial data')).toBeInTheDocument();
    expect(screen.getAllByText('Not available').length).toBeGreaterThanOrEqual(1);
  });

  it('renders empty state when no zone is selected', () => {
    render(<ZoneDetails zone={null} />);

    expect(screen.getByText('No Zone Selected')).toBeInTheDocument();
    expect(screen.getByText(/Select a zone on the map or in the list/i)).toBeInTheDocument();
  });

  it('renders provenance, confidence and the P10 to P90 range when supplied and nothing when null', () => {
    const zoneWithSuppliedFields = {
      ...completeZone,
      provenance: 'observed',
      source: 'SpaceNet 8 / Maxar ground truth',
      confidence: 0.95,
      rank_p10: 12,
      rank_p90: 18,
    };

    const { rerender } = render(
      <ZoneDetails zone={zoneWithSuppliedFields} onClearSelection={vi.fn()} />
    );

    expect(screen.getByText('Provenance')).toBeInTheDocument();
    expect(screen.getByLabelText('Data provenance: Observed')).toBeInTheDocument();
    expect(screen.getByText('Observed')).toBeInTheDocument();
    expect(screen.getByText('SpaceNet 8 / Maxar ground truth')).toBeInTheDocument();
    expect(screen.getByText('Confidence')).toBeInTheDocument();
    expect(screen.getByText('0.95')).toBeInTheDocument();
    expect(screen.getByText('Rank Range (P10 to P90)')).toBeInTheDocument();
    expect(screen.getByText('P10: 12 • P90: 18')).toBeInTheDocument();

    // Now test with null values
    const zoneWithNullFields = {
      ...completeZone,
      provenance: null,
      source: null,
      confidence: null,
      rank_p10: null,
      rank_p90: null,
    };

    rerender(<ZoneDetails zone={zoneWithNullFields} onClearSelection={vi.fn()} />);

    expect(screen.queryByText('Provenance')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Data provenance/i)).not.toBeInTheDocument();
    expect(screen.queryByText('SpaceNet 8 / Maxar ground truth')).not.toBeInTheDocument();
    expect(screen.queryByText('Confidence')).not.toBeInTheDocument();
    expect(screen.queryByText('Rank Range (P10 to P90)')).not.toBeInTheDocument();
  });

  it('renders a small "(test fixture)" note beside confidence and rank values when from a test fixture', () => {
    const fixtureZone = {
      ...completeZone,
      confidence: 0.35,
      rank_p10: 10,
      rank_p90: 30,
      isTestFixture: true,
    };

    const { rerender } = render(
      <ZoneDetails zone={fixtureZone} onClearSelection={vi.fn()} isTestFixture={true} />
    );

    const testFixtureNotes = screen.getAllByText('(test fixture)');
    expect(testFixtureNotes.length).toBe(2); // Beside Confidence and Rank Range
    expect(screen.getByText('0.35')).toBeInTheDocument();
    expect(screen.getByText('P10: 10 • P90: 30')).toBeInTheDocument();

    // When not a fixture (real operational data), "(test fixture)" note must NOT be rendered
    const liveZone = {
      ...completeZone,
      confidence: 0.88,
      rank_p10: 5,
      rank_p90: 8,
      isTestFixture: false,
    };

    rerender(<ZoneDetails zone={liveZone} onClearSelection={vi.fn()} isTestFixture={false} />);

    expect(screen.queryByText('(test fixture)')).not.toBeInTheDocument();
    expect(screen.getByText('0.88')).toBeInTheDocument();
    expect(screen.getByText('P10: 5 • P90: 8')).toBeInTheDocument();
  });

  it('calls onClearSelection when clear button is clicked', () => {
    const handleClear = vi.fn();
    render(<ZoneDetails zone={completeZone} onClearSelection={handleClear} />);

    const clearBtn = screen.getByTitle('Clear zone selection');
    fireEvent.click(clearBtn);
    expect(handleClear).toHaveBeenCalledTimes(1);
  });

  it('renders FloodWatch tile in mock-floodwatch mode with real labels and zero risk implications', () => {
    const floodwatchTile = {
      zoneId: '0_41_58',
      name: 'Tile 0_41_58',
      riskLevel: 'UNKNOWN',
      riskScore: null,
      observed_flooded_count: 181,
      exposedBuildings: 169,
      in_training_pool: true,
      reasons: [
        '169 observed flooded buildings, 12 observed flooded roads (181 total)',
        'Model detected mask pixels: 668123 (fast mode), 733609 (accurate mode)',
        'In model training pool',
      ],
      hasGeometry: true,
    };

    render(<ZoneDetails zone={floodwatchTile} isTestFixture={false} />);

    expect(screen.getByText('Tile 0_41_58')).toBeInTheDocument();
    expect(screen.getByText('Observed flooded buildings (labels)')).toBeInTheDocument();
    expect(screen.getByText('169')).toBeInTheDocument();
    expect(screen.getByText('Observed flooded roads (labels)')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('Model mask pixels (derived)')).toBeInTheDocument();
    expect(screen.getByText(/668,123 \(fast\) • 733,609 \(acc\)/i)).toBeInTheDocument();
    expect(screen.getByText('Observed flooded total (labels)')).toBeInTheDocument();
    expect(screen.getByText('181 features')).toBeInTheDocument();
    expect(screen.getByText('In training pool')).toBeInTheDocument();
    expect(screen.getByText('Observed Features & Model Findings:')).toBeInTheDocument();

    // Confirm that no risk or exposure fields are displayed
    expect(screen.queryByText('Priority Score')).not.toBeInTheDocument();
    expect(screen.queryByText('Accessibility')).not.toBeInTheDocument();
    expect(screen.queryByText('Flooded Area')).not.toBeInTheDocument();
  });
});
