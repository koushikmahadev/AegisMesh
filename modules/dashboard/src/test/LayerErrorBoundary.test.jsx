import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import LayerErrorBoundary from '../features/map/LayerErrorBoundary.jsx';

function BrokenLayerComponent() {
  throw new Error('Simulated layer corruption error');
}

function HealthyLayerComponent() {
  return <div data-testid="healthy-layer">Healthy Map Layer Operating</div>;
}

describe('LayerErrorBoundary (T3.8 & FR-52)', () => {
  it('catches a deliberately broken layer, renders fallback, and isolates the crash', () => {
    // Suppress console.error in test output for intentional error
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const handleError = vi.fn();

    render(
      <div>
        <LayerErrorBoundary
          layerName="broken-flood"
          onError={handleError}
          fallback={<div role="alert">Layer failed: isolated warning</div>}
        >
          <BrokenLayerComponent />
        </LayerErrorBoundary>
        <HealthyLayerComponent />
      </div>
    );

    // Broken layer caught and fallback rendered
    expect(screen.getByRole('alert')).toHaveTextContent('Layer failed: isolated warning');
    expect(handleError).toHaveBeenCalledTimes(1);

    // Healthy layer in same container continues to render normally
    expect(screen.getByTestId('healthy-layer')).toBeInTheDocument();

    spy.mockRestore();
  });
});
