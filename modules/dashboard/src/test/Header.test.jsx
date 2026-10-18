import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Header from '../components/Header.jsx';

describe('Header component', () => {
  it('renders DEMO MODE badge when dataMode is demo (FR-02)', () => {
    render(<Header dataMode="demo" studyArea="Bengaluru, Karnataka" />);
    expect(screen.getByText('DEMO MODE')).toBeInTheDocument();
    expect(screen.getByText(/Bengaluru, Karnataka/)).toBeInTheDocument();
  });

  it('renders Connected data status when dataMode is not demo', () => {
    render(<Header dataMode="live" studyArea="Bengaluru, Karnataka" />);
    expect(screen.queryByText('DEMO MODE')).not.toBeInTheDocument();
    expect(screen.getByText('Connected data')).toBeInTheDocument();
  });

  it('calls onRefresh when refresh button is clicked (FR-03)', () => {
    const handleRefresh = vi.fn();
    render(<Header onRefresh={handleRefresh} loading={false} />);
    const refreshBtn = screen.getByRole('button', { name: /refresh/i });
    fireEvent.click(refreshBtn);
    expect(handleRefresh).toHaveBeenCalledTimes(1);
  });

  it('disables refresh button and displays spinning icon when loading is true', () => {
    const handleRefresh = vi.fn();
    const { rerender } = render(<Header onRefresh={handleRefresh} loading={true} />);
    const refreshBtn = screen.getByRole('button', { name: /refresh/i });
    expect(refreshBtn).toBeDisabled();
    const icon = refreshBtn.querySelector('svg');
    expect(icon).toHaveClass('animate-spin');

    fireEvent.click(refreshBtn);
    expect(handleRefresh).not.toHaveBeenCalled();

    // Re-enables afterwards when loading is false
    rerender(<Header onRefresh={handleRefresh} loading={false} />);
    expect(refreshBtn).not.toBeDisabled();
    expect(icon).not.toHaveClass('animate-spin');
  });

  it('renders distinct "Data generated" and "Last refreshed" timestamps', () => {
    render(
      <Header
        timestamp="2026-10-14T10:00:00Z"
        lastRefreshedAt="2026-10-14T15:45:00Z"
      />
    );

    expect(screen.getByText('Data package generated:')).toBeInTheDocument();
    expect(screen.getByText('Last refreshed:')).toBeInTheDocument();

    const d = new Date('2026-10-14T15:45:00Z');
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    expect(screen.getByText(`${h}:${m}`)).toBeInTheDocument();
  });
});
