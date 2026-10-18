import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchDashboardData } from '../services/dashboardApi.js';
import { adaptDashboardData } from '../data/dataAdapter.js';

/**
 * Returns the localStorage cache key keyed by active VITE_DATA_SOURCE.
 * @param {string} [customSource] 
 * @returns {string}
 */
export function getActiveCacheKey(customSource) {
  const querySource =
    typeof window !== 'undefined' && window.location?.search
      ? new URLSearchParams(window.location.search).get('dataSource') ||
        new URLSearchParams(window.location.search).get('source')
      : null;
  const activeSource =
    customSource ||
    querySource ||
    (typeof import.meta !== 'undefined' ? import.meta.env?.VITE_DATA_SOURCE : null) ||
    'mock';
  return `highwater_cache_${activeSource}`;
}

/**
 * Formats ISO timestamp for cached snapshots: HH:MM, plus date if not today.
 * @param {string} isoString 
 * @returns {string}
 */
export function formatCachedTimestamp(isoString, now = new Date()) {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return String(isoString);
  const nowDate = now instanceof Date ? now : new Date(now);
  const isToday =
    date.getFullYear() === nowDate.getFullYear() &&
    date.getMonth() === nowDate.getMonth() &&
    date.getDate() === nowDate.getDate();

  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const timeStr = `${hours}:${minutes}`;

  if (isToday) {
    return timeStr;
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${timeStr}, ${year}-${month}-${day}`;
}

/**
 * Custom hook to load and manage dashboard data.
 * Manages loading, error, and refresh states with in-flight guard.
 * Supports offline localStorage caching keyed by VITE_DATA_SOURCE when fetch fails.
 */
export function useDashboardData(options) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);
  const inFlightRef = useRef(false);

  const querySource =
    typeof window !== 'undefined' && window.location?.search
      ? new URLSearchParams(window.location.search).get('dataSource') ||
        new URLSearchParams(window.location.search).get('source')
      : null;
  const effectiveOptions = querySource && !options?.dataSource
    ? { ...options, dataSource: querySource }
    : options;

  const dataSource = effectiveOptions?.dataSource;
  const cacheKey = getActiveCacheKey(dataSource);
  const optionsRef = useRef(effectiveOptions);
  optionsRef.current = effectiveOptions;

  const loadData = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setLoading(true);
    setError(null);

    try {
      const raw = await fetchDashboardData(optionsRef.current);

      // Store successful payload in localStorage with ISO timestamp
      try {
        if (typeof localStorage !== 'undefined') {
          const cacheRecord = {
            raw,
            cachedAt: new Date().toISOString(),
          };
          localStorage.setItem(cacheKey, JSON.stringify(cacheRecord));
        }
      } catch {
        // Ignore localStorage quota or access errors
      }

      const now = new Date();
      setLastRefreshedAt(now.toISOString());
      const normalized = adaptDashboardData(raw);
      // Fresh fetch: ensure cached banner is cleared and not shown alongside live data
      normalized.metadata.isFromCache = false;
      normalized.metadata.cachedAt = null;
      normalized.metadata.lastRefreshedAt = now.toISOString();

      setData(normalized);
      setError(null);
    } catch (err) {
      let usedCache = false;

      // Use the cache ONLY when the fetch fails
      try {
        if (typeof localStorage !== 'undefined') {
          const storedStr = localStorage.getItem(cacheKey);
          if (storedStr) {
            const parsed = JSON.parse(storedStr);
            if (parsed && parsed.raw) {
              const cachedNormalized = adaptDashboardData(parsed.raw);
              cachedNormalized.metadata.isFromCache = true;
              cachedNormalized.metadata.cachedAt = parsed.cachedAt || new Date().toISOString();
              setData(cachedNormalized);
              setError(null);
              usedCache = true;
            }
          }
        }
      } catch {
        // Cache parsing failed, proceed to error state
      }

      if (!usedCache) {
        setError(err instanceof Error ? err.message : 'Failed to fetch dashboard data');
      }
    } finally {
      setLoading(false);
      inFlightRef.current = false;
    }
  }, [cacheKey]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return {
    data,
    loading,
    error,
    refresh: loadData,
    lastRefreshedAt,
  };
}
