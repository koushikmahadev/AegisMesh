/**
 * Capture Documentation Screenshots for docs/screenshots/
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9225;
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
    await sleep(2000);

    const shots = [
      { tid: '0_41_58', filename: 'hit_0_41_58.png', label: 'Hit: +39.00%' },
      { tid: '0_23_62', filename: 'miss_0_23_62.png', label: 'Miss: 101 GT features' },
      { tid: '0_20_66', filename: 'false_positive_0_20_66.png', label: 'False Positive: -3.32%' },
      { tid: '0_15_63', filename: 'held_out_0_15_63.png', label: 'Held-out / Not in pool: 0.00%' },
    ];

    for (const item of shots) {
      await cdp.eval(`selectTile('${item.tid}')`);
      await sleep(1000);

      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      const outPath = path.join(SCREENSHOT_DIR, item.filename);
      fs.writeFileSync(outPath, Buffer.from(shot.data, 'base64'));
      console.log(`✓ Saved ${item.label} to ${outPath}`);
    }

  } finally {
    chromeProc.kill();
    console.log('✓ Chrome terminated');
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
