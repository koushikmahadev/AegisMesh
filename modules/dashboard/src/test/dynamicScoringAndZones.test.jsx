import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import fs from 'fs';
import path from 'path';
import { classifyRiskScore, DEFAULT_PRIORITY_THRESHOLDS } from '../config/thresholds.js';
import { adaptZones } from '../data/dataAdapter.js';
import { THEME } from '../config/theme.js';
import RiskBadge, { RISK_CONFIG } from '../components/RiskBadge.jsx';
import ZoneDetails from '../components/ZoneDetails.jsx';
import MapLegend from '../components/MapLegend.jsx';

describe('Dynamic Data-Driven Scoring and Category Thresholds', () => {
  describe('classifyRiskScore threshold boundaries', () => {
    it('correctly classifies boundary values with default thresholds', () => {
      // CRITICAL boundary: >= 70.0
      expect(classifyRiskScore(70.0)).toBe('CRITICAL');
      expect(classifyRiskScore(70.01)).toBe('CRITICAL');
      expect(classifyRiskScore(100.0)).toBe('CRITICAL');
      expect(classifyRiskScore(69.99)).toBe('HIGH');

      // HIGH boundary: >= 45.0
      expect(classifyRiskScore(45.0)).toBe('HIGH');
      expect(classifyRiskScore(45.01)).toBe('HIGH');
      expect(classifyRiskScore(44.99)).toBe('MEDIUM');

      // MEDIUM boundary: >= 20.0
      expect(classifyRiskScore(20.0)).toBe('MEDIUM');
      expect(classifyRiskScore(20.01)).toBe('MEDIUM');
      expect(classifyRiskScore(19.99)).toBe('LOW');

      // LOW boundary: >= 0.0
      expect(classifyRiskScore(0.0)).toBe('LOW');
      expect(classifyRiskScore(0.01)).toBe('LOW');

      // Invalid, negative, or missing values must be UNKNOWN
      expect(classifyRiskScore(-0.01)).toBe('UNKNOWN');
      expect(classifyRiskScore(-5.0)).toBe('UNKNOWN');
      expect(classifyRiskScore(NaN)).toBe('UNKNOWN');
      expect(classifyRiskScore(Infinity)).toBe('UNKNOWN');
      expect(classifyRiskScore(null)).toBe('UNKNOWN');
      expect(classifyRiskScore(undefined)).toBe('UNKNOWN');
    });

    it('honors custom thresholds supplied by backend payload', () => {
      const customThresholds = {
        CRITICAL: 80.0,
        HIGH: 55.0,
        MEDIUM: 30.0,
        LOW: 0.0,
      };

      expect(classifyRiskScore(75.0, customThresholds)).toBe('HIGH');
      expect(classifyRiskScore(80.0, customThresholds)).toBe('CRITICAL');
      expect(classifyRiskScore(30.0, customThresholds)).toBe('MEDIUM');
      expect(classifyRiskScore(29.9, customThresholds)).toBe('LOW');
    });

    it('supports lowercase threshold keys from backend config', () => {
      const lowercaseThresholds = {
        critical: 75.0,
        high: 50.0,
        medium: 25.0,
        low: 0.0,
      };

      expect(classifyRiskScore(75.0, lowercaseThresholds)).toBe('CRITICAL');
      expect(classifyRiskScore(74.9, lowercaseThresholds)).toBe('HIGH');
      expect(classifyRiskScore(50.0, lowercaseThresholds)).toBe('HIGH');
      expect(classifyRiskScore(25.0, lowercaseThresholds)).toBe('MEDIUM');
      expect(classifyRiskScore(24.9, lowercaseThresholds)).toBe('LOW');
    });
  });

  describe('Theme, Badge, and Color Alignment', () => {
    it('guarantees map polygon colors and theme colors strictly agree for all tiers', () => {
      const tiers = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'];
      for (const tier of tiers) {
        const themeColorKey = `risk-${tier.toLowerCase()}`;
        expect(THEME.colors[themeColorKey]).toBeDefined();
        expect(THEME.riskColors[tier]).toBe(THEME.colors[themeColorKey]);
        expect(RISK_CONFIG[tier]).toBeDefined();
      }

      // Verify specific hex colors
      expect(THEME.riskColors.CRITICAL).toBe('#7F1D1D');
      expect(THEME.riskColors.HIGH).toBe('#C62828');
      expect(THEME.riskColors.MEDIUM).toBe('#E69F00');
      expect(THEME.riskColors.LOW).toBe('#2E7D32');
      expect(THEME.riskColors.UNKNOWN).toBe('#6B7280');
    });

    it('renders MapLegend with all risk category swatches', () => {
      render(<MapLegend activeLayers={{ zones: true, flood: true, blockedRoads: true, facilities: true }} />);

      expect(screen.getByText('Priority Risk:')).toBeInTheDocument();
      expect(screen.getByText('CRITICAL')).toBeInTheDocument();
      expect(screen.getByText('HIGH')).toBeInTheDocument();
      expect(screen.getByText('MEDIUM')).toBeInTheDocument();
      expect(screen.getByText('LOW')).toBeInTheDocument();
      expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
    });
  });

  describe('Zones 024, 030, and 035 in actual Dernau dataset', () => {
    const zonesPath = path.resolve(__dirname, '../../public/mock-data-dernau/zones.json');
    const rawPayload = JSON.parse(fs.readFileSync(zonesPath, 'utf8'));
    const { zones } = adaptZones(rawPayload);

    const z024 = zones.find((z) => z.zoneId === 'zone-024');
    const z030 = zones.find((z) => z.zoneId === 'zone-030');
    const z035 = zones.find((z) => z.zoneId === 'zone-035');

    it('verifies actual scores, backend categories, and adapted frontend properties', () => {
      expect(z024).toBeDefined();
      expect(z030).toBeDefined();
      expect(z035).toBeDefined();

      // Zone 024: 0.24% flooded, 2 bldgs -> score 1.5 -> LOW
      expect(z024.rawRiskScore).toBe(1.5);
      expect(z024.riskScore).toBe(2);
      expect(z024.riskLevel).toBe('LOW');
      expect(THEME.riskColors[z024.riskLevel]).toBe('#2E7D32'); // Green

      // Zone 030: 1.90% flooded, 0 bldgs, partial isolation -> score 10.9 -> LOW
      expect(z030.rawRiskScore).toBe(10.9);
      expect(z030.riskScore).toBe(11);
      expect(z030.riskLevel).toBe('LOW');
      expect(THEME.riskColors[z030.riskLevel]).toBe('#2E7D32'); // Green

      // Zone 035: 4.42% flooded, 14 bldgs, partial isolation -> score 22.8 -> MEDIUM
      expect(z035.rawRiskScore).toBe(22.8);
      expect(z035.riskScore).toBe(23);
      expect(z035.riskLevel).toBe('MEDIUM');
      expect(THEME.riskColors[z035.riskLevel]).toBe('#E69F00'); // Orange
    });

    it('renders ZoneDetails DOM for Zone 024 correctly', () => {
      const { unmount } = render(<ZoneDetails zone={z024} onClearSelection={vi.fn()} />);
      expect(screen.getByText('Zone 024 (grid cell)')).toBeInTheDocument();
      expect(screen.getByText('zone-024')).toBeInTheDocument();
      expect(screen.getByText('2 / 100')).toBeInTheDocument();
      expect(screen.getByText('LOW')).toBeInTheDocument();
      unmount();
    });

    it('renders ZoneDetails DOM for Zone 030 correctly', () => {
      const { unmount } = render(<ZoneDetails zone={z030} onClearSelection={vi.fn()} />);
      expect(screen.getByText('Zone 030 (grid cell)')).toBeInTheDocument();
      expect(screen.getByText('zone-030')).toBeInTheDocument();
      expect(screen.getByText('11 / 100')).toBeInTheDocument();
      expect(screen.getByText('LOW')).toBeInTheDocument();
      unmount();
    });

    it('renders ZoneDetails DOM for Zone 035 correctly', () => {
      const { unmount } = render(<ZoneDetails zone={z035} onClearSelection={vi.fn()} />);
      expect(screen.getByText('Zone 035 (grid cell)')).toBeInTheDocument();
      expect(screen.getByText('zone-035')).toBeInTheDocument();
      expect(screen.getByText('23 / 100')).toBeInTheDocument();
      expect(screen.getByText('MEDIUM')).toBeInTheDocument();
      unmount();
    });
  });

  describe('Dynamic recalculation on data changes', () => {
    it('recalculates riskLevel when risk_score changes even if risk_level is omitted', () => {
      const payload = {
        schema_version: '1.0',
        zones: [
          { zone_id: 'zone-024', risk_score: 78.5 }, // Elevated to CRITICAL
          { zone_id: 'zone-035', risk_score: 12.0 }, // Reduced to LOW
        ],
      };

      const { zones } = adaptZones(payload);
      expect(zones[0].riskLevel).toBe('CRITICAL');
      expect(zones[0].riskScore).toBe(79);

      expect(zones[1].riskLevel).toBe('LOW');
      expect(zones[1].riskScore).toBe(12);
    });

    it('never silently coerces missing or non-finite scores into LOW', () => {
      const payload = {
        schema_version: '1.0',
        zones: [
          { zone_id: 'z-null', risk_score: null },
          { zone_id: 'z-missing' },
          { zone_id: 'z-nan', risk_score: 'invalid' },
        ],
      };

      const { zones } = adaptZones(payload);
      expect(zones[0].riskLevel).toBe('UNKNOWN');
      expect(zones[0].riskScore).toBeNull();

      expect(zones[1].riskLevel).toBe('UNKNOWN');
      expect(zones[1].riskScore).toBeNull();

      expect(zones[2].riskLevel).toBe('UNKNOWN');
      expect(zones[2].riskScore).toBeNull();
    });
  });
});
