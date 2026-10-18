import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DashboardLayout from '../app/DashboardLayout.jsx';

describe('Phase 4 Wiring Integration (T4.3 - T4.8)', () => {
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
        reasons: ['Submerged primary road'],
        hasGeometry: true,
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [77.65, 12.92],
              [77.67, 12.92],
              [77.67, 12.94],
              [77.65, 12.94],
              [77.65, 12.92],
            ],
          ],
        },
      },
      {
        zoneId: 'zone-002',
        name: 'Zone 002 - Varthur Spillway',
        riskLevel: 'MEDIUM',
        riskScore: 58,
        floodedAreaKm2: 1.1,
        floodedPercent: 32,
        exposedBuildings: 12,
        accessibility: 'OPEN',
        reasons: ['Overflow risk'],
        hasGeometry: true,
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [77.68, 12.93],
              [77.70, 12.93],
              [77.70, 12.95],
              [77.68, 12.95],
              [77.68, 12.93],
            ],
          ],
        },
      },
      {
        zoneId: 'zone-009',
        name: 'Zone 009 - Peripheral Staging',
        riskLevel: 'UNKNOWN',
        riskScore: null,
        floodedAreaKm2: null,
        floodedPercent: null,
        exposedBuildings: null,
        accessibility: 'UNKNOWN',
        reasons: [],
        hasGeometry: false,
        geometry: null,
      },
    ],
    floodExtent: { type: 'FeatureCollection', features: [] },
    blockedRoads: { type: 'FeatureCollection', features: [] },
    facilities: { type: 'FeatureCollection', features: [] },
    routes: [],
    droppedFeatureCount: 0,
  };

  it('synchronizes selection between ZoneList and ZoneDetails (T4.3, T4.5)', () => {
    render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    // Initially no zone selected
    expect(screen.getByText('No Zone Selected')).toBeInTheDocument();

    // Click on Zone 001 in ZoneList
    const zone1Button = screen.getByRole('button', { name: /Zone 001 - Bellandur Basin/i });
    fireEvent.click(zone1Button);

    // ZoneDetails updates with Zone 001 details
    expect(screen.getByRole('region', { name: /Zone Inspection Details for Zone 001 - Bellandur Basin/i })).toBeInTheDocument();
    expect(screen.getByText('82 / 100')).toBeInTheDocument();
    expect(screen.getByText('Submerged primary road')).toBeInTheDocument();
  });

  it('selects non-spatial zone (zone-009) without crashing the map (T4.6, FR-26)', () => {
    render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    // Click on non-spatial zone 009
    const zone9Button = screen.getByRole('button', { name: /Zone 009 - Peripheral Staging/i });
    fireEvent.click(zone9Button);

    // ZoneDetails shows non-spatial warning
    expect(screen.getByText('Non-spatial staging area')).toBeInTheDocument();
    expect(screen.getByText(/No geospatial boundary coordinates available/i)).toBeInTheDocument();
  });

  it('filters zones by risk level, updating list, status badge, and stats (T4.4, T4.8)', () => {
    render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    // Total 3 zones initially
    expect(screen.getByText('All 3 zones')).toBeInTheDocument();

    // Click HIGH filter pill
    const highFilterBtn = screen.getByRole('button', { name: 'HIGH' });
    fireEvent.click(highFilterBtn);

    // Status updates to "Showing 1 of 3 zones"
    expect(screen.getByText('Showing 1 of 3 zones')).toBeInTheDocument();

    // Only Zone 001 should be present in the directory
    expect(screen.getByText('Zone 001 - Bellandur Basin')).toBeInTheDocument();
    expect(screen.queryByText('Zone 002 - Varthur Spillway')).not.toBeInTheDocument();
    expect(screen.queryByText('Zone 009 - Peripheral Staging')).not.toBeInTheDocument();
  });

  it('clears selection when Reset Extent is clicked (T4.3)', () => {
    render(<DashboardLayout data={mockData} onRefresh={vi.fn()} />);

    // Select Zone 001
    const zone1Button = screen.getByRole('button', { name: /Zone 001 - Bellandur Basin/i });
    fireEvent.click(zone1Button);
    expect(screen.getByText('82 / 100')).toBeInTheDocument();

    // Click Reset Extent
    const resetBtn = screen.getByRole('button', { name: /Reset map to study area bounds/i });
    fireEvent.click(resetBtn);

    // Selection is cleared
    expect(screen.getByText('No Zone Selected')).toBeInTheDocument();
  });
});
