import { describe, it, expect } from 'vitest';
import {
  toLatLng,
  isValidCoordinate,
  areCoordinatesLikelySwapped,
  isValidPolygonRing,
  validateFeatureCollection,
} from '../features/map/mapUtils.js';

describe('mapUtils (T3.2)', () => {
  describe('toLatLng', () => {
    it('converts GeoJSON [lng, lat] to Leaflet [lat, lng]', () => {
      const geoJsonPoint = [77.65, 12.93];
      const leafletPoint = toLatLng(geoJsonPoint);
      expect(leafletPoint).toEqual([12.93, 77.65]);
    });

    it('throws on out-of-range coordinates', () => {
      expect(() => toLatLng([190, 12.0])).toThrow('Coordinate out of range');
      expect(() => toLatLng([77.0, -95.0])).toThrow('Coordinate out of range');
    });

    it('throws on non-array input', () => {
      expect(() => toLatLng('77.6, 12.9')).toThrow('Invalid coordinate array');
    });
  });

  describe('coordinate and ring validation', () => {
    it('detects valid and invalid coordinates', () => {
      expect(isValidCoordinate(77.6, 12.9)).toBe(true);
      expect(isValidCoordinate(-180, 90)).toBe(true);
      expect(isValidCoordinate(-180.1, 0)).toBe(false);
      expect(isValidCoordinate(0, 90.1)).toBe(false);
      expect(isValidCoordinate(NaN, 12.0)).toBe(false);
    });

    it('flags likely swapped coordinates in India context', () => {
      // Swapped: lng = 12.9, lat = 77.6
      expect(areCoordinatesLikelySwapped(12.9, 77.6)).toBe(true);
      // Correct: lng = 77.6, lat = 12.9
      expect(areCoordinatesLikelySwapped(77.6, 12.9)).toBe(false);
    });

    it('rejects unclosed polygon rings', () => {
      const openRing = [
        [77.6, 12.9],
        [77.7, 12.9],
        [77.7, 13.0],
        [77.6, 13.0],
      ];
      expect(isValidPolygonRing(openRing)).toBe(false);

      const closedRing = [
        [77.6, 12.9],
        [77.7, 12.9],
        [77.7, 13.0],
        [77.6, 13.0],
        [77.6, 12.9],
      ];
      expect(isValidPolygonRing(closedRing)).toBe(true);
    });
  });

  describe('validateFeatureCollection', () => {
    it('filters invalid features, drops them and returns warning counts', () => {
      const collection = {
        type: 'FeatureCollection',
        features: [
          {
            id: 'valid-1',
            geometry: {
              type: 'Polygon',
              coordinates: [
                [
                  [77.6, 12.9],
                  [77.7, 12.9],
                  [77.7, 13.0],
                  [77.6, 13.0],
                  [77.6, 12.9],
                ],
              ],
            },
          },
          {
            id: 'broken-ring',
            geometry: {
              type: 'Polygon',
              coordinates: [
                [
                  [77.6, 12.9],
                  [77.7, 12.9],
                  [77.7, 13.0],
                  [77.6, 13.0], // unclosed
                ],
              ],
            },
          },
          {
            id: 'broken-point',
            geometry: {
              type: 'Point',
              coordinates: [200, 12.9], // out of range
            },
          },
        ],
      };

      const result = validateFeatureCollection(collection);
      expect(result.validFeatures).toHaveLength(1);
      expect(result.droppedCount).toBe(2);
      expect(result.warnings).toHaveLength(2);
    });
  });
});
