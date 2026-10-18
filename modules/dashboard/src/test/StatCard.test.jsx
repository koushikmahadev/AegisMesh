import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import StatCard from '../components/StatCard.jsx';

describe('StatCard component', () => {
  it('renders numeric value, title, and unit', () => {
    render(<StatCard title="Inundated Area" value={12.4} unit="km²" isDemo={true} />);
    expect(screen.getByText('Inundated Area')).toBeInTheDocument();
    expect(screen.getByText('12.4')).toBeInTheDocument();
    expect(screen.getByText('km²')).toBeInTheDocument();
    expect(screen.getByText('Simulated')).toBeInTheDocument();
  });

  it('renders "Not available" when value is null (never 0)', () => {
    render(<StatCard title="Flooded Area" value={null} isDemo={true} />);
    expect(screen.getByText('Not available')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('renders "Not available" when value is undefined', () => {
    render(<StatCard title="Risk Score" value={undefined} isDemo={false} />);
    expect(screen.getByText('Not available')).toBeInTheDocument();
  });

  it('omits "Simulated" badge when isDemo is false', () => {
    render(<StatCard title="Sensor Health" value={98} isDemo={false} />);
    expect(screen.queryByText('Simulated')).not.toBeInTheDocument();
  });
});
