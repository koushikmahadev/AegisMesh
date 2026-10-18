import { THEME } from './src/config/theme.js';

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx}',
  ],
  theme: {
    extend: {
      colors: {
        paper: THEME.colors.paper,
        plate: THEME.colors.plate,
        ink: THEME.colors.ink,
        'ink-muted': THEME.colors.inkMuted,
        hairline: THEME.colors.hairline,
        'control-border': THEME.colors.controlBorder,
        observed: THEME.colors.observed,
        derived: THEME.colors.derived,
        notice: THEME.colors.notice,
        'navy-900': THEME.colors['navy-900'],
        'navy-700': THEME.colors['navy-700'],
        surface: THEME.colors.surface,
        card: THEME.colors.card,
        border: THEME.colors.border,
        text: THEME.colors.text,
        'text-muted': THEME.colors['text-muted'],
        flood: THEME.colors.flood,
        'risk-high': THEME.colors['risk-high'],
        'risk-medium': THEME.colors['risk-medium'],
        'risk-low': THEME.colors['risk-low'],
        'risk-unknown': THEME.colors['risk-unknown'],
        route: THEME.colors.route,
        selected: THEME.colors.selected,
        'demo-text': THEME.colors.demo.text,
        'demo-bg': THEME.colors.demo.bg,
      },
      fontFamily: {
        serif: THEME.typography.fontFamily.serif,
        sans: THEME.typography.fontFamily.sans,
        mono: THEME.typography.fontFamily.mono,
      },
      fontSize: {
        title: THEME.typography.fontSize.title,
        heading: THEME.typography.fontSize.heading,
        stat: THEME.typography.fontSize.stat,
        body: THEME.typography.fontSize.body,
        caption: THEME.typography.fontSize.caption,
      },
      borderRadius: {
        card: THEME.borderRadius.card,
        badge: THEME.borderRadius.badge,
      },
    },
  },
  plugins: [],
};
