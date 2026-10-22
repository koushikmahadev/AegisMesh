/**
 * AegisDynamics SOC Command Center Frontend Engine v3.2
 * High-performance telemetry engine with Tier 2 Graph Topology & Spectral Laplacian visualizer,
 * Autoregressive K-step rollout, true signed SHAP attributions, and restrained SOC color palette.
 */

let STATE = {
  currentDataset: "dos_slowloris",
  currentIndex: 0,
  totalWindows: 0,
  isPlaying: false,
  playSpeed: 1,
  playInterval: null,
  timelineData: [],
  windowCache: {},
  graphCache: {},
  currentWin: null,
  currentGraph: null,
  activeSoarTab: "soarIptables",
  voiceAudioEnabled: true,
  isListening: false,
  featureNames: [
    "flow_count", "syn_ratio", "ack_ratio", "fin_ratio", "rst_ratio",
    "flow_duration_mean", "flow_duration_max", "flow_iat_mean",
    "pkt_len_var_mean", "pkt_len_mean", "dst_port_entropy",
    "unallowed_port_ratio", "service_web_ratio", "service_remote_ratio"
  ],
  alerts: []
};

let residualChart = null;
let shapChart = null;

// Initialize immediately when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  initCharts();
  
  try {
    lucide.createIcons();
  } catch (e) {
    console.warn("Lucide init warning:", e);
  }

  loadInitialData();
});

async function loadInitialData() {
  await loadDataset(STATE.currentDataset);
  loadSystemStatus();
  loadBenchmarks();
}

function setupEventListeners() {
  // Scenario Selector
  const datasetSelect = document.getElementById("datasetSelect");
  if (datasetSelect) {
    datasetSelect.addEventListener("change", async (e) => {
      pausePlayback();
      await loadDataset(e.target.value);
    });
  }

  // Timeline Slider Scrubber
  const scrubber = document.getElementById("timelineScrubber");
  if (scrubber) {
    scrubber.addEventListener("input", (e) => {
      const idx = parseInt(e.target.value);
      goToWindow(idx);
    });
  }

  // Play / Step Controls
  const btnPlay = document.getElementById("btnPlay");
  if (btnPlay) btnPlay.onclick = togglePlay;

  const btnPrev = document.getElementById("btnPrev");
  if (btnPrev) {
    btnPrev.onclick = (e) => {
      if (e) e.preventDefault();
      if (STATE.currentIndex > 0) goToWindow(STATE.currentIndex - 1);
    };
  }

  const btnNext = document.getElementById("btnNext");
  if (btnNext) {
    btnNext.onclick = (e) => {
      if (e) e.preventDefault();
      const maxWin = STATE.totalWindows > 0 ? STATE.totalWindows : 1000;
      if (STATE.currentIndex < maxWin - 1) {
        goToWindow(STATE.currentIndex + 1);
      } else {
        goToWindow(0);
      }
    };
  }

  // Speed Toggles
  document.querySelectorAll(".speed-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      STATE.playSpeed = parseInt(btn.dataset.speed) || 1;
      if (STATE.isPlaying) {
        pausePlayback();
        startPlayback();
      }
    });
  });

  // SOAR Remediation Tabs
  document.querySelectorAll(".soar-tab").forEach(tab => {
    tab.addEventListener("click", (e) => {
      document.querySelectorAll(".soar-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      STATE.activeSoarTab = tab.dataset.target;
      renderSoarPlaybook(STATE.currentWin);
    });
  });

  // Export Incident Handlers
  const btnExportJson = document.getElementById("btnExportJson");
  if (btnExportJson) {
    btnExportJson.onclick = async () => {
      try {
        const res = await fetch(`/api/v1/export_incident_report/${STATE.currentIndex}?format=json`);
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `AegisDynamics_Incident_${data.report_id}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error("Error downloading incident JSON:", err);
      }
    };
  }

  const btnExportStix = document.getElementById("btnExportStix");
  if (btnExportStix) {
    btnExportStix.onclick = async () => {
      try {
        const res = await fetch(`/api/v1/export_stix/${STATE.currentIndex}`);
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `AegisDynamics_STIX21_${data.id || STATE.currentIndex}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error("Error downloading STIX bundle:", err);
      }
    };
  }

  const btnExportSigma = document.getElementById("btnExportSigma");
  if (btnExportSigma) {
    btnExportSigma.onclick = async () => {
      try {
        const res = await fetch(`/api/v1/export_sigma/${STATE.currentIndex}`);
        const yamlText = await res.text();
        const blob = new Blob([yamlText], { type: "text/yaml" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `AegisDynamics_Sigma_Rule_${STATE.currentIndex}.yml`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error("Error downloading Sigma rule:", err);
      }
    };
  }

  const btnPrintDossier = document.getElementById("btnPrintDossier");
  if (btnPrintDossier) {
    btnPrintDossier.onclick = () => {
      window.open(`/api/v1/export_incident_report/${STATE.currentIndex}?format=html`, "_blank");
    };
  }

  // Counterfactual Mitigation Simulation Toggle
  const btnSimMit = document.getElementById("btnSimulateMitigation");
  if (btnSimMit) {
    btnSimMit.onclick = async () => {
      STATE.mitigationActive = !STATE.mitigationActive;
      const btnText = document.getElementById("mitigationBtnText");
      const modeTag = document.getElementById("rolloutModeTag");
      if (STATE.mitigationActive) {
        if (btnText) btnText.textContent = "Revert to Status Quo";
        if (modeTag) {
          modeTag.textContent = "SOAR Mitigated (-98% Risk)";
          modeTag.classList.add("text-emerald");
        }
        await fetchCounterfactualRollout(STATE.currentIndex);
      } else {
        if (btnText) btnText.textContent = "Simulate SOAR Mitigation";
        if (modeTag) {
          modeTag.textContent = "Status Quo";
          modeTag.classList.remove("text-emerald");
        }
        if (STATE.currentWin) renderRolloutGrid(STATE.currentWin.rollout_projection || []);
      }
    };
  }

  // ATAK / Cursor-on-Target Handlers
  const btnAtakXml = document.getElementById("btnAtakXml");
  if (btnAtakXml) {
    btnAtakXml.onclick = async () => {
      try {
        const res = await fetch("/api/v1/atak/cot");
        const xmlText = await res.text();
        const blob = new Blob([xmlText], { type: "application/xml" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "AegisMesh_ATAK_CursorOnTarget.xml";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error("Error downloading CoT XML:", err);
      }
    };
  }

  const btnAtakGeoJson = document.getElementById("btnAtakGeoJson");
  if (btnAtakGeoJson) {
    btnAtakGeoJson.onclick = async () => {
      try {
        const res = await fetch("/api/v1/atak/geojson");
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "AegisMesh_ATAK_FieldMap.geojson";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error("Error downloading ATAK GeoJSON:", err);
      }
    };
  }

  const btnAtakUdp = document.getElementById("btnAtakUdp");
  if (btnAtakUdp) {
    btnAtakUdp.onclick = async () => {
      const lbl = document.getElementById("atakStatusLabel");
      try {
        if (lbl) lbl.textContent = "BROADCASTING UDP 4242...";
        const res = await fetch("/api/v1/atak/broadcast", { method: "POST" });
        const data = await res.json();
        if (lbl) {
          lbl.textContent = `UDP: 4242 SENT (${data.events_transmitted} NODES)`;
          setTimeout(() => {
            if (lbl) lbl.textContent = "ATAK UDP 4242: ACTIVE";
          }, 3500);
        }
      } catch (err) {
        console.error("Error broadcasting CoT:", err);
        if (lbl) lbl.textContent = "BROADCAST FAILED";
      }
    };
  }

  // Tactical Voice Copilot Handlers
  const btnVoiceMic = document.getElementById("btnVoiceMic");
  if (btnVoiceMic) {
    btnVoiceMic.onclick = toggleVoiceRecognition;
  }

  const btnVoiceToggle = document.getElementById("btnVoiceToggle");
  if (btnVoiceToggle) {
    btnVoiceToggle.onclick = () => {
      STATE.voiceAudioEnabled = !STATE.voiceAudioEnabled;
      if (STATE.voiceAudioEnabled) {
        btnVoiceToggle.classList.add("voice-toggle-active");
        btnVoiceToggle.innerHTML = '<i data-lucide="volume-2"></i> Voice Radio: ON';
      } else {
        btnVoiceToggle.classList.remove("voice-toggle-active");
        btnVoiceToggle.innerHTML = '<i data-lucide="volume-x"></i> Voice Radio: MUTED';
      }
      try { lucide.createIcons(); } catch (e) {}
    };
  }

  const btnCopilotSend = document.getElementById("btnCopilotSend");
  const copilotInput = document.getElementById("copilotInput");
  if (btnCopilotSend && copilotInput) {
    btnCopilotSend.onclick = () => {
      const q = copilotInput.value;
      if (q) sendCopilotQuery(q);
    };
    copilotInput.onkeydown = (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const q = copilotInput.value;
        if (q) sendCopilotQuery(q);
      }
    };
  }

  // Directive Quick Chips
  document.querySelectorAll(".directive-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const cmd = chip.dataset.cmd;
      if (copilotInput) copilotInput.value = cmd;
      sendCopilotQuery(cmd);
    });
  });
}

// Tactical Radio Audio Synthesizer (MIL-SPEC Dual Frequency Roger Beep)
function playTacticalRogerBeep() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(1760, ctx.currentTime + 0.05);

    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.12);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    osc.stop(ctx.currentTime + 0.12);
  } catch (e) {
    // AudioContext might require user gesture in some browsers
  }
}

// Hands-free Voice Output (TTS)
function speakTacticalTransmission(text) {
  if (!STATE.voiceAudioEnabled || !("speechSynthesis" in window)) return;
  try {
    window.speechSynthesis.cancel();
    playTacticalRogerBeep();

    setTimeout(() => {
      try {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.05;
        utterance.pitch = 0.95;
        const voices = window.speechSynthesis.getVoices();
        const engVoice = voices.find(v => v.lang && v.lang.startsWith("en") && (v.name.includes("Natural") || v.name.includes("David") || v.name.includes("Google") || v.name.includes("English")));
        if (engVoice) utterance.voice = engVoice;
        window.speechSynthesis.speak(utterance);
      } catch (err) {
        console.warn("TTS speak warning:", err);
      }
    }, 130);
  } catch (e) {
    console.warn("Audio warning:", e);
  }
}

// Hands-free Voice Input (STT)
let speechRecognizer = null;

function initVoiceRecognition() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    console.info("Web Speech API not supported in this browser environment.");
    return;
  }

  try {
    speechRecognizer = new SpeechRec();
    speechRecognizer.continuous = false;
    speechRecognizer.interimResults = false;
    speechRecognizer.lang = "en-US";

    speechRecognizer.onstart = () => {
      STATE.isListening = true;
      const micBtn = document.getElementById("btnVoiceMic");
      if (micBtn) micBtn.classList.add("mic-active");
    };

    speechRecognizer.onresult = (event) => {
      if (event.results && event.results[0] && event.results[0][0]) {
        const transcript = event.results[0][0].transcript;
        const input = document.getElementById("copilotInput");
        if (input) input.value = transcript;
        sendCopilotQuery(transcript);
      }
    };

    speechRecognizer.onerror = (event) => {
      console.warn("Speech recognition error:", event.error);
      STATE.isListening = false;
      const micBtn = document.getElementById("btnVoiceMic");
      if (micBtn) micBtn.classList.remove("mic-active");
    };

    speechRecognizer.onend = () => {
      STATE.isListening = false;
      const micBtn = document.getElementById("btnVoiceMic");
      if (micBtn) micBtn.classList.remove("mic-active");
    };
  } catch (err) {
    console.warn("SpeechRec init error:", err);
  }
}

function toggleVoiceRecognition() {
  if (!speechRecognizer) {
    initVoiceRecognition();
  }
  if (!speechRecognizer) {
    alert("Speech recognition is not available in your browser. You can type commands or click the quick directive buttons.");
    return;
  }

  try {
    if (STATE.isListening) {
      speechRecognizer.stop();
      STATE.isListening = false;
      const micBtn = document.getElementById("btnVoiceMic");
      if (micBtn) micBtn.classList.remove("mic-active");
    } else {
      speechRecognizer.start();
    }
  } catch (err) {
    console.warn("Mic toggle error:", err);
  }
}

// Tactical Copilot Directive Execution Engine
async function sendCopilotQuery(queryText) {
  const query = (queryText || "").trim();
  if (!query) return;

  const box = document.getElementById("copilotSpeechText");
  const ts = document.getElementById("copilotTimestamp");
  const badge = document.getElementById("copilotActionBadge");

  if (box) box.textContent = "Transmitting to Aegis Tactical Engine...";
  if (ts) ts.textContent = `T = ${new Date().toISOString().substring(11, 19)} UTC`;

  try {
    const res = await fetch("/api/v1/copilot/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        window_index: STATE.currentIndex
      })
    });

    if (!res.ok) {
      if (box) box.textContent = "Aegis Tactical: Command link temporarily unavailable.";
      return;
    }

    const data = await res.json();
    if (box) box.textContent = data.speech_text || "Directive processed.";
    if (ts) ts.textContent = `T = ${data.timestamp || "LIVE"}`;

    // Speak audio transmission
    speakTacticalTransmission(data.speech_text);

    // Render action badge
    if (badge && data.action) {
      badge.style.display = "inline-flex";
      if (data.action.type === "DYNAMIC_REROUTE") {
        badge.className = "transmission-action action-reroute";
        badge.innerHTML = `<i data-lucide="navigation"></i> <span>REROUTE: ${data.action.sector} | Heading: ${data.action.recommended_heading} | Waypoint: [${data.action.target_coordinates.join(", ")}] | Safe Depth: ${data.action.safety_depth_m}m</span>`;
      } else if (data.action.type === "QUARANTINE_EXECUTE") {
        badge.className = "transmission-action action-quarantine";
        badge.innerHTML = `<i data-lucide="shield-x"></i> <span>QUARANTINE: Injected drop rule for ${data.action.target_ip}</span>`;
      } else if (data.action.type === "ATAK_BROADCAST") {
        badge.className = "transmission-action";
        badge.innerHTML = `<i data-lucide="radio"></i> <span>ATAK: ${data.action.protocol} (${data.action.events_pushed} Nodes Pushed)</span>`;
      } else {
        badge.className = "transmission-action";
        badge.innerHTML = `<i data-lucide="check"></i> <span>ACTION: ${data.action.type}</span>`;
      }
      try { lucide.createIcons(); } catch (e) {}
    }
  } catch (err) {
    console.error("Copilot query error:", err);
    if (box) box.textContent = "Error communicating with tactical copilot service.";
  }
}


async function fetchCounterfactualRollout(index) {
  try {
    const res = await fetch(`/api/v1/counterfactual_rollout/${index}`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.counterfactual_analysis && data.counterfactual_analysis.mitigated_trajectory) {
      renderRolloutGrid(data.counterfactual_analysis.mitigated_trajectory);
    }
  } catch (err) {
    console.error("Error fetching counterfactual rollout:", err);
  }
}

function initCharts() {
  const elRes = document.getElementById("residualChart");
  if (elRes) {
    const ctxRes = elRes.getContext("2d");
    residualChart = new Chart(ctxRes, {
      type: "line",
      data: {
        labels: ["W0"],
        datasets: [
          {
            label: "Residual e(t+1)",
            data: [0.1],
            borderColor: "#38bdf8",
            borderWidth: 2,
            backgroundColor: "rgba(56, 189, 248, 0.08)",
            pointRadius: 0,
            fill: true,
            tension: 0.15,
            yAxisID: "y"
          },
          {
            label: "Infiltration Risk %",
            data: [1.0],
            borderColor: "#ef4444",
            borderWidth: 2,
            borderDash: [3, 3],
            pointRadius: 0,
            fill: false,
            tension: 0.15,
            yAxisID: "y1"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: "index",
            intersect: false,
            backgroundColor: "#0d1322",
            titleFont: { family: "'IBM Plex Mono', monospace", size: 11 },
            bodyFont: { family: "'IBM Plex Mono', monospace", size: 11 },
            borderColor: "#1e293b",
            borderWidth: 1
          }
        },
        scales: {
          x: {
            display: true,
            grid: { color: "#162035" },
            ticks: { color: "#64748b", font: { family: "'IBM Plex Mono', monospace", size: 9 }, maxTicksLimit: 10 }
          },
          y: {
            type: "linear",
            display: true,
            position: "left",
            grid: { color: "#162035" },
            ticks: { color: "#38bdf8", font: { family: "'IBM Plex Mono', monospace", size: 9 } }
          },
          y1: {
            type: "linear",
            display: true,
            position: "right",
            min: 0,
            max: 100,
            grid: { drawOnChartArea: false },
            ticks: { color: "#ef4444", font: { family: "'IBM Plex Mono', monospace", size: 9 }, callback: (v) => v + "%" }
          }
        }
      }
    });
  }

  const elShap = document.getElementById("shapChart");
  if (elShap) {
    const ctxShap = elShap.getContext("2d");
    shapChart = new Chart(ctxShap, {
      type: "bar",
      data: {
        labels: ["flow_count", "flow_duration_mean", "dst_port_entropy", "unallowed_port_ratio"],
        datasets: [
          {
            label: "Directional SHAP Score",
            data: [0.05, 0.12, -0.04, 0.08],
            backgroundColor: ["#ef4444", "#ef4444", "#38bdf8", "#ef4444"],
            borderRadius: 3
          }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#0d1322",
            titleFont: { family: "'IBM Plex Mono', monospace", size: 11 },
            bodyFont: { family: "'IBM Plex Mono', monospace", size: 11 },
            borderColor: "#1e293b",
            borderWidth: 1,
            callbacks: {
              label: function(context) {
                const val = context.raw;
                return val > 0 ? `+${val.toFixed(4)} (Elevates Anomaly Risk)` : `${val.toFixed(4)} (Stabilizes Baseline)`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: "#162035" },
            ticks: { color: "#64748b", font: { family: "'IBM Plex Mono', monospace", size: 9 } }
          },
          y: {
            grid: { display: false },
            ticks: { color: "#cbd5e1", font: { family: "'IBM Plex Mono', monospace", size: 10 } }
          }
        }
      }
    });
  }
}

async function loadSystemStatus() {
  try {
    const res = await fetch("/api/v1/system_status");
    if (!res.ok) return;
    const data = await res.json();
    const gEl = document.getElementById("headerGamma");
    const eEl = document.getElementById("headerE95");
    const qEl = document.getElementById("headerQ99");
    if (gEl) gEl.textContent = Number(data.calibrated_gamma).toFixed(5);
    if (eEl) eEl.textContent = Number(data.threshold_e95).toFixed(5);
    if (qEl && data.conformal_q99) qEl.textContent = Number(data.conformal_q99).toFixed(4);
  } catch (err) {
    console.error("Error loading system status:", err);
  }
}

async function loadDataset(datasetKey) {
  STATE.currentDataset = datasetKey;
  STATE.windowCache = {};
  STATE.graphCache = {};
  
  try {
    fetch(`/api/v1/load_dataset/${datasetKey}`, { method: "POST" });
    
    const tlRes = await fetch("/api/v1/timeline?start=0&limit=2000");
    if (!tlRes.ok) return;
    const tlData = await tlRes.json();
    STATE.timelineData = tlData.timeline;
    STATE.totalWindows = tlData.total_windows || tlData.timeline.length;

    const totEl = document.getElementById("totalWindowsCount");
    if (totEl) totEl.textContent = STATE.totalWindows;
    const scrubber = document.getElementById("timelineScrubber");
    if (scrubber) {
      scrubber.max = Math.max(1, STATE.totalWindows - 1);
      scrubber.value = 0;
    }

    await loadSystemStatus();
    await goToWindow(0);
  } catch (err) {
    console.error("Error loading dataset:", err);
  }
}

async function goToWindow(index) {
  if (index < 0) index = 0;
  if (STATE.totalWindows > 0 && index >= STATE.totalWindows) index = STATE.totalWindows - 1;
  
  STATE.currentIndex = index;
  
  const wIdxEl = document.getElementById("currentWindowIdx");
  if (wIdxEl) wIdxEl.textContent = index;
  const scrubEl = document.getElementById("timelineScrubber");
  if (scrubEl) scrubEl.value = index;

  // Use local cache if available
  if (STATE.windowCache[index]) {
    STATE.currentWin = STATE.windowCache[index];
    renderWindow(STATE.currentWin);
  } else {
    try {
      const res = await fetch(`/api/v1/window/${index}`);
      if (res.ok) {
        const win = await res.json();
        STATE.windowCache[index] = win;
        STATE.currentWin = win;
        renderWindow(win);
      }
    } catch (err) {
      console.error("Error fetching window:", err);
    }
  }

  // Fetch / Render Network Graph
  if (STATE.graphCache[index]) {
    STATE.currentGraph = STATE.graphCache[index];
    renderNetworkGraph(STATE.currentGraph);
  } else {
    try {
      const gRes = await fetch(`/api/v1/network_graph/${index}`);
      if (gRes.ok) {
        const gData = await gRes.json();
        STATE.graphCache[index] = gData;
        STATE.currentGraph = gData;
        renderNetworkGraph(gData);
      }
    } catch (gErr) {
      console.error("Error fetching network graph:", gErr);
    }
  }

  // Pre-fetch next 5 windows and graphs in background
  for (let offset = 1; offset <= 5; offset++) {
    const nextIdx = index + offset;
    if (nextIdx < STATE.totalWindows) {
      if (!STATE.windowCache[nextIdx]) {
        fetch(`/api/v1/window/${nextIdx}`)
          .then(r => r.json())
          .then(w => { STATE.windowCache[nextIdx] = w; })
          .catch(() => {});
      }
      if (!STATE.graphCache[nextIdx]) {
        fetch(`/api/v1/network_graph/${nextIdx}`)
          .then(r => r.json())
          .then(g => { STATE.graphCache[nextIdx] = g; })
          .catch(() => {});
      }
    }
  }
}

function renderWindow(win) {
  if (!win) return;

  const tsEl = document.getElementById("currentTimestamp");
  if (tsEl) tsEl.textContent = `T = ${win.timestamp}`;

  const gtEl = document.getElementById("groundTruthLabel");
  if (gtEl) {
    gtEl.textContent = win.is_attack_ground_truth ? "ATTACK" : "NORMAL";
    gtEl.className = win.is_attack_ground_truth ? "val mono text-crimson" : "val mono text-emerald";
  }

  const tgtIpEl = document.getElementById("targetAttackerIp");
  if (tgtIpEl) tgtIpEl.textContent = win.source_ip || "18.218.115.60";

  // Calibrated Decision Rule: e(t+1) >= e95 <=> P(Infil) >= 0.10
  const prob = win.infiltration_probability;
  const pct = (prob * 100).toFixed(1) + "%";
  
  const riskPctEl = document.getElementById("riskPercent");
  if (riskPctEl) riskPctEl.textContent = pct;

  const barFillEl = document.getElementById("riskBarFill");
  if (barFillEl) barFillEl.style.width = Math.min(100, Math.max(2, prob * 100)) + "%";

  const resEl = document.getElementById("currentResidual");
  if (resEl) resEl.textContent = win.residual_error.toFixed(4);

  const mstEl = document.getElementById("currentMst");
  if (mstEl) mstEl.textContent = (win.m_st !== undefined ? win.m_st : win.residual_error).toFixed(4);

  const threatBadge = document.getElementById("threatBadge");
  const decisionState = document.getElementById("decisionState");

  if (prob >= 0.45) {
    if (threatBadge) {
      threatBadge.textContent = "CRITICAL";
      threatBadge.className = "badge-threat badge-critical";
    }
    if (barFillEl) barFillEl.style.backgroundColor = "var(--crimson)";
    if (decisionState) {
      decisionState.textContent = "ESCALATED INCIDENT";
      decisionState.className = "mono text-crimson";
    }
    logAlert(win, "CRITICAL", `ACL INJECT: DROP ${win.source_ip}/32`);
  } else if (prob >= 0.10) {
    if (threatBadge) {
      threatBadge.textContent = "ELEVATED (e₉₅)";
      threatBadge.className = "badge-threat badge-elevated";
    }
    if (barFillEl) barFillEl.style.backgroundColor = "var(--amber)";
    if (decisionState) {
      decisionState.textContent = "CALIBRATED ANOMALY (e ≥ e₉₅)";
      decisionState.className = "mono text-amber";
    }
    logAlert(win, "ELEVATED", `CALIBRATED ALERT: MONITOR ${win.source_ip}`);
  } else {
    if (threatBadge) {
      threatBadge.textContent = "NOMINAL";
      threatBadge.className = "badge-threat badge-nominal";
    }
    if (barFillEl) barFillEl.style.backgroundColor = "var(--emerald)";
    if (decisionState) {
      decisionState.textContent = "BASELINE (≤ e₉₅)";
      decisionState.className = "mono text-emerald";
    }
  }

  // Conformal Epistemic Status
  const confEl = document.getElementById("conformalStatus");
  if (confEl) {
    if (win.conformal_assessment) {
      const epStatus = win.conformal_assessment.epistemic_status;
      if (epStatus === "CRITICAL_INVARIANT_VIOLATION") {
        confEl.textContent = "INVARIANT VIOLATION (> q₉₉)";
        confEl.className = "mono text-crimson";
      } else if (epStatus === "ELEVATED_COVARIANCE") {
        confEl.textContent = "ELEVATED COVARIANCE (> q₉₀)";
        confEl.className = "mono text-amber";
      } else {
        confEl.textContent = "NOMINAL (≤ q₉₀)";
        confEl.className = "mono text-sky";
      }
    } else {
      confEl.textContent = "NOMINAL (≤ q₉₀)";
      confEl.className = "mono text-sky";
    }
  }

  // MITRE Progression Pills
  renderMitrePills(win.predicted_stage, prob >= 0.10);

  // Policy Compliance
  const unallowed = win.state_vector[11];
  const entropy = win.state_vector[10];
  const unallEl = document.getElementById("unallowedPortVal");
  if (unallEl) unallEl.textContent = (unallowed * 100).toFixed(1) + "%";
  const entEl = document.getElementById("portEntropyVal");
  if (entEl) entEl.textContent = entropy.toFixed(3);

  const polEl = document.getElementById("policyStatus");
  if (polEl) {
    if (unallowed > 0.10) {
      polEl.textContent = "POLICY VIOLATION";
      polEl.className = "badge-threat badge-critical mono";
    } else {
      polEl.textContent = "COMPLIANT";
      polEl.className = "badge-threat badge-nominal mono";
    }
  }

  // Render K-Step Forward Rollout
  if (STATE.mitigationActive) {
    fetchCounterfactualRollout(win.index);
  } else {
    renderRolloutGrid(win.rollout_projection || []);
  }

  // Update Sparkline Chart
  updateResidualChart();

  // Update True SHAP Chart
  updateShapChart(win);

  // Update 14-D Telemetry Table
  renderTelemetryTable(win);

  // Render SOAR Playbook
  renderSoarPlaybook(win);
}

function renderNetworkGraph(graphData) {
  const canvas = document.getElementById("networkCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const w = canvas.clientWidth || 500;
  const h = canvas.clientHeight || 200;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }

  ctx.clearRect(0, 0, w, h);

  // Draw background tactical grid dots
  ctx.fillStyle = "rgba(255, 255, 255, 0.04)";
  for (let gx = 15; gx < w; gx += 20) {
    for (let gy = 15; gy < h; gy += 20) {
      ctx.fillRect(gx, gy, 1.5, 1.5);
    }
  }

  if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
    // Render placeholder topology if loading
    ctx.fillStyle = "#64748b";
    ctx.font = "11px 'IBM Plex Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText("Synchronizing Topology Graph...", w / 2, h / 2);
    return;
  }

  const nodeCntEl = document.getElementById("graphNodesCount");
  if (nodeCntEl) nodeCntEl.textContent = `${graphData.num_nodes} Nodes Active`;

  const l2El = document.getElementById("graphLambda2");
  if (l2El) l2El.textContent = graphData.algebraic_connectivity_lambda2.toFixed(4);

  const velEl = document.getElementById("graphTopoVelocity");
  if (velEl) {
    const v = graphData.topo_velocity !== undefined ? graphData.topo_velocity : 0.0;
    velEl.textContent = v.toFixed(4);
    velEl.className = v > 0.05 ? "mono text-amber" : "mono text-secondary";
  }

  const gapEl = document.getElementById("graphSpectralGap");
  if (gapEl) gapEl.textContent = graphData.spectral_dispersion_gap.toFixed(2);

  const vnEl = document.getElementById("graphVnEntropy");
  if (vnEl) {
    const vn = graphData.von_neumann_entropy !== undefined ? graphData.von_neumann_entropy : 0.0;
    vnEl.textContent = vn.toFixed(4);
  }

  const curvEl = document.getElementById("graphCurvature");
  if (curvEl) {
    const curv = graphData.topological_curvature !== undefined ? graphData.topological_curvature : 0.0;
    curvEl.textContent = curv.toFixed(4);
  }

  const anomEl = document.getElementById("graphAnomEdges");
  if (anomEl) {
    anomEl.textContent = graphData.anomalous_edges_count;
    anomEl.className = graphData.anomalous_edges_count > 0 ? "mono text-crimson" : "mono text-emerald";
  }

  const nodes = graphData.nodes;
  const edges = graphData.edges || [];

  const centerX = w * 0.52;
  const centerY = h * 0.50;
  const radius = Math.min(w, h) * 0.36;

  const nodePositions = {};
  nodes.forEach((n, i) => {
    let x, y;
    if (n.is_crown_jewel) {
      x = centerX + (n.full_ip.endsWith(".50") ? -35 : 35);
      y = centerY;
    } else if (n.is_threat) {
      x = w * 0.12;
      y = h * 0.35;
    } else if (n.full_ip.startsWith("192.168.10.1")) {
      x = centerX;
      y = h * 0.18;
    } else {
      const angle = (i / Math.max(1, nodes.length)) * 2 * Math.PI;
      x = centerX + Math.cos(angle) * radius;
      y = centerY + Math.sin(angle) * (radius * 0.75);
    }
    nodePositions[n.id] = { x, y, node: n };
  });

  // Draw Edges
  edges.forEach(e => {
    const srcPos = nodePositions[e.source];
    const dstPos = nodePositions[e.target];
    if (!srcPos || !dstPos) return;

    ctx.beginPath();
    ctx.moveTo(srcPos.x, srcPos.y);
    ctx.lineTo(dstPos.x, dstPos.y);

    if (e.is_anomalous) {
      ctx.strokeStyle = "#ef4444";
      ctx.lineWidth = 2.0;
      ctx.setLineDash([]);
    } else {
      ctx.strokeStyle = "rgba(148, 163, 184, 0.25)";
      ctx.lineWidth = 1.0;
      ctx.setLineDash([3, 3]);
    }
    ctx.stroke();
  });
  ctx.setLineDash([]);

  // Draw Nodes
  nodes.forEach(n => {
    const pos = nodePositions[n.id];
    if (!pos) return;

    ctx.beginPath();
    let r = 5;
    if (n.is_crown_jewel) {
      r = 8;
      ctx.fillStyle = "#38bdf8";
      // Halo
      ctx.arc(pos.x, pos.y, r + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = "rgba(56, 189, 248, 0.3)";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.beginPath();
    } else if (n.is_threat) {
      r = 8;
      ctx.fillStyle = "#ef4444";
      ctx.arc(pos.x, pos.y, r + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = "rgba(239, 68, 68, 0.35)";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.beginPath();
    } else {
      r = 5;
      ctx.fillStyle = "#64748b";
    }

    ctx.arc(pos.x, pos.y, r, 0, 2 * Math.PI);
    ctx.fill();

    // Node label
    ctx.font = "10px 'IBM Plex Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillStyle = n.is_crown_jewel ? "#38bdf8" : (n.is_threat ? "#f87171" : "#94a3b8");
    ctx.fillText(n.label, pos.x + r + 4, pos.y + 3);
  });
}

function renderRolloutGrid(rolloutSteps) {
  const grid = document.getElementById("rolloutStepsGrid");
  if (!grid) return;
  grid.innerHTML = "";

  rolloutSteps.forEach(step => {
    const card = document.createElement("div");
    const isCrit = step.infiltration_probability >= 0.45;
    const isElev = step.infiltration_probability >= 0.10;
    
    card.className = `rollout-step-card ${isCrit ? 'step-critical' : (isElev ? 'step-elevated' : '')}`;
    const pPct = (step.infiltration_probability * 100).toFixed(1);
    
    card.innerHTML = `
      <div class="step-header">
        <span class="step-horizon">${step.horizon_label}</span>
        <span class="tag-badge ${isCrit ? 'tag-critical' : (isElev ? 'tag-high' : 'tag-nominal')}">${step.severity}</span>
      </div>
      <div class="step-prob ${isCrit ? 'text-crimson' : (isElev ? 'text-amber' : 'text-emerald')}">${pPct}% Risk</div>
      <div class="step-stage-name mono">${step.predicted_stage}</div>
      <div class="step-mini-bar">
        <div class="step-mini-bar-fill" style="width: ${Math.min(100, Math.max(2, step.infiltration_probability * 100))}%; background-color: ${isCrit ? 'var(--crimson)' : (isElev ? 'var(--amber)' : 'var(--emerald)')};"></div>
      </div>
    `;
    grid.appendChild(card);
  });
}

function renderSoarPlaybook(win) {
  if (!win || !win.soar_playbook) return;
  const pre = document.getElementById("soarCodeBlock");
  if (!pre) return;
  
  if (STATE.activeSoarTab === "soarIptables") {
    pre.textContent = win.soar_playbook.iptables || "# No rules generated.";
  } else if (STATE.activeSoarTab === "soarAws") {
    pre.textContent = win.soar_playbook.aws_cli || "# No AWS CLI rules generated.";
  } else if (STATE.activeSoarTab === "soarCisco") {
    pre.textContent = win.soar_playbook.cisco_acl || "# No Cisco ACL rules generated.";
  }
}

function renderMitrePills(predictedStage, isAlert) {
  const pTag = document.getElementById("predictedStageTag");
  if (pTag) {
    pTag.textContent = predictedStage;
    pTag.className = isAlert ? "badge-threat badge-critical mono" : "badge-threat badge-nominal mono";
  }

  const stages = [
    { id: "stageNormal", name: "Normal" },
    { id: "stageRecon", name: "Reconnaissance" },
    { id: "stageAccess", name: "Initial Access" },
    { id: "stageLateral", name: "Lateral Movement" },
    { id: "stageImpact", name: "Impact" }
  ];

  stages.forEach(s => {
    const el = document.getElementById(s.id);
    if (!el) return;
    el.className = "mitre-pill";
    if (predictedStage.toLowerCase().includes(s.name.toLowerCase())) {
      el.className = isAlert ? "mitre-pill active-alert" : "mitre-pill active";
    }
  });
}

function updateResidualChart() {
  if (!residualChart) return;
  
  if (STATE.timelineData && STATE.timelineData.length > 0) {
    const windowSlice = STATE.timelineData.slice(0, STATE.currentIndex + 1);
    const labels = windowSlice.map(w => w.timestamp.split(" ")[1] || `W${w.index}`);
    const resData = windowSlice.map(w => w.residual_error);
    const probData = windowSlice.map(w => w.infiltration_probability * 100);

    residualChart.data.labels = labels;
    residualChart.data.datasets[0].data = resData;
    residualChart.data.datasets[1].data = probData;
  } else if (STATE.currentWin) {
    residualChart.data.labels = [`W${STATE.currentWin.index}`];
    residualChart.data.datasets[0].data = [STATE.currentWin.residual_error];
    residualChart.data.datasets[1].data = [STATE.currentWin.infiltration_probability * 100];
  }
  residualChart.update();
}

function updateShapChart(win) {
  if (!shapChart || !win) return;
  
  const shapItems = win.shap_attributions || [];
  if (shapItems.length === 0) return;
  
  const labels = shapItems.map(f => f.feature);
  const scores = shapItems.map(f => f.shap_direction);
  const colors = shapItems.map(f => f.shap_direction > 0 ? "#ef4444" : "#0284c7");

  shapChart.data.labels = labels;
  shapChart.data.datasets[0].data = scores;
  shapChart.data.datasets[0].backgroundColor = colors;
  shapChart.update();

  const driverEl = document.getElementById("topShapDriver");
  if (driverEl && shapItems.length > 0) {
    driverEl.textContent = `${shapItems[0].feature} (SHAP ${shapItems[0].shap_direction > 0 ? '+' : ''}${shapItems[0].shap_direction.toFixed(3)})`;
  }
}

function renderTelemetryTable(win) {
  const tbody = document.getElementById("telemetryTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  STATE.featureNames.forEach((name, i) => {
    const obs = win.state_vector[i] || 0;
    const pred = win.predicted_state[i] || 0;
    const diff = Math.abs(pred - obs);
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td class="text-secondary">${name}</td>
      <td>${obs.toFixed(3)}</td>
      <td>${pred.toFixed(3)}</td>
      <td class="${diff > 1.0 ? 'text-crimson' : 'text-emerald'}">${diff.toFixed(3)}</td>
      <td><span class="tag-badge ${diff > 1.0 ? 'tag-critical' : 'tag-nominal'}">${diff > 1.0 ? '+ANOMALOUS' : 'STABLE'}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function logAlert(win, severity, actionText) {
  if (STATE.alerts.some(a => a.index === win.index)) return;
  
  const alertObj = {
    index: win.index,
    timestamp: win.timestamp,
    stage: win.predicted_stage,
    residual: win.residual_error.toFixed(4),
    prob: (win.infiltration_probability * 100).toFixed(1) + "%",
    severity: severity,
    action: actionText
  };

  STATE.alerts.unshift(alertObj);
  const cTag = document.getElementById("alertCountTag");
  if (cTag) cTag.textContent = `${STATE.alerts.length} Alerts Recorded`;

  const tbody = document.getElementById("auditTableBody");
  if (!tbody) return;
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>${alertObj.timestamp}</td>
    <td class="text-amber">${alertObj.stage}</td>
    <td>${alertObj.residual}</td>
    <td class="${severity === 'CRITICAL' ? 'text-crimson' : 'text-amber'}">${alertObj.prob}</td>
    <td><span class="tag-badge ${severity === 'CRITICAL' ? 'tag-critical' : 'tag-high'}">${severity}</span></td>
    <td class="text-muted mono">${alertObj.action}</td>
  `;
  tbody.prepend(tr);
}

async function loadBenchmarks() {
  try {
    const res = await fetch("/api/v1/benchmarks");
    if (!res.ok) return;
    const benchmarks = await res.json();
    const grid = document.getElementById("benchmarkGrid");
    if (!grid) return;
    grid.innerHTML = "";

    benchmarks.forEach(b => {
      const wm = b.world_model || b.crit_stcm || b.crit_and || b.temporal || b.baseline || {};
      const bl = b.baseline || {};
      const card = document.createElement("div");
      card.className = "benchmark-card-mini";
      card.innerHTML = `
        <div class="benchmark-mini-header">
          <span class="scen-title">${b.scenario || 'Scenario'}</span>
          <span class="scen-meta mono">${b.mitre || ''}</span>
        </div>
        <div class="metric-comparison-row">
          <span class="metric-lbl">Accuracy</span>
          <span><strong class="val-wm mono">${((wm.acc || 0) * 100).toFixed(1)}%</strong> <span class="val-bl mono">/ ${((bl.acc || 0) * 100).toFixed(1)}%</span></span>
        </div>
        <div class="metric-comparison-row">
          <span class="metric-lbl">Recall</span>
          <span><strong class="val-wm mono">${((wm.rec || 0) * 100).toFixed(1)}%</strong> <span class="val-bl mono">/ ${((bl.rec || 0) * 100).toFixed(1)}%</span></span>
        </div>
        <div class="metric-comparison-row">
          <span class="metric-lbl">Precision</span>
          <span><strong class="val-wm mono">${((wm.prec || 0) * 100).toFixed(1)}%</strong> <span class="val-bl mono">/ ${((bl.prec || 0) * 100).toFixed(1)}%</span></span>
        </div>
        <div class="metric-comparison-row">
          <span class="metric-lbl">F1-Score</span>
          <span><strong class="val-wm mono">${(wm.f1 || 0).toFixed(3)}</strong> <span class="val-bl mono">/ ${(bl.f1 || 0).toFixed(3)}</span></span>
        </div>
        <div class="metric-comparison-row">
          <span class="metric-lbl">FPR (95% CI)</span>
          <span><strong class="val-wm mono">${((wm.fpr || 0) * 100).toFixed(1)}%</strong> <span class="scen-meta mono">${wm.fpr_ci || ''}</span></span>
        </div>
      `;
      grid.appendChild(card);
    });
  } catch (err) {
    console.error("Error loading benchmarks:", err);
  }
}

function togglePlay(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  if (STATE.isPlaying) {
    pausePlayback();
  } else {
    startPlayback();
  }
}

function startPlayback() {
  if (STATE.totalWindows > 0 && STATE.currentIndex >= STATE.totalWindows - 1) {
    goToWindow(0);
  }

  STATE.isPlaying = true;
  const btn = document.getElementById("btnPlay");
  if (btn) {
    btn.innerHTML = '<i data-lucide="pause"></i>';
    btn.title = "Pause Playback (Space)";
    btn.classList.add("playing");
    try { lucide.createIcons(); } catch (e) {}
  }

  if (STATE.playInterval) clearInterval(STATE.playInterval);
  const intervalMs = Math.max(150, 1000 / STATE.playSpeed);
  
  STATE.playInterval = setInterval(() => {
    if (!STATE.isPlaying) {
      clearInterval(STATE.playInterval);
      return;
    }
    const maxWin = STATE.totalWindows > 0 ? STATE.totalWindows : 1000;
    if (STATE.currentIndex < maxWin - 1) {
      goToWindow(STATE.currentIndex + 1);
    } else {
      goToWindow(0);
    }
  }, intervalMs);
}

function pausePlayback() {
  STATE.isPlaying = false;
  const btn = document.getElementById("btnPlay");
  if (btn) {
    btn.innerHTML = '<i data-lucide="play"></i>';
    btn.title = "Start Playback (Space)";
    btn.classList.remove("playing");
    try { lucide.createIcons(); } catch (e) {}
  }
  if (STATE.playInterval) {
    clearInterval(STATE.playInterval);
    STATE.playInterval = null;
  }
}

// Global Keyboard Navigation (Space = Play/Pause, Left = Prev, Right = Next)
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;
  if (e.code === "Space") {
    e.preventDefault();
    togglePlay();
  } else if (e.code === "ArrowLeft") {
    e.preventDefault();
    if (STATE.currentIndex > 0) goToWindow(STATE.currentIndex - 1);
  } else if (e.code === "ArrowRight") {
    e.preventDefault();
    const maxWin = STATE.totalWindows > 0 ? STATE.totalWindows : 1000;
    if (STATE.currentIndex < maxWin - 1) goToWindow(STATE.currentIndex + 1);
  }
});
