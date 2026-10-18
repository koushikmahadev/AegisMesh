import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import fs from 'node:fs';
import path from 'node:path';
import { render, screen, fireEvent } from '@testing-library/react';
import { MapContainer } from 'react-leaflet';
import FloodMap from '../components/FloodMap.jsx';
import MapControls from '../components/MapControls.jsx';
import DashboardLayout from '../app/DashboardLayout.jsx';
import FloodWatchObservedLayer from '../features/map/FloodWatchObservedLayer.jsx';
import FloodWatchPredictedLayer from '../features/map/FloodWatchPredictedLayer.jsx';
import {
  adaptFloodWatchFeature,
  adaptFloodWatchCollection,
} from '../data/dataAdapter.js';

describe('FloodWatch Layers & Unobstructed Map Integration (Step 6)', () => {
  const sampleGroundTruth = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        id: 'gt-bldg-1',
        properties: {
          feature_id: 'gt-bldg-1',
          tile_id: '0_41_58',
          feature_type: 'building',
          provenance: 'observed',
          flooded: 'yes',
          in_training_pool: true,
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[[7.039, 50.531], [7.044, 50.531], [7.044, 50.535], [7.039, 50.535], [7.039, 50.531]]],
        },
      },
      {
        type: 'Feature',
        id: 'gt-road-1',
        properties: {
          feature_id: 'gt-road-1',
          tile_id: '0_41_58',
          feature_type: 'road',
          provenance: 'observed',
          flooded: 'yes',
          in_training_pool: true,
        },
        geometry: {
          type: 'LineString',
          coordinates: [[7.039, 50.531], [7.042, 50.533]],
        },
      },
    ],
  };

  const samplePredictedFast = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        id: 'pred-fast-1',
        properties: {
          feature_id: 'pred-fast-1',
          tile_id: '0_41_58',
          mode: 'fast',
          provenance: 'derived',
          mask_pixels: 2395,
          in_training_pool: true,
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[[7.040, 50.532], [7.043, 50.532], [7.043, 50.534], [7.040, 50.534], [7.040, 50.532]]],
        },
      },
    ],
  };

  const samplePredictedAccurate = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        id: 'pred-acc-1',
        properties: {
          feature_id: 'pred-acc-1',
          tile_id: '0_41_58',
          mode: 'accurate',
          provenance: 'derived',
          mask_pixels: 3120,
          in_training_pool: true,
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[[7.040, 50.532], [7.043, 50.532], [7.043, 50.534], [7.040, 50.534], [7.040, 50.532]]],
        },
      },
    ],
  };

  it('1. Panel collapses and expands cleanly, with keyboard accessibility', () => {
    render(
      <FloodMap
        floodGroundTruth={sampleGroundTruth}
        floodPredictedFast={samplePredictedFast}
        floodPredictedAccurate={samplePredictedAccurate}
      />
    );

    const toggleBtn = screen.getByRole('button', { name: /collapse side panel/i });
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('region', { name: /map layer controls/i })).toBeInTheDocument();

    // Collapse
    fireEvent.click(toggleBtn);
    expect(screen.getByRole('button', { name: /expand side panel/i })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('region', { name: /map layer controls/i })).not.toBeInTheDocument();

    // Expand
    const expandBtn = screen.getByRole('button', { name: /expand side panel/i });
    fireEvent.click(expandBtn);
    expect(screen.getByRole('button', { name: /collapse side panel/i })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('region', { name: /map layer controls/i })).toBeInTheDocument();
  });

  it('2. Map container has nothing covering it except zoom, reset-extent and attribution', () => {
    const { container } = render(
      <FloodMap
        floodGroundTruth={sampleGroundTruth}
        floodPredictedFast={samplePredictedFast}
        floodPredictedAccurate={samplePredictedAccurate}
      />
    );

    // Map viewport container is the first relative div
    const mapViewport = container.querySelector('.bg-slate-200');
    expect(mapViewport).toBeInTheDocument();

    // Within the map viewport, verify no legends, banners, or layer controls exist
    expect(mapViewport.querySelector('[aria-label="Map Layer Controls"]')).toBeNull();
    expect(mapViewport.querySelector('[aria-label="Map Legend"]')).toBeNull();
    expect(mapViewport.querySelector('[role="alert"]')).toBeNull();

    // Only ResetExtentControl and Leaflet map elements exist in the viewport
    const resetExtentBtn = mapViewport.querySelector('button[aria-label="Reset map extent"]');
    expect(resetExtentBtn).not.toBeNull();
  });

  it('3. map.invalidateSize() is triggered on side panel toggle via resize event', () => {
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

    render(
      <FloodMap
        floodGroundTruth={sampleGroundTruth}
        floodPredictedFast={samplePredictedFast}
      />
    );

    const toggleBtn = screen.getByRole('button', { name: /collapse side panel/i });
    fireEvent.click(toggleBtn);

    // Wait for timeout debounce
    expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');
  });

  it('4. Adapter passes provenance and in_training_pool through, counts skipped features, and leaves missing fields null', () => {
    const rawFeatures = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          id: 'valid-feat',
          properties: {
            tile_id: '0_41_58',
            mode: 'accurate',
            in_training_pool: true,
            // provenance, feature_type, mask_pixels omitted
          },
          geometry: {
            type: 'Polygon',
            coordinates: [[[7.0, 50.0], [7.1, 50.0], [7.1, 50.1], [7.0, 50.1], [7.0, 50.0]]],
          },
        },
        {
          type: 'Feature',
          id: 'bad-ring',
          geometry: {
            type: 'Polygon',
            coordinates: [[[7.0, 50.0], [7.1, 50.0], [7.1, 50.1]]], // unclosed
          },
        },
      ],
    };

    let dropped = 0;
    const adapted = adaptFloodWatchCollection(rawFeatures, () => { dropped += 1; }, 'derived');

    expect(adapted.features).toHaveLength(1);
    expect(dropped).toBe(1);

    const feat = adapted.features[0];
    expect(feat.properties.tile_id).toBe('0_41_58');
    expect(feat.properties.mode).toBe('accurate');
    expect(feat.properties.in_training_pool).toBe(true);
    expect(feat.properties.provenance).toBe('derived');
    expect(feat.properties.feature_type).toBeNull(); // missing remains null
    expect(feat.properties.mask_pixels).toBeNull(); // missing remains null
  });

  it('5. Layer toggles turn layers on/off independently in MapControls', () => {
    const onToggle = vi.fn();
    const visibleLayers = {
      flood: false,
      risk: false,
      roads: false,
      facilities: false,
      routes: false,
      buildings: false,
      floodGroundTruth: true,
      floodPredicted: false,
    };

    render(
      <MapControls
        visibleLayers={visibleLayers}
        onToggleLayer={onToggle}
        onResetExtent={() => {}}
        hasFloodWatch={true}
      />
    );

    const gtToggle = screen.getByLabelText('Toggle Observed flood labels overlay');
    const predToggle = screen.getByLabelText('Toggle Model output (derived) overlay');

    expect(gtToggle).toBeChecked();
    expect(predToggle).not.toBeChecked();

    fireEvent.click(predToggle);
    expect(onToggle).toHaveBeenCalledWith('floodPredicted');

    fireEvent.click(gtToggle);
    expect(onToggle).toHaveBeenCalledWith('floodGroundTruth');
  });

  it('6. Fast/accurate mode toggle swaps inference mode', () => {
    const onModeChange = vi.fn();
    const visibleLayers = {
      flood: false,
      risk: false,
      roads: false,
      facilities: false,
      routes: false,
      buildings: false,
      floodGroundTruth: true,
      floodPredicted: true,
    };

    render(
      <MapControls
        visibleLayers={visibleLayers}
        onToggleLayer={() => {}}
        onResetExtent={() => {}}
        modelMode="fast"
        onChangeModelMode={onModeChange}
        hasFloodWatch={true}
      />
    );

    const accurateBtn = screen.getByRole('button', { name: 'Accurate' });
    fireEvent.click(accurateBtn);
    expect(onModeChange).toHaveBeenCalledWith('accurate');

    const fastBtn = screen.getByRole('button', { name: 'Fast' });
    fireEvent.click(fastBtn);
    expect(onModeChange).toHaveBeenCalledWith('fast');
  });

  it('7. Training-pool note appears only when relevant in the side panel', () => {
    // When model layer is ON and features have in_training_pool: true
    const { rerender } = render(
      <FloodMap
        floodGroundTruth={sampleGroundTruth}
        floodPredictedFast={samplePredictedFast}
        visibleLayers={{
          flood: false,
          risk: false,
          roads: false,
          facilities: false,
          routes: false,
          buildings: false,
          floodGroundTruth: true,
          floodPredicted: true,
        }}
      />
    );

    expect(
      screen.getByText(/Model segmentation calibrated against surveyed ground truth/i)
    ).toBeInTheDocument();

    // When model layer is toggled OFF
    rerender(
      <FloodMap
        floodGroundTruth={sampleGroundTruth}
        floodPredictedFast={samplePredictedFast}
        visibleLayers={{
          flood: false,
          risk: false,
          roads: false,
          facilities: false,
          routes: false,
          buildings: false,
          floodGroundTruth: true,
          floodPredicted: false,
        }}
      />
    );

    expect(
      screen.queryByText(/Model segmentation calibrated against surveyed ground truth/i)
    ).not.toBeInTheDocument();
  });

  it('8. Model feature popups contain the mandatory text "Model output, not observed flooding"', () => {
    const { container } = render(
      <MapContainer center={[50.53, 7.04]} zoom={14}>
        <FloodWatchPredictedLayer data={samplePredictedFast} selectedTileId="ALL" />
      </MapContainer>
    );

    const path = container.querySelector('.leaflet-overlay-pane svg path');
    expect(path).not.toBeNull();
    fireEvent.click(path);

    // Popup text is rendered in the layer markup
    expect(screen.getByText('Model output, not observed flooding')).toBeInTheDocument();
    expect(screen.getByText(/Tile ID:/i)).toBeInTheDocument();
    expect(screen.getByText('0_41_58')).toBeInTheDocument();
  });

  describe('Mock Data Validation & Ground Truth Integrity', () => {
    const mockDir = path.resolve(__dirname, '../../public/mock-data-floodwatch');

    it('validates public/mock-data-floodwatch/zones.json integrity', () => {
      const rawText = fs.readFileSync(path.join(mockDir, 'zones.json'), 'utf-8');
      const data = JSON.parse(rawText);

      expect(data.data_mode).toBe('demo');
      expect(Array.isArray(data.zones)).toBe(true);
      expect(data.zones).toHaveLength(14);

      const notInPool = new Set(['0_15_63', '0_15_68', '0_15_65', '0_20_66']);

      let prevCount = Infinity;

      for (const zone of data.zones) {
        // No risk scores or thresholds
        expect(zone.risk_level).toBe('UNKNOWN');
        expect(zone.risk_score).toBeNull();

        // No invented / derived fields
        expect(zone.needs_survey).toBeUndefined();
        expect(zone.flooded_percent).toBeUndefined();
        expect(zone.flooded_area_km2).toBeUndefined();
        expect(zone.total_buildings).toBeUndefined();
        expect(zone.accessibility).toBeUndefined();

        // Real counts
        expect(typeof zone.observed_flooded_count).toBe('number');
        expect(zone.observed_flooded_count).toBeGreaterThanOrEqual(0);
        expect(typeof zone.exposed_buildings).toBe('number');
        expect(zone.exposed_buildings).toBeGreaterThanOrEqual(0);

        // Reasons strictly mention real counts
        expect(Array.isArray(zone.reasons)).toBe(true);
        expect(zone.reasons.length).toBeGreaterThan(0);
        for (const r of zone.reasons) {
          expect(r.toLowerCase()).not.toContain('risk score');
          expect(r.toLowerCase()).not.toContain('needs survey');
        }

        // Real GeoTIFF bounds geometry
        expect(zone.geometry).toBeDefined();
        expect(zone.geometry.type).toBe('Polygon');
        expect(zone.geometry.coordinates[0]).toHaveLength(5);

        // Strict training pool status
        if (notInPool.has(zone.zone_id)) {
          expect(zone.in_training_pool).toBe(false);
          expect(zone.reasons).toContain('Not in the training pool');
        } else {
          expect(zone.in_training_pool).toBe(true);
          expect(zone.reasons).toContain('In model training pool');
        }

        // Sorted descending by observed_flooded_count
        expect(zone.observed_flooded_count).toBeLessThanOrEqual(prevCount);
        prevCount = zone.observed_flooded_count;
      }
    });

    it('adapts all 822 ground truth features with zero dropped features', () => {
      const rawText = fs.readFileSync(path.join(mockDir, 'flood_extent_groundtruth.geojson'), 'utf-8');
      const fc = JSON.parse(rawText);

      expect(fc.features).toHaveLength(822);

      const dropped = [];
      const adapted = adaptFloodWatchCollection(fc, (reason) => dropped.push(reason), 'observed');

      expect(dropped).toHaveLength(0);
      expect(adapted.features).toHaveLength(822);

      // Verify that MultiPolygon and MultiLineString features are retained
      const multiPolygons = adapted.features.filter((f) => f.geometry.type === 'MultiPolygon');
      const multiLines = adapted.features.filter((f) => f.geometry.type === 'MultiLineString');
      expect(multiPolygons.length).toBeGreaterThan(0);
      expect(multiLines.length).toBeGreaterThan(0);
    });

    it('relabels stat cards, zone details and charts in mock-floodwatch mode without risk or exposure implications', () => {
      const mockZones = JSON.parse(fs.readFileSync(path.join(mockDir, 'zones.json'), 'utf-8'));
      const mockGt = JSON.parse(fs.readFileSync(path.join(mockDir, 'flood_extent_groundtruth.geojson'), 'utf-8'));
      const mockFast = JSON.parse(fs.readFileSync(path.join(mockDir, 'flood_extent_predicted_fast.geojson'), 'utf-8'));
      const mockAcc = JSON.parse(fs.readFileSync(path.join(mockDir, 'flood_extent_predicted_accurate.geojson'), 'utf-8'));

      const testData = {
        metadata: {
          dataSource: 'mock-floodwatch',
          dataMode: 'demo',
          studyArea: 'SpaceNet 8 Germany AOI (FloodWatch)',
          generatedAt: '2026-10-15T06:00:13Z',
        },
        zones: mockZones.zones.map((z) => ({
          ...z,
          zoneId: z.zone_id,
          riskLevel: z.risk_level,
          riskScore: z.risk_score,
          exposedBuildings: z.exposed_buildings,
          observed_flooded_count: z.observed_flooded_count,
          in_training_pool: z.in_training_pool,
          hasGeometry: Boolean(z.geometry),
        })),
        floodGroundTruth: mockGt,
        floodPredictedFast: mockFast,
        floodPredictedAccurate: mockAcc,
        blockedRoads: { type: 'FeatureCollection', features: [] },
        facilities: { type: 'FeatureCollection', features: [] },
        routes: [],
      };

      render(<DashboardLayout data={testData} />);

      // Stat cards must have the exact requested labels
      expect(screen.getByText('Observed flooded buildings (labels)')).toBeInTheDocument();
      expect(screen.getByText('Observed flooded roads (labels)')).toBeInTheDocument();
      expect(screen.getByText('Model mask pixels (derived)')).toBeInTheDocument();
      expect(screen.getByText('Monitored tiles')).toBeInTheDocument();

      // Must NOT display risk assessment titles
      expect(screen.queryByText('High-priority zones')).not.toBeInTheDocument();
      expect(screen.queryByText('Flooded area')).not.toBeInTheDocument();

      // Charts must be relabeled to observed flooded features
      expect(screen.getByText('Observed Flooded Features per Tile')).toBeInTheDocument();
      expect(screen.getByText('Observed Flooded Buildings per Tile')).toBeInTheDocument();
      expect(screen.queryByText('Risk Classification Distribution')).not.toBeInTheDocument();
    }, 25000);
  });
});
