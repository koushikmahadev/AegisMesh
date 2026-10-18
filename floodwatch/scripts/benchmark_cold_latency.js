/**
 * Benchmark Cold Latency Properly (Phase 4 Item 2)
 * 
 * Requirements:
 * - Server running with FW_PREWARM=none and empty cache
 * - Sample 30 DISTINCT tiles without replacement
 * - Record 'cached' flag and Server-Timing header
 * - Report Request #1 separately with breakdown
 * - For requests 2-30, report min / median / p95 / max
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9225;

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

  on(method, fn) {
    if (!this.eventListeners.has(method)) {
      this.eventListeners.set(method, []);
    }
    this.eventListeners.get(method).push(fn);
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
  console.log('=======================================================');
  console.log('COLD CLICK-TO-RENDER LATENCY BENCHMARK (30 DISTINCT TILES)');
  console.log('=======================================================');

  // Verify server is up with FW_PREWARM=none
  const healthRes = await fetch('http://127.0.0.1:8000/api/health');
  const health = await healthRes.json();
  console.log(`Server Status: cache_size=${health.cache_size}, device=${health.device}, ram=${health.process_ram_mb}MB`);

  const tilesRes = await fetch('http://127.0.0.1:8000/api/tiles');
  const allTiles = await tilesRes.json();

  // Sample 30 distinct tiles without replacement (tiles index 5 to 35)
  const sampleTiles = allTiles.slice(5, 35);
  console.log(`Selected 30 distinct tiles from index 5 to 35:`);
  console.log(sampleTiles.join(', '));

  console.log('\nStarting Headless Chrome...');
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

    const networkResponses = new Map(); // requestId -> { url, headers }
    cdp.on('Network.responseReceived', (p) => {
      networkResponses.set(p.requestId, {
        url: p.response.url,
        status: p.response.status,
        headers: p.response.headers,
      });
    });

    // Wait 2s for initial page load and DOM render
    await sleep(2000);

    const measurements = [];

    for (let i = 0; i < sampleTiles.length; i++) {
      const tid = sampleTiles[i];
      const isFirst = i === 0;

      // Clear captured network responses for this iteration
      networkResponses.clear();

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

      // Find the analyze request
      let analyzeHeader = null;
      let analyzeStatus = 200;
      for (const [reqId, resp] of networkResponses.entries()) {
        if (resp.url.includes(`/api/analyze/${tid}`)) {
          analyzeHeader = resp.headers['server-timing'] || resp.headers['Server-Timing'];
          analyzeStatus = resp.status;
          break;
        }
      }

      const isCached = analyzeHeader && analyzeHeader.includes('cache;dur=0.0');
      if (isCached) {
        throw new Error(`Tile ${tid} was unexpectedly CACHED during cold benchmark!`);
      }

      // Parse Server-Timing metrics
      let ioMs = 0;
      let gpuMs = 0;
      let preMs = 0;
      let postMs = 0;
      if (analyzeHeader) {
        const mIo = analyzeHeader.match(/io;dur=([\d.]+)/);
        const mGpu = analyzeHeader.match(/gpu;dur=([\d.]+)/);
        const mPre = analyzeHeader.match(/preprocess;dur=([\d.]+)/);
        const mPost = analyzeHeader.match(/postprocess;dur=([\d.]+)/);
        if (mIo) ioMs = parseFloat(mIo[1]);
        if (mGpu) gpuMs = parseFloat(mGpu[1]);
        if (mPre) preMs = parseFloat(mPre[1]);
        if (mPost) postMs = parseFloat(mPost[1]);
      }

      measurements.push({
        index: i + 1,
        tileId: tid,
        clickToRenderMs: r.totalDt,
        serverTiming: analyzeHeader || 'N/A',
        ioMs,
        gpuMs,
        preMs,
        postMs,
        cached: !!isCached,
      });

      console.log(
        `[${String(i + 1).padStart(2)}/30] Tile ${tid.padEnd(8)} | ` +
        `Click-to-Render: ${r.totalDt.toFixed(1).padStart(6)} ms | ` +
        `I/O: ${ioMs.toFixed(1).padStart(5)} ms | ` +
        `GPU: ${gpuMs.toFixed(1).padStart(5)} ms | ` +
        `Cached: NO `
      );
    }

    console.log('\n=======================================================');
    console.log('COLD LATENCY BENCHMARK RESULTS');
    console.log('=======================================================');

    // Report Request #1 separately
    const req1 = measurements[0];
    console.log('REQUEST #1 (Cold Startup Tile):');
    console.log(`  Tile ID:          ${req1.tileId}`);
    console.log(`  Click-to-Render:  ${req1.clickToRenderMs.toFixed(1)} ms`);
    console.log(`  Server-Timing:    ${req1.serverTiming}`);
    console.log(`  I/O:              ${req1.ioMs.toFixed(1)} ms`);
    console.log(`  GPU:              ${req1.gpuMs.toFixed(1)} ms`);

    // Requests 2-30 (excluding any cached requests if present)
    const restLatencies = measurements.slice(1).map((m) => m.clickToRenderMs);
    const restIo = measurements.slice(1).map((m) => m.ioMs);
    const stats = percentiles(restLatencies);
    const ioStats = percentiles(restIo);

    console.log(`\nREQUESTS #2 to #30 (29 distinct uncached tiles):`);
    console.log(`  Click-to-Render Min:    ${stats.min.toFixed(1)} ms`);
    console.log(`  Click-to-Render Median: ${stats.med.toFixed(1)} ms`);
    console.log(`  Click-to-Render P95:    ${stats.p95.toFixed(1)} ms`);
    console.log(`  Click-to-Render Max:    ${stats.max.toFixed(1)} ms`);
    console.log(`  Server-Timing I/O Median: ${ioStats.med.toFixed(1)} ms (Min: ${ioStats.min.toFixed(1)} ms, Max: ${ioStats.max.toFixed(1)} ms)`);
    console.log(`  Note on OS Cache:       OS file-system cache state is NOT controlled (files read via GDAL/rasterio).`);

    // Save results to data/cold_latency_benchmark.json
    const outPath = path.join(__dirname, '..', 'data', 'cold_latency_benchmark.json');
    fs.writeFileSync(outPath, JSON.stringify({
      req1,
      stats,
      ioStats,
      osCacheControlled: false,
      measurements,
    }, null, 2));
    console.log(`\nResults written to ${outPath}`);

  } finally {
    chromeProc.kill();
    console.log('Headless Chrome stopped.');
  }
}

run().catch((e) => {
  console.error('Benchmark failed:', e);
  process.exit(1);
});
