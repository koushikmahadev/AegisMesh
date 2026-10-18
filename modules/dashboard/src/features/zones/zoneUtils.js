/**
 * zoneUtils.js
 * Pure utility functions for filtering and sorting zones.
 * Per rules.md and architecture.md:
 * - Selectors and utils are pure.
 * - Missing/null numeric fields sort last when sorting by that numeric field.
 * - Never coerce null to 0.
 */

/**
 * Priority order weighting for risk levels
 */
const RISK_PRIORITY_WEIGHT = {
  HIGH: 4,
  MEDIUM: 3,
  LOW: 2,
  UNKNOWN: 1,
};

/**
 * Filters a list of normalised zones by risk level and search keyword.
 * @param {Array<object>} zones 
 * @param {{ search?: string, riskLevel?: string }} filters 
 * @returns {Array<object>}
 */
export function filterZones(zones, filters = {}) {
  if (!Array.isArray(zones)) return [];

  const searchKeyword = (filters.search || '').trim().toLowerCase();
  const targetRisk = (filters.riskLevel || 'ALL').toUpperCase();

  return zones.filter((zone) => {
    // 1. Risk level filter
    if (targetRisk !== 'ALL' && zone.riskLevel !== targetRisk) {
      return false;
    }

    // 2. Search keyword filter (by zoneId or name)
    if (searchKeyword) {
      const matchName = (zone.name || '').toLowerCase().includes(searchKeyword);
      const matchId = (zone.zoneId || '').toLowerCase().includes(searchKeyword);
      if (!matchName && !matchId) {
        return false;
      }
    }

    return true;
  });
}

/**
 * Sorts a list of normalised zones.
 * Null values sort last for numeric fields.
 * @param {Array<object>} zones 
 * @param {"priority"|"score"|"buildings"|"name"} sortBy 
 * @returns {Array<object>}
 */
export function sortZones(zones, sortBy = 'priority') {
  if (!Array.isArray(zones)) return [];

  return [...zones].sort((a, b) => {
    if (sortBy === 'score') {
      // Null scores sort last
      if (a.riskScore === null && b.riskScore === null) return 0;
      if (a.riskScore === null) return 1;
      if (b.riskScore === null) return -1;
      return b.riskScore - a.riskScore;
    }

    if (sortBy === 'buildings') {
      // Null exposed buildings sort last
      if (a.exposedBuildings === null && b.exposedBuildings === null) return 0;
      if (a.exposedBuildings === null) return 1;
      if (b.exposedBuildings === null) return -1;
      return b.exposedBuildings - a.exposedBuildings;
    }

    if (sortBy === 'name') {
      return (a.name || '').localeCompare(b.name || '');
    }

    // Default: 'priority' (combines risk level weight then risk score)
    // Any zone without a score sorts after scored zones
    const isScoredA = typeof a.riskScore === 'number' && Number.isFinite(a.riskScore);
    const isScoredB = typeof b.riskScore === 'number' && Number.isFinite(b.riskScore);
    if (isScoredA !== isScoredB) {
      return isScoredB ? 1 : -1;
    }

    const weightA = RISK_PRIORITY_WEIGHT[a.riskLevel] || 0;
    const weightB = RISK_PRIORITY_WEIGHT[b.riskLevel] || 0;
    if (weightA !== weightB) {
      return weightB - weightA;
    }

    // Tie-breaker: risk score descending (nulls last)
    if (a.riskScore === null && b.riskScore === null) return 0;
    if (a.riskScore === null) return 1;
    if (b.riskScore === null) return -1;
    return b.riskScore - a.riskScore;
  });
}
