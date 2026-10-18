import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MapControls from '../components/MapControls.jsx';

describe('MapControls component (T3.6)', () => {
  it('renders all 6 layer toggle switches and enabled count', () => {
    const visibleLayers = { flood: true, risk: true, roads: true, facilities: true, routes: false, buildings: false };
    render(<MapControls visibleLayers={visibleLayers} onToggleLayer={() => {}} onResetExtent={() => {}} />);

    expect(screen.getByText('4 of 6 Enabled')).toBeInTheDocument();
    expect(screen.getByLabelText('Toggle Flood Extent overlay')).toBeChecked();
    expect(screen.getByLabelText('Toggle Risk Zones overlay')).toBeChecked();
    expect(screen.getByLabelText('Toggle Blocked Roads overlay')).toBeChecked();
    expect(screen.getByLabelText('Toggle Rescue Facilities overlay')).toBeChecked();
    expect(screen.getByLabelText('Toggle Evacuation Routes overlay')).not.toBeChecked();
    expect(screen.getByLabelText('Toggle Exposed Buildings overlay')).not.toBeChecked();
  });

  it('triggers onToggleLayer for each individual layer independently', () => {
    const handleToggle = vi.fn();
    const visibleLayers = { flood: true, risk: true, roads: true, facilities: true, routes: false };
    render(<MapControls visibleLayers={visibleLayers} onToggleLayer={handleToggle} onResetExtent={() => {}} />);

    fireEvent.click(screen.getByLabelText('Toggle Flood Extent overlay'));
    expect(handleToggle).toHaveBeenCalledWith('flood');

    fireEvent.click(screen.getByLabelText('Toggle Evacuation Routes overlay'));
    expect(handleToggle).toHaveBeenCalledWith('routes');
  });

  it('triggers onResetExtent when reset button is clicked without toggling layers', () => {
    const handleToggle = vi.fn();
    const handleReset = vi.fn();
    render(<MapControls visibleLayers={{ flood: true }} onToggleLayer={handleToggle} onResetExtent={handleReset} />);

    const resetBtn = screen.getByRole('button', { name: /reset map/i });
    fireEvent.click(resetBtn);

    expect(handleReset).toHaveBeenCalledTimes(1);
    expect(handleToggle).not.toHaveBeenCalled();
  });
});
