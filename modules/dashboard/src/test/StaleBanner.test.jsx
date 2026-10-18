import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import StaleBanner, { isDataStale } from '../components/StaleBanner.jsx';

describe('StaleBanner component (T5.2, FR-51)', () => {
  it('correctly calculates staleness threshold', () => {
    const now = Date.now();
    const freshTimestamp = new Date(now - 10 * 60 * 1000).toISOString(); // 10 min ago
    const staleTimestamp = new Date(now - 120 * 60 * 1000).toISOString(); // 2 hours ago

    expect(isDataStale(freshTimestamp, 60)).toBe(false);
    expect(isDataStale(staleTimestamp, 60)).toBe(true);
    expect(isDataStale(null)).toBe(false);
    expect(isDataStale('invalid-date')).toBe(false);
  });

  it('renders amber warning banner when data is stale and dataMode is "live"', () => {
    const twoHoursAgo = new Date(Date.now() - 120 * 60 * 1000).toISOString();
    const handleRefresh = vi.fn();

    render(
      <StaleBanner
        generatedAt={twoHoursAgo}
        staleMinutes={60}
        dataMode="live"
        onRefresh={handleRefresh}
      />
    );

    expect(screen.getByRole('status', { name: 'Stale Data Warning' })).toBeInTheDocument();
    expect(screen.getByText(/This may be out of date/i)).toBeInTheDocument();

    const refreshBtn = screen.getByRole('button', { name: /Refresh now/i });
    fireEvent.click(refreshBtn);
    expect(handleRefresh).toHaveBeenCalledTimes(1);
  });

  it('suppresses stale warning banner when dataMode is "demo" even if timestamp is old', () => {
    const twoHoursAgo = new Date(Date.now() - 120 * 60 * 1000).toISOString();
    const { container } = render(
      <StaleBanner
        generatedAt={twoHoursAgo}
        staleMinutes={60}
        dataMode="demo"
      />
    );

    // Suppressed because DEMO badge in header already informs operator
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole('status', { name: 'Stale Data Warning' })).not.toBeInTheDocument();
  });

  it('renders nothing when data is within threshold', () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    const { container } = render(
      <StaleBanner
        generatedAt={fiveMinutesAgo}
        staleMinutes={60}
        dataMode="live"
      />
    );

    expect(container.firstChild).toBeNull();
  });
});
