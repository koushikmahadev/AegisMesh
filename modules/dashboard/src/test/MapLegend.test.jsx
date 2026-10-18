import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MapLegend from '../components/MapLegend.jsx';

describe('MapLegend component (T3.7)', () => {
  it('renders only enabled overlays (FR-16)', () => {
    // Only flood and roads enabled
    const visibleLayers = { flood: true, risk: false, roads: true, facilities: false, routes: false };
    render(<MapLegend visibleLayers={visibleLayers} />);

    expect(screen.getByText('Inundation Extent')).toBeInTheDocument();
    expect(screen.getByText('Blocked Roadway')).toBeInTheDocument();

    // Disabled layers should NOT appear
    expect(screen.queryByText('Priority Risk:')).not.toBeInTheDocument();
    expect(screen.queryByText('Facilities:')).not.toBeInTheDocument();
    expect(screen.queryByText('Evacuation Corridor')).not.toBeInTheDocument();
  });

  it('renders priority risk swatches when risk layer is enabled', () => {
    const visibleLayers = { flood: false, risk: true, roads: false, facilities: false, routes: false };
    render(<MapLegend visibleLayers={visibleLayers} />);

    expect(screen.getByText('Priority Risk:')).toBeInTheDocument();
    expect(screen.getByText('HIGH')).toBeInTheDocument();
    expect(screen.getByText('MEDIUM')).toBeInTheDocument();
    expect(screen.getByText('LOW')).toBeInTheDocument();
    expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
  });

  it('renders fallback notice when all layers are toggled off', () => {
    const visibleLayers = { flood: false, risk: false, roads: false, facilities: false, routes: false };
    render(<MapLegend visibleLayers={visibleLayers} />);

    expect(screen.getByText('No map overlays active')).toBeInTheDocument();
  });
});
