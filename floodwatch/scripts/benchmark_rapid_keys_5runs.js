/**
 * Rapid Keys 5-Repetition Benchmark (Phase 4.9 Task 7)
 * Runs 5 repetitions of both conditions from the same verified-uncached start tile (0_15_63)
 * to the same verified-uncached end tile (0_27_63), clearing the cache before each run.
 * 
 * Condition A: With Latest-Wins & Trailing Debounce (default)
 * Condition B: Without Latest-Wins (?disable_latest_wins=1)
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9229;

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

function median(arr) {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

async function run() {
  console.log('=======================================================');
  console.log('TASK 7: RAPID KEYS 5-REPETITION BENCHMARK');
  console.log('Start tile: 0_15_63 | Target end tile: 0_27_63');
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

  const results = {
    with_latest_wins: [],
    without_latest_wins: [],
  };

  try {
    const targetRes = await fetch(`http://127.0.0.1:${PORT}/json/new?http://127.0.0.1:8000/`, { method: 'PUT' });
    const { webSocketDebuggerUrl } = await targetRes.json();
    const cdp = new CdpClient(webSocketDebuggerUrl);
    await cdp.ready();
    await cdp.send('Page.enable');
    await cdp.send('Network.enable');

    async function executeRepetition(conditionUrl, isWithoutLatestWins) {
      // 1. Clear server cache
      await fetch('http://127.0.0.1:8000/api/cache/clear', { method: 'POST' });
      const h = await (await fetch('http://127.0.0.1:8000/api/health')).json();
      if (h.cache_size !== 0) throw new Error('Cache was not cleared!');

      // 2. Navigate fresh
      await cdp.send('Page.navigate', { url: conditionUrl });
      await sleep(2000);

      // 3. Select start tile 0_15_63
      await cdp.eval(`selectTile('0_15_63')`);
      await sleep(1500);

      // Track network requests
      const netReqs = [];
      const onReq = (p) => {
        if (p.request.url.includes('/api/analyze/')) {
          netReqs.push({ type: 'sent', id: p.requestId, url: p.request.url });
        }
      };
      const onResp = (p) => {
        if (p.response.url.includes('/api/analyze/')) {
          netReqs.push({ type: 'resp', id: p.requestId, status: p.response.status });
        }
      };
      const onFail = (p) => {
        netReqs.push({ type: 'fail', id: p.requestId, error: p.errorText });
      };

      cdp.on('Network.requestWillBeSent', onReq);
      cdp.on('Network.responseReceived', onResp);
      cdp.on('Network.loadingFailed', onFail);

      // 4. Dispatch 10 ArrowDown presses 100ms apart
      const burstStart = performance.now();
      for (let i = 1; i <= 10; i++) {
        await cdp.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', windowsVirtualKeyCode: 40, key: 'ArrowDown', code: 'ArrowDown' });
        await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 40, key: 'ArrowDown', code: 'ArrowDown' });
        if (i < 10) await sleep(100);
      }
      const lastKeyTime = performance.now();

      // Verify final tile selected
      const endTile = await cdp.eval(`state.selectedTileId`);
      if (endTile !== '0_27_63') {
        console.warn(`  Warning: End tile was ${endTile}, expected 0_27_63`);
      }

      // 5. Await render of end tile
      await cdp.eval(`(async () => {
        await new Promise((resolve) => {
          const check = () => {
            const card = document.getElementById('resultCard');
            const tileHeader = document.getElementById('resTileId');
            const imgPost = document.getElementById('imgPost');
            const imgPre = document.getElementById('imgPre');
            if (
              card && card.style.display !== 'none' &&
              tileHeader && tileHeader.textContent.includes('${endTile}') &&
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

      const renderTime = performance.now();
      const timeFromLastKey = renderTime - lastKeyTime;
      const totalTimeFromStart = renderTime - burstStart;

      const sent = netReqs.filter(r => r.type === 'sent').length;
      const resp = netReqs.filter(r => r.type === 'resp').length;
      const fail = netReqs.filter(r => r.type === 'fail').length;

      return {
        endTile,
        timeFromLastKey,
        totalTimeFromStart,
        sent,
        resp,
        fail,
      };
    }

    // ------------------------------------------------ Condition A: With Latest-Wins
    console.log('\n--- Condition A: With Latest-Wins & Trailing Debounce (5 reps) ---');
    for (let rep = 1; rep <= 5; rep++) {
      const res = await executeRepetition('http://127.0.0.1:8000/', false);
      results.with_latest_wins.push(res);
      console.log(`  [Rep ${rep}/5] End: ${res.endTile} | Last-Key-to-Render: ${res.timeFromLastKey.toFixed(1)} ms | Requests Sent: ${res.sent} | Cancelled: ${res.fail}`);
      await sleep(1000);
    }

    // ------------------------------------------------ Condition B: Without Latest-Wins
    console.log('\n--- Condition B: Without Latest-Wins (?disable_latest_wins=1) (5 reps) ---');
    for (let rep = 1; rep <= 5; rep++) {
      const res = await executeRepetition('http://127.0.0.1:8000/?disable_latest_wins=1', true);
      results.without_latest_wins.push(res);
      console.log(`  [Rep ${rep}/5] End: ${res.endTile} | Last-Key-to-Render: ${res.timeFromLastKey.toFixed(1)} ms | Requests Sent: ${res.sent} | Cancelled: ${res.fail}`);
      await sleep(1000);
    }

    // Compute medians
    const medA_time = median(results.with_latest_wins.map(r => r.timeFromLastKey));
    const medA_reqs = median(results.with_latest_wins.map(r => r.sent));

    const medB_time = median(results.without_latest_wins.map(r => r.timeFromLastKey));
    const medB_reqs = median(results.without_latest_wins.map(r => r.sent));

    console.log('\n=======================================================');
    console.log('RAPID KEYS 5-REPETITION SUMMARY (MEDIANS)');
    console.log('=======================================================');
    console.log(`Condition A (With Latest-Wins):`);
    console.log(`  Median Time from Last Key Press to Render: ${medA_time.toFixed(1)} ms`);
    console.log(`  Median Network Requests Sent:              ${medA_reqs}`);
    console.log(`Condition B (Without Latest-Wins):`);
    console.log(`  Median Time from Last Key Press to Render: ${medB_time.toFixed(1)} ms`);
    console.log(`  Median Network Requests Sent:              ${medB_reqs}`);

    const outputData = {
      start_tile: "0_15_63",
      end_tile: "0_27_63",
      repetitions: 5,
      condition_a_with_latest_wins: {
        median_time_from_last_key_ms: roundNum(medA_time, 1),
        median_requests_sent: medA_reqs,
        runs: results.with_latest_wins,
      },
      condition_b_without_latest_wins: {
        median_time_from_last_key_ms: roundNum(medB_time, 1),
        median_requests_sent: medB_reqs,
        runs: results.without_latest_wins,
      }
    };

    fs.writeFileSync(
      path.join(__dirname, '..', 'data', 'rapid_keys_5runs.json'),
      JSON.stringify(outputData, null, 2)
    );
    console.log('\nRaw results saved to data/rapid_keys_5runs.json');

  } finally {
    chromeProc.kill();
    console.log('Headless Chrome closed.');
  }
}

function roundNum(val, dec) {
  const f = Math.pow(10, dec);
  return Math.round(val * f) / f;
}

run().catch((e) => {
  console.error('Rapid keys benchmark failed:', e);
  process.exit(1);
});
