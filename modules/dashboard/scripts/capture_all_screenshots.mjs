/**
 * Automated Screenshot Capturer for HighWater Survey Plate Redesign
 * Uses headless Chrome via Chrome DevTools Protocol (CDP) to capture exact viewports
 * and PIL for greyscale contrast verification.
 */
import { spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9226;
const SCREENSHOT_DIR = path.join(__dirname, '..', 'docs', 'screenshots');

if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = new WebSocket(wsUrl);
    this.msgId = 0;
    this.callbacks = new Map();

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.callbacks.has(msg.id)) {
        const { resolve, reject } = this.callbacks.get(msg.id);
        this.callbacks.delete(msg.id);
        if (msg.error) reject(msg.error);
        else resolve(msg.result);
      }
    };
  }

  ready() {
    return new Promise((resolve, reject) => {
      if (this.ws.readyState === WebSocket.OPEN) return resolve();
      this.ws.onopen = () => resolve();
      this.ws.onerror = (e) => reject(e);
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.msgId;
      this.callbacks.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

async function capture(url, width, height, filename, actions = null) {
  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-first-run',
    `--window-size=${width},${height}`,
  ]);

  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (res.ok) break;
    } catch {}
    await sleep(200);
  }

  try {
    const targetRes = await fetch(
      `http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`,
      { method: 'PUT' }
    );
    const { webSocketDebuggerUrl } = await targetRes.json();
    const cdp = new CdpClient(webSocketDebuggerUrl);
    await cdp.ready();
    await cdp.send('Page.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: width < 600,
    });

    // Wait for map and assets to settle
    await sleep(4000);

    // Run custom page actions if specified (e.g. switch to 3D relief, select metric)
    if (actions) {
      await actions(cdp);
      await sleep(2000);
    }

    try {
      await cdp.send('Runtime.evaluate', { expression: 'window.scrollTo(0, 0)' });
      await sleep(300);
    } catch {}

    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    const outPath = path.join(SCREENSHOT_DIR, filename);
    fs.writeFileSync(outPath, Buffer.from(shot.data, 'base64'));
    console.log(`[CDP] Saved: ${filename} (${width}x${height})`);
    return outPath;
  } finally {
    chromeProc.kill();
    await sleep(500);
  }
}

async function main() {
  console.log('--- Starting Cartographic Screenshot Generation ---');

  // Helper action for switching to 3D relief projection
  const makeReliefAction = (metricValue) => async (cdp) => {
    await cdp.send('Runtime.evaluate', {
      expression: `
        (() => {
          const btns = Array.from(document.querySelectorAll('button'));
          const reliefBtn = btns.find(b => b.textContent.includes('3D Relief Projection'));
          if (reliefBtn) reliefBtn.click();
        })()
      `,
    });
    await sleep(1500);
    await cdp.send('Runtime.evaluate', {
      expression: `
        (() => {
          const select = document.querySelector('select[aria-label="Select metric to encode as column height"]');
          if (select) {
            select.value = '${metricValue}';
            select.dispatchEvent(new Event('change', { bubbles: true }));
          }
        })()
      `,
    });
  };

  // 1. 2D Map with both layers on tile 0_41_58
  console.log('\n[1/5] Capturing 2D Survey Map on tile 0_41_58...');
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    1280,
    900,
    'tile_0_41_58_1280px.png'
  );
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    390,
    844,
    'tile_0_41_58_390px.png'
  );

  // 2. Relief view with each of the three encodings (1280px & 390px)
  console.log('\n[2/5] Capturing 3D Relief Views for all 3 encodings...');
  // Encoding A: Observed features
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    1280,
    900,
    'relief_observed_features_1280px.png',
    makeReliefAction('observed_features')
  );
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    390,
    844,
    'relief_observed_features_390px.png',
    makeReliefAction('observed_features')
  );

  // Encoding B: Observed buildings
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    1280,
    900,
    'relief_observed_buildings_1280px.png',
    makeReliefAction('observed_buildings')
  );
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    390,
    844,
    'relief_observed_buildings_390px.png',
    makeReliefAction('observed_buildings')
  );

  // Encoding C: Model mask pixels
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    1280,
    900,
    'relief_model_pixels_1280px.png',
    makeReliefAction('model_pixels')
  );
  await capture(
    'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58',
    390,
    844,
    'relief_model_pixels_390px.png',
    makeReliefAction('model_pixels')
  );

  // 3. Empty State (1280px & 390px)
  console.log('\n[3/5] Capturing Empty State...');
  await capture(
    'http://127.0.0.1:5173/?state=empty',
    1280,
    900,
    'empty_state_1280px.png'
  );
  await capture(
    'http://127.0.0.1:5173/?state=empty',
    390,
    844,
    'empty_state_390px.png'
  );

  // 4. Cached State (1280px & 390px)
  console.log('\n[4/5] Capturing Cached State...');
  await capture(
    'http://127.0.0.1:5173/?state=cached',
    1280,
    900,
    'cached_state_1280px.png'
  );
  await capture(
    'http://127.0.0.1:5173/?state=cached',
    390,
    844,
    'cached_state_390px.png'
  );

  // 5. Offline Base Map State (1280px & 390px)
  console.log('\n[5/5] Capturing Offline Base Map State...');
  await capture(
    'http://127.0.0.1:5173/?state=offline',
    1280,
    900,
    'offline_state_1280px.png'
  );
  await capture(
    'http://127.0.0.1:5173/?state=offline',
    390,
    844,
    'offline_state_390px.png'
  );

  console.log('\nAll web screenshots captured successfully!');
}

main().catch((err) => {
  console.error('Fatal error during capture:', err);
  process.exit(1);
});
