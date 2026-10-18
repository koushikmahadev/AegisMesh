/**
 * End-to-End Headless Browser Verification for FloodWatch (Phase 3)
 * Uses Chrome DevTools Protocol (CDP) via native Node 24 WebSocket.
 * 
 * Verifies:
 * 1. Network Isolation: zero outbound network requests (all traffic strictly localhost:8000).
 * 2. Visual layout: renders grid, demo chips, badges, slider.
 * 3. Real Browser Click-to-Render Latency: measures performance.now() from click to image render over 20 iterations.
 * 4. Captures screenshot to data/floodwatch_ui.png.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9222;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

async function run() {
  console.log('--- Step 1: Starting Headless Chrome ---');
  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--window-size=1600,1000',
  ]);

  chromeProc.stderr.on('data', () => {}); // silence logs

  let versionOk = false;
  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (res.ok) {
        versionOk = true;
        break;
      }
    } catch {}
    await sleep(200);
  }

  if (!versionOk) {
    chromeProc.kill();
    throw new Error('Chrome did not start debugging port in time');
  }

  console.log('✓ Headless Chrome listening on port', PORT);

  try {
    // Create new tab pointing to FloodWatch UI
    const targetRes = await fetch(`http://127.0.0.1:${PORT}/json/new?http://127.0.0.1:8000/`, { method: 'PUT' });
    const targetData = await targetRes.json();
    const wsUrl = targetData.webSocketDebuggerUrl;

    const cdp = new CdpClient(wsUrl);
    await cdp.ready();
    console.log('✓ Connected to CDP session');

    // 1. Monitor network traffic for network isolation verification
    await cdp.send('Network.enable');
    const interceptedRequests = [];
    cdp.on('Network.requestWillBeSent', (params) => {
      interceptedRequests.push(params.request.url);
    });

    await cdp.send('Page.enable');
    // Wait 2.5s for initial DOM and data fetch to populate
    await sleep(2500);

    console.log('\n--- Step 2: Verifying Network Isolation ---');
    const externalRequests = interceptedRequests.filter(
      (url) => !url.startsWith('http://127.0.0.1:8000') && !url.startsWith('http://localhost:8000') && !url.startsWith('data:')
    );

    console.log(`Total HTTP requests made by browser: ${interceptedRequests.length}`);
    if (externalRequests.length > 0) {
      console.error('FAIL: Detected outbound external requests:', externalRequests);
      throw new Error('Outbound network violation!');
    } else {
      console.log('✓ 100% OFFLINE VERIFIED: All requests confined to 127.0.0.1:8000 (0 external calls)');
    }

    console.log('\n--- Step 3: Verifying UI DOM Components ---');
    const domCheck = await cdp.eval(`({
      title: document.title,
      headerBrand: document.querySelector('.brand-title')?.textContent.trim(),
      offlineDot: !!document.querySelector('.badge-offline'),
      demoChipsCount: document.querySelectorAll('.demo-chip').length,
      tileGridCells: document.querySelectorAll('.tile-cell:not(.empty)').length,
      modeActive: document.querySelector('.mode-btn.active')?.dataset.mode,
      heatmapActive: document.querySelector('.tile-grid')?.classList.contains('heatmap-on')
    })`);

    console.log('DOM State:', JSON.stringify(domCheck, null, 2));
    if (domCheck.demoChipsCount < 10) throw new Error('Demo chips not rendered');
    if (domCheck.tileGridCells !== 202) throw new Error(`Expected 202 tile cells, found ${domCheck.tileGridCells}`);
    console.log('✓ All UI components verified in real browser DOM');

    console.log('\n--- Step 4: Measuring Real Click-to-Render Latency (20 Iterations) ---');
    // Test tiles: a mix of hits, misses, true negatives, and regular tiles
    const testTiles = [
      '0_41_58', '0_27_68', '0_41_59', '0_30_63', '0_27_67',
      '0_28_63', '0_23_62', '0_29_66', '0_40_62', '0_39_62',
      '0_15_63', '0_15_68', '0_15_65', '0_20_66', '0_41_58',
      '0_27_68', '0_23_62', '0_15_63', '0_20_66', '0_41_58'
    ];

    const latencies = [];

    for (let i = 0; i < testTiles.length; i++) {
      const tid = testTiles[i];
      const result = await cdp.eval(`(async () => {
        const t0 = performance.now();
        selectTile('${tid}');

        // Wait until resultCard is displayed and both pre & post images have completed loading
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

        const dt = performance.now() - t0;
        const netVal = document.getElementById('resNetValue')?.textContent;
        const sevPill = document.getElementById('resSeverityPill')?.textContent;
        const cached = !document.getElementById('resCachedBadge')?.style.display?.includes('none');
        return { dt, netVal, sevPill, cached };
      })()`);

      latencies.push(result.dt);
      console.log(`[${String(i + 1).padStart(2)}/20] Tile ${tid.padEnd(8)} | Click-to-Render: ${result.dt.toFixed(1).padStart(6)} ms | Cached: ${result.cached} | Net: ${result.netVal.padStart(8)} | Sev: ${result.sevPill}`);
    }

    latencies.sort((a, b) => a - b);
    const min = latencies[0];
    const median = latencies[Math.floor(latencies.length / 2)];
    const p95 = latencies[Math.floor(latencies.length * 0.95)];
    const max = latencies[latencies.length - 1];

    console.log('\n--- Real Browser Click-to-Render Benchmark Summary (20 clicks) ---');
    console.log(`Min:    ${min.toFixed(1)} ms`);
    console.log(`Median: ${median.toFixed(1)} ms`);
    console.log(`P95:    ${p95.toFixed(1)} ms`);
    console.log(`Max:    ${max.toFixed(1)} ms`);

    console.log('\n--- Step 5: Capturing Screenshot ---');
    // Ensure 0_41_58 is selected with swipe slider at 50%
    await cdp.eval(`selectTile('0_41_58')`);
    await sleep(600);

    const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    const screenshotPath = path.join(__dirname, '..', 'data', 'floodwatch_ui.png');
    fs.writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'));
    console.log(`✓ Screenshot captured to ${screenshotPath}`);

  } finally {
    chromeProc.kill();
    console.log('✓ Headless Chrome terminated');
  }
}

run().catch((e) => {
  console.error('Browser test failed:', e);
  process.exit(1);
});
