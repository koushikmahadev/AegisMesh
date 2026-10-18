import React, { useMemo } from 'react';
import { Marker, Popup, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import { toLatLng, validateFeatureCollection } from './mapUtils.js';

import { THEME } from '../../config/theme.js';

// SVG strings for Leaflet divIcons (avoids Vite asset bundler issues with default marker pngs)
const FACILITY_ICONS = {
  hospital: `
    <div style="background-color: ${THEME.riskColors.HIGH}; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 2px solid ${THEME.colors.card}; box-shadow: 0 2px 5px rgba(0,0,0,0.3);">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${THEME.colors.card}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 6v12m-6-6h12"/>
      </svg>
    </div>
  `,
  shelter: `
    <div style="background-color: ${THEME.colors.shelter}; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 2px solid ${THEME.colors.card}; box-shadow: 0 2px 5px rgba(0,0,0,0.3);">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${THEME.colors.card}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
        <polyline points="9 22 9 12 15 12 15 22"/>
      </svg>
    </div>
  `,
  depot: `
    <div style="background-color: ${THEME.colors['navy-900']}; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 2px solid ${THEME.colors.card}; box-shadow: 0 2px 5px rgba(0,0,0,0.3);">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${THEME.colors.card}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>
        <path d="m3.3 7 8.7 5 8.7-5"/>
        <path d="M12 22V12"/>
      </svg>
    </div>
  `,
  default: `
    <div style="background-color: ${THEME.colors['text-muted']}; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 2px solid ${THEME.colors.card}; box-shadow: 0 2px 5px rgba(0,0,0,0.3);">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${THEME.colors.card}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
      </svg>
    </div>
  `,
};

function createFacilityDivIcon(type) {
  const normType = (type || '').toLowerCase();
  const html = FACILITY_ICONS[normType] || FACILITY_ICONS.default;
  return L.divIcon({
    html,
    className: 'custom-facility-marker',
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    popupAnchor: [0, -15],
  });
}

/**
 * FacilityLayer component (FR-11, T3.5)
 * Renders Point facilities (hospitals, shelters, depots) with per-type divIcons.
 */
export default function FacilityLayer({ data }) {
  const { validFeatures } = useMemo(() => {
    return validateFeatureCollection(data);
  }, [data]);

  if (!validFeatures || validFeatures.length === 0) {
    return null;
  }

  return (
    <>
      {validFeatures.map((feature, idx) => {
        const id = feature.properties?.facility_id || `facility-${idx}`;
        const rawCoords = feature.geometry.coordinates;
        const position = toLatLng(rawCoords);
        const props = feature.properties || {};
        const icon = createFacilityDivIcon(props.type);

        return (
          <Marker
            key={id}
            position={position}
            icon={icon}
          >
            <Tooltip>
              <div className="text-xs font-sans">
                <span className="font-bold text-navy-900">{props.name || id}</span>
                <div className="text-[10px] text-text-muted capitalize">Type: {props.type || 'Facility'}</div>
              </div>
            </Tooltip>
            <Popup>
              <div className="text-xs font-sans p-1 min-w-[170px]">
                <h4 className="font-bold text-navy-900 border-b pb-1 mb-1.5">{props.name || id}</h4>
                <div className="space-y-0.5 text-text-muted">
                  <div className="flex justify-between">
                    <span>Category:</span>
                    <span className="font-semibold text-text capitalize">{props.type || 'Facility'}</span>
                  </div>
                  {props.capacity && (
                    <div className="flex justify-between">
                      <span>Capacity:</span>
                      <span className="font-semibold text-text">{props.capacity} beds/pers.</span>
                    </div>
                  )}
                  {props.occupancy !== undefined && (
                    <div className="flex justify-between">
                      <span>Occupancy:</span>
                      <span className="font-semibold text-text">{props.occupancy}</span>
                    </div>
                  )}
                  <div className="flex justify-between pt-1 border-t mt-1">
                    <span>Status:</span>
                    <span className="font-semibold text-emerald-600">{props.status || 'ACTIVE'}</span>
                  </div>
                </div>
              </div>
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}
