import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import React from 'react';
import { useMeshSync } from '../hooks/useMeshSync.js';
import ZoneDetails from '../components/ZoneDetails.jsx';
import Header from '../components/Header.jsx';

// Mock WebSocket implementation for network-free isolated Vitest runs
class MockWebSocket {
  static instances = [];
  static OPEN = 1;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.sent = [];
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    MockWebSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({ code: 1000, reason: 'Normal Closure' });
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen({});
  }

  receive(data) {
    if (this.onmessage) {
      this.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) });
    }
  }

  error() {
    if (this.onerror) this.onerror(new Error('Simulated socket error'));
  }
}

describe('Mesh Sync Unit & Component Test Suite', () => {
  let originalWebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    originalWebSocket = global.WebSocket;
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    vi.restoreAllMocks();
  });

  describe('useMeshSync hook', () => {
    it('handles initial list received on connect', () => {
      const { result } = renderHook(() => useMeshSync({ url: 'ws://localhost:8787' }));
      const ws = MockWebSocket.instances[0];
      expect(ws).toBeDefined();

      act(() => {
        ws.open();
        ws.receive({
          type: 'init',
          updates: [
            { id: 'u1', zoneId: 'z1', surveyStatus: 'flooded', note: 'Water knee high', author: 'Observer A' },
            { id: 'u2', zoneId: 'z2', surveyStatus: 'clear', note: 'Road dry', author: 'Observer B' },
          ],
        });
      });

      expect(result.current.updates).toHaveLength(2);
      expect(result.current.updates[0].id).toBe('u1');
      expect(result.current.updates[1].id).toBe('u2');
    });

    it('receives broadcast update and appends to updates list', () => {
      const { result } = renderHook(() => useMeshSync({ url: 'ws://localhost:8787' }));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws.open();
        ws.receive({
          type: 'update',
          update: { id: 'u3', zoneId: 'z1', surveyStatus: 'unsure', note: 'Water receded slightly' },
        });
      });

      expect(result.current.updates).toHaveLength(1);
      expect(result.current.updates[0].id).toBe('u3');
    });

    it('sends update via sendUpdate when socket is open', () => {
      const { result } = renderHook(() => useMeshSync({ url: 'ws://localhost:8787' }));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws.open();
      });

      let sent;
      act(() => {
        sent = result.current.sendUpdate({
          zoneId: 'z-99',
          surveyStatus: 'flooded',
          note: 'Culvert clogged',
          author: 'Field Scout',
        });
      });

      expect(sent).toBeDefined();
      expect(sent.provenance).toBe('observed');
      expect(ws.sent).toHaveLength(1);
      const payload = JSON.parse(ws.sent[0]);
      expect(payload.type).toBe('update');
      expect(payload.update.zoneId).toBe('z-99');
      expect(payload.update.note).toBe('Culvert clogged');
    });

    it('queues updates made while offline and flushes on reconnect', () => {
      const { result } = renderHook(() => useMeshSync({ url: 'ws://localhost:8787' }));
      const ws = MockWebSocket.instances[0];

      // While socket is connecting / offline:
      act(() => {
        result.current.sendUpdate({
          id: 'queued-1',
          zoneId: 'z-offline',
          surveyStatus: 'clear',
          note: 'Bridge inspected and safe',
        });
      });

      // Nothing sent yet because socket was not open
      expect(ws.sent).toHaveLength(0);

      // Now socket opens -> queue flushes
      act(() => {
        ws.open();
      });

      expect(ws.sent).toHaveLength(1);
      const flushed = JSON.parse(ws.sent[0]);
      expect(flushed.update.id).toBe('queued-1');
      expect(flushed.update.note).toBe('Bridge inspected and safe');
    });

    it('ignores duplicate updates by id', () => {
      const { result } = renderHook(() => useMeshSync({ url: 'ws://localhost:8787' }));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws.open();
        ws.receive({
          type: 'update',
          update: { id: 'dup-1', zoneId: 'z1', surveyStatus: 'flooded', note: 'First arrival' },
        });
      });

      expect(result.current.updates).toHaveLength(1);

      // Duplicate arrival
      act(() => {
        ws.receive({
          type: 'update',
          update: { id: 'dup-1', zoneId: 'z1', surveyStatus: 'flooded', note: 'Duplicate message' },
        });
      });

      expect(result.current.updates).toHaveLength(1);
      expect(result.current.updates[0].note).toBe('First arrival');
    });

    it('tracks status and peerCount transitions correctly', () => {
      const { result } = renderHook(() => useMeshSync({ url: 'ws://localhost:8787' }));
      const ws = MockWebSocket.instances[0];

      expect(result.current.status).toBe('connecting');
      expect(result.current.peerCount).toBe(0);

      act(() => {
        ws.open();
      });
      expect(result.current.status).toBe('active');

      act(() => {
        ws.receive({ type: 'peer_count', count: 5 });
      });
      expect(result.current.peerCount).toBe(5);

      act(() => {
        ws.close();
      });
      expect(result.current.status).toBe('offline');
      expect(result.current.peerCount).toBe(0);
    });
  });

  describe('ZoneDetails component survey integration', () => {
    const testZone = {
      zoneId: 'zone-alpha',
      name: 'Alpha Sector',
      riskLevel: 'HIGH',
      riskScore: 88,
      floodedAreaKm2: 3.2,
      floodedPercent: 45,
      exposedBuildings: 20,
      accessibility: 'LIMITED',
      reasons: ['Flood overflow'],
      hasGeometry: true,
    };

    it('shows updates only for the selected zone', () => {
      const meshUpdates = [
        {
          id: 'u-alpha',
          zoneId: 'zone-alpha',
          surveyStatus: 'flooded',
          note: 'Water 50cm deep at main crossing',
          author: 'Unit 1',
          createdAt: '2026-10-15T12:00:00Z',
          provenance: 'observed',
        },
        {
          id: 'u-beta',
          zoneId: 'zone-beta',
          surveyStatus: 'clear',
          note: 'Beta sector completely dry',
          author: 'Unit 2',
          createdAt: '2026-10-15T12:05:00Z',
          provenance: 'observed',
        },
      ];

      render(
        <ZoneDetails
          zone={testZone}
          meshUpdates={meshUpdates}
          onSendSurveyUpdate={vi.fn()}
        />
      );

      // Alpha update visible
      expect(screen.getByText('Water 50cm deep at main crossing')).toBeInTheDocument();
      expect(screen.getByText('Unit 1')).toBeInTheDocument();

      // Beta update must NOT appear
      expect(screen.queryByText('Beta sector completely dry')).not.toBeInTheDocument();
      expect(screen.queryByText('Unit 2')).not.toBeInTheDocument();
    });

    it('rejects empty and over-280-character notes', () => {
      const handleSend = vi.fn();
      render(
        <ZoneDetails
          zone={testZone}
          meshUpdates={[]}
          onSendSurveyUpdate={handleSend}
        />
      );

      const submitBtn = screen.getByRole('button', { name: /submit field survey/i });
      const noteInput = screen.getByLabelText(/observation note/i);

      // 1. Submit empty note
      fireEvent.change(noteInput, { target: { value: '   ' } });
      fireEvent.click(submitBtn);

      expect(handleSend).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(/cannot be empty/i);

      // 2. Submit over 280 characters
      const longNote = 'A'.repeat(281);
      fireEvent.change(noteInput, { target: { value: longNote } });
      fireEvent.click(submitBtn);

      expect(handleSend).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(/exceeds 280 characters/i);

      // 3. Valid note succeeds
      fireEvent.change(noteInput, { target: { value: 'Valid observation note.' } });
      fireEvent.click(submitBtn);

      expect(handleSend).toHaveBeenCalledTimes(1);
      expect(handleSend).toHaveBeenCalledWith(
        expect.objectContaining({
          zoneId: 'zone-alpha',
          note: 'Valid observation note.',
          surveyStatus: 'flooded',
        })
      );
    });

    it('form has accessible labels and visible focus', () => {
      render(
        <ZoneDetails
          zone={testZone}
          meshUpdates={[]}
          onSendSurveyUpdate={vi.fn()}
        />
      );

      const statusSelect = screen.getByLabelText(/survey status/i);
      const noteInput = screen.getByLabelText(/observation note/i);
      const authorInput = screen.getByLabelText(/author/i);

      expect(statusSelect).toBeInTheDocument();
      expect(noteInput).toBeInTheDocument();
      expect(authorInput).toBeInTheDocument();

      // Verify focus rings are present
      expect(noteInput).toHaveClass('focus:ring-2');
      expect(statusSelect).toHaveClass('focus:ring-2');
      expect(authorInput).toHaveClass('focus:ring-2');
    });
  });

  describe('Header badge', () => {
    it('renders "Mesh active - N peers connected" with aria-live="polite"', () => {
      render(<Header meshStatus="active" meshPeerCount={4} />);

      const badge = screen.getByText('Mesh active - 4 peers connected');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute('aria-live', 'polite');
    });

    it('renders "Mesh offline" with aria-live="polite" when offline', () => {
      render(<Header meshStatus="offline" meshPeerCount={0} />);

      const badge = screen.getByText('Mesh offline');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute('aria-live', 'polite');
    });
  });

  describe('Data immutability & Risk score protection', () => {
    it('proves a mesh update does not change any zone risk level or score', () => {
      const originalZone = Object.freeze({
        zoneId: 'immutable-zone-1',
        name: 'Protection Sector',
        riskLevel: 'HIGH',
        riskScore: 79,
        floodedAreaKm2: 1.8,
        floodedPercent: 30,
        exposedBuildings: 12,
        accessibility: 'OPEN',
        reasons: ['Baseline reason'],
        hasGeometry: true,
      });

      // A mesh update declaring the zone "clear"
      const clearMeshUpdate = {
        id: 'mesh-survey-99',
        zoneId: 'immutable-zone-1',
        surveyStatus: 'clear',
        note: 'Ground survey notes clear waters',
        author: 'Field Scout',
        createdAt: '2026-10-15T12:30:00Z',
        provenance: 'observed',
      };

      const { container } = render(
        <ZoneDetails
          zone={originalZone}
          meshUpdates={[clearMeshUpdate]}
          onSendSurveyUpdate={vi.fn()}
        />
      );

      // Verify Priority Score remains 79 / 100
      expect(screen.getByText('79 / 100')).toBeInTheDocument();
      expect(originalZone.riskScore).toBe(79);

      // Verify Risk Badge remains HIGH
      expect(screen.getByText('HIGH')).toBeInTheDocument();
      expect(originalZone.riskLevel).toBe('HIGH');

      // Verify the field survey note is present in the Field survey section
      expect(screen.getByText('Ground survey notes clear waters')).toBeInTheDocument();
      expect(screen.getAllByText('Clear').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Cyber Mesh & Aegis Security Sync', () => {
    it('initializes with default cyber nodes and updates upon receiving cyber_mesh_init', () => {
      const { result } = renderHook(() => useMeshSync({ enabled: true }));
      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.open();
      });

      expect(result.current.cyberNodes.length).toBeGreaterThanOrEqual(1);

      const incomingNodes = [
        {
          id: 'DRONE-RELAY-01',
          name: 'Drone Relay Alpha',
          ip: '192.168.10.101',
          status: 'HEALTHY',
          spectral_lambda2: 0.88,
          lat: 50.53,
          lng: 7.04,
        },
      ];

      act(() => {
        ws.receive({ type: 'cyber_mesh_init', nodes: incomingNodes });
      });

      expect(result.current.cyberNodes).toHaveLength(1);
      expect(result.current.cyberNodes[0].id).toBe('DRONE-RELAY-01');
    });

    it('updates node state and sets latestCyberAlert upon receiving cyber_mesh_update', () => {
      const { result } = renderHook(() => useMeshSync({ enabled: true }));
      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.open();
      });

      const alertEvent = {
        node_id: 'DRONE-RELAY-01',
        ip: '192.168.10.101',
        status: 'COMPROMISED',
        alert_tier: 'CRITICAL',
        spectral_lambda2: 0.12,
        soar_action: 'ISOLATE_INTERFACE',
      };

      act(() => {
        ws.receive({ type: 'cyber_mesh_update', event: alertEvent });
      });

      expect(result.current.latestCyberAlert).toEqual(alertEvent);
      const updatedNode = result.current.cyberNodes.find((n) => n.id === 'DRONE-RELAY-01');
      expect(updatedNode.status).toBe('COMPROMISED');
      expect(updatedNode.spectral_lambda2).toBe(0.12);
    });
  });
});
