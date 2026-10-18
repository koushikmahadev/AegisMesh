import React, { useMemo } from 'react';
import { Polygon, Tooltip, Popup } from 'react-leaflet';
import { THEME } from '../../config/theme.js';
import { toLatLng } from './mapUtils.js';
import ProvenanceBadge from '../../components/ProvenanceBadge.jsx';

/**
 * FloodWatchPredictedLayer
 * Renders SegFormer-B0 ML model predictions with distinct dashed outline.
 * Supports filtering by selected tile_id.
 * Popups include mandatory text: "Model output, not observed flooding".
 */
export default function FloodWatchPredictedLayer({ data, selectedTileId = null }) {
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

  const predictedCasingStyle = {
    color: '#fdfbf7',
    weight: 4,
    fill: false,
    interactive: false,
  };

  const predictedStyle = {
    fillColor: THEME.colors.floodwatchPredicted,
    fillOpacity: 0.45,
    color: THEME.colors.floodwatchPredictedBorder,
    weight: 2,
    dashArray: '5, 5',
  };

  return (
    <>
      {features.map((feature, idx) => {
        const props = feature.properties || {};
        const geom = feature.geometry;
        const id = feature.id || props.feature_id || `pred-${idx}`;

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

        const tooltipNode = (
          <Tooltip sticky>
            <div className="text-xs font-sans">
              <span className="font-bold text-sky-800">Model Predicted Flood</span>
              <div className="text-[11px] text-text-muted">Tile: {props.tile_id || 'N/A'} ({props.mode || 'derived'})</div>
            </div>
          </Tooltip>
        );

        const popupNode = (
          <Popup>
            <div className="text-xs font-sans p-1 min-w-[200px] space-y-1.5">
              <div className="border-b pb-1 font-bold text-navy-900 flex items-center justify-between">
                <span>Model Output</span>
                <ProvenanceBadge value={props.provenance || 'derived'} />
              </div>

              {/* Mandatory Disclaimer Requirement */}
              <div className="px-2 py-1 bg-amber-50 border border-amber-300 text-amber-900 rounded font-semibold text-[11px]">
                Model output, not observed flooding
              </div>

              <div className="space-y-0.5 text-text-muted text-[11px]">
                <div><span className="font-semibold text-text">Tile ID:</span> {props.tile_id !== null ? props.tile_id : 'null'}</div>
                <div><span className="font-semibold text-text">Mode:</span> {props.mode !== null ? props.mode : 'null'}</div>
                <div><span className="font-semibold text-text">Mask Pixels:</span> {props.mask_pixels !== null ? props.mask_pixels : 'null'}</div>
                <div><span className="font-semibold text-text">In Training Pool:</span> {props.in_training_pool !== null ? String(props.in_training_pool) : 'null'}</div>
                <div><span className="font-semibold text-text">Feature Type:</span> {props.feature_type !== null ? props.feature_type : 'null'}</div>
              </div>
            </div>
          </Popup>
        );

        return (
          <React.Fragment key={id}>
            {/* Paper-colored casing under stroke for satellite basemap contrast */}
            <Polygon positions={positions} pathOptions={predictedCasingStyle}>
              {tooltipNode}
              {popupNode}
            </Polygon>
            <Polygon positions={positions} pathOptions={predictedStyle}>
              {tooltipNode}
              {popupNode}
            </Polygon>
          </React.Fragment>
        );
    })}
    </>
  );
}
