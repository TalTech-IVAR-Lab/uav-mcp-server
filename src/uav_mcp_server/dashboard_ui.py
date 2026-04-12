"""Inline operator dashboard HTML with embedded CSS and JavaScript.

The page stays self-contained in a single response while using Leaflet from a
CDN for the live map layer.
"""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UAV MCP Dashboard</title>
<link
  rel="stylesheet"
  href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
  crossorigin=""
>
<style>
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#050608;
  --bg-alt:#0a0c10;
  --panel:#101318;
  --panel-strong:#141922;
  --panel-soft:#171d28;
  --border:#252c39;
  --border-strong:#384253;
  --text:#f3f6fb;
  --muted:#8d98aa;
  --soft:#667389;
  --blue:#4aa3ff;
  --cyan:#58d7ff;
  --green:#58d68d;
  --amber:#f2b94b;
  --red:#ff6e70;
  --shadow:0 18px 60px rgba(0,0,0,.32);
}
html,body{margin:0;padding:0;background:
  radial-gradient(circle at top left, rgba(74,163,255,.12), transparent 28%),
  radial-gradient(circle at top right, rgba(88,215,255,.08), transparent 24%),
  linear-gradient(180deg, #050608 0%, #07090c 42%, #050608 100%);
  color:var(--text);height:100%}
body{font-family:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;font-size:13px;line-height:1.38;
  min-height:100vh;overflow:hidden}
button,input{font:inherit}
.shell{max-width:1720px;height:100vh;margin:0 auto;padding:12px 16px 14px;display:grid;
  grid-template-rows:auto minmax(0,1fr);gap:12px}
.topbar{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;min-height:0}
.title-wrap{display:flex;flex-direction:column;gap:6px}
.eyebrow{font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--soft)}
.title{font-size:22px;font-weight:600;letter-spacing:.01em}
.subtitle{font-size:12px;color:var(--muted);max-width:760px}
.status-strip{display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:flex-start;gap:8px}
.chip{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;
  border:1px solid var(--border);background:rgba(16,19,24,.84);color:var(--muted);backdrop-filter:blur(12px)}
.dot{width:8px;height:8px;border-radius:999px;background:var(--soft)}
.chip.ok .dot{background:var(--green)}
.chip.warn .dot{background:var(--amber)}
.chip.err .dot{background:var(--red)}
.chip.live .dot{background:var(--cyan);box-shadow:0 0 0 6px rgba(88,215,255,.12)}

.dashboard{min-height:0;display:grid;grid-template-columns:minmax(460px,1.12fr) minmax(400px,.96fr) minmax(320px,.78fr);
  grid-template-rows:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr);gap:12px;
  grid-template-areas:
    "visual map status"
    "visual map commands"
    "visual map events"}
.dashboard>.stack{display:contents}
.stack{min-height:0}
.panel{background:linear-gradient(180deg, rgba(20,25,34,.92), rgba(14,18,24,.92));
  border:1px solid var(--border);border-radius:18px;box-shadow:var(--shadow);overflow:hidden;
  min-height:0;display:flex;flex-direction:column}
.panel-head{display:flex;justify-content:space-between;align-items:center;gap:12px;
  padding:12px 14px;border-bottom:1px solid rgba(56,66,83,.55)}
.panel-title{font-size:13px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.panel-note{font-size:12px;color:var(--soft)}
.panel-body{padding:12px 14px;min-height:0;flex:1}

.visual-panel{grid-area:visual}
.map-panel{grid-area:map}
.status-panel{grid-area:status}
.commands-panel{grid-area:commands}
.events-panel{grid-area:events}
.commands-panel .panel-body{overflow:auto}
.events-panel .panel-body{overflow:hidden}

.telemetry-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.metric{background:linear-gradient(180deg, rgba(8,10,14,.88), rgba(10,13,18,.68));
  border:1px solid rgba(37,44,57,.9);border-radius:14px;padding:10px 12px;min-height:64px}
.metric-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--soft)}
.metric-value{margin-top:6px;font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.metric-sub{margin-top:3px;font-size:11px;color:var(--muted)}
.state-pill{display:inline-flex;align-items:center;padding:8px 12px;border-radius:12px;
  border:1px solid transparent;font-size:12px;letter-spacing:.16em;text-transform:uppercase;font-weight:600}
.state-disconnected{color:var(--red);background:rgba(255,110,112,.12);border-color:rgba(255,110,112,.22)}
.state-connected,.state-ready{color:var(--green);background:rgba(88,214,141,.12);border-color:rgba(88,214,141,.22)}
.state-armed{color:var(--amber);background:rgba(242,185,75,.12);border-color:rgba(242,185,75,.22)}
.state-airborne{color:var(--blue);background:rgba(74,163,255,.12);border-color:rgba(74,163,255,.22)}
.state-landing{color:var(--amber);background:rgba(242,185,75,.12);border-color:rgba(242,185,75,.22)}
.state-fault{color:var(--red);background:rgba(255,110,112,.12);border-color:rgba(255,110,112,.22)}

.command-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.cmd-btn,.action-btn,.voice-btn{appearance:none;border:1px solid var(--border-strong);background:
  linear-gradient(180deg, rgba(8,11,15,.98), rgba(11,15,20,.98));color:var(--text);
  border-radius:14px;padding:10px 12px;text-align:left;cursor:pointer;transition:transform .16s ease,
  border-color .16s ease, background .16s ease, opacity .16s ease}
.cmd-btn:hover,.action-btn:hover,.voice-btn:hover{border-color:var(--cyan);transform:translateY(-1px)}
.cmd-btn:disabled,.action-btn:disabled,.voice-btn:disabled{opacity:.42;cursor:not-allowed;transform:none}
.cmd-name{display:block;font-size:13px;font-weight:600}
.cmd-hint{display:block;margin-top:4px;font-size:11px;color:var(--muted)}
.cmd-btn.safe{border-color:rgba(88,214,141,.34)}
.cmd-btn.caution{border-color:rgba(242,185,75,.34)}
.cmd-btn.danger{border-color:rgba(255,110,112,.34)}
.field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.field-group{display:grid;gap:6px}
.field-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--soft)}
.field-input{width:100%;padding:9px 11px;border-radius:12px;border:1px solid var(--border);
  background:rgba(5,6,8,.86);color:var(--text)}
.field-input:focus{outline:none;border-color:var(--cyan);box-shadow:0 0 0 3px rgba(88,215,255,.12)}
.result-bar{margin-top:10px;padding:10px 11px;border-radius:14px;border:1px solid transparent;
  display:none;font-size:12px;font-family:"IBM Plex Mono","SFMono-Regular",Consolas,monospace}
.result-bar.visible{display:block}
.result-bar.ok{background:rgba(88,214,141,.08);border-color:rgba(88,214,141,.24);color:#d4ffe4}
.result-bar.err{background:rgba(255,110,112,.08);border-color:rgba(255,110,112,.24);color:#ffd9d9}
.result-bar.info{background:rgba(74,163,255,.08);border-color:rgba(74,163,255,.24);color:#d4e9ff}

.camera-wrap{display:grid;grid-template-rows:auto minmax(0,1fr) auto auto;gap:10px;height:100%}
.camera-toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.toolbar-group{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.camera-stage{position:relative;border-radius:22px;overflow:hidden;background:#030405;
  border:1px solid rgba(56,66,83,.55);min-height:0;height:100%}
.camera-stream{width:100%;height:100%;object-fit:cover;display:block;background:#020304}
.camera-overlay{position:absolute;inset:0;cursor:crosshair;touch-action:none}
.crosshair{position:absolute;left:50%;top:50%;width:34px;height:34px;transform:translate(-50%,-50%);
  border:1px solid rgba(255,255,255,.22);border-radius:999px;pointer-events:none}
.crosshair::before,.crosshair::after{content:"";position:absolute;background:rgba(255,255,255,.22)}
.crosshair::before{left:50%;top:4px;width:1px;height:26px;transform:translateX(-50%)}
.crosshair::after{top:50%;left:4px;width:26px;height:1px;transform:translateY(-50%)}
.selection-box{position:absolute;border:1px solid var(--cyan);background:rgba(88,215,255,.08);
  box-shadow:0 0 0 1px rgba(88,215,255,.12) inset;display:none}
.selection-box.visible{display:block}
.camera-placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  padding:18px;text-align:center;color:var(--muted);background:linear-gradient(180deg, rgba(3,4,5,.2), rgba(3,4,5,.85))}
.camera-placeholder.hidden{display:none}
.selection-bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:start}
.selection-card{padding:12px 14px;border-radius:16px;background:rgba(8,11,15,.76);border:1px solid var(--border)}
.selection-title{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--soft)}
.selection-body{margin-top:6px;font-size:12px;font-variant-numeric:tabular-nums;color:var(--text)}
.selection-actions{display:flex;gap:10px;flex-wrap:wrap}
.action-btn{min-width:128px}
.action-btn.primary{border-color:rgba(74,163,255,.34)}
.action-btn.secondary{border-color:rgba(88,214,141,.34)}

.voice-grid{display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;align-items:start}
.voice-btn{width:54px;height:54px;border-radius:16px;padding:0;text-align:center;font-size:18px}
.voice-btn.listening{border-color:var(--red);box-shadow:0 0 0 10px rgba(255,110,112,.1);animation:pulse 1.2s infinite}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 rgba(255,110,112,.28)}
  70%{box-shadow:0 0 0 14px rgba(255,110,112,0)}
  100%{box-shadow:0 0 0 0 rgba(255,110,112,0)}
}
.voice-card{padding:12px 14px;border-radius:16px;background:rgba(8,11,15,.76);border:1px solid var(--border)}
.voice-transcript{margin-top:6px;min-height:32px;color:var(--text)}
.voice-actions{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;margin-top:10px}
.voice-input{width:100%;padding:10px 12px;border-radius:12px;border:1px solid var(--border);
  background:rgba(5,6,8,.86);color:var(--text)}
.voice-input:focus{outline:none;border-color:var(--cyan);box-shadow:0 0 0 3px rgba(88,215,255,.12)}
.voice-submit{min-width:138px;text-align:center}
.voice-hint{margin-top:6px;font-size:11px;color:var(--muted)}

.map-wrap{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr) auto;gap:10px;height:100%}
.map-surface{position:relative;height:100%;min-height:0;border-radius:18px;overflow:hidden;border:1px solid rgba(56,66,83,.55)}
#map{width:100%;height:100%;background:#0b0e12}
.map-note{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;align-content:start}
.map-card{padding:12px 14px;border-radius:16px;background:rgba(8,11,15,.76);border:1px solid var(--border)}
.map-card h3{margin:0;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--soft)}
.map-card p{margin:8px 0 0;color:var(--muted);font-size:12px}
.toggle-row{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:8px}
.toggle{display:inline-flex;align-items:center;gap:8px;color:var(--text)}
.toggle input{accent-color:var(--cyan)}
.legend{display:grid;gap:6px;margin-top:8px}
.legend-row{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12px}
.legend-swatch{width:14px;height:14px;border-radius:999px}
.swatch-drone{background:var(--blue)}
.swatch-home{background:var(--green)}
.swatch-target{background:var(--amber)}
.swatch-fence{background:rgba(88,215,255,.6)}

.events{height:100%;max-height:none;overflow:auto;padding-right:4px}
.event-row{display:grid;grid-template-columns:68px 98px minmax(0,1fr);gap:8px;padding:8px 0;border-bottom:1px solid rgba(37,44,57,.55)}
.event-row:last-child{border-bottom:none}
.event-time,.event-kind{font-family:"IBM Plex Mono","SFMono-Regular",Consolas,monospace;font-size:11px;color:var(--soft)}
.event-kind{color:var(--cyan)}
.event-msg{color:var(--text)}
.event-ok .event-msg{color:#d9ffe8}
.event-err .event-msg{color:#ffd7d7}

.leaflet-container{font:inherit;background:#0c1016}
.leaflet-control-container .leaflet-control{background:rgba(10,12,16,.86);color:var(--text);border:1px solid var(--border)}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#101318;color:var(--text)}
.drone-icon{width:22px;height:22px;border-radius:999px;border:2px solid rgba(255,255,255,.2);
  background:linear-gradient(180deg, var(--blue), #1f6cbb);position:relative;box-shadow:0 0 16px rgba(74,163,255,.4)}
.drone-icon::after{content:"";position:absolute;left:50%;top:3px;transform:translateX(-50%);
  width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:9px solid #eff7ff}
.home-icon,.target-icon{width:16px;height:16px;border-radius:999px;border:2px solid rgba(255,255,255,.2)}
.home-icon{background:var(--green)}
.target-icon{background:var(--amber)}

@media(max-width:1480px){
  .dashboard{grid-template-columns:minmax(420px,1.05fr) minmax(360px,.95fr) minmax(290px,.75fr)}
}
@media(max-width:1180px){
  body{overflow:auto}
  .shell{height:auto;min-height:100vh}
  .dashboard{grid-template-columns:1fr;grid-template-rows:auto;grid-template-areas:none}
  .dashboard>.stack{display:grid;gap:12px}
  .map-wrap{grid-template-columns:1fr;grid-template-rows:minmax(320px,52vh) auto}
  .camera-stage{min-height:360px}
}
@media(max-width:860px){
  .shell{padding:14px}
  .topbar{flex-direction:column}
  .status-strip{justify-content:flex-start}
  .telemetry-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .map-note{grid-template-columns:1fr}
  .selection-bar,.voice-grid{grid-template-columns:1fr}
  .command-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <div class="title-wrap">
      <div class="eyebrow">Pilot Dashboard</div>
      <div class="title">UAV MCP Dashboard</div>
      <div class="subtitle">Black-box operator surface for safe flight control, live video, target selection, orbit actions, and map awareness.</div>
    </div>
    <div class="status-strip">
      <div id="state-chip" class="chip"><span class="dot"></span><span>State unknown</span></div>
      <div id="conn-chip" class="chip err"><span class="dot"></span><span>Telemetry offline</span></div>
      <div id="camera-chip" class="chip warn"><span class="dot"></span><span>Camera pending</span></div>
      <div id="voice-chip" class="chip"><span class="dot"></span><span>Voice idle</span></div>
    </div>
  </header>

  <main class="dashboard">
    <section class="stack">
      <article class="panel visual-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Visual Targeting</div>
            <div class="panel-note">Drag a box or click the camera feed to project a ground point.</div>
          </div>
          <div class="toolbar-group">
            <span id="camera-topic" class="chip"><span class="dot"></span><span>Camera route pending</span></span>
          </div>
        </div>
        <div class="panel-body camera-wrap">
          <div class="camera-toolbar">
            <div class="toolbar-group">
              <button id="clear-selection" class="action-btn" type="button">Clear Selection</button>
              <button id="project-center" class="action-btn" type="button">Project Center</button>
            </div>
            <div class="toolbar-group">
              <span id="selection-status" class="chip"><span class="dot"></span><span>No target selected</span></span>
            </div>
          </div>

          <div class="camera-stage">
            <img id="camera-stream" class="camera-stream" alt="Live drone camera stream">
            <div id="camera-placeholder" class="camera-placeholder">Camera stream unavailable. The dashboard still supports telemetry, commands, map tracking, and selection math when a frame source is configured.</div>
            <div id="camera-overlay" class="camera-overlay">
              <div class="crosshair"></div>
              <div id="selection-box" class="selection-box"></div>
            </div>
          </div>

          <div class="selection-bar">
            <div class="selection-card">
              <div class="selection-title">Selected Target</div>
              <div id="selection-body" class="selection-body">Choose a point in the camera feed to compute its projected world coordinates.</div>
            </div>
            <div class="selection-actions">
              <button id="orbit-selection" class="action-btn primary" type="button" disabled>Orbit Selected Target</button>
              <button id="approach-selection" class="action-btn secondary" type="button" disabled>Approach Selected Target</button>
            </div>
          </div>

          <div class="voice-grid">
            <button id="voice-toggle" class="voice-btn" type="button" title="Toggle voice control">Mic</button>
            <div class="voice-card">
              <div class="selection-title">Voice Control</div>
              <div id="voice-transcript" class="voice-transcript">Voice recognition idle.</div>
              <div class="voice-actions">
                <input id="voice-command-input" class="voice-input" type="text" placeholder="Quick command: take off 10 meters" autocomplete="off" spellcheck="false">
                <button id="voice-submit" class="action-btn voice-submit" type="button">Run Command</button>
              </div>
              <div id="voice-mode-note" class="voice-hint">Mic dictation works in Chromium browsers. Quick Command works in every browser.</div>
              <div class="voice-hint">Examples: “take off 10 meters”, “go north 15 meters”, “circle around the left side”, “approach the center target”.</div>
            </div>
          </div>
        </div>
      </article>

      <article class="panel map-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Live Map</div>
            <div class="panel-note">Telemetry SSE drives position, heading, breadcrumb trail, and orbit target markers.</div>
          </div>
          <div class="toolbar-group">
            <label class="toggle">
              <input id="auto-center" type="checkbox" checked>
              <span>Auto-center map</span>
            </label>
          </div>
        </div>
        <div class="panel-body map-wrap">
          <div class="map-surface">
            <div id="map"></div>
          </div>
          <div class="map-note">
            <div class="map-card">
              <h3>Map State</h3>
              <p id="map-summary">Waiting for config and telemetry.</p>
              <div class="legend">
                <div class="legend-row"><span class="legend-swatch swatch-drone"></span><span>Drone position and heading</span></div>
                <div class="legend-row"><span class="legend-swatch swatch-home"></span><span>Home / geofence center</span></div>
                <div class="legend-row"><span class="legend-swatch swatch-target"></span><span>Projected or orbit target</span></div>
                <div class="legend-row"><span class="legend-swatch swatch-fence"></span><span>Configured geofence</span></div>
              </div>
            </div>
            <div class="map-card">
              <h3>Selection Hint</h3>
              <p>Projection assumes a flat ground plane at the home altitude and uses live yaw, pitch, roll, and altitude telemetry.</p>
            </div>
          </div>
        </div>
      </article>
    </section>

    <section class="stack">
      <article class="panel status-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Flight Status</div>
            <div class="panel-note">Compact operator telemetry tuned for rapid scan under load.</div>
          </div>
        </div>
        <div class="panel-body">
          <div class="telemetry-grid">
            <div class="metric">
              <div class="metric-label">State</div>
              <div class="metric-value"><span id="t-state" class="state-pill state-disconnected">disconnected</span></div>
              <div class="metric-sub" id="t-flight-mode">--</div>
            </div>
            <div class="metric">
              <div class="metric-label">Battery</div>
              <div class="metric-value" id="t-battery">--%</div>
              <div class="metric-sub" id="t-gps">--</div>
            </div>
            <div class="metric">
              <div class="metric-label">Altitude</div>
              <div class="metric-value" id="t-rel-alt">-- m</div>
              <div class="metric-sub" id="t-abs-alt">-- AMSL</div>
            </div>
            <div class="metric">
              <div class="metric-label">Latitude</div>
              <div class="metric-value" id="t-lat">--</div>
              <div class="metric-sub" id="t-lon">--</div>
            </div>
            <div class="metric">
              <div class="metric-label">Yaw / Pitch</div>
              <div class="metric-value" id="t-yaw">--</div>
              <div class="metric-sub" id="t-pitch">--</div>
            </div>
            <div class="metric">
              <div class="metric-label">Roll / Flags</div>
              <div class="metric-value" id="t-roll">--</div>
              <div class="metric-sub" id="t-flags">armed -- | air --</div>
            </div>
          </div>
        </div>
      </article>

      <article class="panel commands-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Command Console</div>
            <div class="panel-note">All command buttons use the same safety-gated server path as MCP tools.</div>
          </div>
        </div>
        <div class="panel-body">
          <div class="command-grid">
            <button class="cmd-btn" type="button" data-command="connect"><span class="cmd-name">Connect</span><span class="cmd-hint">Attach to PX4 backend</span></button>
            <button class="cmd-btn" type="button" data-command="arm"><span class="cmd-name">Arm</span><span class="cmd-hint">Run preflight gate and arm</span></button>
            <button class="cmd-btn caution" type="button" data-command="disarm"><span class="cmd-name">Disarm</span><span class="cmd-hint">Stop motors on ground</span></button>
            <button class="cmd-btn" type="button" id="takeoff-btn"><span class="cmd-name">Takeoff</span><span class="cmd-hint">Climb to configured altitude</span></button>
            <button class="cmd-btn safe" type="button" data-command="hold"><span class="cmd-name">Hold</span><span class="cmd-hint">Pause movement in place</span></button>
            <button class="cmd-btn safe" type="button" data-command="rtl"><span class="cmd-name">RTL</span><span class="cmd-hint">Return to launch safely</span></button>
            <button class="cmd-btn safe" type="button" data-command="land"><span class="cmd-name">Land</span><span class="cmd-hint">Initiate landing</span></button>
            <button class="cmd-btn" type="button" id="goto-btn"><span class="cmd-name">Goto Relative</span><span class="cmd-hint">Move by bounded N/E offset</span></button>
          </div>

          <div class="field-grid">
            <label class="field-group">
              <span class="field-label">Takeoff Altitude (m)</span>
              <input id="p-alt" class="field-input" type="number" value="5" min="2" max="120" step="0.5">
            </label>
            <label class="field-group">
              <span class="field-label">Selection Orbit Radius (m)</span>
              <input id="p-orbit-radius" class="field-input" type="number" value="12" min="5" max="200" step="1">
            </label>
            <label class="field-group">
              <span class="field-label">Goto North (m)</span>
              <input id="p-north" class="field-input" type="number" value="5" step="1">
            </label>
            <label class="field-group">
              <span class="field-label">Goto East (m)</span>
              <input id="p-east" class="field-input" type="number" value="0" step="1">
            </label>
            <label class="field-group">
              <span class="field-label">Goto Altitude (m)</span>
              <input id="p-goto-alt" class="field-input" type="number" value="5" min="2" max="120" step="0.5">
            </label>
            <label class="field-group">
              <span class="field-label">Selection Orbit Speed (m/s)</span>
              <input id="p-orbit-speed" class="field-input" type="number" value="3" min="0.5" max="15" step="0.5">
            </label>
          </div>

          <div id="result-bar" class="result-bar"></div>
        </div>
      </article>

      <article class="panel events-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Event Log</div>
            <div class="panel-note">Server-side command results and route activity stream in real time.</div>
          </div>
        </div>
        <div class="panel-body">
          <div id="events" class="events"></div>
        </div>
      </article>
    </section>
  </main>
</div>

<script
  src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
  crossorigin=""
></script>
<script>
(function(){
  const appState = {
    config: null,
    telemetry: null,
    history: [],
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
    geofenceCircle: null,
    pathLine: null,
    camera: {
      retryTimer: null,
    },
    voice: {
      supported: false,
      recognition: null,
      listening: false,
    },
  };

  const $ = (id) => document.getElementById(id);

  function notify(message, kind) {
    const bar = $('result-bar');
    bar.className = 'result-bar visible ' + (kind || 'info');
    bar.textContent = message;
  }

  function esc(value) {
    const node = document.createElement('div');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

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

  function setChip(id, mode, text) {
    const chip = $(id);
    chip.className = 'chip ' + (mode || '');
    chip.querySelector('span:last-child').textContent = text;
  }

  function formatNumber(value, digits) {
    return value == null || Number.isNaN(value) ? '--' : Number(value).toFixed(digits);
  }

  function updateTelemetry(snapshot) {
    appState.telemetry = snapshot;
    const state = snapshot.state || 'disconnected';
    $('t-state').textContent = state;
    $('t-state').className = 'state-pill state-' + state;
    $('t-flight-mode').textContent = snapshot.flight_mode || '--';
    $('t-battery').textContent = snapshot.battery_percent != null ? snapshot.battery_percent.toFixed(1) + '%' : '--%';
    $('t-gps').textContent = snapshot.gps_satellites != null ? snapshot.gps_satellites + ' satellites' : '-- satellites';
    $('t-rel-alt').textContent = snapshot.relative_altitude_m != null ? snapshot.relative_altitude_m.toFixed(1) + ' m' : '-- m';
    $('t-abs-alt').textContent = snapshot.absolute_altitude_m != null ? snapshot.absolute_altitude_m.toFixed(1) + ' AMSL' : '-- AMSL';
    $('t-lat').textContent = snapshot.latitude_deg != null ? snapshot.latitude_deg.toFixed(6) : '--';
    $('t-lon').textContent = snapshot.longitude_deg != null ? snapshot.longitude_deg.toFixed(6) : '--';
    $('t-yaw').textContent = snapshot.yaw_deg != null ? snapshot.yaw_deg.toFixed(1) + '°' : '--';
    $('t-pitch').textContent = snapshot.pitch_deg != null ? 'pitch ' + snapshot.pitch_deg.toFixed(1) + '°' : '--';
    $('t-roll').textContent = snapshot.roll_deg != null ? snapshot.roll_deg.toFixed(1) + '°' : '--';
    $('t-flags').textContent = 'armed ' + (snapshot.armed ? 'yes' : 'no') + ' | air ' + (snapshot.in_air ? 'yes' : 'no');

    setChip('state-chip', state === 'fault' || state === 'disconnected' ? 'err' : (state === 'airborne' ? 'live' : 'ok'), 'State ' + state);
    setChip('conn-chip', 'ok', 'Telemetry live');

    updateMapWithTelemetry(snapshot);
    updateMapSummary(snapshot);
  }

  function updateMapSummary(snapshot) {
    const parts = [];
    if (snapshot.latitude_deg != null && snapshot.longitude_deg != null) {
      parts.push('Drone at ' + snapshot.latitude_deg.toFixed(5) + ', ' + snapshot.longitude_deg.toFixed(5));
    } else {
      parts.push('Awaiting valid position telemetry');
    }
    if (snapshot.yaw_deg != null) {
      parts.push('heading ' + snapshot.yaw_deg.toFixed(0) + '°');
    }
    if (snapshot.relative_altitude_m != null) {
      parts.push('alt ' + snapshot.relative_altitude_m.toFixed(1) + ' m AGL');
    }
    $('map-summary').textContent = parts.join(' | ');
  }

  function appendEvent(event) {
    const container = $('events');
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
    while (container.children.length > 200) {
      container.lastChild.remove();
    }
  }

  function makeDivIcon(className) {
    return L.divIcon({
      className: '',
      html: '<div class="' + className + '"></div>',
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
  }

  function initMap() {
    if (typeof L === 'undefined' || !appState.config) {
      $('map-summary').textContent = 'Leaflet or dashboard config unavailable.';
      return;
    }

    appState.map = L.map('map', {
      zoomControl: true,
      attributionControl: true,
    }).setView(
      [appState.config.geofence_center_lat, appState.config.geofence_center_lon],
      17
    );

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 20,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(appState.map);

    appState.geofenceCircle = L.circle(
      [appState.config.geofence_center_lat, appState.config.geofence_center_lon],
      {
        radius: appState.config.geofence_radius_m,
        color: '#58d7ff',
        weight: 1.5,
        fillColor: '#58d7ff',
        fillOpacity: 0.06,
      }
    ).addTo(appState.map);

    appState.homeMarker = L.marker(
      [appState.config.geofence_center_lat, appState.config.geofence_center_lon],
      { icon: makeDivIcon('home-icon') }
    ).addTo(appState.map).bindPopup('Home / geofence center');

    appState.droneMarker = L.marker(
      [appState.config.geofence_center_lat, appState.config.geofence_center_lon],
      { icon: makeDivIcon('drone-icon') }
    ).addTo(appState.map).bindPopup('Drone');

    appState.targetMarker = L.marker(
      [appState.config.geofence_center_lat, appState.config.geofence_center_lon],
      { icon: makeDivIcon('target-icon'), opacity: 0.0 }
    ).addTo(appState.map);

    appState.pathLine = L.polyline([], {
      color: '#4aa3ff',
      opacity: 0.85,
      weight: 2.5,
    }).addTo(appState.map);

    appState.mapReady = true;
  }

  function rotateDroneMarker(yawDeg) {
    if (!appState.droneMarker) return;
    const icon = appState.droneMarker.getElement();
    if (!icon) return;
    icon.style.transformOrigin = '11px 11px';
    icon.style.transform = 'rotate(' + (yawDeg || 0) + 'deg)';
  }

  function updateMapWithTelemetry(snapshot) {
    if (!appState.mapReady || snapshot.latitude_deg == null || snapshot.longitude_deg == null) {
      return;
    }

    const latLng = [snapshot.latitude_deg, snapshot.longitude_deg];
    appState.droneMarker.setLatLng(latLng);
    rotateDroneMarker(snapshot.yaw_deg || 0);

    const history = appState.history;
    const last = history.length ? history[history.length - 1] : null;
    if (!last || last[0] !== latLng[0] || last[1] !== latLng[1]) {
      history.push(latLng);
      if (history.length > 200) history.shift();
      appState.pathLine.setLatLngs(history);
    }

    if ($('auto-center').checked) {
      appState.map.panTo(latLng, { animate: true, duration: 0.35 });
    }
  }

  function updateTargetMarker(projection) {
    if (!projection || !appState.mapReady) return;
    appState.targetMarker.setLatLng([projection.latitude_deg, projection.longitude_deg]);
    appState.targetMarker.setOpacity(1.0);
    appState.targetMarker.bindPopup(
      'Target<br>' +
      projection.latitude_deg.toFixed(6) + ', ' +
      projection.longitude_deg.toFixed(6)
    );
  }

  async function loadConfig() {
    appState.config = await fetchJSON('/dashboard/api/config');
    const camera = appState.config.camera || {};
    const cameraLabel = camera.available ? 'Camera ready' : (camera.reason || 'Camera unavailable');
    setChip(
      'camera-chip',
      camera.available ? 'ok' : (camera.enabled ? 'warn' : ''),
      cameraLabel
    );
    const topic = camera.topic || 'camera route';
    $('camera-topic').querySelector('span:last-child').textContent = topic;
  }

  async function refreshCameraConfig() {
    const config = await fetchJSON('/dashboard/api/config');
    appState.config = config;
    const camera = config.camera || {};
    setChip(
      'camera-chip',
      camera.available ? 'ok' : (camera.enabled ? 'warn' : ''),
      camera.available ? 'Camera ready' : (camera.reason || 'Camera unavailable')
    );
    $('camera-topic').querySelector('span:last-child').textContent = camera.topic || 'camera route';
    return camera;
  }

  function clearCameraRetry() {
    if (appState.camera.retryTimer !== null) {
      window.clearTimeout(appState.camera.retryTimer);
      appState.camera.retryTimer = null;
    }
  }

  function cameraPlaceholderText(camera) {
    if (!camera) {
      return 'Camera configuration is unavailable.';
    }
    return camera.reason || 'Camera stream unavailable. Retrying until frames arrive.';
  }

  function scheduleCameraRetry(delayMs) {
    clearCameraRetry();
    appState.camera.retryTimer = window.setTimeout(async () => {
      appState.camera.retryTimer = null;
      try {
        const camera = await refreshCameraConfig();
        loadCameraStream(camera);
      } catch (_) {
        scheduleCameraRetry(delayMs);
      }
    }, delayMs);
  }

  function loadCameraStream(camera) {
    const image = $('camera-stream');
    const placeholder = $('camera-placeholder');
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
    const camera = appState.config && appState.config.camera ? appState.config.camera : null;
    const image = $('camera-stream');
    const placeholder = $('camera-placeholder');
    image.addEventListener('load', () => {
      placeholder.classList.add('hidden');
      setChip('camera-chip', 'ok', 'Camera streaming');
    });
    image.addEventListener('error', async () => {
      placeholder.classList.remove('hidden');
      setChip('camera-chip', camera && camera.enabled ? 'warn' : 'err', 'Waiting for camera');
      try {
        const latestCamera = await refreshCameraConfig();
        placeholder.textContent = cameraPlaceholderText(latestCamera);
      } catch (_) {
        placeholder.textContent = 'Camera stream unavailable. Retrying until frames arrive.';
      }
      scheduleCameraRetry(2500);
    });
    loadCameraStream(camera);
    if (!camera || !camera.available) {
      scheduleCameraRetry(2500);
    }
  }

  function selectionToSummary(selection) {
    if (!selection || !selection.projection) {
      return 'Choose a point in the camera feed to compute its projected world coordinates.';
    }
    const point = selection.projection;
    return [
      'screen (' + selection.u.toFixed(1) + ', ' + selection.v.toFixed(1) + ')',
      'lat ' + point.latitude_deg.toFixed(6),
      'lon ' + point.longitude_deg.toFixed(6),
      'offset N ' + point.north_m.toFixed(1) + ' m / E ' + point.east_m.toFixed(1) + ' m',
      'distance ' + point.distance_m.toFixed(1) + ' m'
    ].join(' | ');
  }

  function updateSelectionUI() {
    const active = !!(appState.selection && appState.selection.projection);
    $('selection-body').textContent = selectionToSummary(appState.selection);
    $('orbit-selection').disabled = !active || appState.selectionBusy;
    $('approach-selection').disabled = !active || appState.selectionBusy;
    setChip(
      'selection-status',
      active ? 'ok' : '',
      active ? 'Target projected' : 'No target selected'
    );
    if (active) {
      updateTargetMarker(appState.selection.projection);
    }
  }

  function clearSelection() {
    appState.selection = null;
    $('selection-box').classList.remove('visible');
    $('selection-box').style.width = '0px';
    $('selection-box').style.height = '0px';
    if (appState.targetMarker) {
      appState.targetMarker.setOpacity(0.0);
    }
    updateSelectionUI();
  }

  function overlayPoint(event) {
    const overlay = $('camera-overlay');
    const rect = overlay.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    const params = appState.config && appState.config.camera ? appState.config.camera.params : null;
    const widthPx = params ? params.width_px : 320;
    const heightPx = params ? params.height_px : 240;
    return {
      x: x,
      y: y,
      rectWidth: rect.width,
      rectHeight: rect.height,
      u: (x / rect.width) * widthPx,
      v: (y / rect.height) * heightPx,
    };
  }

  function setSelectionBox(left, top, width, height) {
    const box = $('selection-box');
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
      const projection = await fetchJSON('/dashboard/api/project_pixel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ u: selection.u, v: selection.v }),
      });
      appState.selection = {
        ...selection,
        projection: projection,
      };
      updateSelectionUI();
      notify('Target projected: ' + projection.latitude_deg.toFixed(6) + ', ' + projection.longitude_deg.toFixed(6), 'info');
    } catch (error) {
      const message = error && error.message ? error.message : 'Projection failed';
      notify(message, 'err');
    } finally {
      appState.selectionBusy = false;
      updateSelectionUI();
    }
  }

  function initSelection() {
    const overlay = $('camera-overlay');

    overlay.addEventListener('pointerdown', (event) => {
      const point = overlayPoint(event);
      appState.selecting = true;
      appState.selectionStart = point;
      setSelectionBox(point.x, point.y, 1, 1);
    });

    overlay.addEventListener('pointermove', (event) => {
      if (!appState.selecting || !appState.selectionStart) return;
      const current = overlayPoint(event);
      const left = Math.min(appState.selectionStart.x, current.x);
      const top = Math.min(appState.selectionStart.y, current.y);
      const width = Math.max(2, Math.abs(current.x - appState.selectionStart.x));
      const height = Math.max(2, Math.abs(current.y - appState.selectionStart.y));
      setSelectionBox(left, top, width, height);
    });

    async function finalizeSelection(event) {
      if (!appState.selecting || !appState.selectionStart) return;
      appState.selecting = false;
      const current = overlayPoint(event);
      const left = Math.min(appState.selectionStart.x, current.x);
      const top = Math.min(appState.selectionStart.y, current.y);
      const width = Math.max(20, Math.abs(current.x - appState.selectionStart.x));
      const height = Math.max(20, Math.abs(current.y - appState.selectionStart.y));
      setSelectionBox(left, top, width, height);
      const centerX = left + width / 2;
      const centerY = top + height / 2;
      const params = appState.config.camera.params;
      const selection = {
        u: (centerX / current.rectWidth) * params.width_px,
        v: (centerY / current.rectHeight) * params.height_px,
      };
      await projectSelection(selection);
    }

    overlay.addEventListener('pointerup', finalizeSelection);
    overlay.addEventListener('pointerleave', (event) => {
      if (appState.selecting) {
        finalizeSelection(event);
      }
    });

    $('clear-selection').addEventListener('click', clearSelection);
    $('project-center').addEventListener('click', () => {
      const params = appState.config.camera.params;
      setSelectionBox(0, 0, 0, 0);
      projectSelection({
        u: params.width_px / 2,
        v: params.height_px / 2,
      });
    });

    $('orbit-selection').addEventListener('click', () => runSelectionAction('orbit'));
    $('approach-selection').addEventListener('click', () => runSelectionAction('approach'));
  }

  async function runSelectionAction(kind) {
    if (!appState.selection || !appState.selection.projection || appState.selectionBusy) {
      return;
    }
    appState.selectionBusy = true;
    updateSelectionUI();
    const route = kind === 'orbit' ? '/dashboard/api/select_and_orbit' : '/dashboard/api/select_and_approach';
    const payload = {
      u: appState.selection.u,
      v: appState.selection.v,
      radius_m: parseFloat($('p-orbit-radius').value),
      velocity_m_s: parseFloat($('p-orbit-speed').value),
      altitude_m: parseFloat($('p-goto-alt').value),
    };
    try {
      const result = await fetchJSON(route, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (result.data && result.data.projection) {
        updateTargetMarker(result.data.projection);
      }
      notify((kind === 'orbit' ? 'Orbit' : 'Approach') + ': ' + result.message, result.success ? 'ok' : 'err');
    } catch (error) {
      notify(error.message || 'Selection command failed', 'err');
    } finally {
      appState.selectionBusy = false;
      updateSelectionUI();
    }
  }

  function connectTelemetrySSE() {
    if (appState.telemetryES) appState.telemetryES.close();
    appState.telemetryES = new EventSource('/dashboard/api/telemetry/stream');
    appState.telemetryES.addEventListener('telemetry', (event) => {
      try {
        updateTelemetry(JSON.parse(event.data));
      } catch (_) {}
    });
    appState.telemetryES.onopen = () => setChip('conn-chip', 'ok', 'Telemetry live');
    appState.telemetryES.onerror = () => setChip('conn-chip', 'err', 'Telemetry reconnecting');
  }

  function connectEventsSSE() {
    if (appState.eventsES) appState.eventsES.close();
    appState.eventsES = new EventSource('/dashboard/api/events/stream');
    appState.eventsES.addEventListener('dashboard_event', (event) => {
      try {
        appendEvent(JSON.parse(event.data));
      } catch (_) {}
    });
  }

  async function loadInitialEvents() {
    try {
      const events = await fetchJSON('/dashboard/api/events?limit=50');
      events.forEach(appendEvent);
    } catch (_) {}
  }

  async function refreshStatus() {
    try {
      updateTelemetry(await fetchJSON('/dashboard/api/status'));
    } catch (error) {
      notify(error.message || 'Failed to load initial status', 'err');
    }
  }

  async function sendCommand(command, body) {
    if (appState.commandBusy) return;
    appState.commandBusy = true;
    notify(command + '...', 'info');
    try {
      const result = await fetchJSON('/dashboard/api/commands/' + encodeURIComponent(command), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      notify(command + ': ' + result.message, result.success ? 'ok' : 'err');
      if (result.data && result.data.target_latitude_deg && result.data.target_longitude_deg) {
        updateTargetMarker({
          latitude_deg: result.data.target_latitude_deg,
          longitude_deg: result.data.target_longitude_deg,
        });
      }
      return result;
    } catch (error) {
      notify(command + ': ' + (error.message || 'request failed'), 'err');
    } finally {
      appState.commandBusy = false;
    }
  }

  function initCommands() {
    document.querySelectorAll('[data-command]').forEach((button) => {
      button.addEventListener('click', () => sendCommand(button.dataset.command));
    });
    $('takeoff-btn').addEventListener('click', () => {
      const altitude_m = parseFloat($('p-alt').value);
      if (Number.isNaN(altitude_m)) {
        notify('Takeoff altitude must be numeric.', 'err');
        return;
      }
      sendCommand('takeoff', { altitude_m: altitude_m });
    });
    $('goto-btn').addEventListener('click', () => {
      const north_m = parseFloat($('p-north').value);
      const east_m = parseFloat($('p-east').value);
      const altitude_m = parseFloat($('p-goto-alt').value);
      if ([north_m, east_m, altitude_m].some((value) => Number.isNaN(value))) {
        notify('Goto inputs must all be numeric.', 'err');
        return;
      }
      sendCommand('goto_relative', {
        north_m: north_m,
        east_m: east_m,
        altitude_m: altitude_m,
      });
    });
  }

  function setVoiceStatus(mode, text) {
    setChip('voice-chip', mode, text);
  }

  async function submitQuickCommand() {
    const input = $('voice-command-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    await executeVoiceCommand(text);
  }

  function spatialReferenceToPixel(text) {
    const params = appState.config.camera.params;
    const center = { u: params.width_px / 2, v: params.height_px / 2 };
    const horizontal = text.includes('left') ? 0.25 : (text.includes('right') ? 0.75 : 0.5);
    const vertical = text.includes('top') ? 0.25 : (text.includes('bottom') ? 0.75 : 0.5);
    if (!/(left|right|top|bottom|center|middle)/.test(text)) {
      return center;
    }
    return {
      u: params.width_px * horizontal,
      v: params.height_px * vertical,
    };
  }

  function parseDirectionalGoto(text) {
    const match = text.match(/go\\s+(north|south|east|west)\\s+(\\d+(?:\\.\\d+)?)\\s*(?:meter|meters|m)?/);
    if (!match) return null;
    const direction = match[1];
    const distance = parseFloat(match[2]);
    const result = { north_m: 0, east_m: 0, altitude_m: parseFloat($('p-goto-alt').value) || 5 };
    if (direction === 'north') result.north_m = distance;
    if (direction === 'south') result.north_m = -distance;
    if (direction === 'east') result.east_m = distance;
    if (direction === 'west') result.east_m = -distance;
    return result;
  }

  async function executeVoiceCommand(text) {
    const normalized = text.trim().toLowerCase();
    $('voice-transcript').textContent = normalized || 'Voice recognition idle.';

    if (!normalized) return;
    if (normalized.includes('connect')) return sendCommand('connect');
    if (normalized.includes('disarm')) return sendCommand('disarm');
    if (normalized.includes('arm')) return sendCommand('arm');
    if (normalized.includes('land')) return sendCommand('land');
    if (/(rtl|return|come back)/.test(normalized)) return sendCommand('rtl');
    if (/(hold|hover|stop)/.test(normalized)) return sendCommand('hold');

    const takeoffMatch = normalized.match(/take\\s*off(?:\\s+to)?\\s+(\\d+(?:\\.\\d+)?)?/);
    if (takeoffMatch) {
      const altitude = takeoffMatch[1] ? parseFloat(takeoffMatch[1]) : parseFloat($('p-alt').value) || 5;
      return sendCommand('takeoff', { altitude_m: altitude });
    }

    const gotoRelative = parseDirectionalGoto(normalized);
    if (gotoRelative) {
      return sendCommand('goto_relative', gotoRelative);
    }

    if (/(circle|orbit)/.test(normalized)) {
      const selection = spatialReferenceToPixel(normalized);
      await projectSelection(selection);
      return runSelectionAction('orbit');
    }

    if (/(approach|inspect)/.test(normalized)) {
      const selection = spatialReferenceToPixel(normalized);
      await projectSelection(selection);
      return runSelectionAction('approach');
    }

    notify('Voice command not recognized: ' + normalized, 'err');
  }

  function initVoice() {
    $('voice-submit').addEventListener('click', () => {
      submitQuickCommand();
    });
    $('voice-command-input').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitQuickCommand();
      }
    });

    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setVoiceStatus('warn', 'Quick command mode');
      $('voice-transcript').textContent = 'This browser does not expose live speech recognition.';
      $('voice-mode-note').textContent = 'Firefox: use Quick Command here, or open the dashboard in Chrome or Edge for microphone dictation.';
      $('voice-toggle').disabled = true;
      return;
    }

    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    appState.voice.supported = true;
    appState.voice.recognition = recognition;
    setVoiceStatus('', 'Voice idle');
    $('voice-mode-note').textContent = 'Microphone dictation is active in this browser. Quick Command stays available as a fallback.';

    recognition.onstart = () => {
      appState.voice.listening = true;
      $('voice-toggle').classList.add('listening');
      setVoiceStatus('live', 'Voice listening');
    };

    recognition.onend = () => {
      appState.voice.listening = false;
      $('voice-toggle').classList.remove('listening');
      setVoiceStatus('', 'Voice idle');
    };

    recognition.onerror = (event) => {
      appState.voice.listening = false;
      $('voice-toggle').classList.remove('listening');
      setVoiceStatus('err', 'Voice error');
      notify('Voice recognition error: ' + event.error, 'err');
    };

    recognition.onresult = async (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          await executeVoiceCommand(transcript);
        } else {
          interim += transcript;
        }
      }
      if (interim) {
        $('voice-transcript').textContent = interim;
      }
    };

    $('voice-toggle').addEventListener('click', () => {
      if (!appState.voice.recognition) return;
      if (appState.voice.listening) {
        appState.voice.recognition.stop();
      } else {
        appState.voice.recognition.start();
      }
    });
  }

  async function boot() {
    try {
      await loadConfig();
      initMap();
      initCamera();
      initSelection();
      initCommands();
      initVoice();
      connectTelemetrySSE();
      connectEventsSSE();
      loadInitialEvents();
      refreshStatus();
      updateSelectionUI();
    } catch (error) {
      notify(error.message || 'Dashboard bootstrap failed', 'err');
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
</script>
</body>
</html>
"""
