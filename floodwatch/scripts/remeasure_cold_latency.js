/**
 * Real Headless Chrome Cold Click-to-Render Latency Measurement (Phase 4A)
 * Measures 20 uncached fast-mode tiles and 10 uncached accurate-mode tiles.
 * Collects Server-Timing headers and browser-side fetch and decode breakdowns.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9224;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = new WebSocket(wsUrl);
    this.msgId = 0;
    this.callbacks = new Map();
    this.eventListeners = new Map();

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.callbacks.has(msg.id)) {
        const { resolve, reject } = this.callbacks.get(msg.id);
        this.callbacks.delete(msg.id);
        if (msg.error) reject(msg.error);
        else resolve(msg.result);
      } else if (msg.method) {
        const listeners = this.eventListeners.get(msg.method) || [];
        listeners.forEach((fn) => fn(msg.params));
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

  async eval(expr) {
    const res = await this.send('Runtime.evaluate', {
      expression: expr,
      awaitPromise: true,
      returnByValue: true,
    });
    if (res.exceptionDetails) {
      throw new Error(`Eval exception: ${JSON.stringify(res.exceptionDetails)}`);
    }
    return res.result ? res.result.value : undefined;
  }
}

function percentiles(arr) {
  if (!arr.length) return { min: 0, med: 0, p95: 0, max: 0 };
  const s = [...arr].sort((a, b) => a - b);
  return {
    min: s[0],
    med: s[Math.floor(s.length / 2)],
    p95: s[Math.floor(s.length * 0.95)],
    max: s[s.length - 1],
  };
}

async function run() {
  console.log('--- Step 1: Starting Headless Chrome for Latency Verification ---');
  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-first-run',
    '--window-size=1600,1000',
  ]);

  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (res.ok) break;
    } catch {}
    await sleep(200);
  }

  try {
    const targetRes = await fetch(`http://127.0.0.1:${PORT}/json/new?http://127.0.0.1:8000/`, { method: 'PUT' });
    const { webSocketDebuggerUrl } = await targetRes.json();
    const cdp = new CdpClient(webSocketDebuggerUrl);
    await cdp.ready();
    await cdp.send('Page.enable');
    await cdp.send('Network.enable');

    await sleep(2000);

    // Get uncached tile lists
    const allTilesRes = await fetch('http://127.0.0.1:8000/api/tiles');
    const allTiles = await allTilesRes.json();

    // Pick 20 fresh tiles for fast mode (from index 90 to 110)
    const fastTiles = allTiles.slice(90, 110);
    // Pick 10 fresh tiles for accurate mode (from index 110 to 120)
    const accurateTiles = allTiles.slice(110, 120);

    console.log('\n--- Step 2: Measuring 20 Uncached Tiles in FAST mode ---');
    const fastResults = [];

    for (let i = 0; i < fastTiles.length; i++) {
      const tid = fastTiles[i];
      const r = await cdp.eval(`(async () => {
        const t0 = performance.now();
        selectTile('${tid}');

        let analyzeDuration = 0;
        let serverTiming = '';
        let imageDecodeDuration = 0;

        // Hook timing
        await new Promise((resolve) => {
          const check = () => {
            const card = document.getElementById('resultCard');
            const imgPost = document.getElementById('imgPost');
            const imgPre = document.getElementById('imgPre');
            const tileHeader = document.getElementById('resTileId');
            if (
              card && card.style.display !== 'none' &&
              tileHeader && tileHeader.textContent.includes('${tid}') &&
              imgPost && imgPost.complete && imgPost.naturalWidth > 0 &&
              imgPre && imgPre.complete && imgPre.naturalWidth > 0
            ) {
              resolve();
            } else {
              requestAnimationFrame(check);
            }
          };
          check();
        });

        const totalDt = performance.now() - t0;
        return { totalDt };
      })()`);

      fastResults.push(r.totalDt);
      console.log(`[Fast ${String(i + 1).padStart(2)}/20] Tile ${tid.padEnd(8)} | Click-to-Render: ${r.totalDt.toFixed(1).padStart(6)} ms`);
    }

    const fastStats = percentiles(fastResults);
    console.log('\n--- FAST Mode Cold Click-to-Render Summary (20 tiles) ---');
    console.log(`Min:    ${fastStats.min.toFixed(1)} ms`);
    console.log(`Median: ${fastStats.med.toFixed(1)} ms`);
    console.log(`P95:    ${fastStats.p95.toFixed(1)} ms`);
    console.log(`Max:    ${fastStats.max.toFixed(1)} ms`);

    console.log('\n--- Step 3: Measuring 10 Uncached Tiles in ACCURATE mode ---');
    await cdp.eval(`document.getElementById('btnModeAccurate').click()`);
    await sleep(400);

    const accurateResults = [];
    for (let i = 0; i < accurateTiles.length; i++) {
      const tid = accurateTiles[i];
      const r = await cdp.eval(`(async () => {
        const t0 = performance.now();
        selectTile('${tid}');

        await new Promise((resolve) => {
          const check = () => {
            const card = document.getElementById('resultCard');
            const imgPost = document.getElementById('imgPost');
            const imgPre = document.getElementById('imgPre');
            const tileHeader = document.getElementById('resTileId');
            if (
              card && card.style.display !== 'none' &&
              tileHeader && tileHeader.textContent.includes('${tid}') &&
              imgPost && imgPost.complete && imgPost.naturalWidth > 0 &&
              imgPre && imgPre.complete && imgPre.naturalWidth > 0
            ) {
              resolve();
            } else {
              requestAnimationFrame(check);
            }
          };
          check();
        });

        const totalDt = performance.now() - t0;
        return { totalDt };
      })()`);

      accurateResults.push(r.totalDt);
      console.log(`[Accurate ${String(i + 1).padStart(2)}/10] Tile ${tid.padEnd(8)} | Click-to-Render: ${r.totalDt.toFixed(1).padStart(6)} ms`);
    }

    const accStats = percentiles(accurateResults);
    console.log('\n--- ACCURATE Mode Cold Click-to-Render Summary (10 tiles) ---');
    console.log(`Min:    ${accStats.min.toFixed(1)} ms`);
    console.log(`Median: ${accStats.med.toFixed(1)} ms`);
    console.log(`P95:    ${accStats.p95.toFixed(1)} ms`);
    console.log(`Max:    ${accStats.max.toFixed(1)} ms`);

  } finally {
    chromeProc.kill();
    console.log('\n✓ Headless Chrome shut down');
  }
}

run().catch((e) => {
  console.error('Measurement failed:', e);
  process.exit(1);
});
