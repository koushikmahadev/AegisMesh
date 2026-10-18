/**
 * Capture screenshots for modules/dashboard at specified viewport widths
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

async function capture(url, width, height, filename) {
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
    const targetRes = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
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
    // Wait for Leaflet map, flyToBounds, and data to settle
    await sleep(4500);

    // Ensure page is positioned at the top to frame map and metrics
    try {
      await cdp.send('Runtime.evaluate', { expression: 'window.scrollTo(0, 0)' });
      await sleep(500);
    } catch {}

    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    const outPath = path.join(SCREENSHOT_DIR, filename);
    fs.writeFileSync(outPath, Buffer.from(shot.data, 'base64'));
    console.log(`Saved screenshot: ${outPath} (${width}x${height})`);
    return outPath;
  } finally {
    chromeProc.kill();
    await sleep(500);
  }
}

async function run() {
  const mode = process.argv[2] || 'tile_0_41_58'; // 'before' | 'after' | 'tile_0_41_58'
  if (mode === 'tile_0_41_58' || mode === 'tile' || mode === 'basemaps') {
    console.log('Capturing tile 0_41_58 Plate basemap screenshot at 1280px...');
    await capture('http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58&basemap=plate', 1280, 900, 'tile_0_41_58_plate.png');
    console.log('Capturing tile 0_41_58 Satellite basemap screenshot at 1280px...');
    await capture('http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58&basemap=satellite', 1280, 900, 'tile_0_41_58_satellite.png');
    console.log('Capture complete for both basemaps.');
    return;
  }
  console.log(`Capturing ${mode} screenshots...`);
  
  await capture('http://127.0.0.1:5173/', 1280, 900, `${mode}_1280px.png`);
  await capture('http://127.0.0.1:5173/', 390, 844, `${mode}_390px.png`);
  console.log('Capture complete.');
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
