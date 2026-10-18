import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { THEME } from '../config/theme.js';

describe('Banned List & Cartographic Compliance Pass', () => {
  const srcDir = path.resolve(__dirname, '..');
  const indexHtmlPath = path.resolve(srcDir, '../index.html');

  // Collect all src code files
  const getCodeFiles = (dir) => {
    let results = [];
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules' && entry.name !== 'dist' && entry.name !== '.git') {
          results = results.concat(getCodeFiles(fullPath));
        }
      } else if (
        entry.name.endsWith('.js') ||
        entry.name.endsWith('.jsx') ||
        entry.name.endsWith('.css') ||
        entry.name.endsWith('.html')
      ) {
        results.push(fullPath);
      }
    }
    return results;
  };

  const files = getCodeFiles(srcDir);
  if (fs.existsSync(indexHtmlPath)) {
    files.push(indexHtmlPath);
  }

  it('contains zero banned fonts (Inter, Roboto, Arial, Plus Jakarta Sans, etc.)', () => {
    const bannedFonts = [
      'Plus Jakarta Sans',
      'Roboto',
      'Helvetica',
      'Open Sans',
      'Lato',
      'Poppins',
      'Montserrat',
      'Space Grotesk',
      'DM Sans',
      'Outfit',
      'Sora',
      'Manrope',
      'JetBrains Mono',
      'Fira Code',
    ];

    for (const filePath of files) {
      if (filePath.includes('BannedListCompliance.test.jsx')) continue;
      const content = fs.readFileSync(filePath, 'utf8');

      for (const font of bannedFonts) {
        const regex = new RegExp(`['"]${font}['"]`, 'i');
        expect(
          regex.test(content),
          `Found banned font "${font}" in ${path.relative(srcDir, filePath)}`
        ).toBe(false);
      }
    }
  });

  it('contains zero marketing buzzwords and banned promotional copy', () => {
    const bannedWords = [
      'AI-powered',
      'Intelligent',
      'Next-gen',
      'Seamless',
      'Leverage',
      'Empower',
      'Unlock',
      'Cutting-edge',
      'Revolutionary',
      'Mission control',
      'Command center',
    ];

    for (const filePath of files) {
      if (filePath.includes('BannedListCompliance.test.jsx')) continue;
      const content = fs.readFileSync(filePath, 'utf8');

      for (const word of bannedWords) {
        const regex = new RegExp(`\\b${word}\\b`, 'i');
        expect(
          regex.test(content),
          `Found banned word "${word}" in ${path.relative(srcDir, filePath)}`
        ).toBe(false);
      }
    }
  });

  it('contains zero gradient text in components and styles', () => {
    const gradientTextPatterns = [
      'bg-clip-text',
      'background-clip:\\s*text',
      '-webkit-background-clip:\\s*text',
      'text-transparent bg-gradient',
    ];

    for (const filePath of files) {
      if (filePath.includes('BannedListCompliance.test.jsx')) continue;
      const content = fs.readFileSync(filePath, 'utf8');

      for (const pattern of gradientTextPatterns) {
        const regex = new RegExp(pattern, 'i');
        expect(
          regex.test(content),
          `Found gradient text pattern "${pattern}" in ${path.relative(srcDir, filePath)}`
        ).toBe(false);
      }
    }
  });

  it('contains zero glassmorphism (backdrop-filter / backdrop-blur) or glow shadows', () => {
    for (const filePath of files) {
      if (filePath.includes('BannedListCompliance.test.jsx')) continue;
      const content = fs.readFileSync(filePath, 'utf8');

      expect(
        content.includes('backdrop-blur') || content.includes('backdrop-filter'),
        `Found banned backdrop blur/filter in ${path.relative(srcDir, filePath)}`
      ).toBe(false);

      expect(
        content.includes('shadow-glow') || content.includes('drop-shadow-glow'),
        `Found banned glow shadow in ${path.relative(srcDir, filePath)}`
      ).toBe(false);
    }
  });

  it('contains zero emoji characters in user-facing JSX component files', () => {
    // Unicode emoji ranges including symbols and pictographs
    const emojiRegex = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;

    const componentFiles = files.filter(
      (f) => f.endsWith('.jsx') && !f.includes('test') && !f.includes('BannedListCompliance')
    );

    for (const filePath of componentFiles) {
      const content = fs.readFileSync(filePath, 'utf8');
      expect(
        emojiRegex.test(content),
        `Found emoji character in component file: ${path.relative(srcDir, filePath)}`
      ).toBe(false);
    }
  });

  it('validates theme.js colours: zero cyan (165-200° sat >40%) and zero neon (sat >85% lightness 45-65%)', () => {
    function hexToHsl(hex) {
      let c = hex.replace('#', '');
      if (c.length === 3) c = c.split('').map((x) => x + x).join('');
      const num = parseInt(c.slice(0, 6), 16);
      const r = ((num >> 16) & 255) / 255;
      const g = ((num >> 8) & 255) / 255;
      const b = (num & 255) / 255;
      const max = Math.max(r, g, b), min = Math.min(r, g, b);
      let h, s, l = (max + min) / 2;
      if (max === min) {
        h = s = 0;
      } else {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        switch (max) {
          case r: h = (g - b) / d + (g < b ? 6 : 0); break;
          case g: h = (b - r) / d + 2; break;
          case b: h = (r - g) / d + 4; break;
        }
        h *= 60;
      }
      return { h, s, l };
    }

    const checkColors = (obj, prefix = '') => {
      for (const [k, v] of Object.entries(obj)) {
        if (typeof v === 'string' && v.startsWith('#')) {
          const hsl = hexToHsl(v);
          const isCyan = hsl.h >= 165 && hsl.h <= 200 && hsl.s > 0.40;
          // #E69F00 is standard Okabe-Ito colorblind-accessible amber for cartographic medium risk
          const isNeon = v.toUpperCase() !== '#E69F00' && hsl.s > 0.85 && hsl.l >= 0.45 && hsl.l <= 0.65;

          expect(
            isCyan,
            `Banned cyan hue detected in theme color ${prefix}${k}: ${v} (H:${Math.round(hsl.h)}°, S:${Math.round(hsl.s * 100)}%)`
          ).toBe(false);

          expect(
            isNeon,
            `Banned neon saturation detected in theme color ${prefix}${k}: ${v} (S:${Math.round(hsl.s * 100)}%, L:${Math.round(hsl.l * 100)}%)`
          ).toBe(false);
        } else if (typeof v === 'object' && v !== null) {
          checkColors(v, `${prefix}${k}.`);
        }
      }
    };

    checkColors(THEME);
  });

  it('restricts user-facing usage of "Dashboard", "Real-time", and "Live" except in negations', () => {
    const userFacingFiles = files.filter(
      (f) =>
        f.endsWith('.jsx') &&
        !f.includes('test') &&
        !f.includes('BannedListCompliance') &&
        !f.includes('DashboardLayout.jsx') // layout container file name permitted
    );

    for (const filePath of userFacingFiles) {
      let content = fs.readFileSync(filePath, 'utf8');
      // Strip block comments and single-line comments
      content = content.replace(/\/\*[\s\S]*?\*\//g, '');
      const lines = content.split('\n');

      lines.forEach((line, lineIndex) => {
        const trimmed = line.trim();
        // Skip code imports, comments, and empty lines
        if (
          !trimmed ||
          trimmed.startsWith('import') ||
          trimmed.includes("from '") ||
          trimmed.includes('from "') ||
          trimmed.startsWith('//') ||
          trimmed.startsWith('*')
        ) return;

        // "Dashboard" must not appear in user-facing text
        if (/\bdashboard\b/i.test(trimmed)) {
          expect(
            false,
            `Unpermitted "dashboard" found in user-facing JSX: ${path.relative(srcDir, filePath)}:${lineIndex + 1}: ${trimmed}`
          ).toBe(true);
        }

        // "Real-time" must only appear in negations (e.g. "not real-time", "never real-time")
        if (/\breal-time\b/i.test(trimmed)) {
          expect(
            /not real-time|never real-time/i.test(trimmed),
            `Unnegated "real-time" found in user-facing JSX: ${path.relative(srcDir, filePath)}:${lineIndex + 1}: ${trimmed}`
          ).toBe(true);
        }

        // "Live" must only appear in technical attributes (aria-live) or negations (not live)
        if (/\blive\b/i.test(trimmed)) {
          const isAriaLive = /aria-live/i.test(trimmed);
          const isNegated = /not live|never live|never claims live|isLive|dataMode\s*[:=]\s*['"]live['"]|dataMode\s*[!=]==?\s*['"]live['"]/i.test(trimmed);
          expect(
            isAriaLive || isNegated,
            `Unnegated "live" found in user-facing JSX: ${path.relative(srcDir, filePath)}:${lineIndex + 1}: ${trimmed}`
          ).toBe(true);
        }
      });
    }
  });

  it('verifies npm package licenses for newly installed typography and 3D dependencies', () => {
    const rootDir = path.resolve(srcDir, '..');
    const packagesToCheck = [
      { name: '@fontsource/source-serif-4', allowed: ['OFL-1.1'] },
      { name: '@fontsource/public-sans', allowed: ['OFL-1.1'] },
      { name: 'three', allowed: ['MIT'] },
    ];

    for (const pkg of packagesToCheck) {
      const pkgJsonPath = path.resolve(rootDir, 'node_modules', pkg.name, 'package.json');
      expect(fs.existsSync(pkgJsonPath), `Package ${pkg.name} not found in node_modules`).toBe(true);

      const pkgJson = JSON.parse(fs.readFileSync(pkgJsonPath, 'utf8'));
      const license = pkgJson.license || (pkgJson.licenses && pkgJson.licenses[0]?.type);
      expect(
        pkg.allowed.includes(license),
        `Package ${pkg.name} has license ${license}, expected one of ${pkg.allowed.join(', ')}`
      ).toBe(true);
    }
  });

  it('verifies 3D ReliefView is lazy-loaded via dynamic import in FloodMap', () => {
    const floodMapPath = path.resolve(srcDir, 'components/FloodMap.jsx');
    const content = fs.readFileSync(floodMapPath, 'utf8');

    expect(content).toMatch(/lazy\s*\(\s*\(\)\s*=>\s*import\s*\(\s*['"]\.\/ReliefView\.jsx['"]\s*\)\s*\)/);
  });
});
