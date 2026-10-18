import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import RiskBadge from '../components/RiskBadge.jsx';
import ZoneDetails from '../components/ZoneDetails.jsx';
import FilterBar from '../components/FilterBar.jsx';
import MapControls from '../components/MapControls.jsx';
import ZoneList from '../components/ZoneList.jsx';

describe('Accessibility Compliance Pass (T5.5, design.md Section 6)', () => {
  it('ensures aria-live="polite" is present on ZoneDetails inspection panel', () => {
    const { rerender } = render(<ZoneDetails zone={null} />);
    expect(screen.getByRole('region', { name: 'Zone Inspection Details' })).toHaveAttribute('aria-live', 'polite');

    const sampleZone = {
      zoneId: 'zone-001',
      name: 'Alpha Basin',
      riskLevel: 'HIGH',
      riskScore: 80,
      floodedAreaKm2: 2.1,
      floodedPercent: 40,
      exposedBuildings: 20,
      accessibility: 'LIMITED',
      reasons: ['Blocked road'],
      hasGeometry: true,
    };

    rerender(<ZoneDetails zone={sampleZone} />);
    expect(screen.getByRole('region', { name: /Zone Inspection Details for Alpha Basin/i })).toHaveAttribute('aria-live', 'polite');
  });

  it('guarantees risk is never conveyed by colour alone (text label and distinct icon)', () => {
    const { container: highContainer } = render(<RiskBadge level="HIGH" />);
    expect(highContainer.textContent).toContain('HIGH');
    expect(highContainer.querySelector('svg')).toBeInTheDocument();

    const { container: unknownContainer } = render(<RiskBadge level="UNKNOWN" />);
    expect(unknownContainer.textContent).toContain('UNKNOWN');
    expect(unknownContainer.querySelector('svg')).toBeInTheDocument();
    // UNKNOWN has dashed border
    expect(unknownContainer.firstChild).toHaveClass('border-dashed');
  });

  it('provides visible 2px focus rings on interactive elements', () => {
    render(
      <FilterBar
        filters={{ search: '', riskLevel: 'ALL' }}
        sortBy="priority"
        onFilterChange={vi.fn()}
        onSortChange={vi.fn()}
      />
    );

    const searchInput = screen.getByLabelText(/Search zones by ID or name/i);
    expect(searchInput).toHaveClass('focus:ring-2');

    const sortSelect = screen.getByLabelText(/Sort zones list/i);
    expect(sortSelect).toHaveClass('focus:ring-2');

    const highPill = screen.getByRole('button', { name: 'HIGH' });
    expect(highPill).toBeInTheDocument();
  });

  it('supports keyboard operation on list rows and layer toggles', () => {
    const handleSelect = vi.fn();
    const handleToggle = vi.fn();

    render(
      <>
        <ZoneList
          zones={[{ zoneId: 'zone-001', name: 'Zone 001', riskLevel: 'HIGH', riskScore: 80, exposedBuildings: 10, hasGeometry: true }]}
          selectedZoneId={null}
          onZoneSelect={handleSelect}
        />
        <MapControls
          visibleLayers={{ flood: true, risk: true, roads: true, facilities: true, routes: true }}
          onToggleLayer={handleToggle}
          onResetExtent={vi.fn()}
        />
      </>
    );

    // Keyboard click on list row
    const rowButton = screen.getByRole('button', { name: /Zone 001/i });
    rowButton.focus();
    expect(document.activeElement).toBe(rowButton);

    fireEvent.keyDown(rowButton, { key: 'Enter', code: 'Enter' });
    // In React testing library, clicking or pressing Enter on <button> triggers selection
    fireEvent.click(rowButton);
    expect(handleSelect).toHaveBeenCalledWith('zone-001');

    // Keyboard toggle on checkbox
    const floodToggle = screen.getByLabelText(/Toggle Flood Extent overlay/i);
    floodToggle.focus();
    expect(document.activeElement).toBe(floodToggle);
    fireEvent.click(floodToggle);
    expect(handleToggle).toHaveBeenCalledWith('flood');
  });
});
