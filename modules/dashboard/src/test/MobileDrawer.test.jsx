import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import DashboardLayout from '../app/DashboardLayout.jsx';

describe('Mobile Drawer and Layout (T5.4)', () => {
  const mockData = {
    metadata: {
      studyArea: 'Bengaluru Core',
      generatedAt: '2026-10-12T10:00:00Z',
      dataMode: 'demo',
    },
    zones: [
      {
        zoneId: 'zone-001',
        name: 'Zone 001 - Bellandur Basin',
        riskLevel: 'HIGH',
        riskScore: 82,
        floodedAreaKm2: 2.4,
        floodedPercent: 68,
        exposedBuildings: 34,
        accessibility: 'LIMITED',
        reasons: ['Critical stormwater drainage blockage'],
        hasGeometry: true,
      },
    ],
    floodExtent: { type: 'FeatureCollection', features: [] },
    blockedRoads: { type: 'FeatureCollection', features: [] },
    facilities: { type: 'FeatureCollection', features: [] },
    routes: [],
  };

  it('renders mobile drawer trigger, opens bottom sheet dialog, and navigates tabs', async () => {
    vi.useFakeTimers();
    const resizeSpy = vi.spyOn(window, 'dispatchEvent');

    render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    // Mobile trigger button exists
    const trigger = screen.getByRole('button', { name: /Open mobile inspection drawer/i });
    expect(trigger).toBeInTheDocument();

    // Drawer is closed initially
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Click trigger to open drawer
    fireEvent.click(trigger);
    expect(screen.getByRole('dialog', { name: /Mobile Navigation and Inspection Drawer/i })).toBeInTheDocument();

    // Resize event dispatched to invalidate map size
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(resizeSpy).toHaveBeenCalledWith(expect.any(Event));

    // Drawer tabs are visible and operable
    expect(screen.getByRole('button', { name: 'Zones & Filters' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Inspection Details' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Map Layers' })).toBeInTheDocument();

    // Switch to Map Layers tab
    fireEvent.click(screen.getByRole('button', { name: 'Map Layers' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('Layer Overlays');

    // Close drawer via close button
    const closeBtn = screen.getByRole('button', { name: /Close mobile drawer/i });
    fireEvent.click(closeBtn);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Resize event dispatched again after closing
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(resizeSpy).toHaveBeenCalled();

    vi.useRealTimers();
  });
});
