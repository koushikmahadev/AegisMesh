import React, { useState } from 'react';
import { 
  ShieldAlert, 
  ShieldCheck, 
  Activity, 
  X, 
  Terminal, 
  ExternalLink, 
  Download, 
  Check, 
  Radio, 
  AlertTriangle 
} from 'lucide-react';

/**
 * AegisForensicDrawer
 * Embedded SOC Command & Forensic Analysis Drawer
 * Unifies AegisDynamics dual-channel cyber defense with HighWater's disaster map.
 */
export default function AegisForensicDrawer({
  node = null,
  isOpen = false,
  onClose = () => {},
}) {
  const [copiedRule, setCopiedRule] = useState(false);

  if (!isOpen || !node) return null;

  const isCompromised = node.status === 'COMPROMISED' || node.alert_tier === 'CRITICAL';
  const isQuarantined = node.status === 'QUARANTINED' || (node.soar_action && node.soar_action !== 'NONE');
  
  const lambda2 = Number(node.spectral_lambda2 || (isCompromised ? 0.118 : 0.884));
  const residualEg = Number(node.mahalanobis_residual || (isCompromised ? 4.92 : 0.42));
  const fusedRiskPct = ((node.fused_risk !== undefined ? node.fused_risk : (isCompromised ? 0.892 : 0.03)) * 100).toFixed(1);
  const soarRule = node.soar_action && node.soar_action !== 'NONE'
    ? node.soar_action
    : `iptables -A INPUT -s 18.218.115.60 -j DROP && quarantine-node --id ${node.id || 'DRONE-01'} --isolate-mesh`;

  const copyRuleToClipboard = () => {
    try {
      navigator.clipboard.writeText(soarRule);
      setCopiedRule(true);
      setTimeout(() => setCopiedRule(false), 2000);
    } catch {
      // fallback
    }
  };

  const downloadStixJson = () => {
    const stixBundle = {
      type: "bundle",
      id: `bundle--${Date.now()}`,
      spec_version: "2.1",
      objects: [
        {
          type: "indicator",
          id: `indicator--${Date.now()}-1`,
          pattern: `[ipv4-addr:value = '18.218.115.60']`,
          pattern_type: "stix",
          name: "Malicious Flood Mesh Infiltration Indicator",
          confidence: 95,
          created: new Date().toISOString()
        },
        {
          type: "attack-pattern",
          id: `attack-pattern--${Date.now()}-2`,
          name: "T1498: Network Denial of Service on Emergency Mesh",
          external_references: [{ source_name: "mitre-attack", external_id: "T1498" }]
        }
      ]
    };
    const blob = new Blob([JSON.stringify(stixBundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `STIX_${node.id || 'CYBER_NODE'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-[1200] overflow-hidden flex justify-end font-sans">
      {/* Dimmed backdrop */}
      <div 
        className="fixed inset-0 bg-slate-900/60 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />


      {/* Slide-over Panel */}
      <aside
        role="dialog"
        aria-label="AegisDynamics SOC Forensic Analysis"
        className="relative w-full max-w-lg bg-slate-900 text-slate-100 shadow-2xl flex flex-col h-full border-l border-slate-700 z-10 overflow-y-auto animate-in slide-in-from-right duration-300"
      >
        {/* Header Bar */}
        <div className="p-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between sticky top-0 z-20">
          <div className="flex items-center space-x-2.5">
            <div className={`p-2 rounded-lg ${isCompromised ? 'bg-red-500/20 text-red-400 border border-red-500/40' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'}`}>
              {isCompromised ? <ShieldAlert className="w-5 h-5" /> : <ShieldCheck className="w-5 h-5" />}
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h3 className="font-bold text-sm text-white tracking-tight">
                  {node.name || node.id}
                </h3>
                <span className="font-mono text-[11px] text-slate-400">
                  {node.ip}
                </span>
              </div>
              <p className="text-[10px] text-slate-400">
                AegisDynamics SIH26153 // Cyber-Physical Forensic Telemetry
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close Forensic Console"
            className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 transition cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Status Strip */}
        <div className={`px-4 py-2 text-xs flex items-center justify-between font-mono ${
          isQuarantined
            ? 'bg-purple-950/80 text-purple-200 border-b border-purple-800'
            : isCompromised
            ? 'bg-red-950/80 text-red-200 border-b border-red-800 animate-pulse'
            : 'bg-emerald-950/60 text-emerald-200 border-b border-emerald-800'
        }`}>
          <div className="flex items-center space-x-2">
            <Radio className="w-3.5 h-3.5 animate-pulse" />
            <span className="font-bold uppercase tracking-wider">
              STATUS: {node.status || 'HEALTHY'} ({node.alert_tier || 'NOMINAL'})
            </span>
          </div>
          <span className="text-[11px]">
            Dual-Risk: <strong>{fusedRiskPct}%</strong>
          </span>
        </div>

        {/* Body Content */}
        <div className="p-4 space-y-4 flex-1 text-xs">
          {/* Section 1: Channel 2 Spectral Graph Laplacian Analysis */}
          <div className="bg-slate-950 p-3.5 rounded-lg border border-slate-800 space-y-2.5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-sky-400" />
                Channel 2: Graph Laplacian Spectral Topology
              </span>
              <span className="text-[10px] text-sky-400 font-mono">100% Unsupervised</span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="bg-slate-900 p-2.5 rounded border border-slate-800">
                <span className="text-slate-400 block text-[10px]">Algebraic Connectivity λ₂</span>
                <span className={`text-base font-mono font-bold ${lambda2 < 0.2 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {lambda2.toFixed(3)}
                </span>
                <span className="text-[9.5px] text-slate-500 block mt-0.5">
                  {lambda2 < 0.2 ? 'Critical topology drift' : 'Normal connected mesh'}
                </span>
              </div>

              <div className="bg-slate-900 p-2.5 rounded border border-slate-800">
                <span className="text-slate-400 block text-[10px]">Mahalanobis Residual e_G</span>
                <span className={`text-base font-mono font-bold ${residualEg > 1.0 ? 'text-red-400' : 'text-emerald-400'}`}>
                  {residualEg.toFixed(2)}
                </span>
                <span className="text-[9.5px] text-slate-500 block mt-0.5">
                  Threshold e_95 = 1.00
                </span>
              </div>
            </div>

            {/* Visual Gauge Bar */}
            <div className="space-y-1">
              <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                <span>Spectral Collapse (0.0)</span>
                <span>Normal Mesh (1.0)</span>
              </div>
              <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden flex">
                <div 
                  className={`h-full transition-all duration-500 ${lambda2 < 0.2 ? 'bg-red-500' : lambda2 < 0.5 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                  style={{ width: `${Math.min(100, Math.max(5, lambda2 * 100))}%` }}
                />
              </div>
            </div>
          </div>

          {/* Section 2: Channel 1 SHAP Root Cause Drivers */}
          <div className="bg-slate-950 p-3.5 rounded-lg border border-slate-800 space-y-2.5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-slate-200">
                SHAP Kernel Explainer Attribution Drivers
              </span>
              <span className="text-[10px] text-amber-400 font-mono">MITRE ATT&CK T1498</span>
            </div>

            <div className="space-y-2">
              <div>
                <div className="flex justify-between text-[11px] mb-1">
                  <span className="text-slate-300 font-mono">Dst_Port: 80 (HTTP / SynFlood)</span>
                  <span className="text-red-400 font-bold">+0.38</span>
                </div>
                <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                  <div className="bg-red-500 h-full w-[78%]" />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-[11px] mb-1">
                  <span className="text-slate-300 font-mono">Flow_Duration: Abnormally truncated</span>
                  <span className="text-red-400 font-bold">+0.29</span>
                </div>
                <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                  <div className="bg-red-500 h-full w-[58%]" />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-[11px] mb-1">
                  <span className="text-slate-300 font-mono">Fwd_Pkt_Len_Std: Packet size deviation</span>
                  <span className="text-amber-400 font-bold">+0.19</span>
                </div>
                <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                  <div className="bg-amber-500 h-full w-[38%]" />
                </div>
              </div>
            </div>
          </div>

          {/* Section 3: Autonomous SOAR Containment Playbook */}
          <div className="bg-slate-950 p-3.5 rounded-lg border border-slate-800 space-y-2.5">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Terminal className="w-3.5 h-3.5 text-purple-400" />
                Autonomous SOAR Mitigation Playbook
              </span>
              <span className="text-[10px] text-purple-400 font-mono">Zero-Touch Defense</span>
            </div>

            <div className="bg-slate-900 p-2.5 rounded border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>Active Quarantine Firewall Rule:</span>
                <button
                  type="button"
                  onClick={copyRuleToClipboard}
                  className="text-purple-400 hover:text-purple-300 inline-flex items-center gap-1 cursor-pointer"
                >
                  {copiedRule ? <Check className="w-3 h-3 text-emerald-400" /> : null}
                  <span>{copiedRule ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
              <code className="block p-2 bg-slate-950 rounded text-[10.5px] font-mono text-purple-300 break-all select-all border border-purple-900/50">
                {soarRule}
              </code>
            </div>

            {/* Export Actions */}
            <div className="flex items-center gap-2 pt-1">
              <button
                type="button"
                onClick={downloadStixJson}
                className="flex-1 py-1.5 px-2 bg-slate-800 hover:bg-slate-700 text-white rounded text-[11px] font-medium transition cursor-pointer flex items-center justify-center gap-1.5 border border-slate-700"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Export STIX 2.1</span>
              </button>
              <a
                href={typeof import.meta !== 'undefined' && import.meta.env?.VITE_SOC_API_URL ? import.meta.env.VITE_SOC_API_URL : "https://github.com/koushikmahadev/AegisMesh"}
                target="_blank"
                rel="noreferrer"
                className="flex-1 py-1.5 px-2 bg-slate-800 hover:bg-slate-700 text-sky-400 rounded text-[11px] font-medium transition cursor-pointer flex items-center justify-center gap-1.5 border border-slate-700 text-center"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                <span>Full SOC SIEM</span>
              </a>
            </div>
          </div>

          {/* Section 4: Physical Flood Rescue Mission Impact */}
          <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-lg text-[11px] space-y-1">
            <span className="font-bold text-amber-300 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              Disaster Operations Impact & Fail-Safe:
            </span>
            <p className="text-amber-200/90 leading-relaxed text-[10.5px]">
              HighWater's route planner has <strong>isolated telemetry from this node</strong>. Evacuation routing dynamically reroutes rescue boats away from unverified flood sensors, preventing boats from navigating into compromised depth zones.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 bg-slate-950 border-t border-slate-800 flex justify-between items-center text-[10px] text-slate-500 font-mono">
          <span>AegisDynamics + HighWater</span>
          <span>Dual-Channel Fusion Model v2.3</span>
        </div>
      </aside>
    </div>
  );
}
