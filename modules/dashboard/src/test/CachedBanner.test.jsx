import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import CachedBanner from '../components/CachedBanner.jsx';

describe('CachedBanner component', () => {
  it('does not render when isFromCache is false (never shown alongside live data)', () => {
    const { container } = render(
      <CachedBanner
        isFromCache={false}
        cachedAt={new Date().toISOString()}
        onRefresh={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('does not render when cachedAt is null or undefined', () => {
    const { container } = render(
      <CachedBanner
        isFromCache={true}
        cachedAt={null}
        onRefresh={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders cached snapshot notice with formatted time for today', () => {
    const today = new Date();
    today.setHours(14, 30, 0, 0);
    const isoToday = today.toISOString();

    render(
      <CachedBanner
        isFromCache={true}
        cachedAt={isoToday}
        onRefresh={vi.fn()}
      />
    );

    const banner = screen.getByRole('status', { name: 'Offline Cached Data Warning' });
    expect(banner).toBeInTheDocument();
    expect(screen.getByText(/Network fetch failed\. Showing cached snapshot from 14:30\./i)).toBeInTheDocument();
  });

  it('renders cached snapshot notice with formatted time and date when snapshot is not from today', () => {
    // 2 days ago
    const pastDate = new Date('2026-10-10T09:15:00.000Z');
    const hours = String(pastDate.getHours()).padStart(2, '0');
    const minutes = String(pastDate.getMinutes()).padStart(2, '0');
    const year = pastDate.getFullYear();
    const month = String(pastDate.getMonth() + 1).padStart(2, '0');
    const day = String(pastDate.getDate()).padStart(2, '0');

    render(
      <CachedBanner
        isFromCache={true}
        cachedAt={pastDate.toISOString()}
        onRefresh={vi.fn()}
      />
    );

    const expectedString = `${hours}:${minutes}, ${year}-${month}-${day}`;
    expect(screen.getByText(new RegExp(`Showing cached snapshot from ${expectedString}`, 'i'))).toBeInTheDocument();
  });

  it('calls onRefresh when Retry button is clicked', () => {
    const handleRefresh = vi.fn();
    render(
      <CachedBanner
        isFromCache={true}
        cachedAt={new Date().toISOString()}
        onRefresh={handleRefresh}
      />
    );

    const retryBtn = screen.getByRole('button', { name: /Retry/i });
    fireEvent.click(retryBtn);
    expect(handleRefresh).toHaveBeenCalledTimes(1);
  });
});
