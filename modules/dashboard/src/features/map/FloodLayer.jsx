import React, { useMemo } from 'react';
import { Polygon, Tooltip, Popup } from 'react-leaflet';
import { THEME } from '../../config/theme.js';
import { toLatLng, validateFeatureCollection } from './mapUtils.js';

/**
 * FloodLayer component (FR-11, T3.3)
 * Renders verified flood extent polygons with water depth and provenance details.
 */
export default function FloodLayer({ data }) {
  const { validFeatures } = useMemo(() => {
    return validateFeatureCollection(data);
  }, [data]);

  if (!validFeatures || validFeatures.length === 0) {
    return null;
  }

  const floodStyle = {
    fillColor: THEME.colors.flood,
    fillOpacity: 0.35,
    color: THEME.colors.floodBorder,
    weight: 1.5,
  };

  return (
    <>
      {validFeatures.map((feature, idx) => {
        const key = feature.properties?.feature_id || `flood-${idx}`;
        const rawRing = feature.geometry.coordinates[0];
        const latLngs = rawRing.map(toLatLng);
        const props = feature.properties || {};

        return (
          <Polygon
            key={key}
            positions={latLngs}
            pathOptions={floodStyle}
          >
            <Tooltip sticky>
              <div className="text-xs font-sans">
                <span className="font-bold text-navy-900">Flood Inundation</span>
                {props.water_depth_m && <div>Depth: {props.water_depth_m}m</div>}
                {props.area_sqkm && <div>Area: {props.area_sqkm} km²</div>}
              </div>
            </Tooltip>
            <Popup>
              <div className="text-xs font-sans p-1">
                <h4 className="font-bold text-navy-900 border-b pb-1 mb-1">
                  {props.feature_id || 'Flood Extent'}
                </h4>
                <div className="space-y-0.5">
                  <div>Status: <span className="font-semibold text-flood">{props.flood_status || 'FLOODED'}</span></div>
                  {props.water_depth_m && <div>Water Depth: <span className="font-semibold">{props.water_depth_m} m</span></div>}
                  {props.area_sqkm && <div>Area: <span className="font-semibold">{props.area_sqkm} km²</span></div>}
                  {props.provenance && (
                    <div className="pt-1">
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-700 uppercase font-semibold">
                        Provenance: {props.provenance}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </Popup>
          </Polygon>
        );
      })}
    </>
  );
}
