/**
 * Frozen Re-Measurement Benchmark Suite (Phase 4 Corrections - Item 4)
 * Runs all remaining required measurements via Chrome DevTools Protocol:
 * 1. Accurate Mode Click-to-Render (10 distinct uncached tiles)
 * 2. Mask Toggle Latency (0_41_58 and 0_27_68)
 * 3. Rapid Keys Burst (with latest-wins vs ?disable_latest_wins=1)
 * 4. Prewarmed Click-to-Render (30 distinct tiles)
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9228;

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
  console.log('FROZEN RE-MEASUREMENT BENCHMARK SUITE');
  console.log('=======================================================');

  // Verify server
  const healthRes = await fetch('http://127.0.0.1:8000/api/health');
  const health = await healthRes.json();
  console.log(`Server Status: device=${health.device}, initial cache_size=${health.cache_size}`);

  const tilesRes = await fetch('http://127.0.0.1:8000/api/tiles');
  const allTiles = await tilesRes.json();

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

  const outputResults = {};

  try {
    const targetRes = await fetch(`http://127.0.0.1:${PORT}/json/new?http://127.0.0.1:8000/`, { method: 'PUT' });
    const { webSocketDebuggerUrl } = await targetRes.json();
    const cdp = new CdpClient(webSocketDebuggerUrl);
    await cdp.ready();
    await cdp.send('Page.enable');
    await cdp.send('Network.enable');

    await sleep(2000);

    // =========================================================================
    // 1. ACCURATE MODE CLICK-TO-RENDER (10 DISTINCT UNCACHED TILES)
    // =========================================================================
    console.log('\n--- 1. Accurate Mode Click-to-Render (10 Uncached Tiles) ---');
    await fetch('http://127.0.0.1:8000/api/cache/clear', { method: 'POST' });

    // Switch to Accurate mode in UI
    await cdp.eval(`document.getElementById('btnModeAccurate').click()`);
    await sleep(300);

    // Pick 10 fresh uncached tiles (e.g. index 60 to 70)
    const accTiles = allTiles.slice(60, 70);
    const accLatencies = [];

    for (let i = 0; i < accTiles.length; i++) {
      const tid = accTiles[i];
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

        return performance.now() - t0;
      })()`);

      accLatencies.push(r);
      console.log(`  [Accurate ${i + 1}/10] Tile ${tid.padEnd(8)} | Click-to-Render: ${r.toFixed(1).padStart(6)} ms`);
    }

    const accStats = percentiles(accLatencies);
    console.log(`Accurate Mode Summary (10 tiles): Min: ${accStats.min.toFixed(1)} ms | Median: ${accStats.med.toFixed(1)} ms | P95: ${accStats.p95.toFixed(1)} ms | Max: ${accStats.max.toFixed(1)} ms`);
    outputResults.accurate_cold_10 = accStats;

    // Switch back to fast mode
    await cdp.eval(`document.getElementById('btnModeFast').click()`);
    await sleep(300);

    // =========================================================================
    // 2. MASK TOGGLE LATENCY (0_41_58 and 0_27_68)
    // =========================================================================
    console.log('\n--- 2. Mask Toggle Latency Benchmark ---');
    // Test on 0_41_58 (largest flooded mask)
    console.log('Loading tile 0_41_58 for mask toggle measurement...');
    await cdp.eval(`selectTile('0_41_58')`);
    await sleep(1500);

    const toggle0_41_58 = await cdp.eval(`(async () => {
      const chk = document.getElementById('chkMaskOverlay');
      // Measure toggle off (hide mask)
      const t0 = performance.now();
      chk.click();
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const dtOff = performance.now() - t0;

      // Measure toggle on (show mask)
      const t1 = performance.now();
      chk.click();
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const dtOn = performance.now() - t1;

      return { dtOff, dtOn };
    })()`);

    console.log(`Tile 0_41_58 (Largest Mask): Toggle Hide = ${toggle0_41_58.dtOff.toFixed(2)} ms | Toggle Show = ${toggle0_41_58.dtOn.toFixed(2)} ms`);

    // Test on 0_27_68 (mid-severity tile)
    console.log('Loading tile 0_27_68 for mask toggle measurement...');
    await cdp.eval(`selectTile('0_27_68')`);
    await sleep(1500);

    const toggle0_27_68 = await cdp.eval(`(async () => {
      const chk = document.getElementById('chkMaskOverlay');
      const t0 = performance.now();
      chk.click();
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const dtOff = performance.now() - t0;

      const t1 = performance.now();
      chk.click();
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const dtOn = performance.now() - t1;

      return { dtOff, dtOn };
    })()`);

    console.log(`Tile 0_27_68 (Mid-Severity): Toggle Hide = ${toggle0_27_68.dtOff.toFixed(2)} ms | Toggle Show = ${toggle0_27_68.dtOn.toFixed(2)} ms`);

    outputResults.mask_toggle = {
      tile_0_41_58: toggle0_41_58,
      tile_0_27_68: toggle0_27_68,
    };

    // =========================================================================
    // 3. RAPID KEYS BURST (LATEST-WINS vs DISABLE_LATEST_WINS)
    // =========================================================================
    console.log('\n--- 3. Rapid Key Burst (10 presses 100ms apart) ---');

    async function runRapidBurst(pageUrl, label) {
      console.log(`\nTesting ${label} on ${pageUrl}...`);
      await fetch('http://127.0.0.1:8000/api/cache/clear', { method: 'POST' });

      await cdp.send('Page.navigate', { url: pageUrl });
      await sleep(2500);

      // Select initial tile 0_15_63
      await cdp.eval(`selectTile('0_15_63')`);
      await sleep(1500);

      const netEvents = [];
      const onReq = (p) => {
        if (p.request.url.includes('/api/analyze/')) {
          netEvents.push({ type: 'sent', url: p.request.url, id: p.requestId });
        }
      };
      const onResp = (p) => {
        if (p.response.url.includes('/api/analyze/')) {
          netEvents.push({ type: 'resp', url: p.response.url, status: p.response.status, id: p.requestId });
        }
      };
      const onFail = (p) => {
        netEvents.push({ type: 'fail', id: p.requestId, errorText: p.errorText });
      };

      cdp.on('Network.requestWillBeSent', onReq);
      cdp.on('Network.responseReceived', onResp);
      cdp.on('Network.loadingFailed', onFail);

      const burstStart = performance.now();
      for (let i = 1; i <= 10; i++) {
        await cdp.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', windowsVirtualKeyCode: 40, key: 'ArrowDown', code: 'ArrowDown' });
        await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 40, key: 'ArrowDown', code: 'ArrowDown' });
        if (i < 10) await sleep(100);
      }
      const lastKeyTime = performance.now();

      const finalSelectedTile = await cdp.eval(`document.querySelector('.tile-cell.selected')?.dataset.tileId`);
      console.log(`  Dispatched 10 Down keys in ${(lastKeyTime - burstStart).toFixed(1)} ms. Final selected tile: ${finalSelectedTile}`);

      // Await final render
      await cdp.eval(`(async () => {
        await new Promise((resolve) => {
          const check = () => {
            const card = document.getElementById('resultCard');
            const tileHeader = document.getElementById('resTileId');
            const imgPost = document.getElementById('imgPost');
            const imgPre = document.getElementById('imgPre');
            if (
              card && card.style.display !== 'none' &&
              tileHeader && tileHeader.textContent.includes('${finalSelectedTile}') &&
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
      })()`);

      const finalRenderTime = performance.now();
      const totalDt = finalRenderTime - burstStart;
      const latencyFromLast = finalRenderTime - lastKeyTime;

      const sentCount = netEvents.filter(e => e.type === 'sent').length;
      const respCount = netEvents.filter(e => e.type === 'resp').length;
      const failCount = netEvents.filter(e => e.type === 'fail').length;

      console.log(`  ${label} Result:`);
      console.log(`    Total Duration from Start: ${totalDt.toFixed(1)} ms`);
      console.log(`    Latency from Final Key:    ${latencyFromLast.toFixed(1)} ms`);
      console.log(`    Network Requests Sent:     ${sentCount}`);
      console.log(`    Responses Received:        ${respCount}`);
      console.log(`    Cancelled / Failed:        ${failCount}`);

      return {
        label,
        totalDt,
        latencyFromLast,
        sentCount,
        respCount,
        failCount,
        finalTile: finalSelectedTile,
      };
    }

    const rapidWithLatestWins = await runRapidBurst('http://127.0.0.1:8000/', 'With Latest-Wins & Trailing Debounce');
    const rapidWithoutLatestWins = await runRapidBurst('http://127.0.0.1:8000/?disable_latest_wins=1', 'Without Latest-Wins (?disable_latest_wins=1)');

    outputResults.rapid_keys = {
      with_latest_wins: rapidWithLatestWins,
      without_latest_wins: rapidWithoutLatestWins,
    };

    // =========================================================================
    // 4. PREWARMED CLICK-TO-RENDER (30 DISTINCT TILES)
    // =========================================================================
    console.log('\n--- 4. Prewarmed Click-to-Render Benchmark (30 Distinct Tiles) ---');
    console.log('Prewarming all tiles via API...');
    // Prewarm all tiles directly
    const tPrewarmStart = performance.now();
    for (const tid of allTiles) {
      await fetch(`http://127.0.0.1:8000/api/analyze/${tid}?mode=fast`);
    }
    console.log(`Prewarm complete in ${((performance.now() - tPrewarmStart) / 1000).toFixed(1)}s.`);

    // Navigate fresh page
    await cdp.send('Page.navigate', { url: 'http://127.0.0.1:8000/' });
    await sleep(2000);

    const prewarmedSample = allTiles.slice(10, 40);
    const prewarmedLatencies = [];

    for (let i = 0; i < prewarmedSample.length; i++) {
      const tid = prewarmedSample[i];
      const dt = await cdp.eval(`(async () => {
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

        return performance.now() - t0;
      })()`);

      prewarmedLatencies.push(dt);
      if ((i + 1) % 5 === 0 || i === 29) {
        console.log(`  [Prewarmed ${i + 1}/30] Tile ${tid.padEnd(8)} | Click-to-Render: ${dt.toFixed(1)} ms`);
      }
    }

    const preStats = percentiles(prewarmedLatencies);
    console.log(`\nPrewarmed Click-to-Render Summary (30 tiles):`);
    console.log(`  Min:    ${preStats.min.toFixed(1)} ms`);
    console.log(`  Median: ${preStats.med.toFixed(1)} ms`);
    console.log(`  P95:    ${preStats.p95.toFixed(1)} ms`);
    console.log(`  Max:    ${preStats.max.toFixed(1)} ms`);

    outputResults.prewarmed_30 = preStats;

    // Save all results to data/frozen_benchmarks_results.json
    fs.writeFileSync(
      path.join(__dirname, '..', 'data', 'frozen_benchmarks_results.json'),
      JSON.stringify(outputResults, null, 2)
    );
    console.log('\nAll benchmark results successfully written to data/frozen_benchmarks_results.json');

  } finally {
    chromeProc.kill();
    console.log('Headless Chrome shut down.');
  }
}

run().catch((e) => {
  console.error('Frozen benchmark failed:', e);
  process.exit(1);
});
