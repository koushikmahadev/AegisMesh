import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LoadingState from '../components/states/LoadingState.jsx';
import EmptyState from '../components/states/EmptyState.jsx';
import ErrorState from '../components/states/ErrorState.jsx';

describe('State Screens (T5.1, FR-50, design.md Section 4)', () => {
  describe('LoadingState', () => {
    it('renders skeleton UI with readable progress status and accessible aria-live', () => {
      render(<LoadingState message="Loading flood response data…" />);

      expect(screen.getByRole('status')).toBeInTheDocument();
      expect(screen.getByText('HIGHWATER')).toBeInTheDocument();
      expect(screen.getByText('Loading flood response data…')).toBeInTheDocument();
      expect(screen.getByText('Initialising geospatial engine…')).toBeInTheDocument();
    });
  });

  describe('EmptyState', () => {
    it('renders explanation that empty zones do not imply zero risk and provides refresh button', () => {
      const handleRefresh = vi.fn();
      render(<EmptyState onRefresh={handleRefresh} loading={false} />);

      expect(screen.getByRole('region', { name: 'Empty Data State' })).toBeInTheDocument();
      expect(screen.getByText('No Zones Available')).toBeInTheDocument();
      expect(screen.getByText(/This does not imply zero risk/i)).toBeInTheDocument();

      const refreshBtn = screen.getByRole('button', { name: /Check for Updates/i });
      fireEvent.click(refreshBtn);
      expect(handleRefresh).toHaveBeenCalledTimes(1);
    });
  });

  describe('ErrorState', () => {
    it('renders plain-language error notification and calls retry callback', () => {
      const handleRetry = vi.fn();
      render(<ErrorState error="Connection to flood telemetry timed out" onRetry={handleRetry} />);

      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('Data Synchronization Issue')).toBeInTheDocument();
      expect(screen.getByText('Connection to flood telemetry timed out')).toBeInTheDocument();

      const retryBtn = screen.getByRole('button', { name: /Retry/i });
      fireEvent.click(retryBtn);
      expect(handleRetry).toHaveBeenCalledTimes(1);
    });
  });
});
