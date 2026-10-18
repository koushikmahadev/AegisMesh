import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import AegisForensicDrawer from '../components/AegisForensicDrawer.jsx';

describe('AegisForensicDrawer Component', () => {
  const mockNode = {
    id: 'DRONE-RELAY-01',
    name: 'Drone Relay Alpha',
    type: 'drone',
    ip: '192.168.10.101',
    status: 'COMPROMISED',
    alert_tier: 'CRITICAL',
    spectral_lambda2: 0.118,
    mahalanobis_residual: 4.92,
    fused_risk: 0.892,
    soar_action: 'iptables -A INPUT -s 18.218.115.60 -j DROP',
  };

  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <AegisForensicDrawer node={mockNode} isOpen={false} onClose={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders forensic telemetry, spectral metrics, and SOAR rule when open', () => {
    render(
      <AegisForensicDrawer node={mockNode} isOpen={true} onClose={() => {}} />
    );

    expect(screen.getByText('Drone Relay Alpha')).toBeInTheDocument();
    expect(screen.getByText('192.168.10.101')).toBeInTheDocument();
    expect(screen.getByText('0.118')).toBeInTheDocument();
    expect(screen.getByText('4.92')).toBeInTheDocument();
    expect(screen.getByText('89.2%')).toBeInTheDocument();
    expect(screen.getByText('iptables -A INPUT -s 18.218.115.60 -j DROP')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', () => {
    const handleClose = vi.fn();
    render(
      <AegisForensicDrawer node={mockNode} isOpen={true} onClose={handleClose} />
    );

    const closeBtn = screen.getByRole('button', { name: /close forensic console/i });
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);
  });
});
