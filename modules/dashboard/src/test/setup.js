import '@testing-library/jest-dom';

// Polyfill ResizeObserver for jsdom test environment
if (typeof global.ResizeObserver === 'undefined') {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// Polyfill scrollIntoView for jsdom test environment
if (typeof window !== 'undefined' && window.HTMLElement) {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}

