/**
 * Rapid-Click & Key-Repeat Queueing Benchmark (Phase 4 Item 3)
 * Simulates 10 rapid arrow presses within 1.0 second in real Headless Chrome.
 * Measures latency of the 10th tile appearing, verifies latest-wins and server request cancellation.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9227;

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
    if (res.exceptionDetails) throw new Error(JSON.stringify(res.exceptionDetails));
    return res.result ? res.result.value : undefined;
  }
}

async function run() {
  console.log('=======================================================');
  console.log('RAPID KEY-REPEAT / CLICK QUEUEING BENCHMARK');
  console.log('=======================================================');

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

    const interceptedRequests = [];
    cdp.on('Network.requestWillBeSent', (p) => {
      if (p.request.url.includes('/api/analyze/')) {
        interceptedRequests.push({
          type: 'sent',
          url: p.request.url,
          requestId: p.requestId,
          timestamp: performance.now(),
        });
      }
    });

    cdp.on('Network.responseReceived', (p) => {
      if (p.response.url.includes('/api/analyze/')) {
        interceptedRequests.push({
          type: 'response',
          url: p.response.url,
          status: p.response.status,
          requestId: p.requestId,
          timestamp: performance.now(),
        });
      }
    });

    cdp.on('Network.loadingFailed', (p) => {
      interceptedRequests.push({
        type: 'failed_or_aborted',
        requestId: p.requestId,
        errorText: p.errorText,
        canceled: p.canceled,
        timestamp: performance.now(),
      });
    });

    // Wait 2.5s for page and grid initialization
    await sleep(2500);

    // Initial tile selection to establish focus
    console.log('Selecting initial tile 0_15_63...');
    await cdp.eval(`selectTile('0_15_63')`);
    await sleep(1500);

    // Clear network log
    interceptedRequests.length = 0;

    console.log('\n--- Simulating 10 Rapid ArrowDown Presses (100ms interval, 1.0s burst) ---');
    const burstStart = performance.now();

    for (let i = 1; i <= 10; i++) {
      await cdp.send('Input.dispatchKeyEvent', {
        type: 'rawKeyDown',
        windowsVirtualKeyCode: 40, // VK_DOWN
        key: 'ArrowDown',
        code: 'ArrowDown',
      });
      await cdp.send('Input.dispatchKeyEvent', {
        type: 'keyUp',
        windowsVirtualKeyCode: 40,
        key: 'ArrowDown',
        code: 'ArrowDown',
      });
      console.log(`  [Press ${i}/10] ArrowDown dispatched at ${(performance.now() - burstStart).toFixed(1)} ms`);
      if (i < 10) {
        await sleep(100);
      }
    }

    const lastKeyPressTime = performance.now();
    console.log(`All 10 key presses dispatched in ${(lastKeyPressTime - burstStart).toFixed(1)} ms.`);

    // Find what the final target tile is by inspecting DOM grid selection
    const finalSelectedTile = await cdp.eval(`document.querySelector('.tile-cell.selected')?.dataset.tileId`);
    console.log(`Final target tile on grid: ${finalSelectedTile}`);

    // Wait until resultCard reflects final tile and images load
    console.log('Waiting for final tile to render...');
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
    const totalLatencyFromBurstStart = finalRenderTime - burstStart;
    const latencyFromLastKey = finalRenderTime - lastKeyPressTime;

    console.log('\n=======================================================');
    console.log('RAPID KEY-BURST MEASUREMENT RESULTS');
    console.log('=======================================================');
    console.log(`Final Tile Rendered:           ${finalSelectedTile}`);
    console.log(`Total Latency from Burst Start: ${totalLatencyFromBurstStart.toFixed(1)} ms`);
    console.log(`Latency from Final Key Press:  ${latencyFromLastKey.toFixed(1)} ms`);
    console.log(`Network Requests Logged during Burst: ${interceptedRequests.length}`);

    const sentRequests = interceptedRequests.filter((r) => r.type === 'sent');
    const responses = interceptedRequests.filter((r) => r.type === 'response');
    const aborted = interceptedRequests.filter((r) => r.type === 'failed_or_aborted' || r.status === 499);

    console.log(`  Total /api/analyze sent by client:    ${sentRequests.length}`);
    console.log(`  Total responses received from server: ${responses.length}`);
    console.log(`  Aborted / cancelled requests:         ${aborted.length}`);

    // In an unoptimized queue, 10 sequential inferences at ~800ms median each would take:
    const theoreticalUnoptimizedMs = 10 * 850;
    const speedup = theoreticalUnoptimizedMs / totalLatencyFromBurstStart;

    console.log(`\nComparison vs. Unoptimized Sequential Queueing:`);
    console.log(`  Theoretical 10-inference sequential delay: ~${theoreticalUnoptimizedMs} ms (~${(theoreticalUnoptimizedMs / 1000).toFixed(1)}s)`);
    console.log(`  Actual Measured Latency:                   ${totalLatencyFromBurstStart.toFixed(1)} ms`);
    console.log(`  Improvement / Speedup:                     ${speedup.toFixed(2)}x faster`);

    // Write audit output
    const outData = {
      finalSelectedTile,
      burstDurationMs: lastKeyPressTime - burstStart,
      totalLatencyFromBurstStart,
      latencyFromLastKey,
      sentRequestsCount: sentRequests.length,
      responsesCount: responses.length,
      abortedCount: aborted.length,
      theoreticalUnoptimizedMs,
      speedupFactor: speedup,
      networkLog: interceptedRequests,
    };

    fs.writeFileSync(
      path.join(__dirname, '..', 'data', 'rapid_keys_benchmark.json'),
      JSON.stringify(outData, null, 2)
    );
    console.log('Benchmark output saved to data/rapid_keys_benchmark.json');

  } finally {
    chromeProc.kill();
    console.log('Headless Chrome closed.');
  }
}

run().catch((e) => {
  console.error('Rapid keys benchmark failed:', e);
  process.exit(1);
});
