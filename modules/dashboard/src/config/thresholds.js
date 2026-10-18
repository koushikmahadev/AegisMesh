/**
 * thresholds.js
 * Centralized Priority Risk Thresholds for HighWater.
 * Strictly aligned with Module 3 (Risk & Prioritization Engine) config.
 *
 * Lower bound thresholds (inclusive):
 * - CRITICAL: score >= 70.0
 * - HIGH:     score >= 45.0
 * - MEDIUM:   score >= 20.0
 * - LOW:      score >= 0.0
 * - UNKNOWN:  missing, null, non-finite, or insufficient data
 */

export const DEFAULT_PRIORITY_THRESHOLDS = {
  CRITICAL: 70.0,
  HIGH: 45.0,
  MEDIUM: 20.0,
  LOW: 0.0,
  critical: 70.0,
  high: 45.0,
  medium: 20.0,
  low: 0.0,
};

/**
 * Classifies a numerical risk score (0-100) into a priority category.
 * Guarantees that frontend and backend cannot silently disagree on thresholds.
 *
 * @param {number|null|undefined} score - Numerical risk score on 0-100 scale
 * @param {object} [thresholds] - Optional custom thresholds object
 * @returns {"CRITICAL"|"HIGH"|"MEDIUM"|"LOW"|"UNKNOWN"}
 */
export function classifyRiskScore(score, thresholds = DEFAULT_PRIORITY_THRESHOLDS) {
  if (score === null || score === undefined || typeof score !== 'number' || !Number.isFinite(score)) {
    return 'UNKNOWN';
  }
  const th = thresholds || DEFAULT_PRIORITY_THRESHOLDS;
  const critical = typeof th.CRITICAL === 'number' ? th.CRITICAL : (typeof th.critical === 'number' ? th.critical : 70.0);
  const high = typeof th.HIGH === 'number' ? th.HIGH : (typeof th.high === 'number' ? th.high : 45.0);
  const medium = typeof th.MEDIUM === 'number' ? th.MEDIUM : (typeof th.medium === 'number' ? th.medium : 20.0);
  const low = typeof th.LOW === 'number' ? th.LOW : (typeof th.low === 'number' ? th.low : 0.0);

  if (score >= critical) return 'CRITICAL';
  if (score >= high) return 'HIGH';
  if (score >= medium) return 'MEDIUM';
  if (score >= low) return 'LOW';
  return 'UNKNOWN';
}
