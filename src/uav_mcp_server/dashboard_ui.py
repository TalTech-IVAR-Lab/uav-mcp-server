"""Inline operator dashboard HTML with embedded CSS and JavaScript.

The page stays self-contained in a single response while using MapLibre GL JS
from a CDN for the live 3D map layer.
"""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UAV MCP Dashboard</title>
<meta name="description" content="Real-time UAV operator dashboard with telemetry, map, camera targeting, and AI-assisted command execution.">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@^4.7.1/dist/maplibre-gl.css" crossorigin="">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  /* ── Design Tokens ── */
  :root {
    --bg-primary: #05050a;
    --bg-radial: radial-gradient(ellipse at 50% -20%, #12132a 0%, #05050a 70%);
    --panel-bg: rgba(10, 12, 22, 0.55);
    --panel-border: rgba(255, 255, 255, 0.07);
    --panel-shadow: 0 4px 24px rgba(0, 0, 0, 0.5);
    --accent: #00e5ff;
    --accent-dim: rgba(0, 229, 255, 0.12);
    --accent-hover: #00b8d4;
    --accent-glow: rgba(0, 229, 255, 0.45);
    --purple: #9d4edd;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text-main: #f0f4f8;
    --text-muted: #7e8fa6;
    --font: 'Outfit', system-ui, -apple-system, sans-serif;
    --radius: 10px;
    --radius-sm: 6px;
    --transition: 0.18s cubic-bezier(0.4, 0, 0.2, 1);
  }

  html, body {
    width: 100%; height: 100%; overflow: hidden;
    background: var(--bg-radial);
    color: var(--text-main);
    font-family: var(--font);
    font-size: 12px;
    line-height: 1.35;
  }

  /* ── Animations ── */
  @keyframes pulseGlow {
    0%, 100% { box-shadow: 0 0 4px var(--accent-glow); }
    50% { box-shadow: 0 0 14px var(--accent-glow); }
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }

  /* ── Shell ── */
  .shell {
    display: grid;
    grid-template-rows: auto 1fr;
    height: 100vh;
    padding: 6px 12px 12px;
    gap: 8px;
    max-width: 1920px;
    margin: 0 auto;
    animation: fadeIn 0.35s ease-out;
  }

  /* ── Top Bar ── */
  .topbar {
    display: flex; justify-content: space-between; align-items: center;
    background: var(--panel-bg); backdrop-filter: blur(16px);
    border: 1px solid var(--panel-border); border-radius: var(--radius);
    padding: 6px 16px;
  }
  .title-block .eyebrow {
    color: var(--accent); font-weight: 600; font-size: 9px;
    text-transform: uppercase; letter-spacing: 0.15em;
  }
  .title-block h1 {
    font-size: 15px; font-weight: 700; margin: 1px 0 0;
    background: linear-gradient(135deg, #fff 30%, var(--accent));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  /* ── Status Chips ── */
  .status-strip { display: flex; gap: 8px; flex-wrap: wrap; }
  .chip {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 10px; border-radius: 12px;
    background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.04);
    font-size: 10px; font-weight: 500; white-space: nowrap;
  }
  .chip .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--text-muted); flex-shrink: 0; }
  .chip.ok .dot   { background: var(--success); box-shadow: 0 0 6px var(--success); }
  .chip.warn .dot  { background: var(--warning); box-shadow: 0 0 6px var(--warning); }
  .chip.err .dot   { background: var(--danger);  box-shadow: 0 0 6px var(--danger); }
  .chip.live       { background: var(--accent-dim); border-color: rgba(0,229,255,0.15); }
  .chip.live .dot  { background: var(--accent);  box-shadow: 0 0 6px var(--accent); }

  /* ── Dashboard Grid ── */
  .dashboard {
    display: grid;
    grid-template-columns: minmax(340px, 1fr) minmax(300px, 0.85fr) minmax(280px, 0.75fr);
    grid-template-rows: minmax(0, 1.15fr) minmax(0, 0.85fr);
    gap: 8px;
    height: 100%;
    min-height: 0;
    grid-template-areas:
      "visual map    status"
      "visual commands controls";
  }

  /* ── Panel Base ── */
  .panel {
    display: flex; flex-direction: column;
    background: var(--panel-bg); backdrop-filter: blur(20px);
    border: 1px solid var(--panel-border); border-radius: var(--radius);
    box-shadow: var(--panel-shadow);
    overflow: hidden; min-height: 0;
  }
  .visual-panel   { grid-area: visual; }
  .map-panel      { grid-area: map; }
  .status-panel   { grid-area: status; }
  .commands-panel  { grid-area: commands; }
  .controls-panel  { grid-area: controls; }

  .panel-head {
    display: flex; justify-content: space-between; align-items: center;
    padding: 7px 12px;
    background: rgba(255,255,255,0.015);
    border-bottom: 1px solid var(--panel-border);
    flex-shrink: 0;
  }
  .panel-title {
    font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.1em;
    color: rgba(255,255,255,0.85);
  }
  .panel-body {
    padding: 8px 10px; flex: 1; min-height: 0;
    overflow-y: auto; display: flex; flex-direction: column;
  }

  /* ── Buttons ── */
  button { cursor: pointer; font-family: var(--font); }
  .action-btn {
    padding: 4px 10px; font-weight: 500; font-size: 11px;
    border: 1px solid var(--panel-border);
    background: rgba(255,255,255,0.03); color: var(--text-main);
    border-radius: var(--radius-sm);
    transition: all var(--transition);
  }
  .action-btn:hover { background: rgba(255,255,255,0.07); border-color: rgba(255,255,255,0.15); }
  .action-btn:active { transform: scale(0.97); }
  .action-btn:disabled { opacity: 0.35; cursor: not-allowed; transform: none; }
  .action-btn.primary {
    background: var(--accent); color: #000; border: none; font-weight: 600;
  }
  .action-btn.primary:hover { background: var(--accent-hover); box-shadow: 0 2px 10px var(--accent-glow); }
  .action-btn.secondary { background: transparent; border: 1px solid var(--accent); color: var(--accent); }
  .action-btn.secondary:hover { background: var(--accent-dim); }

  /* ── Inputs ── */
  .field-input {
    width: 100%; border-radius: var(--radius-sm);
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(0,0,0,0.35); color: var(--text-main);
    font-family: var(--font); padding: 5px 8px; font-size: 11px;
    outline: none; transition: border-color var(--transition);
  }
  .field-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(0,229,255,0.08); }
  .field-group { display: flex; flex-direction: column; gap: 2px; }
  .field-label {
    font-size: 9px; text-transform: uppercase;
    color: var(--text-muted); font-weight: 600; letter-spacing: 0.05em;
  }

  /* ── Cards ── */
  .card {
    background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.04);
    border-radius: 8px; padding: 6px 10px;
  }
  .card-title {
    color: var(--text-muted); font-size: 9px;
    text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;
  }

  /* ── State Pills ── */
  .state-pill {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 2px 6px; border-radius: 4px;
    font-size: 9px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
  }
  .state-disconnected { color: var(--danger); background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.25); }
  .state-connected, .state-ready { color: var(--success); background: rgba(16,185,129,0.12); border: 1px solid rgba(16,185,129,0.25); }
  .state-armed { color: var(--warning); background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.25); }
  .state-airborne { color: var(--accent); background: var(--accent-dim); border: 1px solid rgba(0,229,255,0.25); }
  .state-landing { color: var(--purple); background: rgba(157,78,221,0.12); border: 1px solid rgba(157,78,221,0.25); }
  .state-fault { color: var(--danger); background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.25); }

  /* ── Camera / Visual Targeting ── */
  .camera-shell { display: flex; flex-direction: column; height: 100%; gap: 6px; }
  .camera-toolbar { display: flex; justify-content: space-between; align-items: center; }
  .camera-stage {
    position: relative; flex: 1; min-height: 120px;
    border-radius: 8px; overflow: hidden;
    border: 1px solid var(--panel-border);
    background: #020304;
  }
  .camera-stream { width: 100%; height: 100%; object-fit: cover; }
  .camera-overlay { position: absolute; inset: 0; cursor: crosshair; touch-action: none; }
  .crosshair {
    position: absolute; left: 50%; top: 50%; width: 24px; height: 24px;
    transform: translate(-50%, -50%);
    border: 1px solid rgba(0,229,255,0.35); border-radius: 50%;
    pointer-events: none;
  }
  .crosshair::before, .crosshair::after { content: ""; position: absolute; background: rgba(0,229,255,0.5); }
  .crosshair::before { left: 50%; top: -4px; width: 1px; height: 32px; transform: translateX(-50%); }
  .crosshair::after  { top: 50%; left: -4px; width: 32px; height: 1px; transform: translateY(-50%); }
  .selection-box { position: absolute; display: none; border: 1px solid var(--accent); background: rgba(0,229,255,0.08); }
  .selection-box.visible { display: block; animation: pulseGlow 2s infinite; }
  .camera-placeholder {
    position: absolute; inset: 0; display: flex; align-items: center;
    justify-content: center; text-align: center; color: var(--text-muted);
    font-size: 11px;
    background: radial-gradient(circle, rgba(10,12,22,0.85), rgba(0,0,0,0.95));
  }
  .camera-placeholder.hidden { display: none; }
  .visual-footer { display: flex; flex-direction: column; gap: 6px; }
  .target-line { display: flex; justify-content: space-between; align-items: center; padding: 1px 0; }
  .target-line span { color: var(--text-muted); font-size: 10px; }
  .target-line strong { font-weight: 500; font-size: 10px; }

  /* ── Telemetry Matrix ── */
  .status-panel .panel-body { gap: 6px; }
  .telemetry-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .metric {
    background: linear-gradient(145deg, rgba(255,255,255,0.02), rgba(0,0,0,0.15));
    border: 1px solid rgba(255,255,255,0.025);
    border-radius: 8px; padding: 6px 8px;
  }
  .metric-label { color: var(--text-muted); font-size: 8px; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }
  .metric-value { font-size: 13px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
  .metric-sub { margin-top: 1px; color: var(--text-muted); font-size: 9px; }
  .monitor-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .monitor-card { display: flex; flex-direction: column; gap: 2px; min-height: 0; }
  .monitor-card strong { max-width: 145px; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .flag-strip { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .monitor-flags { display: flex; flex-direction: column; gap: 4px; }

  /* ── Event Matrix (inside telemetry) ── */
  .events-section { flex: 1; display: flex; flex-direction: column; overflow: hidden; margin-top: 4px; }
  .events { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 1px; }
  .event-row {
    padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.025);
    display: grid; grid-template-columns: 52px 60px 1fr; gap: 4px; font-size: 10px;
  }
  .event-time { color: var(--text-muted); font-family: monospace; font-size: 9px; }
  .event-kind { color: var(--accent); font-size: 9px; }
  .event-msg  { color: var(--text-main); font-size: 9px; }
  .event-ok .event-msg { color: var(--success); }
  .event-err .event-msg { color: var(--danger); }

  /* ── Map ── */
  .map-shell { display: flex; flex-direction: column; height: 100%; gap: 6px; }
  .map-surface { flex: 1; min-height: 80px; border-radius: 8px; overflow: hidden; border: 1px solid var(--panel-border); }
  #map { width: 100%; height: 100%; filter: contrast(1.1) brightness(0.8) sepia(0.25) hue-rotate(180deg) saturate(1.4); }
  .map-footer { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px; }
  .legend-row { display: flex; align-items: center; gap: 3px; color: var(--text-muted); font-size: 10px; }
  .legend-swatch { width: 8px; height: 8px; border-radius: 50%; }
  .swatch-drone  { background: var(--accent); }
  .swatch-home   { background: var(--success); }
  .swatch-target { background: var(--warning); }
  .swatch-fence  { background: rgba(0,229,255,0.4); border: 1px solid var(--accent); }
  .maplibregl-map { background: transparent !important; }
  .drone-icon {
    width: 20px; height: 20px; border-radius: 50%;
    border: 2px solid #fff; background: var(--accent);
    box-shadow: 0 0 8px var(--accent); position: relative;
  }
  .drone-icon::after {
    content: ''; position: absolute; top: 0; left: 50%;
    transform: translateX(-50%) translateY(-50%);
    width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 7px solid #fff;
  }
  .home-icon   { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff; background: var(--success); }
  .target-icon { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff; background: var(--warning); animation: pulseGlow 2s infinite; }

  /* ── Command Execution Panel ── */
  .command-shell { display: flex; flex-direction: column; gap: 6px; height: 100%; }
  .tabs { display: flex; border-bottom: 1px solid var(--panel-border); gap: 0; flex-shrink: 0; }
  .tab-btn {
    background: none; border: none; border-bottom: 2px solid transparent;
    color: var(--text-muted); padding: 6px 14px;
    font-size: 11px; font-weight: 500; border-radius: 0;
    transition: color var(--transition);
  }
  .tab-btn:hover { color: var(--text-main); }
  .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-content { flex: 1; min-height: 0; overflow-y: auto; }

  .command-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; }
  .cmd-btn {
    padding: 6px 4px; display: flex; flex-direction: column; gap: 2px;
    align-items: center; text-align: center;
    border: 1px solid var(--panel-border);
    background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent);
    color: var(--text-main); border-radius: var(--radius-sm);
    font-family: var(--font); transition: all var(--transition);
  }
  .cmd-btn:hover { background: rgba(255,255,255,0.06); transform: translateY(-1px); }
  .cmd-btn:active { transform: scale(0.97); }
  .cmd-btn:disabled { opacity: 0.35; cursor: not-allowed; transform: none; }
  .cmd-label { font-size: 10px; font-weight: 600; }
  .cmd-meta  { font-size: 8px; color: var(--text-muted); letter-spacing: 0.08em; }
  .cmd-safe   { border-left: 2px solid var(--success); }
  .cmd-danger { border-left: 2px solid var(--danger); }
  .cmd-ghost  { border-left: 2px solid var(--text-muted); }
  .field-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }

  /* ── Manual Override Panel ── */
  .controls-shell { display: flex; flex-direction: column; gap: 4px; height: 100%; }
  .result-bar {
    padding: 5px 10px; border-radius: var(--radius-sm);
    font-size: 11px; font-weight: 500;
    background: rgba(0,0,0,0.25); border: 1px solid transparent;
    flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .result-bar.ok   { background: rgba(16,185,129,0.08); border-color: var(--success); color: var(--success); }
  .result-bar.err  { background: rgba(239,68,68,0.08); border-color: var(--danger); color: var(--danger); }
  .result-bar.info { background: var(--accent-dim); border-color: rgba(0,229,255,0.2); color: var(--accent); }
  .result-bar.connecting {
    background: rgba(245,158,11,0.08); border-color: var(--warning); color: var(--warning);
  }
  .result-bar.connecting::after {
    content: ''; display: inline-block; width: 10px; height: 10px;
    border: 2px solid var(--warning); border-top-color: transparent;
    border-radius: 50%; animation: spin 0.8s linear infinite;
    margin-left: 8px; vertical-align: middle;
  }

  .manual-core {
    display: grid;
    grid-template-columns: auto auto;
    gap: 4px 16px;
    justify-content: center;
    align-items: start;
  }
  .manual-group-label {
    font-size: 9px; font-weight: 600; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.08em;
    text-align: center; margin-bottom: 2px;
  }
  .manual-pad {
    display: grid; grid-template-columns: repeat(3, 32px);
    grid-template-rows: repeat(2, 32px); gap: 3px; justify-content: center;
  }
  .key-w  { grid-column: 2; grid-row: 1; }
  .key-a  { grid-column: 1; grid-row: 2; }
  .key-s  { grid-column: 2; grid-row: 2; }
  .key-d  { grid-column: 3; grid-row: 2; }
  .key-up    { grid-column: 2; grid-row: 1; }
  .key-left  { grid-column: 1; grid-row: 2; }
  .key-down  { grid-column: 2; grid-row: 2; }
  .key-right { grid-column: 3; grid-row: 2; }

  .key-btn {
    display: flex; align-items: center; justify-content: center;
    border-radius: 4px; width: 32px; height: 32px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.08);
    transition: all 0.1s; padding: 0;
    color: var(--text-main); font-family: var(--font);
  }
  .key-cap { font-family: monospace; font-size: 12px; font-weight: 700; line-height: 1; }
  .key-btn.active { background: rgba(0,229,255,0.2); border-color: var(--accent); transform: scale(0.92); }
  .key-btn:active { transform: scale(0.92); }
  .key-btn.unsupported { opacity: 0.2; pointer-events: none; }

  .manual-aux {
    display: flex; gap: 4px; align-items: center; justify-content: center;
  }
  .key-btn-sm {
    display: flex; align-items: center; justify-content: center;
    width: 28px; height: 24px; border-radius: 4px;
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
    transition: all 0.1s; padding: 0;
    color: var(--text-main); font-family: var(--font); cursor: pointer;
  }
  .key-btn-sm .key-cap { font-size: 11px; }
  .key-btn-sm.unsupported { opacity: 0.2; pointer-events: none; }
  .key-btn-sm.active { background: rgba(0,229,255,0.2); border-color: var(--accent); }

  .manual-bottom {
    display: grid; grid-template-columns: auto 1fr auto 1fr; gap: 4px;
    align-items: center; margin-top: 2px;
  }
  .manual-bottom .field-input { padding: 3px 6px; font-size: 10px; }
  .manual-bottom .field-label { font-size: 8px; }

  .quick-bar { display: flex; gap: 4px; margin-top: auto; }
  .quick-bar .field-input { flex: 1; padding: 4px 8px; font-size: 10px; }
  .quick-bar .action-btn { padding: 4px 8px; font-size: 10px; }

  .manual-meta { font-size: 9px; color: var(--text-muted); text-align: center; }

  /* ── Chat / AI Panel ── */
  .chat-card {
    display: flex; flex-direction: column; flex: 1; min-height: 0;
    background: rgba(0,0,0,0.15); border: 1px solid rgba(255,255,255,0.04);
    border-radius: 8px; overflow: hidden;
  }
  .chat-head {
    display: flex; justify-content: space-between; align-items: center;
    padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.04);
    flex-shrink: 0;
  }
  .chat-body { padding: 6px 8px; display: flex; flex-direction: column; gap: 6px; flex: 1; min-height: 0; }
  .chat-log { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
  .chat-empty { color: var(--text-muted); font-size: 10px; text-align: center; margin-top: 16px; }
  .chat-row {
    padding: 6px 8px; border-radius: 8px; font-size: 11px; line-height: 1.35;
    background: rgba(255,255,255,0.02); border-left: 2px solid transparent;
  }
  .chat-row.operator { border-color: var(--accent); align-self: flex-end; background: rgba(0,229,255,0.04); max-width: 88%; }
  .chat-row.assistant { border-color: var(--success); max-width: 88%; }
  .chat-row.system    { border-color: var(--text-muted); font-size: 10px; color: var(--text-muted); }
  .chat-role { font-size: 8px; text-transform: uppercase; margin-bottom: 2px; opacity: 0.6; }
  .trace-list { margin-top: 4px; display: flex; flex-direction: column; gap: 3px; }
  .trace-item { padding: 4px; background: rgba(0,0,0,0.3); border-radius: 4px; font-family: monospace; font-size: 9px; }
  .trace-item.ok  { border-left: 2px solid var(--success); }
  .trace-item.err { border-left: 2px solid var(--danger); }

  .chat-compose { display: flex; gap: 4px; align-items: stretch; flex-shrink: 0; }
  .confirm-bar {
    display: none; padding: 5px 8px; font-size: 10px;
    background: rgba(245,158,11,0.08); border: 1px solid var(--warning);
    border-radius: var(--radius-sm); justify-content: space-between; align-items: center;
    flex-shrink: 0;
  }
  .confirm-bar.visible { display: flex; }

  .voice-btn {
    background: rgba(0,229,255,0.08); border: 1px solid rgba(0,229,255,0.2);
    border-radius: var(--radius-sm); color: var(--accent);
    padding: 0 8px; cursor: pointer; transition: all var(--transition);
    font-size: 14px; line-height: 1;
  }
  .voice-btn:hover { background: rgba(0,229,255,0.15); }
  .voice-btn.recording { background: var(--danger); border-color: var(--danger); color: #fff; animation: pulseGlow 1s infinite; }

  /* ── Toggles ── */
  .toggle { display: flex; align-items: center; gap: 5px; color: var(--text-main); font-size: 10px; }
  input[type="checkbox"] { accent-color: var(--accent); width: 12px; height: 12px; }

  /* ── Utilities ── */
  .flex-row { display: flex; gap: 6px; }
  .text-muted { color: var(--text-muted); }
  #map-summary { font-size: 10px; color: var(--text-main); margin-bottom: 4px; }
</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <div class="title-block">
      <div class="eyebrow">Advanced Operator Surface</div>
      <h1>UAV MCP Interface</h1>
    </div>
    <div class="status-strip">
      <a href="/dashboard/observability/" class="chip live" style="text-decoration:none;"><span class="dot"></span><span>Observability</span></a>
      <div id="state-chip" class="chip"><span class="dot"></span><span>Initializing</span></div>
      <div id="conn-chip" class="chip err"><span class="dot"></span><span>Backend offline</span></div>
      <div id="camera-chip" class="chip warn"><span class="dot"></span><span>Camera pending</span></div>
      <div id="control-chip" class="chip"><span class="dot"></span><span>Manual locked</span></div>
    </div>
  </header>

  <main class="dashboard">
    <!-- ═══ Visual Targeting ═══ -->
    <article class="panel visual-panel">
      <div class="panel-head">
        <div class="panel-title">Visual Targeting</div>
        <span id="camera-topic" class="chip"><span class="dot"></span><span>Route pending</span></span>
      </div>
      <div class="panel-body camera-shell">
        <div class="camera-toolbar">
          <div class="flex-row">
            <button id="clear-selection" class="action-btn" type="button">Clear</button>
            <button id="project-center" class="action-btn" type="button">Lock Center</button>
          </div>
          <span id="selection-status" class="chip"><span class="dot"></span><span>No target</span></span>
        </div>
        <div class="camera-stage">
          <img id="camera-stream" class="camera-stream" alt="">
          <div id="camera-placeholder" class="camera-placeholder">Live feed unavailable.</div>
          <div id="camera-overlay" class="camera-overlay">
            <div class="crosshair"></div>
            <div id="selection-box" class="selection-box"></div>
          </div>
        </div>
        <div class="visual-footer">
          <div class="card">
            <div class="card-title" style="margin-bottom:3px;">Reticle Target</div>
            <div class="target-line"><span>Optical</span><strong id="selection-body">Select on video feed</strong></div>
            <div class="target-line"><span>Spatial</span><strong id="map-target-body">Define via map click</strong></div>
            <div class="flex-row" style="margin-top:4px;">
              <button id="orbit-selection" class="action-btn primary" style="flex:1" disabled>Orbit Optic</button>
              <button id="approach-selection" class="action-btn secondary" style="flex:1" disabled>Approach Optic</button>
            </div>
          </div>
        </div>
      </div>
    </article>

    <!-- ═══ Spatial Awareness (Map) ═══ -->
    <article class="panel map-panel">
      <div class="panel-head">
        <div class="panel-title">Spatial Awareness</div>
        <label class="toggle"><input id="auto-center" type="checkbox" checked><span>Track Asset</span></label>
      </div>
      <div class="panel-body map-shell">
        <div class="map-surface"><div id="map"></div></div>
        <div class="map-footer">
          <div class="card">
            <div class="card-title">Nav Solution</div>
            <div id="map-summary" style="margin: 2px 0 4px;">Waiting for data stream.</div>
            <div class="flex-row">
              <button id="map-target-clear" class="action-btn" type="button">Reset</button>
              <button id="map-target-orbit" class="action-btn primary" type="button" disabled>Orbit</button>
              <button id="map-target-approach" class="action-btn secondary" type="button" disabled>Approach</button>
            </div>
          </div>
          <div class="card" style="display:flex; flex-direction:column; justify-content:center;">
            <div class="card-title" style="margin-bottom:4px;">Symbology</div>
            <div class="legend">
              <div class="legend-row"><span class="legend-swatch swatch-drone"></span>Asset</div>
              <div class="legend-row"><span class="legend-swatch swatch-home"></span>Home</div>
              <div class="legend-row"><span class="legend-swatch swatch-target"></span>Objective</div>
              <div class="legend-row"><span class="legend-swatch swatch-fence"></span>Geofence</div>
            </div>
          </div>
        </div>
      </div>
    </article>

    <!-- ═══ Telemetry Matrix ═══ -->
    <article class="panel status-panel">
      <div class="panel-head">
        <div class="panel-title">Telemetry Matrix</div>
      </div>
      <div class="panel-body">
        <div class="telemetry-grid">
          <div class="metric"><div class="metric-label">State</div><div class="metric-value"><span id="t-state" class="state-pill state-disconnected">OFFLINE</span></div><div class="metric-sub" id="t-flight-mode">--</div></div>
          <div class="metric"><div class="metric-label">Power</div><div class="metric-value" id="t-battery">--%</div><div class="metric-sub" id="t-gps">--</div></div>
          <div class="metric"><div class="metric-label">Altitude</div><div class="metric-value" id="t-rel-alt">-- m</div><div class="metric-sub" id="t-abs-alt">--</div></div>
          <div class="metric"><div class="metric-label">Position</div><div class="metric-value" id="t-lat">--</div><div class="metric-sub" id="t-lon">--</div></div>
          <div class="metric"><div class="metric-label">Attitude</div><div class="metric-value" id="t-yaw">--</div><div class="metric-sub" id="t-pitch">--</div></div>
          <div class="metric"><div class="metric-label">Roll / Flags</div><div class="metric-value" id="t-roll">--</div><div class="metric-sub" id="t-flags">--</div></div>
        </div>
        <div class="monitor-grid">
          <div class="card monitor-card">
            <div class="card-title">Runtime Context</div>
            <div class="target-line"><span>Airframe</span><strong id="runtime-airframe">--</strong></div>
            <div class="target-line"><span>World</span><strong id="runtime-world">--</strong></div>
            <div class="target-line"><span>Stack</span><strong id="runtime-stack">--</strong></div>
            <div class="metric-sub" id="runtime-stack-sub">Waiting for runtime metadata.</div>
          </div>
          <div class="card monitor-card">
            <div class="card-title">Stack Health</div>
            <div class="target-line"><span>Camera</span><strong id="runtime-camera">--</strong></div>
            <div class="target-line"><span>Gimbal</span><strong id="runtime-gimbal">--</strong></div>
            <div class="target-line"><span>Telemetry</span><strong id="runtime-telemetry">--</strong></div>
            <div class="metric-sub" id="runtime-health-sub">Read-only component checks only.</div>
          </div>
          <div class="card monitor-card">
            <div class="card-title">Thesis Evaluation</div>
            <div class="target-line"><span>Latest</span><strong id="eval-latest">No results</strong></div>
            <div class="target-line"><span>Latency</span><strong id="eval-latency">--</strong></div>
            <div class="target-line"><span>Reliability</span><strong id="eval-reliability">--</strong></div>
            <div class="target-line"><span>Safety</span><strong id="eval-safety">--</strong></div>
            <div class="metric-sub" id="eval-sub">Run CLI benchmarks to populate evaluation/results.</div>
          </div>
        </div>
        <div class="card monitor-flags">
          <div class="card-title">Readiness Flags</div>
          <div class="flag-strip">
            <div id="flag-link" class="chip"><span class="dot"></span><span>Link pending</span></div>
            <div id="flag-pose" class="chip"><span class="dot"></span><span>Pose pending</span></div>
            <div id="flag-preflight" class="chip"><span class="dot"></span><span>Preflight pending</span></div>
            <div id="flag-camera" class="chip"><span class="dot"></span><span>Camera pending</span></div>
            <div id="flag-gimbal" class="chip"><span class="dot"></span><span>Gimbal pending</span></div>
            <div id="flag-eval" class="chip"><span class="dot"></span><span>Eval pending</span></div>
          </div>
          <div class="metric-sub" id="readiness-summary">Monitoring surface warming up.</div>
        </div>
        <div class="events-section card" style="margin-top:6px;">
          <div class="card-title" style="margin-bottom:3px;">Event Matrix</div>
          <div id="events" class="events"></div>
        </div>
      </div>
    </article>

    <!-- ═══ Command Execution ═══ -->
    <article class="panel commands-panel">
      <div class="panel-head">
        <div class="panel-title">Command Execution</div>
        <span id="command-summary" class="text-muted" style="font-size:9px;">Loading...</span>
      </div>
      <div class="panel-body command-shell" style="padding-top:0;">
        <div class="tabs">
          <button class="tab-btn active" id="tab-cmd">Commands</button>
          <button class="tab-btn" id="tab-ai">AI Assistant</button>
        </div>

        <div id="panel-cmd" class="tab-content">
          <div id="command-grid" class="command-grid"></div>
          <div class="field-grid" style="margin-top:8px;">
            <label class="field-group"><span class="field-label">Takeoff Alt</span><input id="p-alt" class="field-input" type="number" value="5" step="0.5"></label>
            <label class="field-group"><span class="field-label">Vector N</span><input id="p-north" class="field-input" type="number" value="5" step="1"></label>
            <label class="field-group"><span class="field-label">Vector E</span><input id="p-east" class="field-input" type="number" value="0" step="1"></label>
            <label class="field-group"><span class="field-label">Goto Alt</span><input id="p-goto-alt" class="field-input" type="number" value="5" step="0.5"></label>
            <label class="field-group"><span class="field-label">Orbit Radius</span><input id="p-orbit-radius" class="field-input" type="number" value="12" step="1"></label>
            <label class="field-group"><span class="field-label">Velocity</span><input id="p-orbit-speed" class="field-input" type="number" value="3" step="0.5"></label>
          </div>
        </div>

        <div id="panel-ai" class="tab-content" style="display:none; flex-direction:column;">
          <div class="chat-card">
            <div class="chat-head">
              <div class="card-title" style="margin:0;">Assistant Uplink</div>
              <label class="toggle"><input id="assistant-bypass" type="checkbox"><span>Auto-Exec</span></label>
            </div>
            <div class="chat-body">
              <div id="chat-log" class="chat-log"><div class="chat-empty">Ready. Use mic or type a command.</div></div>
              <div class="confirm-bar" id="assistant-confirm-bar">
                <div id="assistant-confirm-text" style="font-size:10px;"></div>
                <button id="assistant-confirm" class="action-btn primary" disabled>Commit</button>
              </div>
              <div class="chat-compose">
                <button id="voice-cmd-btn" class="voice-btn" title="Voice input">&#x1F3A4;</button>
                <input id="assistant-input" class="field-input" style="flex:1;" type="text" placeholder="Enter command..." autocomplete="off">
                <button id="assistant-preview" class="action-btn secondary">Preview</button>
                <button id="assistant-run" class="action-btn primary">Send</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </article>

    <!-- ═══ Manual Override ═══ -->
    <article class="panel controls-panel">
      <div class="panel-head">
        <div class="panel-title">Manual Override</div>
        <label class="toggle"><input id="manual-toggle" type="checkbox"><span id="manual-status">Off</span></label>
      </div>
      <div class="panel-body controls-shell">
        <div id="result-bar" class="result-bar">Awaiting backend connection...</div>

        <div class="manual-core">
          <div>
            <div class="manual-group-label">WASD Translate</div>
            <div class="manual-pad">
              <button class="key-btn key-w" data-manual-action="move_forward"><span class="key-cap">W</span></button>
              <button class="key-btn key-a" data-manual-action="move_left"><span class="key-cap">A</span></button>
              <button class="key-btn key-s" data-manual-action="move_back"><span class="key-cap">S</span></button>
              <button class="key-btn key-d" data-manual-action="move_right"><span class="key-cap">D</span></button>
            </div>
          </div>
          <div>
            <div class="manual-group-label">Alt / Yaw</div>
            <div class="manual-pad">
              <button class="key-btn key-up" data-manual-action="altitude_up"><span class="key-cap">&#x25B2;</span></button>
              <button class="key-btn key-left" data-manual-action="yaw_left"><span class="key-cap">&#x25C0;</span></button>
              <button class="key-btn key-down" data-manual-action="altitude_down"><span class="key-cap">&#x25BC;</span></button>
              <button class="key-btn key-right" data-manual-action="yaw_right"><span class="key-cap">&#x25B6;</span></button>
            </div>
          </div>
        </div>

        <div class="manual-aux">
          <button class="key-btn-sm" data-manual-action="gimbal_up"><span class="key-cap">Q</span></button>
          <span class="manual-group-label" style="margin:0 4px;">Gimbal</span>
          <button class="key-btn-sm" data-manual-action="gimbal_down"><span class="key-cap">E</span></button>
        </div>

        <div class="manual-bottom">
          <span class="field-label">XY</span>
          <input id="manual-step" class="field-input" type="number" value="3" min="0.5" step="0.5">
          <span class="field-label">Z</span>
          <input id="manual-alt-step" class="field-input" type="number" value="1.5" min="0.5" step="0.5">
        </div>

        <div class="quick-bar">
          <input id="quick-command-input" class="field-input" type="text" placeholder="Quick command..." autocomplete="off">
          <button id="quick-command-submit" class="action-btn">Run</button>
        </div>

        <div class="manual-meta" id="manual-summary">Enable toggle to accept keyboard controls.</div>
      </div>
    </article>
  </main>
</div>

<script src="https://unpkg.com/maplibre-gl@^4.7.1/dist/maplibre-gl.js" crossorigin=""></script>
<script>
(function(){
  'use strict';

  /* ── Application State ── */
  const appState = {
    config: null,
    telemetry: null,
    commands: [],
    history: [],
    mapTarget: null,
    commandBusy: false,
    selectionBusy: false,
    telemetryES: null,
    eventsES: null,
    selection: null,
    selecting: false,
    selectionStart: null,
    map: null,
    mapReady: false,
    droneMarker: null,
    homeMarker: null,
    targetMarker: null,
    mapTargetMarker: null,
    geofenceCircle: null,
    pathLine: null,
    backendOnline: false,
    bootRetryCount: 0,
    bootRetryTimer: null,
    assistant: {
      busy: false,
      pendingPlan: null,
      pendingText: '',
      bypass: false,
      queue: [],
    },
    camera: {
      retryTimer: null,
    },
    manual: {
      enabled: false,
      activeAction: null,
      lastIssuedAt: 0,
      minIntervalMs: 240,
    },
    monitoring: {
      runtime: null,
      evaluation: null,
      pollTimer: null,
    },
  };

  const MANUAL_KEYMAP = {
    w: 'move_forward',
    a: 'move_left',
    s: 'move_back',
    d: 'move_right',
    ArrowUp: 'altitude_up',
    ArrowDown: 'altitude_down',
    ArrowLeft: 'yaw_left',
    ArrowRight: 'yaw_right',
    q: 'gimbal_up',
    e: 'gimbal_down',
  };

  const MAX_BOOT_RETRIES = 120;
  const BOOT_RETRY_INTERVAL_MS = 3000;

  /* ── DOM Helpers ── */
  const $ = (id) => document.getElementById(id);

  function esc(value) {
    const node = document.createElement('div');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

  function notify(message, kind) {
    const bar = $('result-bar');
    bar.className = 'result-bar ' + (kind || 'info');
    bar.textContent = message;
  }

  function setChip(id, mode, text) {
    const chip = $(id);
    if (!chip) return;
    chip.className = 'chip ' + (mode || '');
    const span = chip.querySelector('span:last-child');
    if (span) span.textContent = text;
  }

  function formatNumber(value, digits) {
    return value == null || Number.isNaN(value) ? '--' : Number(value).toFixed(digits);
  }

  function monitorMode(status) {
    if (status === true || status === 'available' || status === 'healthy' || status === 'ready') return 'ok';
    if (status === 'external' || status === 'idle' || status === 'unknown' || status === 'degraded') return 'warn';
    return 'err';
  }

  function monitorLabel(entry, fallback) {
    if (!entry) return fallback;
    if (entry.headline) return entry.headline;
    return fallback;
  }

  /* ── Network ── */
  async function fetchJSON(url, options) {
    const response = await fetch(url, options || {});
    const data = await response.json();
    if (!response.ok) {
      const message = data && data.message ? data.message : 'Request failed';
      const error = new Error(message);
      error.data = data;
      throw error;
    }
    return data;
  }

  /* ── Telemetry ── */
  function currentRelativeAltitude() {
    if (appState.telemetry && appState.telemetry.relative_altitude_m != null) {
      return appState.telemetry.relative_altitude_m;
    }
    return parseFloat($('p-goto-alt').value) || parseFloat($('p-alt').value) || 5;
  }

  function commandDescriptor(command) {
    const name = command.name;
    if (name === 'guided_takeoff' || name === 'takeoff') return 'ALT';
    if (name === 'goto_relative') return 'MOVE';
    if (name === 'get_status' || name === 'get_telemetry') return 'SYNC';
    return 'SAFE';
  }

  function updateTelemetry(snapshot) {
    appState.telemetry = snapshot;
    const state = snapshot.state || 'disconnected';
    $('t-state').textContent = state.toUpperCase();
    $('t-state').className = 'state-pill state-' + state;
    $('t-flight-mode').textContent = snapshot.flight_mode || '--';
    $('t-battery').textContent = snapshot.battery_percent != null ? snapshot.battery_percent.toFixed(0) + '%' : '--%';
    $('t-gps').textContent = snapshot.gps_satellites != null ? snapshot.gps_satellites + ' sat' : '--';
    $('t-rel-alt').textContent = snapshot.relative_altitude_m != null ? snapshot.relative_altitude_m.toFixed(1) + ' m' : '-- m';
    $('t-abs-alt').textContent = snapshot.absolute_altitude_m != null ? snapshot.absolute_altitude_m.toFixed(1) + ' AMSL' : '--';
    $('t-lat').textContent = snapshot.latitude_deg != null ? snapshot.latitude_deg.toFixed(6) : '--';
    $('t-lon').textContent = snapshot.longitude_deg != null ? snapshot.longitude_deg.toFixed(6) : '--';
    $('t-yaw').textContent = snapshot.yaw_deg != null ? snapshot.yaw_deg.toFixed(1) + '°' : '--';
    $('t-pitch').textContent = snapshot.pitch_deg != null ? 'p ' + snapshot.pitch_deg.toFixed(1) + '°' : '--';
    $('t-roll').textContent = snapshot.roll_deg != null ? snapshot.roll_deg.toFixed(1) + '°' : '--';
    $('t-flags').textContent = (snapshot.armed ? 'ARM' : 'SAFE') + ' | ' + (snapshot.in_air ? 'AIR' : 'GND');

    setChip('state-chip',
      state === 'fault' || state === 'disconnected' ? 'err' : (state === 'airborne' ? 'live' : 'ok'),
      state.charAt(0).toUpperCase() + state.slice(1)
    );
    setChip('conn-chip', 'ok', 'Telemetry live');

    updateMapWithTelemetry(snapshot);
    updateMapSummary(snapshot);
    updateManualUI();
  }

  function updateMapSummary(snapshot) {
    const parts = [];
    if (snapshot.latitude_deg != null && snapshot.longitude_deg != null) {
      parts.push(snapshot.latitude_deg.toFixed(5) + ', ' + snapshot.longitude_deg.toFixed(5));
    } else {
      parts.push('Awaiting position');
    }
    if (snapshot.yaw_deg != null) parts.push('hdg ' + snapshot.yaw_deg.toFixed(0) + '°');
    if (snapshot.relative_altitude_m != null) parts.push(snapshot.relative_altitude_m.toFixed(1) + ' m AGL');
    if (appState.mapTarget) {
      parts.push('tgt ' + appState.mapTarget.latitude_deg.toFixed(5) + ', ' + appState.mapTarget.longitude_deg.toFixed(5));
    }
    $('map-summary').textContent = parts.join(' | ');
  }

  /* ── Thesis Monitoring ── */
  function updateRuntimeHealth(runtime) {
    appState.monitoring.runtime = runtime;
    if (!runtime) return;

    var airframe = runtime.airframe || {};
    var world = runtime.world || {};
    var stack = runtime.stack || {};
    var camera = runtime.camera || {};
    var gimbal = runtime.gimbal || {};
    var readiness = runtime.readiness || {};
    var flags = readiness.flags || {};

    $('runtime-airframe').textContent = airframe.label || airframe.make_target || airframe.requested_model || '--';
    $('runtime-world').textContent = world.label || '--';
    $('runtime-stack').textContent = (stack.status || '--').toUpperCase();
    $('runtime-stack-sub').textContent = stack.summary || 'Runtime metadata unavailable.';

    $('runtime-camera').textContent = camera.available ? 'STREAMING' : (camera.enabled ? 'WAITING' : 'DISABLED');
    $('runtime-gimbal').textContent = (gimbal.status || 'unknown').toUpperCase();
    $('runtime-telemetry').textContent = runtime.telemetry && runtime.telemetry.connected ? 'LINKED' : 'IDLE';
    $('runtime-health-sub').textContent = gimbal.reason || camera.reason || 'Read-only component checks only.';

    setChip('flag-link', flags.telemetry_link ? 'ok' : 'warn', flags.telemetry_link ? 'Link ready' : 'Link pending');
    setChip('flag-pose', flags.pose ? 'ok' : 'warn', flags.pose ? 'Pose ready' : 'Pose pending');
    setChip('flag-preflight', flags.preflight ? 'ok' : 'warn', flags.preflight ? 'Preflight ready' : 'Preflight blocked');
    setChip('flag-camera', flags.camera ? 'ok' : (camera.enabled ? 'warn' : 'err'), flags.camera ? 'Camera ready' : (camera.enabled ? 'Camera pending' : 'Camera off'));
    setChip('flag-gimbal', flags.gimbal ? 'ok' : monitorMode(gimbal.status), flags.gimbal ? 'Gimbal ready' : ((gimbal.status || 'unknown') === 'disabled' ? 'Gimbal off' : 'Gimbal pending'));

    var evalReady = !!(appState.monitoring.evaluation && appState.monitoring.evaluation.readiness && appState.monitoring.evaluation.readiness.ready_for_review);
    setChip('flag-eval', evalReady ? 'ok' : 'warn', evalReady ? 'Eval ready' : 'Eval pending');
    $('readiness-summary').textContent = readiness.summary || 'Waiting for runtime readiness.';
  }

  function updateEvaluationSummary(summary) {
    appState.monitoring.evaluation = summary;
    if (!summary) return;

    var latest = summary.latest_run || null;
    var benchmarks = summary.benchmarks || {};
    var latency = benchmarks.latency || null;
    var reliability = benchmarks.reliability || null;
    var safety = benchmarks.safety || null;

    $('eval-latest').textContent = latest ? (latest.benchmark + ' @ ' + (latest.timestamp || 'unknown')) : 'No results';
    $('eval-latency').textContent = monitorLabel(latency, 'Missing');
    $('eval-reliability').textContent = monitorLabel(reliability, 'Missing');
    $('eval-safety').textContent = monitorLabel(safety, 'Missing');
    $('eval-sub').textContent = summary.summary_line || 'Evaluation summary unavailable.';

    var evalReady = !!(summary.readiness && summary.readiness.ready_for_review);
    setChip('flag-eval', evalReady ? 'ok' : 'warn', evalReady ? 'Eval ready' : 'Eval pending');
    if (appState.monitoring.runtime && appState.monitoring.runtime.readiness && appState.monitoring.runtime.readiness.summary) {
      $('readiness-summary').textContent = appState.monitoring.runtime.readiness.summary;
    }
  }

  async function refreshMonitoring() {
    try {
      updateRuntimeHealth(await fetchJSON('/dashboard/api/runtime-health'));
    } catch (_) { /* monitoring is optional */ }

    try {
      updateEvaluationSummary(await fetchJSON('/dashboard/api/evaluation-summary'));
    } catch (_) { /* monitoring is optional */ }
  }

  function startMonitoringPolling() {
    if (appState.monitoring.pollTimer !== null) window.clearInterval(appState.monitoring.pollTimer);
    appState.monitoring.pollTimer = window.setInterval(refreshMonitoring, 10000);
  }

  /* ── Events ── */
  function appendEvent(event) {
    const container = $('events');
    if (!container) return;
    const row = document.createElement('div');
    const ok = event.data && event.data.success === true;
    const err = event.data && event.data.success === false;
    row.className = 'event-row' + (ok ? ' event-ok' : '') + (err ? ' event-err' : '');
    const time = event.timestamp ? event.timestamp.split('T')[1].split('.')[0] : '--:--:--';
    row.innerHTML =
      '<div class="event-time">' + esc(time) + '</div>' +
      '<div class="event-kind">' + esc(event.kind || 'event') + '</div>' +
      '<div class="event-msg">' + esc(event.summary || '') + '</div>';
    container.prepend(row);
    while (container.children.length > 8) container.lastChild.remove();
    appendChatEvent(event);
  }

  /* ── Chat ── */
  function appendChatRow(role, text, traces) {
    const container = $('chat-log');
    if (!container) return;
    const empty = container.querySelector('.chat-empty');
    if (empty) empty.remove();
    const row = document.createElement('div');
    row.className = 'chat-row ' + role;
    row.innerHTML =
      '<div class="chat-role">' + esc(role) + '</div>' +
      '<div class="chat-text">' + esc(text || '') + '</div>';
    if (Array.isArray(traces) && traces.length) {
      const traceList = document.createElement('div');
      traceList.className = 'trace-list';
      traces.forEach(function(trace) {
        const traceRow = document.createElement('div');
        traceRow.className = 'trace-item ' + (trace.success ? 'ok' : 'err');
        traceRow.innerHTML =
          '<div class="trace-name">' + esc(trace.command || 'tool') + '</div>' +
          '<div class="trace-meta">' + esc(trace.message || '') + '</div>';
        traceList.appendChild(traceRow);
      });
      row.appendChild(traceList);
    }
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
  }

  function appendChatEvent(event) {
    if (!event || !event.kind) return;
    if (event.kind === 'assistant_plan') {
      const data = event.data || {};
      if (data.operator_text) appendChatRow('operator', data.operator_text, null);
      appendChatRow('assistant', data.assistant_text || 'Planning command.', data.proposed_calls || []);
      if (data.fallback_reason) appendChatRow('system', data.fallback_reason, null);
      return;
    }
    if (event.kind === 'assistant_execute') {
      const data = event.data || {};
      appendChatRow('system', data.assistant_text || 'Executed command.', data.executed_calls || []);
      return;
    }
    if (event.kind === 'target_update') {
      const data = event.data || {};
      const target = data.target;
      if (target) {
        appendChatRow('system', 'Target: ' + target.latitude_deg.toFixed(6) + ', ' + target.longitude_deg.toFixed(6), null);
      } else {
        appendChatRow('system', 'Map target cleared.', null);
      }
    }
  }

  /* ── Map ── */
  function makeDivIconEl(className) {
    var el = document.createElement('div');
    el.className = className;
    return el;
  }

  function circleGeoJSON(lat, lon, radiusM) {
    var coords = [];
    var steps = 64;
    var earthR = 6371000;
    for (var i = 0; i <= steps; i++) {
      var angle = (i / steps) * 2 * Math.PI;
      var dLat = (radiusM * Math.cos(angle)) / earthR * (180 / Math.PI);
      var dLon = (radiusM * Math.sin(angle)) / (earthR * Math.cos(lat * Math.PI / 180)) * (180 / Math.PI);
      coords.push([lon + dLon, lat + dLat]);
    }
    return { type: 'Feature', geometry: { type: 'Polygon', coordinates: [coords] } };
  }

  function initMap() {
    if (typeof maplibregl === 'undefined' || !appState.config) {
      $('map-summary').textContent = 'Map library or config unavailable.';
      return;
    }

    var centerLon = appState.config.geofence_center_lon;
    var centerLat = appState.config.geofence_center_lat;

    appState.map = new maplibregl.Map({
      container: 'map',
      style: 'https://tiles.openfreemap.org/styles/liberty',
      center: [centerLon, centerLat],
      zoom: 17,
      pitch: 45,
      bearing: 0,
      attributionControl: false,
    });

    var homeEl = makeDivIconEl('home-icon');
    var droneEl = makeDivIconEl('drone-icon');
    var targetEl = makeDivIconEl('target-icon');
    var mapTargetEl = makeDivIconEl('target-icon');
    targetEl.style.display = 'none';
    mapTargetEl.style.display = 'none';

    appState.homeMarker = new maplibregl.Marker({ element: homeEl, anchor: 'center' })
      .setLngLat([centerLon, centerLat])
      .setPopup(new maplibregl.Popup({ closeButton: false }).setHTML('Home'))
      .addTo(appState.map);

    appState.droneMarker = new maplibregl.Marker({ element: droneEl, anchor: 'center' })
      .setLngLat([centerLon, centerLat])
      .setPopup(new maplibregl.Popup({ closeButton: false }).setHTML('Drone'))
      .addTo(appState.map);

    appState.targetMarker = new maplibregl.Marker({ element: targetEl, anchor: 'center' })
      .setLngLat([centerLon, centerLat])
      .addTo(appState.map);

    appState.mapTargetMarker = new maplibregl.Marker({ element: mapTargetEl, anchor: 'center' })
      .setLngLat([centerLon, centerLat])
      .addTo(appState.map);

    appState.map.on('load', function() {
      var layers = appState.map.getStyle().layers;
      var labelLayerId;
      for (var i = 0; i < layers.length; i++) {
        if (layers[i].type === 'symbol' && layers[i].layout && layers[i].layout['text-field']) {
          labelLayerId = layers[i].id;
          break;
        }
      }

      appState.map.addSource('geofence', {
        type: 'geojson',
        data: circleGeoJSON(centerLat, centerLon, appState.config.geofence_radius_m || 200),
      });
      appState.map.addLayer({ id: 'geofence-fill', type: 'fill', source: 'geofence',
        paint: { 'fill-color': '#5dc8d8', 'fill-opacity': 0.05 } }, labelLayerId);
      appState.map.addLayer({ id: 'geofence-border', type: 'line', source: 'geofence',
        paint: { 'line-color': '#5dc8d8', 'line-width': 1.5 } }, labelLayerId);

      appState.map.addSource('drone-path', {
        type: 'geojson',
        data: { type: 'Feature', geometry: { type: 'LineString', coordinates: [] } },
      });
      appState.map.addLayer({ id: 'drone-path', type: 'line', source: 'drone-path',
        paint: { 'line-color': '#79a9ff', 'line-opacity': 0.75, 'line-width': 2 } });

      if (!appState.map.getLayer('3d-buildings')) {
        appState.map.addLayer({
          id: '3d-buildings',
          source: 'openmaptiles',
          'source-layer': 'building',
          type: 'fill-extrusion',
          minzoom: 14,
          paint: {
            'fill-extrusion-color': '#2a3a5a',
            'fill-extrusion-height': ['coalesce', ['get', 'render_height'], ['get', 'height'], 5],
            'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], ['get', 'min_height'], 0],
            'fill-extrusion-opacity': 0.75,
          },
        }, labelLayerId);
      }

      appState.mapReady = true;
    });

    appState.map.on('click', function(event) {
      setMapTarget({
        latitude_deg: event.lngLat.lat,
        longitude_deg: event.lngLat.lng,
        label: 'Map target',
        source: 'map',
      });
    });
  }

  function rotateDroneMarker(yawDeg) {
    if (!appState.droneMarker) return;
    var icon = appState.droneMarker.getElement();
    if (!icon) return;
    icon.style.transformOrigin = '10px 10px';
    icon.style.transform = 'rotate(' + (yawDeg || 0) + 'deg)';
  }

  function updateMapWithTelemetry(snapshot) {
    if (!appState.mapReady || snapshot.latitude_deg == null || snapshot.longitude_deg == null) return;
    var lngLat = [snapshot.longitude_deg, snapshot.latitude_deg];
    appState.droneMarker.setLngLat(lngLat);
    rotateDroneMarker(snapshot.yaw_deg || 0);
    var history = appState.history;
    var last = history.length ? history[history.length - 1] : null;
    if (!last || last[0] !== lngLat[0] || last[1] !== lngLat[1]) {
      history.push(lngLat);
      if (history.length > 160) history.shift();
      var src = appState.map.getSource('drone-path');
      if (src) src.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: history } });
    }
    if ($('auto-center').checked) {
      appState.map.panTo(lngLat, { animate: true });
    }
  }

  function updateTargetMarker(projection) {
    if (!projection || !appState.mapReady) return;
    var el = appState.targetMarker.getElement();
    if (el) el.style.display = '';
    appState.targetMarker.setLngLat([projection.longitude_deg, projection.latitude_deg]);
    appState.targetMarker.setPopup(
      new maplibregl.Popup({ closeButton: false }).setHTML(
        'Target<br>' + projection.latitude_deg.toFixed(6) + ', ' + projection.longitude_deg.toFixed(6)
      )
    );
  }

  function updateMapTargetMarker(target) {
    if (!appState.mapReady || !appState.mapTargetMarker) return;
    var el = appState.mapTargetMarker.getElement();
    if (!target) {
      if (el) el.style.display = 'none';
      $('map-target-body').textContent = 'Define via map click';
      $('map-target-orbit').disabled = true;
      $('map-target-approach').disabled = true;
      return;
    }
    appState.mapTargetMarker.setLngLat([target.longitude_deg, target.latitude_deg]);
    if (el) el.style.display = '';
    appState.mapTargetMarker.setPopup(
      new maplibregl.Popup({ closeButton: false }).setHTML(
        'Map target<br>' + target.latitude_deg.toFixed(6) + ', ' + target.longitude_deg.toFixed(6)
      )
    );
    $('map-target-body').textContent = target.latitude_deg.toFixed(6) + ', ' + target.longitude_deg.toFixed(6);
    $('map-target-orbit').disabled = appState.commandBusy || appState.selectionBusy;
    $('map-target-approach').disabled = appState.commandBusy || appState.selectionBusy;
  }

  /* ── Config & Boot ── */
  async function loadConfig() {
    appState.config = await fetchJSON('/dashboard/api/config');
    var camera = appState.config.camera || {};
    var manual = appState.config.manual_control || {};
    $('p-alt').value = appState.config.default_takeoff_altitude_m || 5;
    $('p-goto-alt').value = appState.config.default_takeoff_altitude_m || 5;
    $('manual-step').value = manual.translation_step_m || 3;
    $('manual-alt-step').value = manual.altitude_step_m || 1.5;
    setChip(
      'camera-chip',
      camera.available ? 'ok' : (camera.enabled ? 'warn' : ''),
      camera.available ? 'Camera ready' : (camera.reason || 'Camera unavailable')
    );
    var topicSpan = $('camera-topic').querySelector('span:last-child');
    if (topicSpan) topicSpan.textContent = camera.topic || 'camera route';
    updateManualUI();
  }

  async function loadCommandManifest() {
    var data = await fetchJSON('/dashboard/api/commands');
    appState.commands = Array.isArray(data.commands) ? data.commands : [];
    renderCommands();
  }

  async function loadSelectedTarget() {
    try {
      var data = await fetchJSON('/dashboard/api/target');
      appState.mapTarget = data && data.target ? data.target : null;
      updateMapTargetMarker(appState.mapTarget);
    } catch (_) { /* target endpoint is optional */ }
  }

  /* ── Camera ── */
  function clearCameraRetry() {
    if (appState.camera.retryTimer !== null) {
      window.clearTimeout(appState.camera.retryTimer);
      appState.camera.retryTimer = null;
    }
  }

  function cameraPlaceholderText(camera) {
    if (!camera) return 'Camera configuration unavailable.';
    return camera.reason || 'Waiting for camera stream...';
  }

  async function refreshCameraConfig() {
    var config = await fetchJSON('/dashboard/api/config');
    appState.config = config;
    var camera = config.camera || {};
    setChip('camera-chip',
      camera.available ? 'ok' : (camera.enabled ? 'warn' : ''),
      camera.available ? 'Camera ready' : (camera.reason || 'Camera unavailable')
    );
    var topicSpan = $('camera-topic').querySelector('span:last-child');
    if (topicSpan) topicSpan.textContent = camera.topic || 'camera route';
    return camera;
  }

  function scheduleCameraRetry(delayMs) {
    clearCameraRetry();
    appState.camera.retryTimer = window.setTimeout(async function() {
      appState.camera.retryTimer = null;
      try {
        var camera = await refreshCameraConfig();
        loadCameraStream(camera);
      } catch (_) {
        scheduleCameraRetry(delayMs);
      }
    }, delayMs);
  }

  function loadCameraStream(camera) {
    var image = $('camera-stream');
    var placeholder = $('camera-placeholder');
    clearCameraRetry();
    if (!camera || !camera.enabled) {
      image.removeAttribute('src');
      placeholder.textContent = cameraPlaceholderText(camera);
      placeholder.classList.remove('hidden');
      return;
    }
    placeholder.textContent = cameraPlaceholderText(camera);
    placeholder.classList.remove('hidden');
    image.src = camera.stream_url + (camera.stream_url.indexOf('?') === -1 ? '?' : '&') + 'ts=' + Date.now();
  }

  function initCamera() {
    var camera = appState.config && appState.config.camera ? appState.config.camera : null;
    var image = $('camera-stream');
    var placeholder = $('camera-placeholder');
    image.addEventListener('load', function() {
      placeholder.classList.add('hidden');
      setChip('camera-chip', 'ok', 'Camera streaming');
    });
    image.addEventListener('error', async function() {
      placeholder.classList.remove('hidden');
      setChip('camera-chip', camera && camera.enabled ? 'warn' : 'err', 'Waiting for camera');
      try {
        var latestCamera = await refreshCameraConfig();
        placeholder.textContent = cameraPlaceholderText(latestCamera);
      } catch (_) {
        placeholder.textContent = 'Camera unavailable. Retrying...';
      }
      scheduleCameraRetry(2500);
    });
    loadCameraStream(camera);
    if (!camera || !camera.available) scheduleCameraRetry(2500);
  }

  /* ── Selection ── */
  function selectionToSummary(selection) {
    if (!selection || !selection.projection) {
      return 'Select a point in the camera feed.';
    }
    var p = selection.projection;
    return [
      'px ' + selection.u.toFixed(0) + ',' + selection.v.toFixed(0),
      p.latitude_deg.toFixed(6),
      p.longitude_deg.toFixed(6),
      p.distance_m.toFixed(1) + 'm'
    ].join(' | ');
  }

  function updateSelectionUI() {
    var active = !!(appState.selection && appState.selection.projection);
    $('selection-body').textContent = selectionToSummary(appState.selection);
    $('orbit-selection').disabled = !active || appState.selectionBusy;
    $('approach-selection').disabled = !active || appState.selectionBusy;
    setChip('selection-status', active ? 'ok' : '', active ? 'Projected' : 'No target');
    if (active) updateTargetMarker(appState.selection.projection);
  }

  function clearSelection() {
    appState.selection = null;
    $('selection-box').classList.remove('visible');
    $('selection-box').style.width = '0px';
    $('selection-box').style.height = '0px';
    if (appState.targetMarker) { var _tel = appState.targetMarker.getElement(); if (_tel) _tel.style.display = 'none'; }
    updateSelectionUI();
  }

  function overlayPoint(event) {
    var overlay = $('camera-overlay');
    var rect = overlay.getBoundingClientRect();
    var x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    var y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    var params = appState.config && appState.config.camera ? appState.config.camera.params : null;
    var widthPx = params ? params.width_px : 320;
    var heightPx = params ? params.height_px : 240;
    return {
      x: x, y: y,
      rectWidth: rect.width, rectHeight: rect.height,
      u: rect.width ? (x / rect.width) * widthPx : widthPx / 2,
      v: rect.height ? (y / rect.height) * heightPx : heightPx / 2,
    };
  }

  function setSelectionBox(left, top, width, height) {
    var box = $('selection-box');
    box.classList.add('visible');
    box.style.left = left + 'px';
    box.style.top = top + 'px';
    box.style.width = width + 'px';
    box.style.height = height + 'px';
  }

  async function projectSelection(selection) {
    appState.selectionBusy = true;
    updateSelectionUI();
    try {
      var projection = await fetchJSON('/dashboard/api/project_pixel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ u: selection.u, v: selection.v }),
      });
      appState.selection = Object.assign({}, selection, { projection: projection });
      updateSelectionUI();
      notify('Projected: ' + projection.latitude_deg.toFixed(6) + ', ' + projection.longitude_deg.toFixed(6), 'info');
    } catch (error) {
      notify(error && error.message ? error.message : 'Projection failed', 'err');
    } finally {
      appState.selectionBusy = false;
      updateSelectionUI();
    }
  }

  function initSelection() {
    var overlay = $('camera-overlay');

    overlay.addEventListener('pointerdown', function(event) {
      var point = overlayPoint(event);
      appState.selecting = true;
      appState.selectionStart = point;
      setSelectionBox(point.x, point.y, 1, 1);
    });

    overlay.addEventListener('pointermove', function(event) {
      if (!appState.selecting || !appState.selectionStart) return;
      var current = overlayPoint(event);
      var left = Math.min(appState.selectionStart.x, current.x);
      var top = Math.min(appState.selectionStart.y, current.y);
      var width = Math.max(2, Math.abs(current.x - appState.selectionStart.x));
      var height = Math.max(2, Math.abs(current.y - appState.selectionStart.y));
      setSelectionBox(left, top, width, height);
    });

    async function finalizeSelection(event) {
      if (!appState.selecting || !appState.selectionStart) return;
      appState.selecting = false;
      var current = overlayPoint(event);
      var left = Math.min(appState.selectionStart.x, current.x);
      var top = Math.min(appState.selectionStart.y, current.y);
      var width = Math.max(20, Math.abs(current.x - appState.selectionStart.x));
      var height = Math.max(20, Math.abs(current.y - appState.selectionStart.y));
      setSelectionBox(left, top, width, height);
      var params = appState.config && appState.config.camera ? appState.config.camera.params : null;
      if (!params || !current.rectWidth || !current.rectHeight) {
        notify('Camera parameters unavailable.', 'err');
        return;
      }
      var centerX = left + width / 2;
      var centerY = top + height / 2;
      await projectSelection({
        u: (centerX / current.rectWidth) * params.width_px,
        v: (centerY / current.rectHeight) * params.height_px,
      });
    }

    overlay.addEventListener('pointerup', finalizeSelection);
    overlay.addEventListener('pointerleave', function(event) {
      if (appState.selecting) finalizeSelection(event);
    });

    $('clear-selection').addEventListener('click', clearSelection);
    $('project-center').addEventListener('click', function() {
      var params = appState.config && appState.config.camera ? appState.config.camera.params : null;
      if (!params) { notify('Camera parameters unavailable.', 'err'); return; }
      setSelectionBox(0, 0, 0, 0);
      projectSelection({ u: params.width_px / 2, v: params.height_px / 2 });
    });
    $('orbit-selection').addEventListener('click', function() { runSelectionAction('orbit'); });
    $('approach-selection').addEventListener('click', function() { runSelectionAction('approach'); });
  }

  async function runSelectionAction(kind) {
    if (!appState.selection || !appState.selection.projection || appState.selectionBusy) return;
    appState.selectionBusy = true;
    updateSelectionUI();
    var route = kind === 'orbit' ? '/dashboard/api/select_and_orbit' : '/dashboard/api/select_and_approach';
    var payload = {
      u: appState.selection.u,
      v: appState.selection.v,
      radius_m: parseFloat($('p-orbit-radius').value),
      velocity_m_s: parseFloat($('p-orbit-speed').value),
      altitude_m: parseFloat($('p-goto-alt').value),
    };
    try {
      var result = await fetchJSON(route, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (result.data && result.data.projection) updateTargetMarker(result.data.projection);
      notify((kind === 'orbit' ? 'Orbit' : 'Approach') + ': ' + result.message, result.success ? 'ok' : 'err');
    } catch (error) {
      notify(error.message || 'Selection command failed', 'err');
    } finally {
      appState.selectionBusy = false;
      updateSelectionUI();
    }
  }

  /* ── Commands ── */
  function setCommandControlsDisabled(disabled) {
    document.querySelectorAll('.cmd-btn').forEach(function(b) { b.disabled = disabled; });
    document.querySelectorAll('[data-manual-action]').forEach(function(b) { b.disabled = disabled; });
    $('map-target-clear').disabled = disabled;
    $('map-target-orbit').disabled = disabled || !appState.mapTarget;
    $('map-target-approach').disabled = disabled || !appState.mapTarget;
    $('quick-command-submit').disabled = disabled;
    $('assistant-confirm').disabled = disabled || !appState.assistant.pendingPlan;
    updateChatBusyState();
    updateManualUI();
  }

  async function sendCommand(command, body) {
    if (appState.commandBusy) return null;
    appState.commandBusy = true;
    setCommandControlsDisabled(true);
    notify(command + '...', 'info');
    try {
      var result = await fetchJSON('/dashboard/api/commands/' + encodeURIComponent(command), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      if (result.data && result.data.state) updateTelemetry(result.data);
      if (result.data && result.data.target_latitude_deg && result.data.target_longitude_deg) {
        updateTargetMarker({
          latitude_deg: result.data.target_latitude_deg,
          longitude_deg: result.data.target_longitude_deg,
        });
      }
      notify(command + ': ' + result.message, result.success ? 'ok' : 'err');
      return result;
    } catch (error) {
      notify(command + ': ' + (error.message || 'request failed'), 'err');
      return null;
    } finally {
      appState.commandBusy = false;
      setCommandControlsDisabled(false);
    }
  }

  function commandPayloadFor(name) {
    if (name === 'guided_takeoff' || name === 'takeoff') {
      var altitude = parseFloat($('p-alt').value);
      if (Number.isNaN(altitude)) { notify('Altitude must be numeric.', 'err'); return null; }
      return { altitude_m: altitude };
    }
    if (name === 'goto_relative') {
      var north = parseFloat($('p-north').value);
      var east = parseFloat($('p-east').value);
      var alt = parseFloat($('p-goto-alt').value);
      if ([north, east, alt].some(function(v) { return Number.isNaN(v); })) {
        notify('Goto inputs must be numeric.', 'err'); return null;
      }
      return { north_m: north, east_m: east, altitude_m: alt };
    }
    return {};
  }

  function handleCommandClick(commandName) {
    var payload = commandPayloadFor(commandName);
    if (payload === null) return;
    sendCommand(commandName, payload);
  }

  function renderCommands() {
    var container = $('command-grid');
    var summary = $('command-summary');
    container.innerHTML = '';
    if (!appState.commands.length) {
      if (summary) summary.textContent = 'No commands available.';
      return;
    }
    if (summary) summary.textContent = appState.commands.length + ' commands';
    appState.commands.forEach(function(command) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'cmd-btn cmd-' + (command.tone || 'neutral');
      button.title = command.hint || command.label;
      button.dataset.command = command.name;
      button.innerHTML =
        '<span class="cmd-label">' + esc(command.label || command.name) + '</span>' +
        '<span class="cmd-meta">' + esc(commandDescriptor(command)) + '</span>';
      button.addEventListener('click', function() { handleCommandClick(command.name); });
      container.appendChild(button);
    });
  }

  /* ── SSE Streams ── */
  function connectTelemetrySSE() {
    if (appState.telemetryES) appState.telemetryES.close();
    appState.telemetryES = new EventSource('/dashboard/api/telemetry/stream');
    appState.telemetryES.addEventListener('telemetry', function(event) {
      try { updateTelemetry(JSON.parse(event.data)); } catch (_) {}
    });
    appState.telemetryES.onopen = function() { setChip('conn-chip', 'ok', 'Telemetry live'); };
    appState.telemetryES.onerror = function() { setChip('conn-chip', 'err', 'Reconnecting...'); };
  }

  function connectEventsSSE() {
    if (appState.eventsES) appState.eventsES.close();
    appState.eventsES = new EventSource('/dashboard/api/events/stream');
    appState.eventsES.addEventListener('dashboard_event', function(event) {
      try { appendEvent(JSON.parse(event.data)); } catch (_) {}
    });
  }

  async function loadInitialEvents() {
    try {
      var events = await fetchJSON('/dashboard/api/events?limit=12');
      events.forEach(appendEvent);
    } catch (_) {}
  }

  async function refreshStatus() {
    try { updateTelemetry(await fetchJSON('/dashboard/api/status')); }
    catch (error) { notify(error.message || 'Failed to load status', 'err'); }
  }

  /* ── Assistant ── */
  function setAssistantPending(plan, text) {
    appState.assistant.pendingPlan = plan;
    appState.assistant.pendingText = text || '';
    var visible = !!(plan && plan.proposed_calls && plan.proposed_calls.length);
    $('assistant-confirm-bar').classList.toggle('visible', visible);
    $('assistant-confirm-text').textContent = visible
      ? 'Preview: ' + plan.proposed_calls.map(function(c) { return c.command || c.name || '?'; }).join(' → ')
      : '';
    $('assistant-confirm').disabled = !visible;
  }

  function clearAssistantPending() {
    appState.assistant.pendingPlan = null;
    appState.assistant.pendingText = '';
    $('assistant-confirm-bar').classList.remove('visible');
    $('assistant-confirm').disabled = true;
  }

  function updateChatBusyState() {
    var busy = appState.assistant.busy || appState.commandBusy;
    var hasPending = !!appState.assistant.pendingPlan;
    $('assistant-input').disabled = false;
    $('assistant-preview').disabled = hasPending;
    $('assistant-run').disabled = false;
    $('assistant-confirm').disabled = busy || !hasPending;
  }

  function enqueueAssistantRequest(kind, text) {
    var trimmed = (text || '').trim();
    if (!trimmed) return null;
    appState.assistant.queue.push({ kind: kind, text: trimmed });
    appendChatRow('system', 'Queued: ' + trimmed, null);
    notify('Assistant busy. Queued command #' + appState.assistant.queue.length + '.', 'info');
    updateChatBusyState();
    return null;
  }

  async function drainAssistantQueue() {
    if (appState.assistant.busy || appState.commandBusy || appState.assistant.pendingPlan) return null;
    var next = appState.assistant.queue.shift();
    if (!next) {
      updateChatBusyState();
      return null;
    }
    updateChatBusyState();
    if (next.kind === 'preview') return previewAssistantCommand(next.text);
    return runAssistantCommand(next.text);
  }

  async function executeAssistantPlan(text, plan) {
    var payload = { text: text || '' };
    if (plan && Array.isArray(plan.proposed_calls)) payload.proposed_calls = plan.proposed_calls;
    if (plan && plan.assistant_text) payload.assistant_text = plan.assistant_text;
    var result = await fetchJSON('/dashboard/api/assistant/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (Array.isArray(result.executed_calls) && result.executed_calls.length) {
      result.executed_calls.forEach(function(call) {
        if (call && call.data && call.data.state) updateTelemetry(call.data);
        if (call && call.data && call.data.target) {
          appState.mapTarget = call.data.target;
          updateMapTargetMarker(appState.mapTarget);
        }
      });
    }
    clearAssistantPending();
    notify(result.success ? 'Execution complete.' : 'Execution stopped.', result.success ? 'ok' : 'err');
    return result;
  }

  async function previewAssistantCommand(text) {
    var trimmed = text.trim();
    if (!trimmed) return null;
    if (appState.assistant.busy || appState.commandBusy || appState.assistant.pendingPlan) {
      return enqueueAssistantRequest('preview', trimmed);
    }
    appState.assistant.busy = true;
    updateChatBusyState();
    try {
      var result = await fetchJSON('/dashboard/api/assistant/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: trimmed }),
      });
      if (result.selected_target) {
        appState.mapTarget = result.selected_target;
        updateMapTargetMarker(appState.mapTarget);
      }
      if (result.requires_confirmation && !appState.assistant.bypass && Array.isArray(result.proposed_calls) && result.proposed_calls.length) {
        setAssistantPending(result, trimmed);
      } else if (Array.isArray(result.proposed_calls) && result.proposed_calls.length) {
        clearAssistantPending();
        await executeAssistantPlan(trimmed, result);
      } else {
        clearAssistantPending();
      }
      return result;
    } catch (error) {
      clearAssistantPending();
      notify(error.message || 'Assistant unavailable; using fallback.', 'err');
      executeQuickCommand(trimmed);
      return null;
    } finally {
      appState.assistant.busy = false;
      updateChatBusyState();
      if (!appState.assistant.pendingPlan) drainAssistantQueue();
    }
  }

  async function runAssistantCommand(text) {
    var trimmed = text.trim();
    if (!trimmed) return null;
    if (appState.assistant.busy || appState.commandBusy || appState.assistant.pendingPlan) {
      return enqueueAssistantRequest('run', trimmed);
    }
    if (appState.assistant.bypass) {
      appState.assistant.busy = true;
      updateChatBusyState();
      try { return await executeAssistantPlan(text); }
      catch (error) {
        notify(error.message || 'Assistant unavailable.', 'err');
        executeQuickCommand(text);
        return null;
      } finally {
        appState.assistant.busy = false;
        updateChatBusyState();
        if (!appState.assistant.pendingPlan) drainAssistantQueue();
      }
    }
    return previewAssistantCommand(trimmed);
  }

  async function executePendingAssistantCommand() {
    var pending = appState.assistant.pendingPlan;
    var text = appState.assistant.pendingText;
    if (!pending || !text) return;
    appState.assistant.busy = true;
    updateChatBusyState();
    try { await executeAssistantPlan(text, pending); }
    catch (error) { notify(error.message || 'Execution failed.', 'err'); }
    finally {
      appState.assistant.busy = false;
      updateChatBusyState();
      if (!appState.assistant.pendingPlan) drainAssistantQueue();
    }
  }

  /* ── Map Target ── */
  async function setMapTarget(target) {
    try {
      var result = await fetchJSON('/dashboard/api/target', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(target),
      });
      appState.mapTarget = result.target || null;
      updateMapTargetMarker(appState.mapTarget);
      updateMapSummary(appState.telemetry || {});
      if (appState.mapTarget) {
        notify('Target: ' + appState.mapTarget.latitude_deg.toFixed(6) + ', ' + appState.mapTarget.longitude_deg.toFixed(6), 'info');
      }
    } catch (error) {
      notify(error.message || 'Failed to set target.', 'err');
    }
  }

  async function clearMapTarget() {
    try {
      await fetchJSON('/dashboard/api/target', { method: 'DELETE' });
      appState.mapTarget = null;
      updateMapTargetMarker(null);
      updateMapSummary(appState.telemetry || {});
      notify('Target cleared.', 'info');
    } catch (error) {
      notify(error.message || 'Failed to clear target.', 'err');
    }
  }

  async function runMapTargetAction(kind) {
    if (!appState.mapTarget) return;
    var route = kind === 'orbit' ? '/dashboard/api/target/orbit' : '/dashboard/api/target/approach';
    try {
      appState.commandBusy = true;
      setCommandControlsDisabled(true);
      var result = await fetchJSON(route, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          radius_m: parseFloat($('p-orbit-radius').value),
          velocity_m_s: parseFloat($('p-orbit-speed').value),
        }),
      });
      if (result.data && result.data.target) {
        appState.mapTarget = result.data.target;
        updateMapTargetMarker(appState.mapTarget);
      }
      notify((kind === 'orbit' ? 'Orbit' : 'Approach') + ': ' + result.message, result.success ? 'ok' : 'err');
    } catch (error) {
      notify(error.message || 'Target action failed.', 'err');
    } finally {
      appState.commandBusy = false;
      setCommandControlsDisabled(false);
    }
  }

  /* ── Quick Command Parser ── */
  function executeQuickCommand(text) {
    var normalized = text.trim().toLowerCase();
    if (!normalized) return;

    if (normalized.indexOf('connect') !== -1) return sendCommand('connect');
    if (normalized.indexOf('disarm') !== -1)  return sendCommand('disarm');
    if (normalized.indexOf('arm') !== -1)     return sendCommand('arm');
    if (normalized.indexOf('land') !== -1)    return sendCommand('land');
    if (/rtl|return|come back/.test(normalized)) return sendCommand('rtl');
    if (/hold|hover|stop/.test(normalized))      return sendCommand('hold');

    var takeoffMatch = normalized.match(/take\\s*off(?:\\s+to)?\\s+(\\d+(?:\\.\\d+)?)/);
    if (takeoffMatch) {
      return sendCommand('guided_takeoff', { altitude_m: parseFloat(takeoffMatch[1]) });
    }
    if (/take\\s*off/.test(normalized)) {
      return sendCommand('guided_takeoff', { altitude_m: parseFloat($('p-alt').value) || 5 });
    }

    var gotoMatch = normalized.match(/go\\s+(north|south|east|west)\\s+(\\d+(?:\\.\\d+)?)\\s*(?:meters?|m)?/);
    if (gotoMatch) {
      var dir = gotoMatch[1];
      var dist = parseFloat(gotoMatch[2]);
      var p = { north_m: 0, east_m: 0, altitude_m: parseFloat($('p-goto-alt').value) || 5 };
      if (dir === 'north') p.north_m = dist;
      if (dir === 'south') p.north_m = -dist;
      if (dir === 'east')  p.east_m = dist;
      if (dir === 'west')  p.east_m = -dist;
      return sendCommand('goto_relative', p);
    }

    if (/circle|orbit/.test(normalized)) {
      if (appState.mapTarget && /target|map/.test(normalized)) return runMapTargetAction('orbit');
      return runSelectionAction('orbit');
    }
    if (/approach|inspect/.test(normalized)) {
      if (appState.mapTarget && /target|map/.test(normalized)) return runMapTargetAction('approach');
      return runSelectionAction('approach');
    }

    notify('Unrecognized command: ' + normalized, 'err');
    return null;
  }

  /* ── Manual Controls ── */
  function bodyFrameOffsetToNed(forwardM, rightM, yawDeg) {
    var yawRad = ((yawDeg || 0) * Math.PI) / 180;
    return {
      north_m: (Math.cos(yawRad) * forwardM) - (Math.sin(yawRad) * rightM),
      east_m:  (Math.sin(yawRad) * forwardM) + (Math.cos(yawRad) * rightM),
    };
  }

  function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }

  function manualCapabilities() {
    return appState.config && appState.config.manual_control ? appState.config.manual_control : {};
  }

  function manualSupports(action) {
    var caps = manualCapabilities();
    if (action.indexOf('move_') === 0)    return !!caps.supports_translation;
    if (action.indexOf('altitude_') === 0) return !!caps.supports_altitude;
    if (action.indexOf('yaw_') === 0)      return !!caps.supports_yaw;
    if (action === 'gimbal_up' || action === 'gimbal_down') return !!caps.supports_gimbal_pitch;
    return false;
  }

  function manualTooltipFor(action) {
    if (action.indexOf('yaw_') === 0)    return 'Yaw unavailable in active backend.';
    if (action === 'gimbal_up' || action === 'gimbal_down') return 'Gimbal pitch unavailable in active backend.';
    return '';
  }

  async function sendManualRequest(route, payload, label) {
    if (appState.commandBusy) return null;
    appState.commandBusy = true;
    setCommandControlsDisabled(true);
    try {
      var result = await fetchJSON(route, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (result.data && result.data.state) updateTelemetry(result.data);
      notify(label + ': ' + result.message, result.success ? 'ok' : 'err');
      return result;
    } catch (error) {
      notify(label + ': ' + (error.message || 'failed'), 'err');
      return null;
    } finally {
      appState.commandBusy = false;
      setCommandControlsDisabled(false);
    }
  }

  function updateManualUI() {
    var enabled = $('manual-toggle').checked;
    appState.manual.enabled = enabled;
    var caps = manualCapabilities();
    $('manual-status').textContent = enabled ? 'Active' : 'Off';
    $('manual-summary').textContent = enabled
      ? 'Keyboard active. Focus input to pause.'
      : 'Enable toggle for keyboard control.';
    setChip('control-chip', enabled ? 'live' : '', enabled ? 'Manual active' : 'Manual locked');

    document.querySelectorAll('[data-manual-action]').forEach(function(button) {
      var action = button.dataset.manualAction;
      var supported = manualSupports(action);
      button.classList.toggle('unsupported', !supported);
      button.disabled = appState.commandBusy || !supported;
      if (!supported) button.title = manualTooltipFor(action);
    });

    if (enabled) {
      var unsupported = [];
      if (!caps.supports_yaw) unsupported.push('yaw');
      if (!caps.supports_gimbal_pitch) unsupported.push('gimbal');
      if (unsupported.length) {
        $('manual-status').textContent = 'Active (' + unsupported.join(', ') + ' N/A)';
      }
    }
  }

  async function sendManualAction(action) {
    var now = Date.now();
    if (!appState.manual.enabled || appState.commandBusy) return;
    if (now - appState.manual.lastIssuedAt < appState.manual.minIntervalMs) return;
    appState.manual.lastIssuedAt = now;

    if (!manualSupports(action)) { notify(manualTooltipFor(action), 'err'); return; }

    var moveStep = parseFloat($('manual-step').value);
    var altitudeStep = parseFloat($('manual-alt-step').value);
    var snapshot = appState.telemetry || {};
    var currentAlt = currentRelativeAltitude();
    var config = appState.config || {};
    var minAlt = config.min_altitude_m != null ? config.min_altitude_m : 0.5;
    var maxAlt = config.max_altitude_m != null ? config.max_altitude_m : 120;
    var payload = null;

    if (action === 'move_forward') payload = bodyFrameOffsetToNed(moveStep, 0, snapshot.yaw_deg || 0);
    if (action === 'move_back')    payload = bodyFrameOffsetToNed(-moveStep, 0, snapshot.yaw_deg || 0);
    if (action === 'move_left')    payload = bodyFrameOffsetToNed(0, -moveStep, snapshot.yaw_deg || 0);
    if (action === 'move_right')   payload = bodyFrameOffsetToNed(0, moveStep, snapshot.yaw_deg || 0);

    if (payload) {
      return sendManualRequest('/dashboard/api/manual/move', {
        north_m: payload.north_m, east_m: payload.east_m,
        altitude_m: clamp(currentAlt, minAlt, maxAlt),
      }, 'move');
    }

    if (action === 'altitude_up' || action === 'altitude_down') {
      var delta = action === 'altitude_up' ? altitudeStep : -altitudeStep;
      return sendManualRequest('/dashboard/api/manual/move', {
        north_m: 0, east_m: 0, altitude_m: clamp(currentAlt + delta, minAlt, maxAlt),
      }, 'altitude');
    }

    if (action === 'yaw_left' || action === 'yaw_right') {
      var caps = manualCapabilities();
      var yawStep = caps.yaw_step_deg || 15;
      return sendManualRequest('/dashboard/api/manual/yaw', {
        delta_deg: action === 'yaw_left' ? -yawStep : yawStep,
      }, 'yaw');
    }

    if (action === 'gimbal_up' || action === 'gimbal_down') {
      var caps2 = manualCapabilities();
      var gimbalStep = caps2.gimbal_pitch_step_deg || 10;
      return sendManualRequest('/dashboard/api/manual/gimbal_pitch', {
        delta_deg: action === 'gimbal_up' ? gimbalStep : -gimbalStep,
      }, 'gimbal');
    }
  }

  function setActiveManualButton(action) {
    appState.manual.activeAction = action;
    document.querySelectorAll('[data-manual-action]').forEach(function(b) {
      b.classList.toggle('active', b.dataset.manualAction === action);
    });
  }

  function clearActiveManualButton(action) {
    if (!action || appState.manual.activeAction !== action) return;
    appState.manual.activeAction = null;
    document.querySelectorAll('[data-manual-action]').forEach(function(b) { b.classList.remove('active'); });
  }

  function initManualControls() {
    $('manual-toggle').addEventListener('change', updateManualUI);

    document.querySelectorAll('[data-manual-action]').forEach(function(button) {
      button.addEventListener('mousedown', function() { setActiveManualButton(button.dataset.manualAction); });
      button.addEventListener('mouseup', function() { clearActiveManualButton(button.dataset.manualAction); });
      button.addEventListener('mouseleave', function() { clearActiveManualButton(button.dataset.manualAction); });
      button.addEventListener('click', function() {
        setActiveManualButton(button.dataset.manualAction);
        sendManualAction(button.dataset.manualAction).then(function() {
          window.setTimeout(function() { clearActiveManualButton(button.dataset.manualAction); }, 120);
        });
      });
    });

    $('quick-command-submit').addEventListener('click', function() {
      var input = $('quick-command-input');
      var text = input.value.trim();
      if (!text) return;
      input.value = '';
      executeQuickCommand(text);
    });

    $('quick-command-input').addEventListener('keydown', function(event) {
      if (event.key === 'Enter') { event.preventDefault(); $('quick-command-submit').click(); }
    });

    window.addEventListener('keydown', function(event) {
      var tag = event.target && event.target.tagName ? event.target.tagName.toLowerCase() : '';
      if (tag === 'input' || tag === 'textarea') return;
      var action = MANUAL_KEYMAP[event.key];
      if (!action || !appState.manual.enabled) return;
      event.preventDefault();
      setActiveManualButton(action);
      sendManualAction(action);
    });

    window.addEventListener('keyup', function(event) {
      var action = MANUAL_KEYMAP[event.key];
      if (action) clearActiveManualButton(action);
    });
  }

  /* ── Assistant Chat Init ── */
  function initAssistantChat() {
    $('assistant-bypass').addEventListener('change', function(event) {
      appState.assistant.bypass = event.target.checked;
      if (appState.assistant.bypass) $('assistant-confirm-bar').classList.remove('visible');
    });

    $('assistant-preview').addEventListener('click', function() {
      var text = $('assistant-input').value.trim();
      if (text) previewAssistantCommand(text);
    });

    $('assistant-run').addEventListener('click', function() {
      var input = $('assistant-input');
      var text = input.value.trim();
      if (!text) return;
      input.value = '';
      runAssistantCommand(text);
    });

    $('assistant-confirm').addEventListener('click', executePendingAssistantCommand);

    /* Voice recognition (Chrome Web Speech API) */
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    var micBtn = $('voice-cmd-btn');
    if (SpeechRecognition && micBtn) {
      var recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;

      micBtn.addEventListener('click', function() {
        micBtn.classList.add('recording');
        micBtn.textContent = '●';
        recognition.start();
      });

      recognition.onresult = function(event) {
        micBtn.classList.remove('recording');
        micBtn.innerHTML = '&#x1F3A4;';
        $('assistant-input').value = event.results[0][0].transcript;
        $('assistant-run').click();
      };
      recognition.onerror = function(event) {
        micBtn.classList.remove('recording');
        micBtn.innerHTML = '&#x1F3A4;';
        notify('Voice: ' + event.error, 'err');
      };
      recognition.onend = function() {
        micBtn.classList.remove('recording');
        micBtn.innerHTML = '&#x1F3A4;';
      };
    } else if (micBtn) {
      micBtn.disabled = true;
      micBtn.title = 'Voice input not supported in this browser.';
      micBtn.style.opacity = '0.3';
    }

    $('assistant-input').addEventListener('keydown', function(event) {
      if (event.key === 'Enter') { event.preventDefault(); $('assistant-run').click(); }
    });
  }

  function initMapTargetControls() {
    $('map-target-clear').addEventListener('click', function() { clearMapTarget(); });
    $('map-target-orbit').addEventListener('click', function() { runMapTargetAction('orbit'); });
    $('map-target-approach').addEventListener('click', function() { runMapTargetAction('approach'); });
  }

  /* ── Tab Switching ── */
  function initTabs() {
    var tabCmd = $('tab-cmd');
    var tabAi = $('tab-ai');
    var panelCmd = $('panel-cmd');
    var panelAi = $('panel-ai');
    if (!tabCmd || !tabAi) return;

    tabCmd.addEventListener('click', function() {
      tabCmd.classList.add('active');
      tabAi.classList.remove('active');
      panelCmd.style.display = 'block';
      panelAi.style.display = 'none';
    });
    tabAi.addEventListener('click', function() {
      tabAi.classList.add('active');
      tabCmd.classList.remove('active');
      panelAi.style.display = 'flex';
      panelCmd.style.display = 'none';
    });
  }

  /* ── Boot ── */

  /* UI-only init — runs once, no network needed */
  function initUI() {
    initTabs();
    initSelection();
    initManualControls();
    initAssistantChat();
    initMapTargetControls();
    updateManualUI();
  }

  /* Network-dependent init — retries until the backend is reachable */
  async function connectBackend() {
    try {
      notify('Connecting to backend...', 'connecting');
      setChip('conn-chip', 'warn', 'Connecting...');

      await loadConfig();
      await loadCommandManifest();
      await loadSelectedTarget();

      appState.backendOnline = true;
      appState.bootRetryCount = 0;
      notify('Backend connected. System nominal.', 'ok');

      initMap();
      initCamera();
      connectTelemetrySSE();
      connectEventsSSE();
      loadInitialEvents();
      refreshStatus();
      refreshMonitoring();
      startMonitoringPolling();
      updateSelectionUI();
      updateMapTargetMarker(appState.mapTarget);
      updateManualUI();
      updateChatBusyState();
    } catch (error) {
      appState.backendOnline = false;
      appState.bootRetryCount++;

      if (appState.bootRetryCount >= MAX_BOOT_RETRIES) {
        notify('Backend unreachable. Refresh page to retry.', 'err');
        setChip('conn-chip', 'err', 'Backend offline');
        return;
      }

      var msg = 'Backend unavailable. Retry ' + appState.bootRetryCount + '/' + MAX_BOOT_RETRIES + '...';
      notify(msg, 'connecting');
      setChip('conn-chip', 'warn', 'Retrying...');

      appState.bootRetryTimer = window.setTimeout(connectBackend, BOOT_RETRY_INTERVAL_MS);
    }
  }

  window.addEventListener('beforeunload', function() {
    clearCameraRetry();
    if (appState.bootRetryTimer) window.clearTimeout(appState.bootRetryTimer);
    if (appState.monitoring.pollTimer) window.clearInterval(appState.monitoring.pollTimer);
    if (appState.telemetryES) appState.telemetryES.close();
    if (appState.eventsES) appState.eventsES.close();
  });

  initUI();
  connectBackend();
})();
</script>
</body>
</html>
"""
