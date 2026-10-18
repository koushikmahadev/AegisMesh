/**
 * Design tokens for HighWater Dashboard
 * All colours, typography, spacing, and risk mappings live here.
 * As per rules.md: No hex codes outside theme.js and index.css.
 */

export const THEME = {
  colors: {
    // Survey plate paper and ink foundations
    paper: '#F6F3ED',
    plate: '#FCFAF6',
    surface: '#F6F3ED',
    card: '#FCFAF6',
    ink: '#1C1917',
    text: '#1C1917',
    inkMuted: '#57534E',
    'text-muted': '#57534E',
    hairline: '#DCD6CA',
    border: '#DCD6CA',
    controlBorder: '#78716C', // 3.3:1 contrast against paper for interactive boundaries

    // Cartographic Title Block Ink
    'navy-900': '#1C1917',
    'navy-700': '#292524',

    // Core Survey Roles
    observed: '#9A3412', // Burnt sienna (6.2:1 contrast against paper)
    observedBorder: '#7C2D12',
    derived: '#1E3A8A', // Deep cartographic indigo (9.5:1 contrast against paper)
    derivedBorder: '#172554',

    // Layer styles
    flood: '#1E3A8A',
    floodBorder: '#172554',
    shelter: '#1E3A8A',
    route: '#581C87',
    selected: '#1C1917',
    buildingFlooded: '#9A3412',
    buildingFloodedBorder: '#7C2D12',
    floodwatchObservedBuilding: '#9A3412',
    floodwatchObservedBuildingBorder: '#7C2D12',
    floodwatchObservedRoad: '#C2410C',
    floodwatchObservedRoadBorder: '#9A3412',
    floodwatchPredicted: '#1E3A8A',
    floodwatchPredictedBorder: '#172554',

    // Operational notices (Muted ochre: 5.8:1 contrast against paper)
    notice: '#854D0E',
    noticeBg: '#FEF3C7',
    noticeBorder: '#D97706',
    demo: {
      text: '#854D0E',
      specText: '#854D0E',
      bg: '#FEF3C7',
    },

    // Risk levels in cartographic inks (all WCAG AA)
    'risk-critical': '#7F1D1D',
    'risk-high': '#C62828',
    'risk-medium': '#E69F00',
    'risk-low': '#2E7D32',
    'risk-unknown': '#6B7280',
  },
  typography: {
    fontFamily: {
      serif: ['"Source Serif 4"', 'Georgia', 'serif'],
      sans: ['"Public Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      mono: ['"Public Sans"', 'monospace'],
    },
    fontSize: {
      title: '18px',
      heading: '16px',
      stat: '28px',
      body: '14px',
      caption: '12px',
    },
  },
  spacing: {
    1: '4px',
    2: '8px',
    3: '12px',
    4: '16px',
    6: '24px',
    8: '32px',
  },
  borderRadius: {
    card: '2px', // Cartographic sharp plates
    badge: '2px',
  },
  riskColors: {
    CRITICAL: '#7F1D1D',
    HIGH: '#C62828',
    MEDIUM: '#E69F00',
    LOW: '#2E7D32',
    UNKNOWN: '#6B7280',
  },
};

export const colors = THEME.colors;
export const riskColors = THEME.riskColors;
export default THEME;
