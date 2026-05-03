import re
import sys

def main():
    file_path = "/home/ed/thesis/taltech-uav-mcp-server/src/uav_mcp_server/dashboard_ui.py"
    with open(file_path, "r") as f:
        content = f.read()

    # 1. Design Tokens
    content = re.sub(r'/\* ── Design Tokens ── \*/.*?}', """/* ── Design Tokens ── */
  :root {
    --bg-primary: #000000;
    --panel-bg: #1c1c1e;
    --panel-border: rgba(255, 255, 255, 0.05);
    --panel-shadow: none;
    --accent: #f5c518;
    --accent-dim: rgba(245, 197, 24, 0.15);
    --accent-hover: #ffda47;
    --accent-glow: transparent;
    --purple: #4a90e2;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text-main: #e0e0e0;
    --text-muted: #888888;
    --font: 'Outfit', system-ui, -apple-system, sans-serif;
    --radius: 8px;
    --radius-sm: 4px;
    --transition: 0.18s cubic-bezier(0.4, 0, 0.2, 1);
  }""", content, flags=re.DOTALL)

    # 2. Body
    content = re.sub(r'html, body \{.*?\n  \}', """html, body {
    width: 100%; height: 100%; overflow: hidden;
    background: var(--bg-primary);
    color: var(--text-main);
    font-family: var(--font);
    font-size: 12px;
    line-height: 1.35;
  }""", content, flags=re.DOTALL)

    # 3. Animations
    content = re.sub(r'@keyframes pulseGlow \{.*?\}', """@keyframes pulseGlow {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }""", content, flags=re.DOTALL)

    # 4. Shell
    content = re.sub(r'/\* ── Shell ── \*/\s*\.shell \{.*?\n  \}', """/* ── Shell ── */
  .shell {
    display: grid;
    grid-template-rows: auto 1fr;
    height: 100vh;
    padding: 16px;
    gap: 16px;
    margin: 0;
    animation: fadeIn 0.35s ease-out;
  }""", content, flags=re.DOTALL)

    # 5. Dashboard Grid
    content = re.sub(r'/\* ── Dashboard Grid ── \*/\s*\.dashboard \{.*?\.controls-panel\s*\{.*?\}', """/* ── Dashboard Grid ── */
  .dashboard {
    display: grid;
    grid-template-columns: 320px 1fr 340px;
    grid-template-rows: 1fr 280px;
    gap: 16px;
    height: 100%;
    min-height: 0;
  }

  /* ── Panel Base ── */
  .panel {
    display: flex; flex-direction: column;
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: var(--radius);
    overflow: hidden; min-height: 0;
  }
  .visual-panel   { grid-column: 1 / span 2; grid-row: 1; border: none; background: #000; }
  .visual-panel .panel-head { display: none; }
  .visual-panel .panel-body { padding: 0; }
  .camera-stage { border-radius: 0; border: none; height: 100%; }

  .map-panel      { grid-column: 1; grid-row: 2; }
  .commands-panel  { grid-column: 2; grid-row: 2; }
  .status-panel   { grid-column: 3; grid-row: 1; }
  .controls-panel  { grid-column: 3; grid-row: 2; }""", content, flags=re.DOTALL)

    # 6. Chips
    content = re.sub(r'\.chip \{(.*?)\.chip\.live \.dot(.*?\n)', """.chip {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 4px 10px; border-radius: 4px;
    background: rgba(255,255,255,0.05); border: 1px solid var(--panel-border);
    font-size: 10px; font-weight: 500; white-space: nowrap;
  }
  .chip .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); flex-shrink: 0; }
  .chip.ok .dot   { background: var(--success); }
  .chip.warn .dot  { background: var(--warning); }
  .chip.err .dot   { background: var(--danger); }
  .chip.live       { background: var(--accent-dim); border-color: rgba(245,197,24,0.15); color: var(--accent); }
  .chip.live .dot  { background: var(--accent); }
""", content, flags=re.DOTALL)

    # Buttons
    content = re.sub(r'\.action-btn\.primary:hover \{ background: var\(--accent-hover\);.*?\}', 
                     '.action-btn.primary:hover { background: var(--accent-hover); }', content)
    
    # 7. HTML monitor grid removal
    content = re.sub(r'<div class="monitor-grid">.*?</div>\s*<div class="card monitor-flags">', r'<div class="card monitor-flags">', content, flags=re.DOTALL)
    
    # HTML manual toggle removal
    content = re.sub(r'<label class="toggle"><input id="manual-toggle" type="checkbox"><span id="manual-status">Off</span></label>', r'<span id="manual-status" style="font-size:10px;color:var(--accent);font-weight:600;letter-spacing:0.1em;text-transform:uppercase;">Active</span>', content)

    # 8. JS Removals
    content = re.sub(r'function updateRuntimeHealth\(runtime\) \{.*?\}\n', '', content, flags=re.DOTALL)
    content = re.sub(r'function updateEvaluationSummary\(summary\) \{.*?\}\n', '', content, flags=re.DOTALL)
    content = re.sub(r'async function refreshMonitoring\(\) \{.*?\}\n', '', content, flags=re.DOTALL)
    content = re.sub(r'function startMonitoringPolling\(\) \{.*?\}\n', '', content, flags=re.DOTALL)
    
    content = re.sub(r'refreshMonitoring\(\);\s*', '', content)
    content = re.sub(r'startMonitoringPolling\(\);\s*', '', content)
    content = re.sub(r'if \(appState\.monitoring\.pollTimer\) window\.clearInterval\(appState\.monitoring\.pollTimer\);\s*', '', content)

    # 9. Update Manual Controls State
    content = content.replace("enabled: false,", "enabled: true,")

    new_update_manual = """function updateManualUI() {
    appState.manual.enabled = true;
    var caps = manualCapabilities();
    var statusEl = $('manual-status');
    if (statusEl && !statusEl.textContent.includes('Active')) statusEl.textContent = 'Active';
    var summaryEl = $('manual-summary');
    if (summaryEl) summaryEl.textContent = 'Keyboard active. Focus input to pause.';
    setChip('control-chip', 'live', 'Manual active');

    document.querySelectorAll('[data-manual-action]').forEach(function(button) {
      var action = button.dataset.manualAction;
      var supported = manualSupports(action);
      button.classList.toggle('unsupported', !supported);
      button.disabled = appState.commandBusy || !supported;
      if (!supported) button.title = manualTooltipFor(action);
    });

    var unsupported = [];
    if (!caps.supports_yaw) unsupported.push('yaw');
    if (!caps.supports_gimbal_pitch) unsupported.push('gimbal');
    if (unsupported.length && statusEl) {
      statusEl.textContent = 'Active (' + unsupported.join(', ') + ' N/A)';
    }
  }"""
    content = re.sub(r'function updateManualUI\(\) \{.*?\}\s*(?=async function sendManualAction)', new_update_manual + "\n\n  ", content, flags=re.DOTALL)

    content = re.sub(r"\$\('manual-toggle'\)\.addEventListener\('change', updateManualUI\);\s*", "", content)

    # Re-position Visual Footer (targeting tools)
    content = re.sub(r'\.camera-placeholder\.hidden \{ display: none; \}', """.camera-placeholder.hidden { display: none; }
  .visual-footer { position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); width: 400px; z-index: 20; background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: var(--radius); padding: 12px; backdrop-filter: blur(10px); }""", content)

    with open(file_path, "w") as f:
        f.write(content)
        
    print("Dashboard UI rewritten successfully.")

if __name__ == "__main__":
    main()
