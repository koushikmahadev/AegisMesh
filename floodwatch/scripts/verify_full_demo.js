/**
 * Full End-to-End Demo Script Automated Verification (Phase 4 Verification)
 * Runs the complete demo flow in Headless Chrome via CDP, logging network traffic and console errors.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9226;

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
  console.log('Starting Full Demo Flow Automated Verification');
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

    const networkRequests = [];
    const consoleErrors = [];

    await cdp.send('Network.enable');
    cdp.on('Network.requestWillBeSent', (p) => {
      networkRequests.push(p.request.url);
    });

    await cdp.send('Runtime.enable');
    cdp.on('Runtime.consoleAPICalled', (p) => {
      if (p.type === 'error') {
        consoleErrors.push(p.args.map((a) => a.value || a.description).join(' '));
      }
    });

    await cdp.send('Page.enable');
    await sleep(2000);

    console.log('\n--- Executing Demo Steps ---');

    // 1. Severe Hit: 0_41_58
    await cdp.eval(`selectTile('0_41_58')`);
    await sleep(600);
    const r1 = await cdp.eval(`({
      tileId: document.getElementById('resTileId')?.textContent,
      net: document.getElementById('resNetValue')?.textContent,
      badge: document.getElementById('resTrainingBadge')?.textContent,
      latency: document.getElementById('resLatencyBadge')?.textContent
    })`);
    console.log('Step 1 (Severe Hit):', JSON.stringify(r1));

    // 2. Moderate Hit: 0_27_68
    await cdp.eval(`selectTile('0_27_68')`);
    await sleep(600);
    const r2 = await cdp.eval(`({
      tileId: document.getElementById('resTileId')?.textContent,
      net: document.getElementById('resNetValue')?.textContent,
      gt: document.getElementById('resGtDetails')?.textContent
    })`);
    console.log('Step 2 (Moderate Hit):', JSON.stringify(r2));

    // 3. Model Miss: 0_23_62
    await cdp.eval(`selectTile('0_23_62')`);
    await sleep(600);
    const r3 = await cdp.eval(`({
      tileId: document.getElementById('resTileId')?.textContent,
      net: document.getElementById('resNetValue')?.textContent,
      gt: document.getElementById('resGtDetails')?.textContent
    })`);
    console.log('Step 3 (Model Miss):', JSON.stringify(r3));

    // 4. True Negative: 0_15_63
    await cdp.eval(`selectTile('0_15_63')`);
    await sleep(600);
    const r4 = await cdp.eval(`({
      tileId: document.getElementById('resTileId')?.textContent,
      net: document.getElementById('resNetValue')?.textContent,
      badge: document.getElementById('resTrainingBadge')?.textContent
    })`);
    console.log('Step 4 (True Negative):', JSON.stringify(r4));

    // 5. False Positive: 0_20_66
    await cdp.eval(`selectTile('0_20_66')`);
    await sleep(600);
    const r5 = await cdp.eval(`({
      tileId: document.getElementById('resTileId')?.textContent,
      net: document.getElementById('resNetValue')?.textContent,
      negCardVisible: document.getElementById('resNegativeCard')?.style.display !== 'none',
      bannerText: document.getElementById('resNegativeCard')?.textContent.trim().replace(/\\s+/g, ' ')
    })`);
    console.log('Step 5 (False Positive):', JSON.stringify(r5));

    // 6. Accurate Mode Toggle & Execution on 0_41_58
    console.log('\n--- Testing Accurate Mode Toggle ---');
    await cdp.eval(`document.getElementById('btnModeAccurate').click()`);
    await sleep(300);
    await cdp.eval(`selectTile('0_41_58')`);
    await sleep(1200);
    const r6 = await cdp.eval(`({
      mode: document.querySelector('.mode-btn.active')?.dataset.mode,
      tileId: document.getElementById('resTileId')?.textContent,
      net: document.getElementById('resNetValue')?.textContent
    })`);
    console.log('Step 6 (Accurate Mode Execution):', JSON.stringify(r6));

    // 7. Interactive Controls: Slider, Mask, Heatmap, Keyboard
    console.log('\n--- Testing Slider, Mask Toggle, Heatmap, and Keyboard Navigation ---');
    await cdp.eval(`updateSlider(25)`);
    await sleep(100);
    await cdp.eval(`updateSlider(75)`);
    await sleep(100);
    await cdp.eval(`updateSlider(50)`);
    await sleep(100);

    // Toggle Mask checkbox
    await cdp.eval(`document.getElementById('chkMaskOverlay').click()`);
    await sleep(100);
    await cdp.eval(`document.getElementById('chkMaskOverlay').click()`);
    await sleep(100);

    // Toggle Heatmap button
    await cdp.eval(`document.getElementById('btnToggleHeatmap').click()`);
    await sleep(100);
    await cdp.eval(`document.getElementById('btnToggleHeatmap').click()`);
    await sleep(100);

    // Keyboard Arrow navigation
    await cdp.eval(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))`);
    await sleep(400);
    await cdp.eval(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))`);
    await sleep(400);

    const activeTileAfterKeyboard = await cdp.eval(`state.selectedTileId`);
    console.log('Keyboard Navigation Target Selected:', activeTileAfterKeyboard);

    // ---------------------------------------------------------------- Network & Console Assertions
    console.log('\n--- Final Verification Checks ---');
    const externalRequests = networkRequests.filter(
      (url) => !url.startsWith('http://127.0.0.1:8000') && !url.startsWith('http://localhost:8000') && !url.startsWith('data:')
    );

    console.log(`Total HTTP Requests Intercepted: ${networkRequests.length}`);
    console.log(`External Outbound Requests:      ${externalRequests.length}`);
    console.log(`Console Errors Intercepted:      ${consoleErrors.length}`);

    if (externalRequests.length > 0) {
      console.error('FAIL: Detected external requests:', externalRequests);
      process.exit(1);
    }
    if (consoleErrors.length > 0) {
      console.error('FAIL: Detected browser console errors:', consoleErrors);
      process.exit(1);
    }

    console.log('\nSUCCESS: 100% offline isolation verified (0 external requests) and 0 console errors!');
  } finally {
    chromeProc.kill();
    console.log('✓ Headless Chrome shut down');
  }
}

run().catch((e) => {
  console.error('Demo verification failed:', e);
  process.exit(1);
});
