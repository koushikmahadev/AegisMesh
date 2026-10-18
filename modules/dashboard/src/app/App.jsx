import React from 'react';
import DashboardLayout from './DashboardLayout.jsx';
import LoadingState from '../components/states/LoadingState.jsx';
import { useDashboardData } from '../hooks/useDashboardData.js';

/**
 * App root component
 * Wires useDashboardData hook to DashboardLayout and renders LoadingState on initial fetch.
 */
export default function App() {
  const { data, loading, error, refresh, lastRefreshedAt } = useDashboardData();

  if (loading && !data) {
    return <LoadingState message="Loading flood response data…" />;
  }

  return (
    <DashboardLayout
      data={data}
      loading={loading}
      error={error}
      onRefresh={refresh}
      lastRefreshedAt={lastRefreshedAt}
    />
  );
}
