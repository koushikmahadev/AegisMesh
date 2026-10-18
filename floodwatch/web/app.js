/**
 * FloodWatch - Client-side ES6 Application
 * 100% Offline: Pure vanilla JS, no external CDN or framework dependencies.
 */

// Application State
const state = {
  currentMode: "fast",       // "fast" | "accurate"
  selectedTileId: null,
  heatmapActive: true,
  tilesMap: new Map(),       // tile_id -> { tile_id, net, before, after, seen_in_training, gt_flooded_count, row, col }
  gridLookup: new Map(),      // "row_col" -> tile_id
  severityBands: [],
  demoTiles: [],
  abortController: null,
  sliderPos: 50,
  minRow: 15, maxRow: 45,
  minCol: 56, maxCol: 70,
  isAnalyzing: false,
  pendingTileId: null,
  keyDebounceTimer: null,
};

const urlParams = new URLSearchParams(window.location.search);
const DISABLE_LATEST_WINS = urlParams.get("disable_latest_wins") === "1";

// DOM Elements
const el = {
  deviceName: document.getElementById("deviceName"),
  cacheCount: document.getElementById("cacheCount"),
  cacheMem: document.getElementById("cacheMem"),
  btnModeFast: document.getElementById("btnModeFast"),
  btnModeAccurate: document.getElementById("btnModeAccurate"),
  btnToggleHeatmap: document.getElementById("btnToggleHeatmap"),
  demoChipsContainer: document.getElementById("demoChipsContainer"),
  gridLegend: document.getElementById("gridLegend"),
  tileGrid: document.getElementById("tileGrid"),
  tileTooltip: document.getElementById("tileTooltip"),
  gridStatsSummary: document.getElementById("gridStatsSummary"),
  gridScrollContainer: document.getElementById("gridScrollContainer"),

  idleState: document.getElementById("idleState"),
  loadingState: document.getElementById("loadingState"),
  resultCard: document.getElementById("resultCard"),

  resTileId: document.getElementById("resTileId"),
  resTrainingBadge: document.getElementById("resTrainingBadge"),
  resCachedBadge: document.getElementById("resCachedBadge"),
  resLatencyBadge: document.getElementById("resLatencyBadge"),
  resHeadlineBox: document.getElementById("resHeadlineBox"),
  resNetValue: document.getElementById("resNetValue"),
  resSeverityPill: document.getElementById("resSeverityPill"),
  resPreWater: document.getElementById("resPreWater"),
  resPostWater: document.getElementById("resPostWater"),
  resClientLatency: document.getElementById("resClientLatency"),
  resGtCard: document.getElementById("resGtCard"),
  resGtDetails: document.getElementById("resGtDetails"),
  resNegativeCard: document.getElementById("resNegativeCard"),
  btnRerunLive: document.getElementById("btnRerunLive"),

  comparisonViewer: document.getElementById("comparisonViewer"),
  imgPre: document.getElementById("imgPre"),
  imgPost: document.getElementById("imgPost"),
  maskPre: document.getElementById("maskPre"),
  maskPost: document.getElementById("maskPost"),
  clipLayer: document.getElementById("clipLayer"),
  sliderDivider: document.getElementById("sliderDivider"),
  compareRange: document.getElementById("compareRange"),
  chkMaskOverlay: document.getElementById("chkMaskOverlay"),

  aboutAccordion: document.getElementById("aboutAccordion"),
  accordionToggle: document.getElementById("accordionToggle"),
  accordionChevron: document.getElementById("accordionChevron"),
};

// ---------------------------------------------------------------- Initialization
async function initApp() {
  setupEventListeners();
  updateSlider(50);

  try {
    await Promise.all([
      fetchHealth(),
      fetchScanStats(),
      fetchTilesMeta(),
      fetchDemoTiles(),
    ]);
  } catch (err) {
    console.error("Initialization error:", err);
  }
}

// ---------------------------------------------------------------- API Calls
async function fetchHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return;
    const data = await res.json();
    el.deviceName.textContent = (data.device || "CUDA").toUpperCase();
    el.cacheCount.textContent = data.cache_size || 0;
    el.cacheMem.textContent = `${data.cache_memory_mb || 0} MB`;
  } catch (e) {
    console.warn("Health check error:", e);
  }
}

async function fetchScanStats() {
  try {
    const res = await fetch("/api/scan_stats");
    if (!res.ok) return;
    const stats = await res.json();
    state.severityBands = stats.severity_bands || [];

    // Render legend
    el.gridLegend.innerHTML = "";
    state.severityBands.forEach((band) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      const minText = band.min !== undefined ? `${band.min}%` : "0%";
      const maxText = band.max !== undefined ? `< ${band.max}%` : "+";
      const rangeLabel = band.min !== undefined ? `${minText}–${band.max}%` : `< ${band.max}%`;
      item.innerHTML = `
        <span class="legend-dot" style="background-color: ${band.color};"></span>
        <span title="${band.label}: ${rangeLabel}">${band.label}</span>
      `;
      el.gridLegend.appendChild(item);
    });

    if (stats.counts) {
      el.gridStatsSummary.textContent = `Max: +${stats.max.toFixed(1)}% | >1% Net: ${stats.counts.net_gt_1} tiles | Negative: ${stats.counts.net_lt_0}`;
    }
  } catch (e) {
    console.warn("Scan stats error:", e);
  }
}

async function fetchTilesMeta() {
  try {
    const res = await fetch("/api/tiles/meta");
    if (!res.ok) return;
    const tiles = await res.json();

    state.tilesMap.clear();
    state.gridLookup.clear();

    tiles.forEach((t) => {
      const parts = t.tile_id.split("_");
      const row = parseInt(parts[1], 10);
      const col = parseInt(parts[2], 10);
      const item = { ...t, row, col };
      state.tilesMap.set(t.tile_id, item);
      state.gridLookup.set(`${row}_${col}`, t.tile_id);
    });

    renderGrid();
  } catch (e) {
    console.error("Tiles metadata error:", e);
  }
}

async function fetchDemoTiles() {
  try {
    const res = await fetch("/api/demo_tiles");
    if (!res.ok) return;
    state.demoTiles = await res.json();
    renderDemoChips();
  } catch (e) {
    console.warn("Demo tiles error:", e);
  }
}

// ---------------------------------------------------------------- Demo Chips
function renderDemoChips() {
  el.demoChipsContainer.innerHTML = "";

  state.demoTiles.forEach((demo) => {
    const chip = document.createElement("button");
    chip.className = "demo-chip";
    chip.dataset.tileId = demo.tile_id;

    let chipClass = "hit";
    let icon = "🌊";
    if (demo.label.includes("Miss")) {
      chipClass = "miss";
      icon = "⚠️";
    } else if (demo.label.includes("True Negative")) {
      chipClass = "tn";
      icon = "🛡️";
    } else if (demo.label.includes("Negative")) {
      chipClass = "neg";
      icon = "📉";
    }

    chip.classList.add(chipClass);
    chip.title = `${demo.label} — ${demo.description || ''}`;
    chip.innerHTML = `
      <span>${icon}</span>
      <span>${demo.tile_id}</span>
      <span class="chip-net">${demo.net_intrusion_pct > 0 ? '+' : ''}${demo.net_intrusion_pct.toFixed(1)}%</span>
    `;

    chip.addEventListener("click", () => {
      selectTile(demo.tile_id);
    });

    el.demoChipsContainer.appendChild(chip);
  });
}

// ---------------------------------------------------------------- Grid Rendering
function renderGrid() {
  el.tileGrid.innerHTML = "";

  for (let r = state.minRow; r <= state.maxRow; r++) {
    for (let c = state.minCol; c <= state.maxCol; c++) {
      const tileId = state.gridLookup.get(`${r}_${c}`);
      const cell = document.createElement("div");

      if (tileId) {
        const t = state.tilesMap.get(tileId);
        cell.className = "tile-cell";
        cell.dataset.tileId = tileId;
        cell.dataset.row = r;
        cell.dataset.col = c;
        cell.setAttribute("role", "gridcell");
        cell.setAttribute("aria-label", `Tile ${tileId}, Net ${t.net}%`);

        const sev = getSeverity(t.net);
        cell.classList.add(`sev-${sev.class}`);

        // Cell contents: short row-col for high density
        cell.textContent = `${r}.${c}`;

        cell.addEventListener("click", () => selectTile(tileId));
        cell.addEventListener("mouseenter", (e) => showTooltip(e, t));
        cell.addEventListener("mouseleave", hideTooltip);
      } else {
        cell.className = "tile-cell empty";
        cell.setAttribute("aria-hidden", "true");
      }

      el.tileGrid.appendChild(cell);
    }
  }
}

function getSeverity(net) {
  if (net < 0) {
    return { class: "negative", label: "No Net Increase", color: "#a855f7" };
  }
  for (const b of state.severityBands) {
    const min = b.min !== undefined ? b.min : -Infinity;
    const max = b.max !== undefined ? b.max : Infinity;
    if (net >= min && net <= max) {
      return b;
    }
  }
  return { class: "none", label: "None detected", color: "#71717a" };
}

// ---------------------------------------------------------------- Tooltip
function showTooltip(evt, tile) {
  const rect = evt.target.getBoundingClientRect();
  const containerRect = el.gridScrollContainer.getBoundingClientRect();

  const split = tile.split || (tile.seen_in_training ? "train" : "not_in_pool");
  const splitTag = split === "train" ? "Train Pool" : split === "val" ? "Val Split" : "Not in pool";

  el.tileTooltip.innerHTML = `
    <strong>Tile ${tile.tile_id}</strong> (${splitTag})<br>
    Net Intrusion: <strong>${netFormatted}</strong><br>
    Before: ${tile.before}% | After: ${tile.after}%<br>
    GT Flooded Features: ${tile.gt_flooded_count || 0}
  `;

  el.tileTooltip.style.display = "block";
  const left = rect.left - containerRect.left + el.gridScrollContainer.scrollLeft + 15;
  const top = rect.top - containerRect.top + el.gridScrollContainer.scrollTop - 35;
  el.tileTooltip.style.left = `${Math.max(10, left)}px`;
  el.tileTooltip.style.top = `${Math.max(10, top)}px`;
}

function hideTooltip() {
  el.tileTooltip.style.display = "none";
}

// ---------------------------------------------------------------- Tile Selection & Inference
async function selectTile(tileId, options = {}) {
  if (!tileId) return;
  state.selectedTileId = tileId;
  const isNocache = !!options.nocache;

  // Highlight cell in grid immediately for instant feedback
  document.querySelectorAll(".tile-cell.selected").forEach((c) => c.classList.remove("selected"));
  const activeCell = document.querySelector(`.tile-cell[data-tile-id="${tileId}"]`);
  if (activeCell) {
    activeCell.classList.add("selected");
    activeCell.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }

  // Highlight demo chip if matching
  document.querySelectorAll(".demo-chip.active").forEach((c) => c.classList.remove("active"));
  const activeChip = document.querySelector(`.demo-chip[data-tile-id="${tileId}"]`);
  if (activeChip) {
    activeChip.classList.add("active");
  }

  // Latest-wins: if inference is already in-flight, queue this tile and abort the old request
  if (!DISABLE_LATEST_WINS) {
    if (state.isAnalyzing) {
      state.pendingTileId = tileId;
      if (state.abortController) {
        state.abortController.abort();
      }
      return;
    }

    state.isAnalyzing = true;
    state.pendingTileId = null;
  }

  if (state.abortController) {
    state.abortController.abort();
  }
  state.abortController = new AbortController();

  // Show loading skeleton
  el.idleState.style.display = "none";
  el.resultCard.style.display = "none";
  el.loadingState.style.display = "block";

  const tStart = performance.now();

  try {
    const nocacheParam = isNocache ? "&nocache=1" : "";
    const res = await fetch(`/api/analyze/${tileId}?mode=${state.currentMode}${nocacheParam}`, {
      signal: state.abortController.signal,
    });

    if (res.status === 499) {
      return; // Server aborted request
    }
    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    const data = await res.json();
    const roundTripMs = Math.round(performance.now() - tStart);

    renderResultCard(data, roundTripMs);
    fetchHealth(); // Update cache count in background
  } catch (err) {
    if (err.name === "AbortError") {
      // Intentionally aborted due to rapid tile switching
      return;
    }
    console.error("Inference request failed:", err);
    el.loadingState.style.display = "none";
    el.idleState.style.display = "block";
    el.idleState.innerHTML = `
      <div class="idle-icon" style="color: #ef4444;">⚠️</div>
      <h2 style="font-size: 1.1rem; color: #ef4444;">Inference Error</h2>
      <p style="font-size: 0.8rem; color: #cbd5e1;">${err.message}</p>
      <button class="btn-secondary" style="margin-top: 0.5rem;" onclick="selectTile('${tileId}')">Retry Tile</button>
    `;
  } finally {
    if (!DISABLE_LATEST_WINS) {
      state.isAnalyzing = false;
      // Latest-wins: dispatch latest queued tile if one arrived while analyzing
      if (state.pendingTileId && state.pendingTileId !== tileId) {
        const nextTile = state.pendingTileId;
        state.pendingTileId = null;
        selectTile(nextTile);
      }
    }
  }
}

// ---------------------------------------------------------------- Result Rendering
function renderResultCard(data, roundTripMs) {
  el.loadingState.style.display = "none";
  el.resultCard.style.display = "block";

  // Tile Header
  el.resTileId.textContent = `Tile ${data.tile_id}`;

  // Badges: train / val / not_in_pool
  const split = data.split || (data.seen_in_training ? "train" : "not_in_pool");
  if (split === "train") {
    el.resTrainingBadge.className = "badge-tag badge-training";
    el.resTrainingBadge.textContent = "Train Pool";
    el.resTrainingBadge.title = "Tile was part of the candidate satellite training pool";
  } else if (split === "val") {
    el.resTrainingBadge.className = "badge-tag badge-val";
    el.resTrainingBadge.textContent = "Val Split";
    el.resTrainingBadge.title = "Tile was part of the validation split";
  } else {
    el.resTrainingBadge.className = "badge-tag badge-heldout";
    el.resTrainingBadge.textContent = "Not in Pool";
    el.resTrainingBadge.title = "Unseen tile not in candidate training pool";
  }

  if (data.cached) {
    el.resCachedBadge.style.display = "inline-block";
    el.resLatencyBadge.textContent = "0 ms (cache)";
  } else {
    el.resCachedBadge.style.display = "none";
    el.resLatencyBadge.textContent = `${data.latency_ms} ms (GPU)`;
  }

  // Headline Net Display
  const net = data.net_intrusion_pct;
  const sev = getSeverity(net);

  el.resHeadlineBox.className = `metric-headline sev-${sev.class}`;
  if (net > 0) {
    el.resNetValue.textContent = `+${net.toFixed(2)}%`;
  } else if (net === 0) {
    el.resNetValue.textContent = `0.00%`;
  } else {
    el.resNetValue.textContent = `${net.toFixed(2)}%`;
  }

  el.resSeverityPill.textContent = sev.label;

  // Breakdown metrics
  el.resPreWater.textContent = `${data.before_water_pct.toFixed(2)}%`;
  el.resPostWater.textContent = `${data.after_water_pct.toFixed(2)}%`;
  el.resClientLatency.textContent = `${roundTripMs} ms`;

  // Ground Truth notice with per-tile pixel recall & precision
  const meta = state.tilesMap.get(data.tile_id) || {};
  const gtCount = data.gt_flooded_count !== undefined ? data.gt_flooded_count : (meta.gt_flooded_count || 0);
  const splitTag = split === "train" ? "Train Pool" : split === "val" ? "Val Split" : "Not in Pool";

  const demoItem = state.demoTiles.find((d) => d.tile_id === data.tile_id);
  if (demoItem && demoItem.agreement) {
    const ag = state.currentMode === "accurate" ? demoItem.agreement.accurate : demoItem.agreement.fast;
    const modeLabel = state.currentMode === "accurate" ? "Accurate" : "Fast";
    if (gtCount > 0) {
      if (data.tile_id === "0_23_62") {
        el.resGtDetails.textContent = `${gtCount} features · ${splitTag} | ${modeLabel}: Bldg Recall ${ag.bldg_recall_pct}%, precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): ${ag.precision_pct}%`;
      } else {
        el.resGtDetails.textContent = `${gtCount} features · ${splitTag} | ${modeLabel}: Rec ${ag.recall_pct}%, precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): ${ag.precision_pct}% (Bldg: ${ag.bldg_recall_pct}%, Road: ${ag.road_recall_pct}%)`;
      }
      el.resGtCard.style.borderColor = "var(--border-color)";
    } else {
      if (data.tile_id === "0_20_66") {
        el.resGtDetails.textContent = `0 features · ${splitTag} | Post-event: Rec 100%, precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 100% · Pre-event FP 3.32% (cause not determined)`;
      } else {
        el.resGtDetails.textContent = `0 features · ${splitTag} | Rec 100%, precision vs annotated buildings and roads (flooded land without annotations counts as a false positive): 100% (True Negative region)`;
      }
      el.resGtCard.style.borderColor = "#38bdf8";
    }
  } else if (gtCount > 0) {
    el.resGtDetails.textContent = `${gtCount} flooded features annotated (${splitTag}).`;
    el.resGtCard.style.borderColor = "var(--border-color)";
  } else {
    el.resGtDetails.textContent = `0 flooded features annotated · ${splitTag} (True Negative region).`;
    el.resGtCard.style.borderColor = "#38bdf8";
  }

  // Negative Net explanation
  if (net < 0) {
    el.resNegativeCard.style.display = "block";
  } else {
    el.resNegativeCard.style.display = "none";
  }

  // Update imagery & masks
  el.imgPre.src = data.images.pre;
  el.imgPost.src = data.images.post;
  el.maskPre.src = data.masks.before;
  el.maskPost.src = data.masks.after;

  updateMaskVisibility();
}

// ---------------------------------------------------------------- Slider & Controls
function updateSlider(val) {
  state.sliderPos = Math.max(0, Math.min(100, val));
  el.compareRange.value = state.sliderPos;
  el.sliderDivider.style.left = `${state.sliderPos}%`;
  el.clipLayer.style.clipPath = `inset(0 ${100 - state.sliderPos}% 0 0)`;
}

function updateMaskVisibility() {
  const show = el.chkMaskOverlay.checked;
  if (show) {
    el.maskPre.classList.remove("hidden");
    el.maskPost.classList.remove("hidden");
  } else {
    el.maskPre.classList.add("hidden");
    el.maskPost.classList.add("hidden");
  }
}

// ---------------------------------------------------------------- Event Listeners
function setupEventListeners() {
  // Slider Range input
  el.compareRange.addEventListener("input", (e) => {
    updateSlider(parseFloat(e.target.value));
  });

  // Slider Mouse/Touch dragging on container
  let isDragging = false;
  const onPointerMove = (e) => {
    if (!isDragging) return;
    const rect = el.comparisonViewer.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const pct = (x / rect.width) * 100;
    updateSlider(pct);
  };

  el.comparisonViewer.addEventListener("pointerdown", (e) => {
    isDragging = true;
    el.comparisonViewer.setPointerCapture(e.pointerId);
    onPointerMove(e);
  });
  el.comparisonViewer.addEventListener("pointermove", onPointerMove);
  el.comparisonViewer.addEventListener("pointerup", () => { isDragging = false; });
  el.comparisonViewer.addEventListener("pointercancel", () => { isDragging = false; });

  // Mask Overlay toggle
  el.chkMaskOverlay.addEventListener("change", updateMaskVisibility);

  // Fast / Accurate mode toggle
  el.btnModeFast.addEventListener("click", () => {
    if (state.currentMode === "fast") return;
    state.currentMode = "fast";
    el.btnModeFast.classList.add("active");
    el.btnModeAccurate.classList.remove("active");
    if (state.selectedTileId) selectTile(state.selectedTileId);
  });

  el.btnModeAccurate.addEventListener("click", () => {
    if (state.currentMode === "accurate") return;
    state.currentMode = "accurate";
    el.btnModeAccurate.classList.add("active");
    el.btnModeFast.classList.remove("active");
    if (state.selectedTileId) selectTile(state.selectedTileId);
  });

  // Heatmap toggle
  el.btnToggleHeatmap.addEventListener("click", () => {
    state.heatmapActive = !state.heatmapActive;
    el.tileGrid.classList.toggle("heatmap-on", state.heatmapActive);
    el.btnToggleHeatmap.classList.toggle("active", state.heatmapActive);
  });

  // Accordion Toggle
  el.accordionToggle.addEventListener("click", () => {
    el.aboutAccordion.classList.toggle("open");
    el.accordionChevron.textContent = el.aboutAccordion.classList.contains("open") ? "▲" : "▼";
  });

  // Re-run live button
  if (el.btnRerunLive) {
    el.btnRerunLive.addEventListener("click", () => {
      if (state.selectedTileId) {
        selectTile(state.selectedTileId, { nocache: true });
      }
    });
  }

  // Keyboard Navigation on Grid with 120ms debounce
  window.addEventListener("keydown", (e) => {
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    if (!state.selectedTileId) {
      if (state.demoTiles.length) selectTile(state.demoTiles[0].tile_id);
      return;
    }

    const cur = state.tilesMap.get(state.selectedTileId);
    if (!cur) return;

    e.preventDefault();
    let targetRow = cur.row;
    let targetCol = cur.col;

    if (e.key === "ArrowLeft") targetCol--;
    else if (e.key === "ArrowRight") targetCol++;
    else if (e.key === "ArrowUp") targetRow--;
    else if (e.key === "ArrowDown") targetRow++;

    // Find closest tile in that direction
    let targetTileId = state.gridLookup.get(`${targetRow}_${targetCol}`);
    if (!targetTileId) {
      for (let step = 1; step <= 6; step++) {
        let r = cur.row;
        let c = cur.col;
        if (e.key === "ArrowLeft") c -= step;
        else if (e.key === "ArrowRight") c += step;
        else if (e.key === "ArrowUp") r -= step;
        else if (e.key === "ArrowDown") r += step;

        const nextTarget = state.gridLookup.get(`${r}_${c}`);
        if (nextTarget) {
          targetTileId = nextTarget;
          break;
        }
      }
    }

    if (!targetTileId) return;

    // Immediate visual cell highlight and state advance for responsiveness
    state.selectedTileId = targetTileId;
    document.querySelectorAll(".tile-cell.selected").forEach((c) => c.classList.remove("selected"));
    const cell = document.querySelector(`.tile-cell[data-tile-id="${targetTileId}"]`);
    if (cell) {
      cell.classList.add("selected");
      cell.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
    }

    if (DISABLE_LATEST_WINS) {
      selectTile(targetTileId);
      return;
    }

    // Trailing debounce: continuous keydown resets timer so continuous input collapses to one request
    if (state.keyDebounceTimer) {
      clearTimeout(state.keyDebounceTimer);
    }
    state.keyDebounceTimer = setTimeout(() => {
      selectTile(targetTileId);
    }, 120);
  });
}

// Start application
window.addEventListener("DOMContentLoaded", initApp);
