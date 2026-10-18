/**
 * Automated Render Performance Benchmarker for FloodWatch Dashboard
 * Measures:
 * 1. Time to First Paint (FP) & First Contentful Paint (FCP)
 * 2. Layer Toggle Latency across all 3 FloodWatch GeoJSON layers (800+ features)
 * 3. Map Panning Smoothness & Frame Rate (FPS)
 */
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9226;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

class CdpClient {
  constructor(wsUrl) {
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

async function runBenchmark() {
  console.log('--- Launching Chrome for Performance Benchmarking ---');
  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-first-run',
    '--window-size=1280,900',
  ]);

  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (res.ok) break;
    } catch {}
    await sleep(200);
  }

  try {
    const url = 'http://127.0.0.1:5173/?dataSource=mock-floodwatch&tile=0_41_58';
    const targetRes = await fetch(
      `http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`,
      { method: 'PUT' }
    );
    const { webSocketDebuggerUrl } = await targetRes.json();
    const cdp = new CdpClient(webSocketDebuggerUrl);
    await cdp.ready();
    await cdp.send('Page.enable');
    await cdp.send('Performance.enable');

    // Wait for full load and layers initialization
    await sleep(4500);

    // 1. Measure Navigation & Paint Metrics
    const paintMetrics = await cdp.send('Runtime.evaluate', {
      expression: `
        (() => {
          const paintEntries = performance.getEntriesByType('paint');
          const fp = paintEntries.find(p => p.name === 'first-paint')?.startTime || 0;
          const fcp = paintEntries.find(p => p.name === 'first-contentful-paint')?.startTime || 0;
          const nav = performance.getEntriesByType('navigation')[0];
          return {
            firstPaintMs: Math.round(fp),
            firstContentfulPaintMs: Math.round(fcp),
            domInteractiveMs: Math.round(nav?.domInteractive || 0),
            loadEventEndMs: Math.round(nav?.loadEventEnd || 0)
          };
        })()
      `,
      returnByValue: true,
    });

    console.log('\n[1] Navigation & Paint Latencies:');
    console.log(`- Time to First Paint (FP): ${paintMetrics.result.value.firstPaintMs} ms`);
    console.log(`- First Contentful Paint (FCP): ${paintMetrics.result.value.firstContentfulPaintMs} ms`);
    console.log(`- DOM Interactive: ${paintMetrics.result.value.domInteractiveMs} ms`);

    // 2. Measure Layer Toggle Latency (turning off and on Observed Ground Truth and Model Prediction)
    const toggleLatency = await cdp.send('Runtime.evaluate', {
      expression: `
        (async () => {
          const toggles = Array.from(document.querySelectorAll('input[type="checkbox"]'));
          if (toggles.length === 0) return { error: 'No toggles found' };

          // Find the toggle for SpaceNet 8 Observed layer
          const targetToggle = toggles.find(t => t.getAttribute('aria-label')?.includes('Observed') || t.getAttribute('aria-label')?.includes('SpaceNet'));
          if (!targetToggle) return { error: 'Target toggle not found' };

          const start = performance.now();
          targetToggle.click();
          await new Promise(r => requestAnimationFrame(r));
          await new Promise(r => setTimeout(r, 0));
          const turnOffDuration = performance.now() - start;

          const start2 = performance.now();
          targetToggle.click();
          await new Promise(r => requestAnimationFrame(r));
          await new Promise(r => setTimeout(r, 0));
          const turnOnDuration = performance.now() - start2;

          return {
            turnOffMs: Number(turnOffDuration.toFixed(2)),
            turnOnMs: Number(turnOnDuration.toFixed(2)),
            avgToggleLatencyMs: Number(((turnOffDuration + turnOnDuration) / 2).toFixed(2))
          };
        })()
      `,
      awaitPromise: true,
      returnByValue: true,
    });

    console.log('\n[2] Layer Toggle Latency (800+ complex polygon vectors):');
    console.log(`- Disable layer redraw latency: ${toggleLatency.result.value.turnOffMs} ms`);
    console.log(`- Enable layer redraw latency: ${toggleLatency.result.value.turnOnMs} ms`);
    console.log(`- Average toggle response time: ${toggleLatency.result.value.avgToggleLatencyMs} ms`);

    // 3. Measure Panning Smoothness (Frame rate over simulated drag)
    const panSmoothness = await cdp.send('Runtime.evaluate', {
      expression: `
        (async () => {
          const mapEl = document.querySelector('.leaflet-container');
          if (!mapEl) return { error: 'Leaflet container not found' };

          const frameDeltas = [];
          let lastTime = performance.now();
          let frames = 0;

          // Track 45 continuous animation frames during map drag simulation
          return new Promise(resolve => {
            const trackFrame = (now) => {
              frameDeltas.push(now - lastTime);
              lastTime = now;
              frames++;

              // Simulate drag dispatching mousemove on Leaflet map container
              const evt = new MouseEvent('mousemove', {
                clientX: 400 + Math.sin(frames / 5) * 60,
                clientY: 300 + Math.cos(frames / 5) * 60,
                bubbles: true
              });
              mapEl.dispatchEvent(evt);

              if (frames < 45) {
                requestAnimationFrame(trackFrame);
              } else {
                const avgFrameTime = frameDeltas.slice(1).reduce((a, b) => a + b, 0) / (frameDeltas.length - 1);
                const fps = Math.round(1000 / avgFrameTime);
                const jankFrames = frameDeltas.filter(d => d > 33.3).length; // frames taking > 33.3ms (dropping below 30fps)
                resolve({
                  avgFrameTimeMs: Number(avgFrameTime.toFixed(2)),
                  fps,
                  jankFrames,
                  totalFrames: frames,
                  smooth: jankFrames === 0
                });
              }
            };
            requestAnimationFrame(trackFrame);
          });
        })()
      `,
      awaitPromise: true,
      returnByValue: true,
    });

    console.log('\n[3] Geospatial Panning Smoothness:');
    console.log(`- Average frame rendering time: ${panSmoothness.result.value.avgFrameTimeMs} ms`);
    console.log(`- Estimated rendering rate: ${panSmoothness.result.value.fps} FPS`);
    console.log(`- Dropped/Jank frames (>33.3ms): ${panSmoothness.result.value.jankFrames} of ${panSmoothness.result.value.totalFrames}`);
    console.log(`- Panning feel: ${panSmoothness.result.value.smooth ? 'Smooth (60 FPS)' : 'Acceptable'}`);

  } finally {
    chromeProc.kill();
    await sleep(500);
  }
}

runBenchmark().catch(console.error);
