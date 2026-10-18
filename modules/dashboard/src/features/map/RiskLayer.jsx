import React from 'react';
import { Polygon, Popup, Tooltip } from 'react-leaflet';
import { THEME } from '../../config/theme.js';
import { toLatLng } from './mapUtils.js';

/**
 * RiskLayer component (FR-12, FR-13, T3.4)
 * Renders priority zone boundaries with risk classification colours.
 * Clicking a polygon selects the zone and triggers onZoneSelect.
 */
export default function RiskLayer({
  zones = [],
  selectedZoneId = null,
  onZoneSelect,
}) {
  const spatialZones = zones.filter((z) => z.hasGeometry && z.geometry?.coordinates);

  const getStyleForZone = (zone) => {
    const isSelected = zone.zoneId === selectedZoneId;
    const riskLevel = zone.riskLevel || 'UNKNOWN';
    const riskColor = THEME.riskColors[riskLevel] || THEME.riskColors.UNKNOWN;

    if (isSelected) {
      return {
        color: THEME.colors.selected,
        weight: 4,
        fillColor: riskColor,
        fillOpacity: 0.45,
        dashArray: null,
      };
    }

    if (riskLevel === 'UNKNOWN') {
      return {
        color: THEME.riskColors.UNKNOWN,
        weight: 2,
        fillColor: THEME.riskColors.UNKNOWN,
        fillOpacity: 0.15,
        dashArray: '4, 4',
      };
    }

    return {
      color: riskColor,
      weight: 2,
      fillColor: riskColor,
      fillOpacity: 0.25,
      dashArray: null,
    };
  };

  return (
    <>
      {spatialZones.map((zone) => {
        const rawRing = zone.geometry.coordinates[0];
        const latLngs = rawRing.map(toLatLng);
        const style = getStyleForZone(zone);

        return (
          <Polygon
            key={zone.zoneId}
            positions={latLngs}
            pathOptions={style}
            eventHandlers={{
              click: () => {
                if (onZoneSelect) {
                  onZoneSelect(zone.zoneId);
                }
              },
            }}
          >
            <Tooltip sticky>
              <div className="text-xs font-sans">
                <div className="font-bold text-navy-900">{zone.name}</div>
                <div className="flex items-center space-x-1 mt-0.5">
                  <span className="font-semibold">Risk:</span>
                  <span
                    className="font-bold px-1 rounded text-[10px]"
                    style={{
                      backgroundColor: `${THEME.riskColors[zone.riskLevel]}20`,
                      color: THEME.riskColors[zone.riskLevel],
                    }}
                  >
                    {zone.riskLevel}
                  </span>
                </div>
              </div>
            </Tooltip>
            <Popup>
              <div className="text-xs font-sans p-1 min-w-[180px]">
                <div className="font-bold text-navy-900 border-b pb-1 mb-1.5 flex items-center justify-between">
                  <span>{zone.name}</span>
                  <span
                    className="px-1.5 py-0.5 rounded text-[10px] font-bold"
                    style={{
                      backgroundColor: `${THEME.riskColors[zone.riskLevel]}20`,
                      color: THEME.riskColors[zone.riskLevel],
                    }}
                  >
                    {zone.riskLevel}
                  </span>
                </div>
                <div className="space-y-1 text-text-muted">
                  <div className="flex justify-between">
                    <span>Priority Score:</span>
                    <span className="font-semibold text-text">
                      {zone.riskScore !== null ? `${zone.riskScore} / 100` : 'Not available'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Flooded:</span>
                    <span className="font-semibold text-text">
                      {zone.floodedPercent !== null ? `${zone.floodedPercent}%` : 'Not available'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Exposed Buildings:</span>
                    <span className="font-semibold text-text">
                      {zone.exposedBuildings !== null ? zone.exposedBuildings : 'Not available'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Accessibility:</span>
                    <span className="font-semibold text-text">{zone.accessibility}</span>
                  </div>
                </div>
                <div className="mt-2 pt-1 border-t text-center">
                  <button
                    type="button"
                    onClick={() => onZoneSelect && onZoneSelect(zone.zoneId)}
                    className="text-[11px] text-flood hover:underline font-semibold"
                  >
                    View Zone Details &rarr;
                  </button>
                </div>
              </div>
            </Popup>
          </Polygon>
        );
      })}
    </>
  );
}
