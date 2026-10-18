import React, { useMemo } from 'react';
import { Polygon, Tooltip, Popup } from 'react-leaflet';
import { THEME } from '../../config/theme.js';
import { toLatLng } from './mapUtils.js';
import ProvenanceBadge from '../../components/ProvenanceBadge.jsx';

/**
 * BuildingLayer component (6th overlay)
 * Renders exposed and flooded building footprints.
 * Flooded buildings are styled distinctly using buildingFlooded theme tokens.
 */
export default function BuildingLayer({ data }) {
  const features = useMemo(() => {
    if (!data || !Array.isArray(data.features)) return [];
    return data.features.filter((f) => {
      const geom = f.geometry;
      return geom && (geom.type === 'Polygon' || geom.type === 'MultiPolygon') && Array.isArray(geom.coordinates);
    });
  }, [data]);

  if (!features || features.length === 0) {
    return null;
  }

  return (
    <>
      {features.map((feature, idx) => {
        const props = feature.properties || {};
        const isFlooded = props.flooded === true || props.flooded === 'yes';
        const id = props.id || props.feature_id || `bldg-${idx}`;

        const style = {
          fillColor: isFlooded ? THEME.colors.buildingFlooded : THEME.colors['text-muted'],
          fillOpacity: isFlooded ? 0.75 : 0.25,
          color: isFlooded ? THEME.colors.buildingFloodedBorder : THEME.colors.border,
          weight: 1,
        };

        const geom = feature.geometry;
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

        return (
          <Polygon key={id} positions={positions} pathOptions={style}>
            <Tooltip sticky>
              <div className="text-xs font-sans">
                <span className={`font-bold ${isFlooded ? 'text-amber-800' : 'text-navy-900'}`}>
                  {isFlooded ? 'Flooded Building' : 'Building'}
                </span>
                <div className="text-[11px] text-text-muted">{id}</div>
              </div>
            </Tooltip>
            <Popup>
              <div className="text-xs font-sans p-1 min-w-[160px]">
                <h4 className="font-bold text-navy-900 border-b pb-1 mb-1">{id}</h4>
                <div className="space-y-0.5 text-text-muted">
                  <div>
                    Status:{' '}
                    <span className={`font-bold ${isFlooded ? 'text-amber-800' : 'text-slate-700'}`}>
                      {isFlooded ? 'FLOODED' : 'NOT FLOODED'}
                    </span>
                  </div>
                  {props.building && <div>Type: <span className="font-semibold text-text">{props.building}</span></div>}
                  <div className="pt-1 mt-1 border-t">
                    <ProvenanceBadge value={props.provenance || 'observed'} />
                  </div>
                </div>
              </div>
            </Popup>
          </Polygon>
        );
      })}
    </>
  );
}
