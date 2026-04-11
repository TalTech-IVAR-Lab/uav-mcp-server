"""Inline HTML for the thin operator dashboard.

The entire UI is a single self-contained HTML page with embedded CSS and
JavaScript.  No external build system, no CDN dependencies.
"""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UAV MCP Dashboard</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f1117;--surface:#1a1d27;--border:#2a2d3a;
  --text:#e1e4ed;--muted:#8b8fa3;--accent:#4f8ff7;
  --green:#2dd4a8;--red:#f45d6b;--amber:#f5a623;
}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}
.container{max-width:1100px;margin:0 auto;padding:16px}
header{display:flex;justify-content:space-between;align-items:center;
  padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:16px}
header h1{font-size:18px;font-weight:600}
.conn-badge{font-size:12px;padding:4px 10px;border-radius:12px;font-weight:500}
.conn-badge.ok{background:#2dd4a822;color:var(--green)}
.conn-badge.err{background:#f45d6b22;color:var(--red)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:16px}
.card h2{font-size:14px;font-weight:600;color:var(--muted);
  text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px}
.telem-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.telem-item{background:var(--bg);border-radius:6px;padding:8px 10px}
.telem-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.3px}
.telem-value{font-size:16px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}
.state-badge{display:inline-block;font-size:13px;font-weight:600;padding:4px 12px;
  border-radius:6px;text-transform:uppercase;letter-spacing:.5px}
.state-disconnected{background:#f45d6b22;color:var(--red)}
.state-connected,.state-ready{background:#2dd4a822;color:var(--green)}
.state-armed{background:#f5a62322;color:var(--amber)}
.state-airborne{background:#4f8ff722;color:var(--accent)}
.state-landing{background:#f5a62322;color:var(--amber)}
.state-fault{background:#f45d6b22;color:var(--red)}
.cmds{display:flex;flex-wrap:wrap;gap:8px}
.cmd-btn{background:var(--bg);color:var(--text);border:1px solid var(--border);
  border-radius:6px;padding:8px 16px;cursor:pointer;font-size:13px;font-weight:500;
  transition:border-color .15s,background .15s}
.cmd-btn:hover{border-color:var(--accent);background:#4f8ff711}
.cmd-btn:active{background:#4f8ff722}
.cmd-btn:disabled{opacity:.4;cursor:not-allowed}
.cmd-btn.safe{border-color:var(--green)}
.cmd-btn.caution{border-color:var(--amber)}
.param-row{display:flex;gap:6px;align-items:center;margin-top:8px;flex-wrap:wrap}
.param-input{background:var(--bg);color:var(--text);border:1px solid var(--border);
  border-radius:4px;padding:5px 8px;width:70px;font-size:13px;font-variant-numeric:tabular-nums}
.param-input:focus{outline:none;border-color:var(--accent)}
.param-label{font-size:12px;color:var(--muted)}
.events{max-height:280px;overflow-y:auto;font-family:"SF Mono",Consolas,monospace;font-size:12px}
.event-row{padding:4px 0;border-bottom:1px solid var(--border);display:flex;gap:8px}
.event-time{color:var(--muted);flex-shrink:0;width:85px}
.event-kind{color:var(--accent);flex-shrink:0;width:110px}
.event-msg{color:var(--text)}
.event-ok .event-msg{color:var(--green)}
.event-err .event-msg{color:var(--red)}
.result-bar{margin-top:12px;padding:8px 10px;border-radius:6px;font-size:12px;
  font-family:"SF Mono",Consolas,monospace;display:none}
.result-bar.visible{display:block}
.result-bar.ok{background:#2dd4a811;border:1px solid #2dd4a833}
.result-bar.err{background:#f45d6b11;border:1px solid #f45d6b33}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>UAV MCP Dashboard</h1>
    <span id="conn-badge" class="conn-badge err">SSE disconnected</span>
  </header>

  <div class="grid">
    <div class="card">
      <h2>Telemetry</h2>
      <div class="telem-grid">
        <div class="telem-item">
          <div class="telem-label">State</div>
          <div class="telem-value"><span id="t-state" class="state-badge state-disconnected">disconnected</span></div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Armed</div>
          <div class="telem-value" id="t-armed">--</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">In Air</div>
          <div class="telem-value" id="t-in-air">--</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Battery</div>
          <div class="telem-value" id="t-battery">--%</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Lat</div>
          <div class="telem-value" id="t-lat">--</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Lon</div>
          <div class="telem-value" id="t-lon">--</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Rel Alt</div>
          <div class="telem-value" id="t-rel-alt">-- m</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Flight Mode</div>
          <div class="telem-value" id="t-flight-mode">--</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">GPS</div>
          <div class="telem-value" id="t-gps">--</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Commands</h2>
      <div class="cmds">
        <button class="cmd-btn" onclick="sendCmd('connect')">Connect</button>
        <button class="cmd-btn" onclick="sendCmd('arm')">Arm</button>
        <button class="cmd-btn caution" onclick="sendCmd('disarm')">Disarm</button>
        <button class="cmd-btn" onclick="sendTakeoff()">Takeoff</button>
        <button class="cmd-btn safe" onclick="sendCmd('land')">Land</button>
        <button class="cmd-btn safe" onclick="sendCmd('hold')">Hold</button>
        <button class="cmd-btn safe" onclick="sendCmd('rtl')">RTL</button>
        <button class="cmd-btn" onclick="sendGoto()">Goto Rel</button>
      </div>
      <div class="param-row">
        <span class="param-label">Takeoff alt:</span>
        <input id="p-alt" class="param-input" type="number" value="5" min="2" max="120" step="0.5"> m
      </div>
      <div class="param-row">
        <span class="param-label">Goto:</span>
        <span class="param-label">N</span><input id="p-north" class="param-input" type="number" value="5" step="1">
        <span class="param-label">E</span><input id="p-east" class="param-input" type="number" value="0" step="1">
        <span class="param-label">Alt</span><input id="p-goto-alt" class="param-input" type="number" value="5" min="2" max="120" step="0.5"> m
      </div>
      <div id="result-bar" class="result-bar"></div>
    </div>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>Event Log</h2>
    <div id="events" class="events"></div>
  </div>
</div>

<script>
(function(){
  const $ = (id) => document.getElementById(id);

  // --- Telemetry SSE ---
  let telemES = null;
  function connectTelemetrySSE() {
    if (telemES) telemES.close();
    telemES = new EventSource('/dashboard/api/telemetry/stream');
    telemES.addEventListener('telemetry', (e) => {
      try { updateTelemetry(JSON.parse(e.data)); } catch(_){}
    });
    telemES.onopen = () => {
      $('conn-badge').className = 'conn-badge ok';
      $('conn-badge').textContent = 'SSE connected';
    };
    telemES.onerror = () => {
      $('conn-badge').className = 'conn-badge err';
      $('conn-badge').textContent = 'SSE disconnected';
    };
  }

  function updateTelemetry(t) {
    const stateEl = $('t-state');
    stateEl.textContent = t.state || '--';
    stateEl.className = 'state-badge state-' + (t.state || 'disconnected');

    $('t-armed').textContent = t.armed ? 'YES' : 'NO';
    $('t-armed').style.color = t.armed ? 'var(--amber)' : 'var(--muted)';
    $('t-in-air').textContent = t.in_air ? 'YES' : 'NO';
    $('t-in-air').style.color = t.in_air ? 'var(--accent)' : 'var(--muted)';
    $('t-battery').textContent = t.battery_percent != null ? t.battery_percent.toFixed(1) + '%' : '--%';
    $('t-lat').textContent = t.latitude_deg != null ? t.latitude_deg.toFixed(6) : '--';
    $('t-lon').textContent = t.longitude_deg != null ? t.longitude_deg.toFixed(6) : '--';
    $('t-rel-alt').textContent = t.relative_altitude_m != null ? t.relative_altitude_m.toFixed(1) + ' m' : '-- m';
    $('t-flight-mode').textContent = t.flight_mode || '--';
    $('t-gps').textContent = t.gps_satellites != null ? t.gps_satellites + ' sats' : '--';
  }

  // --- Events SSE ---
  let eventsES = null;
  function connectEventsSSE() {
    if (eventsES) eventsES.close();
    eventsES = new EventSource('/dashboard/api/events/stream');
    eventsES.addEventListener('dashboard_event', (e) => {
      try { appendEvent(JSON.parse(e.data)); } catch(_){}
    });
  }

  function appendEvent(ev) {
    const container = $('events');
    const row = document.createElement('div');
    const isOk = ev.data && ev.data.success === true;
    const isErr = ev.data && ev.data.success === false;
    row.className = 'event-row' + (isOk ? ' event-ok' : '') + (isErr ? ' event-err' : '');
    const time = ev.timestamp ? ev.timestamp.split('T')[1].split('.')[0] : '';
    row.innerHTML =
      '<span class="event-time">' + esc(time) + '</span>' +
      '<span class="event-kind">' + esc(ev.kind) + '</span>' +
      '<span class="event-msg">' + esc(ev.summary) + '</span>';
    container.prepend(row);
    while (container.children.length > 200) container.lastChild.remove();
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  // --- Commands ---
  let cmdInFlight = false;

  async function sendCmd(name, body) {
    if (cmdInFlight) return;
    cmdInFlight = true;
    const bar = $('result-bar');
    bar.className = 'result-bar visible ok';
    bar.textContent = name + '...';
    try {
      const resp = await fetch('/dashboard/api/commands/' + encodeURIComponent(name), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {}),
      });
      const result = await resp.json();
      bar.className = 'result-bar visible ' + (result.success ? 'ok' : 'err');
      bar.textContent = name + ': ' + (result.message || (result.success ? 'ok' : 'failed'));
    } catch(e) {
      bar.className = 'result-bar visible err';
      bar.textContent = name + ': network error';
    } finally {
      cmdInFlight = false;
    }
  }

  window.sendCmd = sendCmd;

  window.sendTakeoff = function() {
    const alt = parseFloat($('p-alt').value);
    if (isNaN(alt)) return;
    sendCmd('takeoff', {altitude_m: alt});
  };

  window.sendGoto = function() {
    const n = parseFloat($('p-north').value);
    const e = parseFloat($('p-east').value);
    const a = parseFloat($('p-goto-alt').value);
    if (isNaN(n) || isNaN(e) || isNaN(a)) return;
    sendCmd('goto_relative', {north_m: n, east_m: e, altitude_m: a});
  };

  // --- Start SSE first, then backfill historical events ---
  connectTelemetrySSE();
  connectEventsSSE();

  fetch('/dashboard/api/events?limit=50')
    .then(r => r.json())
    .then(events => { events.forEach(appendEvent); })
    .catch(() => {});
})();
</script>
</body>
</html>
"""
