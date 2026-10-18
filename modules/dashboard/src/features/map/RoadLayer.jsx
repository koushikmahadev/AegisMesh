import React, { useMemo } from 'react';
import { Polyline, Popup, Tooltip } from 'react-leaflet';
import { THEME } from '../../config/theme.js';
import { toLatLng, validateFeatureCollection } from './mapUtils.js';

/**
 * RoadLayer component (FR-11, FR-41, T3.5)
 * Renders blocked roadways as prominent dashed red lines.
 */
export default function RoadLayer({ data }) {
  const { validFeatures } = useMemo(() => {
    return validateFeatureCollection(data);
  }, [data]);

  if (!validFeatures || validFeatures.length === 0) {
    return null;
  }

  const roadStyle = {
    color: THEME.colors['risk-high'],
    weight: 4,
    dashArray: '6, 6',
    lineCap: 'round',
  };

  return (
    <>
      {validFeatures.map((feature, idx) => {
        const id = feature.properties?.road_id || `road-${idx}`;
        const rawCoords = feature.geometry.coordinates;
        const latLngs = rawCoords.map(toLatLng);
        const props = feature.properties || {};

        return (
          <Polyline
            key={id}
            positions={latLngs}
            pathOptions={roadStyle}
          >
            <Tooltip sticky>
              <div className="text-xs font-sans">
                <span className="font-bold text-risk-high">BLOCKED ROAD</span>
                <div>{props.name || id}</div>
              </div>
            </Tooltip>
            <Popup>
              <div className="text-xs font-sans p-1 min-w-[170px]">
                <div className="flex items-center space-x-1.5 font-bold text-risk-high border-b pb-1 mb-1">
                  <span>{props.name || id}</span>
                </div>
                <div className="space-y-0.5 text-text-muted">
                  <div>Status: <span className="font-bold text-risk-high">BLOCKED</span></div>
                  {props.reason && <div>Reason: <span className="font-semibold text-text">{props.reason}</span></div>}
                  {props.water_depth_m && <div>Water Depth: <span className="font-semibold">{props.water_depth_m} m</span></div>}
                  {props.length_km && <div>Length: <span className="font-semibold">{props.length_km} km</span></div>}
                  {props.provenance && (
                    <div className="pt-1 mt-1 border-t">
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-700 uppercase font-semibold">
                        Provenance: {props.provenance}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </Popup>
          </Polyline>
        );
      })}
    </>
  );
}
