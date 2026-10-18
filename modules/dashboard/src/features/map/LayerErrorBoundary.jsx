import React from 'react';

/**
 * LayerErrorBoundary
 * Isolates runtime crashes within individual map layers (FR-52, T3.8).
 * Ensures a malformed or broken layer does not crash the Leaflet base map or other layers.
 */
export class LayerErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error(`[LayerErrorBoundary] Error in layer "${this.props.layerName || 'unknown'}":`, error, errorInfo);
    if (this.props.onError) {
      this.props.onError(error);
    }
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return null;
    }

    return this.props.children;
  }
}

export default LayerErrorBoundary;
