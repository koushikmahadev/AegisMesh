import React, { useMemo } from 'react';
import { Polygon, Polyline, Tooltip, Popup } from 'react-leaflet';
import { THEME } from '../../config/theme.js';
import { toLatLng } from './mapUtils.js';
import ProvenanceBadge from '../../components/ProvenanceBadge.jsx';

/**
 * FloodWatchObservedLayer
 * Renders human-labelled ground truth from SpaceNet 8 (building polygons & road line segments).
 * Supports filtering by selected tile_id.
 */
export default function FloodWatchObservedLayer({ data, selectedTileId = null }) {
  const features = useMemo(() => {
    if (!data || !Array.isArray(data.features)) return [];
    return data.features.filter((f) => {
      if (!f?.geometry?.coordinates) return false;
      if (selectedTileId && selectedTileId !== 'ALL' && f.properties?.tile_id !== selectedTileId) {
        return false;
      }
      return true;
    });
  }, [data, selectedTileId]);

  if (!features || features.length === 0) {
    return null;
  }

  const buildingCasingStyle = {
    color: '#fdfbf7',
    weight: 3.5,
    fill: false,
    interactive: false,
  };

  const buildingStyle = {
    fillColor: THEME.colors.floodwatchObservedBuilding,
    fillOpacity: 0.65,
    color: THEME.colors.floodwatchObservedBuildingBorder,
    weight: 1.5,
  };

  const roadCasingStyle = {
    color: '#fdfbf7',
    weight: 5.5,
    lineCap: 'round',
    interactive: false,
  };

  const roadStyle = {
    color: THEME.colors.floodwatchObservedRoad,
    weight: 3.5,
    lineCap: 'round',
  };

  return (
    <>
      {features.map((feature, idx) => {
        const props = feature.properties || {};
        const geom = feature.geometry;
        const id = feature.id || props.feature_id || `gt-${idx}`;
        const featureType = props.feature_type || (geom.type === 'LineString' ? 'road' : 'building');

        if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
          let positions;
          try {
            if (geom.type === 'Polygon') {
              positions = geom.coordinates[0].map(toLatLng);
            } else if (geom.type === 'MultiPolygon') {
              positions = geom.coordinates.map((poly) => poly[0].map(toLatLng));
            }
          } catch {
            return null;
          }
          if (!positions || positions.length === 0) return null;

          const buildingTooltip = (
            <Tooltip sticky>
              <div className="text-xs font-sans">
                <span className="font-bold text-amber-800">Observed Building</span>
                <div className="text-[11px] text-text-muted">Tile: {props.tile_id || 'N/A'}</div>
              </div>
            </Tooltip>
          );

          const buildingPopup = (
            <Popup>
              <div className="text-xs font-sans p-1 min-w-[180px] space-y-1.5">
                <div className="border-b pb-1 font-bold text-navy-900 flex items-center justify-between">
                  <span>Observed Label</span>
                  <ProvenanceBadge value={props.provenance || 'observed'} />
                </div>
                <div className="space-y-0.5 text-text-muted text-[11px]">
                  <div><span className="font-semibold text-text">Tile ID:</span> {props.tile_id !== null ? props.tile_id : 'null'}</div>
                  <div><span className="font-semibold text-text">Feature Type:</span> {props.feature_type !== null ? props.feature_type : 'building'}</div>
                  <div><span className="font-semibold text-text">Mode:</span> {props.mode !== null ? props.mode : 'null'}</div>
                  <div><span className="font-semibold text-text">Mask Pixels:</span> {props.mask_pixels !== null ? props.mask_pixels : 'null'}</div>
                  <div><span className="font-semibold text-text">In Training Pool:</span> {props.in_training_pool !== null ? String(props.in_training_pool) : 'null'}</div>
                  {props.flooded && <div><span className="font-semibold text-text">Flooded:</span> {props.flooded}</div>}
                  {props.source && <div><span className="font-semibold text-text">Source:</span> {props.source}</div>}
                </div>
              </div>
            </Popup>
          );

          return (
            <React.Fragment key={id}>
              {/* Paper-colored casing under stroke for satellite basemap contrast */}
              <Polygon positions={positions} pathOptions={buildingCasingStyle}>
                {buildingTooltip}
                {buildingPopup}
              </Polygon>
              <Polygon positions={positions} pathOptions={buildingStyle}>
                {buildingTooltip}
                {buildingPopup}
              </Polygon>
            </React.Fragment>
          );
        }

        if (geom.type === 'LineString' || geom.type === 'MultiLineString') {
          let latLngs;
          try {
            if (geom.type === 'LineString') {
              latLngs = geom.coordinates.map(toLatLng);
            } else if (geom.type === 'MultiLineString') {
              latLngs = geom.coordinates.map((line) => line.map(toLatLng));
            }
          } catch {
            return null;
          }
          if (!latLngs || latLngs.length === 0) return null;

          const roadTooltip = (
            <Tooltip sticky>
              <div className="text-xs font-sans">
                <span className="font-bold text-orange-700">Observed Flooded Road</span>
                <div className="text-[11px] text-text-muted">Tile: {props.tile_id || 'N/A'}</div>
              </div>
            </Tooltip>
          );

          const roadPopup = (
            <Popup>
              <div className="text-xs font-sans p-1 min-w-[180px] space-y-1.5">
                <div className="border-b pb-1 font-bold text-navy-900 flex items-center justify-between">
                  <span>Observed Road</span>
                  <ProvenanceBadge value={props.provenance || 'observed'} />
                </div>
                <div className="space-y-0.5 text-text-muted text-[11px]">
                  <div><span className="font-semibold text-text">Tile ID:</span> {props.tile_id !== null ? props.tile_id : 'null'}</div>
                  <div><span className="font-semibold text-text">Feature Type:</span> {props.feature_type !== null ? props.feature_type : 'road'}</div>
                  <div><span className="font-semibold text-text">Mode:</span> {props.mode !== null ? props.mode : 'null'}</div>
                  <div><span className="font-semibold text-text">Mask Pixels:</span> {props.mask_pixels !== null ? props.mask_pixels : 'null'}</div>
                  <div><span className="font-semibold text-text">In Training Pool:</span> {props.in_training_pool !== null ? String(props.in_training_pool) : 'null'}</div>
                  {props.flooded && <div><span className="font-semibold text-text">Flooded:</span> {props.flooded}</div>}
                  {props.source && <div><span className="font-semibold text-text">Source:</span> {props.source}</div>}
                </div>
              </div>
            </Popup>
          );

          return (
            <React.Fragment key={id}>
              {/* Paper-colored casing under stroke for satellite basemap contrast */}
              <Polyline positions={latLngs} pathOptions={roadCasingStyle}>
                {roadTooltip}
                {roadPopup}
              </Polyline>
              <Polyline positions={latLngs} pathOptions={roadStyle}>
                {roadTooltip}
                {roadPopup}
              </Polyline>
            </React.Fragment>
          );
        }

        return null;
      })}
    </>
  );
}
