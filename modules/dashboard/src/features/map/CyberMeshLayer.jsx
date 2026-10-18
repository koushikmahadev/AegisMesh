import React, { useMemo } from 'react';
import { Marker, Popup, Tooltip } from 'react-leaflet';
import L from 'leaflet';

// Dynamic HTML/SVG DivIcons for Drone Relays, Water Sensors, and SOC Uplink
function createCyberDivIcon(node) {
  const isCompromised = node.status === 'COMPROMISED' || node.alert_tier === 'CRITICAL';
  const isQuarantined = node.status === 'QUARANTINED' || (node.soar_action && node.soar_action !== 'NONE');
  const isWatch = node.status === 'WATCH' || node.alert_tier === 'WATCH';

  let bgColor = '#10b981'; // Healthy Emerald
  let ringColor = 'rgba(16, 185, 129, 0.4)';
  let animClass = '';
  
  if (isQuarantined) {
    bgColor = '#7c3aed'; // Purple Quarantined
    ringColor = 'rgba(124, 58, 237, 0.5)';
  } else if (isCompromised) {
    bgColor = '#dc2626'; // Red Compromised
    ringColor = 'rgba(220, 38, 38, 0.6)';
    animClass = 'animation: pulse 1.2s infinite;';
  } else if (isWatch) {
    bgColor = '#d97706'; // Amber Watch
    ringColor = 'rgba(217, 119, 6, 0.4)';
    animClass = 'animation: pulse 2s infinite;';
  }

  const isDrone = node.type === 'drone';
  const isSensor = node.type === 'sensor';

  const iconSvg = isDrone ? `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/>
      <path d="M4.5 4.5l5 5m5 5l5 5m-15 0l5-5m5-5l5-5"/>
      <circle cx="4" cy="4" r="2.5"/>
      <circle cx="20" cy="4" r="2.5"/>
      <circle cx="4" cy="20" r="2.5"/>
      <circle cx="20" cy="20" r="2.5"/>
    </svg>
  ` : isSensor ? `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/>
      <path d="M12 12v4"/>
    </svg>
  ` : `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2a10 10 0 0 1 10 10c0 4.42-2.87 8.17-6.84 9.5"/>
      <path d="M12 18v4"/>
      <path d="M8 22h8"/>
      <path d="M12 6a6 6 0 0 1 6 6"/>
    </svg>
  `;

  const html = `
    <div style="position: relative; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center;">
      <div style="position: absolute; width: 36px; height: 36px; border-radius: 50%; background: ${ringColor}; ${animClass}"></div>
      <div style="position: relative; background: ${bgColor}; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 2px solid #ffffff; box-shadow: 0 2px 6px rgba(0,0,0,0.35);">
        ${iconSvg}
      </div>
    </div>
  `;

  return L.divIcon({
    html,
    className: 'cyber-mesh-node-marker',
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -18],
  });
}

/**
 * CyberMeshLayer
 * Visualizes cyber-physical mesh telemetry, drone relays, and water sensors protected by AegisDynamics.
 */
export default function CyberMeshLayer({ nodes = [], onSelectNode = () => {} }) {
  const activeNodes = useMemo(() => {
    if (!Array.isArray(nodes)) return [];
    return nodes.filter((n) => typeof n.lat === 'number' && typeof n.lng === 'number');
  }, [nodes]);

  if (activeNodes.length === 0) return null;

  return (
    <>
      {activeNodes.map((node) => {
        const isCompromised = node.status === 'COMPROMISED' || node.alert_tier === 'CRITICAL';
        const isQuarantined = node.status === 'QUARANTINED' || (node.soar_action && node.soar_action !== 'NONE');
        const statusBadgeColor = isQuarantined
          ? 'bg-purple-100 text-purple-900 border-purple-300'
          : isCompromised
          ? 'bg-red-100 text-red-900 border-red-300'
          : 'bg-emerald-100 text-emerald-900 border-emerald-300';

        return (
          <Marker
            key={node.id || node.ip}
            position={[node.lat, node.lng]}
            icon={createCyberDivIcon(node)}
          >
            <Tooltip direction="top" offset={[0, -16]} opacity={0.95}>
              <div className="font-sans text-xs">
                <span className="font-bold">{node.name || node.id}</span>
                <span className="text-gray-500 ml-1">({node.ip})</span>
                <div className="text-[10px] uppercase font-semibold mt-0.5" style={{ color: isCompromised ? '#dc2626' : '#059669' }}>
                  Aegis: {node.status || 'HEALTHY'} (λ₂: {Number(node.spectral_lambda2 || 0.88).toFixed(2)})
                </div>
              </div>
            </Tooltip>

            <Popup className="cyber-node-popup">
              <div className="p-1 space-y-2 font-sans max-w-[260px]">
                <div className="flex items-center justify-between border-b pb-1">
                  <div>
                    <h4 className="font-bold text-xs text-gray-900">{node.name || node.id}</h4>
                    <p className="font-mono text-[11px] text-gray-500">{node.ip}</p>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${statusBadgeColor}`}>
                    {node.status || 'HEALTHY'}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-1.5 text-[11px] bg-slate-50 p-2 rounded border border-slate-200">
                  <div>
                    <span className="text-gray-500 block text-[10px]">Laplacian λ₂:</span>
                    <span className="font-mono font-bold">{Number(node.spectral_lambda2 || 0.88).toFixed(3)}</span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px]">Anomaly e_G:</span>
                    <span className="font-mono font-bold">{Number(node.mahalanobis_residual || 0.42).toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px]">Dual-Risk P_ST:</span>
                    <span className="font-mono font-bold">{((node.fused_risk || 0.02) * 100).toFixed(1)}%</span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px]">Telemetry:</span>
                    <span className={`font-mono font-bold text-[10px] ${node.telemetry_status === 'UNTRUSTED' ? 'text-red-700' : 'text-emerald-700'}`}>
                      {node.telemetry_status || 'TRUSTED'}
                    </span>
                  </div>
                </div>

                {node.soar_action && node.soar_action !== 'NONE' && (
                  <div className="bg-purple-50 border border-purple-200 p-1.5 rounded text-[10px]">
                    <span className="font-bold text-purple-900 block">Aegis SOAR Containment:</span>
                    <code className="text-purple-800 break-all font-mono text-[9.5px]">{node.soar_action}</code>
                  </div>
                )}

                {node.notes && (
                  <p className="text-[10px] text-gray-600 italic">
                    {node.notes}
                  </p>
                )}

                <button
                  type="button"
                  onClick={() => onSelectNode(node)}
                  className="w-full mt-1.5 py-1 px-2 bg-slate-900 hover:bg-slate-800 text-white rounded text-[10.5px] font-semibold flex items-center justify-center gap-1 cursor-pointer transition shadow-xs"
                >
                  <span>Open Aegis Threat Forensics</span>
                  <span aria-hidden="true">&rarr;</span>
                </button>
              </div>
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}
