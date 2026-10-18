import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SurveyNeededList from '../components/SurveyNeededList.jsx';

describe('SurveyNeededList component', () => {
  const sampleZones = [
    {
      zoneId: 'zone-001',
      name: 'Zone Alpha',
      riskLevel: 'HIGH',
      needsSurvey: true,
      confidence: 0.9,
    },
    {
      zoneId: 'zone-002',
      name: 'Zone Beta',
      riskLevel: 'MEDIUM',
      needsSurvey: false,
      confidence: 0.2, // Low confidence must NOT cause needsSurvey to become true
    },
    {
      zoneId: 'zone-003',
      name: 'Zone Gamma',
      riskLevel: 'LOW',
      needsSurvey: 'true', // String "true" must NOT be treated as true
      confidence: 0.5,
    },
    {
      zoneId: 'zone-004',
      name: 'Zone Delta',
      riskLevel: 'LOW',
      needsSurvey: 1, // Number 1 must NOT be treated as true
      confidence: 0.4,
    },
    {
      zoneId: 'zone-005',
      name: 'Zone Epsilon',
      riskLevel: 'UNKNOWN',
      needsSurvey: true,
      confidence: null,
    },
  ];

  it('shows only needsSurvey:true zones (strict boolean, never derived from confidence)', () => {
    render(<SurveyNeededList zones={sampleZones} onSelectZone={vi.fn()} />);

    // Only zone-001 and zone-005 have boolean true
    expect(screen.getByText('Zone Alpha')).toBeInTheDocument();
    expect(screen.getByText('Zone Epsilon')).toBeInTheDocument();

    // Others must NOT be shown
    expect(screen.queryByText('Zone Beta')).not.toBeInTheDocument();
    expect(screen.queryByText('Zone Gamma')).not.toBeInTheDocument();
    expect(screen.queryByText('Zone Delta')).not.toBeInTheDocument();

    // Header counter reflects only the 2 valid zones
    expect(screen.getByText('2 zones')).toBeInTheDocument();
  });

  it('shows the empty state when no zones match or list is empty', () => {
    const noSurveyZones = [
      { zoneId: 'zone-010', name: 'Safe Area', needsSurvey: false, riskLevel: 'LOW' },
      { zoneId: 'zone-011', name: 'Stable Area', needsSurvey: null, riskLevel: 'LOW' },
    ];

    const { rerender } = render(
      <SurveyNeededList zones={noSurveyZones} onSelectZone={vi.fn()} />
    );

    expect(
      screen.getByText('No zones currently flagged for aerial reconnaissance.')
    ).toBeInTheDocument();

    // Also test with empty array
    rerender(<SurveyNeededList zones={[]} onSelectZone={vi.fn()} />);
    expect(
      screen.getByText('No zones currently flagged for aerial reconnaissance.')
    ).toBeInTheDocument();
  });

  it('calls onSelectZone with the right id when a zone is clicked', () => {
    const handleSelect = vi.fn();
    render(<SurveyNeededList zones={sampleZones} onSelectZone={handleSelect} />);

    const alphaBtn = screen.getByRole('button', { name: /Zone Alpha/i });
    fireEvent.click(alphaBtn);

    expect(handleSelect).toHaveBeenCalledTimes(1);
    expect(handleSelect).toHaveBeenCalledWith('zone-001');

    const epsilonBtn = screen.getByRole('button', { name: /Zone Epsilon/i });
    fireEvent.click(epsilonBtn);

    expect(handleSelect).toHaveBeenCalledTimes(2);
    expect(handleSelect).toHaveBeenCalledWith('zone-005');
  });
});
