import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ZoneList from '../components/ZoneList.jsx';

describe('ZoneList component (T4.4, T4.6, FR-22, FR-26)', () => {
  const sampleZones = [
    {
      zoneId: 'zone-001',
      name: 'Alpha Basin',
      riskLevel: 'HIGH',
      riskScore: 85,
      exposedBuildings: 40,
      hasGeometry: true,
    },
    {
      zoneId: 'zone-009',
      name: 'Delta Staging',
      riskLevel: 'UNKNOWN',
      riskScore: null,
      exposedBuildings: null,
      hasGeometry: false,
    },
  ];

  it('renders zone rows with rank, name, and metrics', () => {
    render(<ZoneList zones={sampleZones} selectedZoneId={null} onZoneSelect={vi.fn()} />);

    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.getByText('Alpha Basin')).toBeInTheDocument();
    expect(screen.getByText('Score: 85')).toBeInTheDocument();
    expect(screen.getByText('40 bldgs')).toBeInTheDocument();

    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.getByText('Delta Staging')).toBeInTheDocument();
    expect(screen.getByText('Score: Not assessed')).toBeInTheDocument();
    expect(screen.getByText('Bldgs: Not available')).toBeInTheDocument();
  });

  it('displays "No map shape" note for non-spatial zones (T4.6, FR-26)', () => {
    render(<ZoneList zones={sampleZones} selectedZoneId={null} onZoneSelect={vi.fn()} />);

    expect(screen.getByText('No map shape')).toBeInTheDocument();
  });

  it('calls onZoneSelect with the correct zoneId when a row is clicked', () => {
    const handleSelect = vi.fn();
    render(<ZoneList zones={sampleZones} selectedZoneId={null} onZoneSelect={handleSelect} />);

    fireEvent.click(screen.getByText('Alpha Basin'));
    expect(handleSelect).toHaveBeenCalledWith('zone-001');

    fireEvent.click(screen.getByText('Delta Staging'));
    expect(handleSelect).toHaveBeenCalledWith('zone-009');
  });

  it('marks the selected row with aria-selected="true"', () => {
    render(<ZoneList zones={sampleZones} selectedZoneId="zone-001" onZoneSelect={vi.fn()} />);

    const rows = screen.getAllByRole('button');
    expect(rows[0]).toHaveAttribute('aria-selected', 'true');
    expect(rows[1]).toHaveAttribute('aria-selected', 'false');
  });

  it('renders empty state notice when zones array is empty', () => {
    render(<ZoneList zones={[]} selectedZoneId={null} onZoneSelect={vi.fn()} />);
    expect(screen.getByText(/No zones match the current search or filter criteria/i)).toBeInTheDocument();
  });

  it('displays "Partial data" note for zones with partialData or null numeric fields', () => {
    render(<ZoneList zones={sampleZones} selectedZoneId={null} onZoneSelect={vi.fn()} />);
    expect(screen.getByText('Partial data')).toBeInTheDocument();
  });
});
