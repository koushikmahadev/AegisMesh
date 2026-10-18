import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * Resolves the WebSocket URL for the mesh relay server.
 * Priority: customUrl > VITE_MESH_RELAY_URL > ws://<page hostname>:8787 > ws://localhost:8787
 * @param {string} [customUrl]
 * @returns {string}
 */
export function getRelayUrl(customUrl) {
  if (customUrl && typeof customUrl === 'string' && customUrl.trim()) {
    return customUrl.trim();
  }
  const envUrl = typeof import.meta !== 'undefined' ? import.meta.env?.VITE_MESH_RELAY_URL : undefined;
  if (envUrl && typeof envUrl === 'string' && envUrl.trim()) {
    return envUrl.trim();
  }
  const hostname =
    typeof window !== 'undefined' && window.location?.hostname
      ? window.location.hostname
      : 'localhost';
  return `ws://${hostname}:8787`;
}

/**
 * Custom hook for peer-to-peer field survey sync via local WebSocket relay.
 * Designed for zero-internet / local hotspot disaster response environments.
 *
 * @param {Object} [options]
 * @param {string} [options.url] Override relay WebSocket URL
 * @param {boolean} [options.enabled=true] Enable connection
 * @returns {{
 *   updates: Array<Object>,
 *   sendUpdate: (update: Object) => Object,
 *   peerCount: number,
 *   status: 'active' | 'connecting' | 'offline'
 * }}
 */
export const DEFAULT_CYBER_NODES = [
  {
    id: 'DRONE-RELAY-01',
    name: 'Drone Relay Alpha',
    type: 'drone',
    ip: '192.168.10.101',
    lat: 50.5365,
    lng: 7.0410,
    status: 'HEALTHY',
    alert_tier: 'NOMINAL',
    spectral_lambda2: 0.88,
    mahalanobis_residual: 0.42,
    fused_risk: 0.03,
    soar_action: 'NONE',
    telemetry_status: 'TRUSTED',
    notes: 'Aerial field relay covering Ahr valley central evacuation axis'
  },
  {
    id: 'DRONE-RELAY-02',
    name: 'Drone Relay Beta',
    type: 'drone',
    ip: '192.168.10.102',
    lat: 50.5392,
    lng: 7.0485,
    status: 'HEALTHY',
    alert_tier: 'NOMINAL',
    spectral_lambda2: 0.85,
    mahalanobis_residual: 0.51,
    fused_risk: 0.04,
    soar_action: 'NONE',
    telemetry_status: 'TRUSTED',
    notes: 'High-altitude mesh repeater linked to sector 2 command post'
  },
  {
    id: 'SENSOR-GATEWAY-01',
    name: 'IoT Water Gauge Alpha',
    type: 'sensor',
    ip: '192.168.10.25',
    lat: 50.5320,
    lng: 7.0375,
    status: 'HEALTHY',
    alert_tier: 'NOMINAL',
    spectral_lambda2: 0.91,
    mahalanobis_residual: 0.38,
    fused_risk: 0.02,
    soar_action: 'NONE',
    telemetry_status: 'TRUSTED',
    notes: 'Submersible ultrasonic river depth gauge & telemetry uplink'
  },
  {
    id: 'SENSOR-GATEWAY-02',
    name: 'IoT Water Gauge Beta',
    type: 'sensor',
    ip: '192.168.10.50',
    lat: 50.5435,
    lng: 7.0520,
    status: 'HEALTHY',
    alert_tier: 'NOMINAL',
    spectral_lambda2: 0.87,
    mahalanobis_residual: 0.45,
    fused_risk: 0.03,
    soar_action: 'NONE',
    telemetry_status: 'TRUSTED',
    notes: 'Dike crest water pressure monitor & siren activation trigger'
  },
  {
    id: 'SOC-GATEWAY-01',
    name: 'Aegis SOC Command Uplink',
    type: 'gateway',
    ip: '192.168.10.1',
    lat: 50.5290,
    lng: 7.0340,
    status: 'HEALTHY',
    alert_tier: 'NOMINAL',
    spectral_lambda2: 0.94,
    mahalanobis_residual: 0.29,
    fused_risk: 0.01,
    soar_action: 'NONE',
    telemetry_status: 'TRUSTED',
    notes: 'Central dispatch operations vehicle & secure satellite uplink'
  }
];

export function useMeshSync(options = {}) {
  const { url: customUrl, enabled = true } = options;
  const relayUrl = getRelayUrl(customUrl);

  const [updates, setUpdates] = useState([]);
  const [peerCount, setPeerCount] = useState(0);
  const [status, setStatus] = useState('connecting');
  const [cyberNodes, setCyberNodes] = useState(DEFAULT_CYBER_NODES);
  const [latestCyberAlert, setLatestCyberAlert] = useState(null);

  const wsRef = useRef(null);
  const offlineQueueRef = useRef([]);
  const reconnectTimeoutRef = useRef(null);
  const backoffDelayRef = useRef(1000);
  const isMountedRef = useRef(true);

  // Send update function
  const sendUpdate = useCallback((updateData) => {
    if (!updateData || !updateData.zoneId) {
      console.warn('[MeshSync] Cannot send update without zoneId:', updateData);
      return null;
    }

    const newUpdate = {
      id: updateData.id || `mesh-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      zoneId: String(updateData.zoneId),
      surveyStatus: ['flooded', 'clear', 'unsure'].includes(updateData.surveyStatus)
        ? updateData.surveyStatus
        : 'unsure',
      note: (updateData.note || '').slice(0, 280),
      author: (updateData.author && String(updateData.author).trim()) || 'Field user',
      createdAt: updateData.createdAt || new Date().toISOString(),
      provenance: 'observed',
    };

    // Optimistically record locally (ignoring duplicates)
    setUpdates((prev) => {
      if (prev.some((u) => u.id === newUpdate.id)) return prev;
      return [...prev, newUpdate];
    });

    const ws = wsRef.current;
    if (ws && ws.readyState === (typeof WebSocket !== 'undefined' ? WebSocket.OPEN : 1)) {
      try {
        ws.send(JSON.stringify({ type: 'update', update: newUpdate }));
      } catch (err) {
        offlineQueueRef.current.push(newUpdate);
      }
    } else {
      // Offline: queue for transmission upon reconnection
      offlineQueueRef.current.push(newUpdate);
    }

    return newUpdate;
  }, []);

  useEffect(() => {
    isMountedRef.current = true;

    if (!enabled) {
      setStatus('offline');
      return;
    }

    function connect() {
      if (!isMountedRef.current) return;

      if (typeof WebSocket === 'undefined') {
        setStatus('offline');
        return;
      }

      setStatus('connecting');

      try {
        const ws = new WebSocket(relayUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMountedRef.current) return;
          setStatus('active');
          backoffDelayRef.current = 1000; // Reset backoff on successful connection

          // Flush queued offline updates
          while (offlineQueueRef.current.length > 0) {
            const queued = offlineQueueRef.current.shift();
            try {
              ws.send(JSON.stringify({ type: 'update', update: queued }));
            } catch (err) {
              offlineQueueRef.current.unshift(queued);
              break;
            }
          }
        };

        ws.onmessage = (event) => {
          if (!isMountedRef.current) return;
          try {
            const payload = JSON.parse(event.data);
            if (payload.type === 'init' && Array.isArray(payload.updates)) {
              setUpdates((prev) => {
                const map = new Map();
                for (const u of prev) {
                  if (u && u.id) map.set(u.id, u);
                }
                for (const u of payload.updates) {
                  if (u && u.id) map.set(u.id, u);
                }
                return Array.from(map.values());
              });
            } else if (payload.type === 'peer_count' && typeof payload.count === 'number') {
              setPeerCount(payload.count);
            } else if (payload.type === 'update' && payload.update && payload.update.id) {
              setUpdates((prev) => {
                if (prev.some((u) => u.id === payload.update.id)) return prev;
                return [...prev, payload.update];
              });
            } else if (payload.type === 'cyber_mesh_init' && Array.isArray(payload.nodes)) {
              setCyberNodes(payload.nodes);
            } else if (payload.type === 'cyber_mesh_update') {
              if (payload.nodes && Array.isArray(payload.nodes)) {
                setCyberNodes(payload.nodes);
              } else if (payload.event) {
                const evt = payload.event;
                setCyberNodes((prev) => {
                  const idx = prev.findIndex((n) => n.id === evt.node_id || n.ip === evt.ip);
                  if (idx !== -1) {
                    const next = [...prev];
                    next[idx] = { ...next[idx], ...evt };
                    return next;
                  }
                  return [...prev, evt];
                });
              }
              if (payload.event) {
                setLatestCyberAlert(payload.event);
              }
            }
          } catch (e) {
            // Silently ignore non-JSON messages
          }
        };

        ws.onclose = () => {
          if (!isMountedRef.current) return;
          setStatus('offline');
          setPeerCount(0);
          scheduleReconnect();
        };

        ws.onerror = () => {
          if (!isMountedRef.current) return;
          setStatus('offline');
          // Error triggers close or reconnect
        };
      } catch (err) {
        setStatus('offline');
        scheduleReconnect();
      }
    }

    function scheduleReconnect() {
      if (!isMountedRef.current) return;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      const delay = backoffDelayRef.current;
      backoffDelayRef.current = Math.min(delay * 2, 10000);
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, delay);
    }

    connect();

    return () => {
      isMountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.close();
      }
    };
  }, [relayUrl, enabled]);

  return {
    updates,
    sendUpdate,
    peerCount,
    status,
    cyberNodes,
    latestCyberAlert,
  };
}
