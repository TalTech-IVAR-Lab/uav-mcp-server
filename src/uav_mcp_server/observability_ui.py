"""Self-contained observability dashboard page."""

OBSERVABILITY_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UAV MCP Observability</title>
<meta name="description" content="Latency, reliability, safety, and runtime observability dashboard for the UAV MCP thesis system.">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; }
  :root {
    --bg: #07110f;
    --bg-2: #0d1d18;
    --panel: rgba(236, 230, 207, 0.07);
    --panel-strong: rgba(236, 230, 207, 0.12);
    --line: rgba(236, 230, 207, 0.14);
    --text: #f3ecd8;
    --muted: #9ca997;
    --ink: #06100d;
    --accent: #d7ff4f;
    --blue: #76e4ff;
    --green: #7cff9b;
    --amber: #ffbf66;
    --red: #ff6d6d;
    --shadow: 0 24px 80px rgba(0,0,0,0.35);
    --radius: 18px;
    --font: 'IBM Plex Sans', system-ui, sans-serif;
    --mono: 'IBM Plex Mono', monospace;
  }
  html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); font-family: var(--font); }
  body {
    background:
      radial-gradient(circle at 15% 10%, rgba(215,255,79,0.12), transparent 28%),
      radial-gradient(circle at 88% 8%, rgba(118,228,255,0.12), transparent 28%),
      linear-gradient(135deg, #07110f 0%, #11251e 48%, #07110f 100%);
  }
  a { color: inherit; }
  .shell { max-width: 1720px; margin: 0 auto; padding: 24px; }
  .hero {
    display: grid; grid-template-columns: minmax(320px, 1.2fr) minmax(300px, 0.8fr);
    gap: 18px; margin-bottom: 18px;
  }
  .hero-card, .panel {
    background: linear-gradient(160deg, var(--panel), rgba(0,0,0,0.22));
    border: 1px solid var(--line); border-radius: var(--radius);
    box-shadow: var(--shadow); backdrop-filter: blur(18px);
  }
  .hero-card { padding: 28px; min-height: 250px; position: relative; overflow: hidden; }
  .hero-card::after {
    content: ""; position: absolute; inset: auto -80px -120px auto;
    width: 360px; height: 360px; border-radius: 50%;
    background: radial-gradient(circle, rgba(215,255,79,0.22), transparent 64%);
  }
  .eyebrow {
    color: var(--accent); font-family: var(--mono); font-size: 12px;
    letter-spacing: 0.16em; text-transform: uppercase; font-weight: 600;
  }
  h1 { font-size: clamp(36px, 5vw, 76px); line-height: 0.92; margin: 14px 0 18px; max-width: 900px; }
  .hero p { max-width: 760px; color: var(--muted); font-size: 16px; line-height: 1.6; margin: 0; }
  .nav { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 24px; }
  .btn {
    border: 1px solid var(--line); background: rgba(236,230,207,0.08); color: var(--text);
    padding: 10px 14px; border-radius: 999px; font-weight: 600; text-decoration: none;
    font-size: 13px; cursor: pointer;
  }
  .btn.primary { background: var(--accent); color: var(--ink); border-color: var(--accent); }
  .status-card { padding: 20px; display: grid; gap: 12px; }
  .status-line { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
  .pill {
    display: inline-flex; align-items: center; gap: 8px; border-radius: 999px;
    padding: 7px 10px; background: rgba(236,230,207,0.08); border: 1px solid var(--line);
    color: var(--muted); font-size: 12px; font-family: var(--mono);
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .ok .dot { background: var(--green); box-shadow: 0 0 12px var(--green); }
  .warn .dot { background: var(--amber); box-shadow: 0 0 12px var(--amber); }
  .err .dot { background: var(--red); box-shadow: 0 0 12px var(--red); }
  .grid { display: grid; gap: 18px; }
  .grid.metrics { grid-template-columns: repeat(4, minmax(180px, 1fr)); }
  .grid.main { grid-template-columns: minmax(520px, 1.1fr) minmax(420px, 0.9fr); align-items: start; }
  .panel { padding: 18px; min-width: 0; }
  .panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 14px; }
  .panel-title { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700; }
  .metric {
    min-height: 150px; display: flex; flex-direction: column; justify-content: space-between;
    background: linear-gradient(145deg, rgba(236,230,207,0.10), rgba(0,0,0,0.16));
  }
  .metric-value { font-size: 34px; line-height: 1; font-weight: 700; font-family: var(--mono); }
  .metric-sub { color: var(--muted); font-size: 13px; margin-top: 8px; line-height: 1.45; }
  .metric-accent { color: var(--accent); }
  .metric-blue { color: var(--blue); }
  .metric-green { color: var(--green); }
  .metric-amber { color: var(--amber); }
  .section { margin-top: 18px; }
  .chart-wrap { height: 260px; position: relative; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: rgba(0,0,0,0.16); }
  svg { width: 100%; height: 100%; display: block; }
  .bars { display: grid; gap: 10px; }
  .bar-row { display: grid; grid-template-columns: 132px 1fr 72px; gap: 10px; align-items: center; font-family: var(--mono); font-size: 12px; }
  .bar-track { height: 12px; border-radius: 999px; background: rgba(236,230,207,0.10); overflow: hidden; }
  .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--blue)); border-radius: inherit; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; }
  table { width: 100%; border-collapse: collapse; min-width: 720px; }
  th, td { padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
  th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; }
  td { font-size: 13px; }
  td.mono, .mono { font-family: var(--mono); }
  tr:last-child td { border-bottom: none; }
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .card-mini { border: 1px solid var(--line); border-radius: 14px; padding: 14px; background: rgba(0,0,0,0.14); }
  .list { display: grid; gap: 8px; }
  .event {
    display: grid; grid-template-columns: 144px 92px 1fr auto; gap: 10px;
    padding: 10px 0; border-bottom: 1px solid var(--line); font-size: 12px;
  }
  .event:last-child { border-bottom: none; }
  .event .message { color: var(--muted); }
  .empty { color: var(--muted); padding: 18px; border: 1px dashed var(--line); border-radius: 14px; }
  .footer-note { color: var(--muted); font-size: 12px; margin-top: 18px; line-height: 1.5; }
  @media (max-width: 1160px) {
    .hero, .grid.main { grid-template-columns: 1fr; }
    .grid.metrics { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
  }
  @media (max-width: 720px) {
    .shell { padding: 14px; }
    .grid.metrics, .split { grid-template-columns: 1fr; }
    .event { grid-template-columns: 1fr; }
    h1 { font-size: 38px; }
  }
</style>
</head>
<body>
<div class="shell">
  <section class="hero">
    <article class="hero-card">
      <div class="eyebrow">TalTech UAV MCP Thesis Evidence</div>
      <h1>Observability for latency, reliability, and safety behavior.</h1>
      <p>
        This page separates reproducible benchmark artifacts from live operational traces,
        so thesis claims can be tied back to raw JSON/CSV evidence and the current runtime context.
      </p>
      <div class="nav">
        <a class="btn primary" href="/dashboard/">Operator Dashboard</a>
        <button id="refresh" class="btn" type="button">Refresh Data</button>
        <a class="btn" href="/dashboard/api/observability/export">Export JSON</a>
      </div>
    </article>
    <aside class="hero-card status-card">
      <div class="status-line"><span class="panel-title">Readiness</span><span id="ready-pill" class="pill warn"><span class="dot"></span><span>Loading</span></span></div>
      <div class="status-line"><span>Latest artifact</span><strong id="latest-run">--</strong></div>
      <div class="status-line"><span>Runtime profile</span><strong id="runtime-profile">--</strong></div>
      <div class="status-line"><span>Event store</span><strong id="event-store">--</strong></div>
      <p class="footer-note" id="summary-note">Waiting for observability API.</p>
    </aside>
  </section>

  <section class="grid metrics">
    <article class="panel metric"><div><div class="panel-title">Latency P95</div><div id="m-latency" class="metric-value metric-accent">--</div></div><div id="m-latency-sub" class="metric-sub">No latency run loaded.</div></article>
    <article class="panel metric"><div><div class="panel-title">Reliability</div><div id="m-reliability" class="metric-value metric-green">--</div></div><div id="m-reliability-sub" class="metric-sub">No reliability run loaded.</div></article>
    <article class="panel metric"><div><div class="panel-title">Safety Checks</div><div id="m-safety" class="metric-value metric-amber">--</div></div><div id="m-safety-sub" class="metric-sub">No safety run loaded.</div></article>
    <article class="panel metric"><div><div class="panel-title">Live Rejections</div><div id="m-rejections" class="metric-value metric-blue">--</div></div><div id="m-rejections-sub" class="metric-sub">Runtime command trace is empty.</div></article>
  </section>

  <section class="grid main section">
    <article class="panel">
      <div class="panel-head"><div><div class="panel-title">Latency Analysis</div><h2>Per-tool middleware and action latency</h2></div><span id="latency-headline" class="pill">--</span></div>
      <div class="chart-wrap"><svg id="latency-chart" role="img" aria-label="Latency trend chart"></svg></div>
      <div id="latency-bars" class="bars section"></div>
    </article>

    <article class="panel">
      <div class="panel-head"><div><div class="panel-title">Safety Behavior</div><h2>Rejection matrix and safety cases</h2></div><span id="safety-headline" class="pill">--</span></div>
      <div class="split">
        <div class="card-mini"><div class="panel-title">Benchmark Scenarios</div><div id="safety-scenarios" class="list section"></div></div>
        <div class="card-mini"><div class="panel-title">Live Error Codes</div><div id="error-bars" class="bars section"></div></div>
      </div>
    </article>
  </section>

  <section class="grid main section">
    <article class="panel">
      <div class="panel-head"><div><div class="panel-title">Benchmark Artifact Explorer</div><h2>Reproducible runs</h2></div><span id="run-count" class="pill">0 runs</span></div>
      <div class="table-wrap"><table><thead><tr><th>Time</th><th>Benchmark</th><th>Headline</th><th>Records</th><th>Result</th></tr></thead><tbody id="runs-table"></tbody></table></div>
    </article>

    <article class="panel">
      <div class="panel-head"><div><div class="panel-title">Live Command Trace</div><h2>Runtime events and validation outcomes</h2></div><span id="event-count" class="pill">0 events</span></div>
      <div id="events-list" class="list"></div>
    </article>
  </section>

  <section class="panel section">
    <div class="panel-head"><div><div class="panel-title">Runtime Context</div><h2>Configuration evidence for interpreting results</h2></div></div>
    <div class="split">
      <div class="card-mini"><div class="panel-title">Stack</div><div id="runtime-stack" class="list section"></div></div>
      <div class="card-mini"><div class="panel-title">Readiness Flags</div><div id="runtime-flags" class="list section"></div></div>
    </div>
  </section>
</div>

<script>
(function(){
  'use strict';

  const $ = (id) => document.getElementById(id);
  const api = {
    summary: '/dashboard/api/observability/summary',
    runs: '/dashboard/api/observability/runs',
    events: '/dashboard/api/observability/events?limit=100'
  };

  function fmtMs(value) {
    return Number.isFinite(value) ? `${value.toFixed(value >= 100 ? 0 : 1)} ms` : '--';
  }
  function fmtPct(value) {
    return Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : '--';
  }
  function text(value, fallback='--') {
    return value === null || value === undefined || value === '' ? fallback : String(value);
  }
  function setPill(el, ok, label) {
    el.className = `pill ${ok ? 'ok' : 'warn'}`;
    el.innerHTML = `<span class="dot"></span><span>${label}</span>`;
  }
  function miniRow(label, value) {
    return `<div class="status-line"><span>${label}</span><strong class="mono">${value}</strong></div>`;
  }
  function empty(message) {
    return `<div class="empty">${message}</div>`;
  }

  async function fetchJson(url) {
    const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    return response.json();
  }

  function renderLatency(summary) {
    const latency = summary.benchmarks?.latency;
    const stats = latency?.derived?.latency_ms || {};
    $('m-latency').textContent = fmtMs(Number(stats.p95));
    $('m-latency-sub').textContent = latency ? `Mean ${fmtMs(Number(stats.mean))}, p99 ${fmtMs(Number(stats.p99))}.` : 'No latency benchmark artifact found.';
    $('latency-headline').textContent = latency?.headline || 'No latency run';

    const byTool = latency?.derived?.by_tool || {};
    const maxValue = Math.max(1, ...Object.values(byTool).map(item => Number(item.p95 || item.max || 0)));
    $('latency-bars').innerHTML = Object.entries(byTool).map(([tool, item]) => {
      const value = Number(item.p95 || item.max || 0);
      return `<div class="bar-row"><span>${tool}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.min(100, value / maxValue * 100)}%"></span></span><span>${fmtMs(value)}</span></div>`;
    }).join('') || empty('No per-tool latency samples are available.');

    const samples = latency?.derived?.slowest_samples || [];
    drawLatencyChart(samples.slice().reverse().map(sample => Number(sample.latency_ms || 0)));
  }

  function drawLatencyChart(values) {
    const svg = $('latency-chart');
    const width = svg.clientWidth || 800;
    const height = svg.clientHeight || 260;
    const pad = 28;
    if (!values.length) {
      svg.innerHTML = `<text x="24" y="44" fill="#9ca997">No latency samples</text>`;
      return;
    }
    const max = Math.max(...values, 1);
    const points = values.map((value, index) => {
      const x = pad + (values.length === 1 ? 0 : index * (width - pad * 2) / (values.length - 1));
      const y = height - pad - (value / max) * (height - pad * 2);
      return `${x},${y}`;
    }).join(' ');
    const circles = values.map((value, index) => {
      const x = pad + (values.length === 1 ? 0 : index * (width - pad * 2) / (values.length - 1));
      const y = height - pad - (value / max) * (height - pad * 2);
      return `<circle cx="${x}" cy="${y}" r="4" fill="#d7ff4f"><title>${fmtMs(value)}</title></circle>`;
    }).join('');
    svg.innerHTML = `
      <line x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}" stroke="rgba(236,230,207,0.18)" />
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height-pad}" stroke="rgba(236,230,207,0.18)" />
      <polyline fill="none" stroke="#d7ff4f" stroke-width="3" points="${points}" />
      ${circles}
      <text x="${pad}" y="${pad - 8}" fill="#9ca997">${fmtMs(max)}</text>
    `;
  }

  function renderReliability(summary) {
    const reliability = summary.benchmarks?.reliability;
    const successRate = Number(reliability?.derived?.success_rate ?? reliability?.summary?.success_rate);
    $('m-reliability').textContent = fmtPct(successRate);
    $('m-reliability-sub').textContent = reliability ? reliability.headline : 'No reliability benchmark artifact found.';
  }

  function renderSafety(summary) {
    const safety = summary.benchmarks?.safety;
    const passRate = Number(safety?.derived?.pass_rate);
    $('m-safety').textContent = fmtPct(passRate);
    $('m-safety-sub').textContent = safety ? safety.headline : 'No safety benchmark artifact found.';
    $('safety-headline').textContent = safety?.headline || 'No safety run';
    const scenarios = safety?.derived?.by_scenario || {};
    $('safety-scenarios').innerHTML = Object.entries(scenarios).map(([name, item]) => {
      const cls = item.passed ? 'ok' : 'err';
      return `<span class="pill ${cls}"><span class="dot"></span><span>${name}: ${text(item.error_code)}</span></span>`;
    }).join('') || empty('No safety scenarios are available.');
  }

  function renderEvents(summary, events) {
    const eventSummary = summary.events || {};
    $('m-rejections').textContent = text(eventSummary.safety_rejection_count, '0');
    $('m-rejections-sub').textContent = `${text(eventSummary.command_count, '0')} commands recorded in the live event store.`;
    $('event-store').textContent = `${text(eventSummary.event_count, '0')} events`;
    $('event-count').textContent = `${events.length} shown`;

    const errors = eventSummary.by_error_code || {};
    const maxError = Math.max(1, ...Object.values(errors).map(Number));
    $('error-bars').innerHTML = Object.entries(errors).filter(([key]) => key !== 'none').map(([key, value]) => {
      return `<div class="bar-row"><span>${key}</span><span class="bar-track"><span class="bar-fill" style="width:${Number(value)/maxError*100}%"></span></span><span>${value}</span></div>`;
    }).join('') || empty('No live safety rejections recorded.');

    $('events-list').innerHTML = events.map(event => {
      const cls = event.success === false ? 'err' : 'ok';
      return `<div class="event"><span class="mono">${text(event.timestamp)}</span><span class="pill ${cls}"><span class="dot"></span><span>${text(event.command, event.action)}</span></span><span class="message">${text(event.message)}</span><span class="mono">${fmtMs(Number(event.duration_ms))}</span></div>`;
    }).join('') || empty('No live command trace events have been recorded yet.');
  }

  function renderRuns(runs) {
    $('run-count').textContent = `${runs.length} runs`;
    $('runs-table').innerHTML = runs.map(run => {
      const result = run.passed === true ? 'pass' : run.passed === false ? 'fail' : 'n/a';
      return `<tr><td class="mono">${text(run.timestamp)}</td><td>${text(run.benchmark)}</td><td>${text(run.headline)}</td><td class="mono">${text(run.record_count, '0')}</td><td>${result}</td></tr>`;
    }).join('') || `<tr><td colspan="5">${empty('No benchmark artifacts found under evaluation/results.')}</td></tr>`;
  }

  function renderRuntime(summary) {
    const runtime = summary.runtime || {};
    const airframe = runtime.airframe?.label || runtime.backend_mode || '--';
    const world = runtime.world?.label || '--';
    const stack = runtime.stack?.status || '--';
    $('runtime-profile').textContent = `${airframe} / ${world}`;
    $('runtime-stack').innerHTML = [
      miniRow('Backend', text(runtime.backend_mode)),
      miniRow('Airframe', text(airframe)),
      miniRow('World', text(world)),
      miniRow('Stack', text(stack)),
      miniRow('Telemetry', text(runtime.telemetry?.state))
    ].join('');

    const flags = runtime.readiness?.flags || {};
    $('runtime-flags').innerHTML = Object.entries(flags).map(([name, value]) => {
      return `<span class="pill ${value ? 'ok' : 'warn'}"><span class="dot"></span><span>${name}: ${value ? 'ready' : 'pending'}</span></span>`;
    }).join('') || empty('Runtime readiness flags are unavailable.');
  }

  async function refresh() {
    $('summary-note').textContent = 'Loading observability data...';
    const [summary, runsPayload, eventsPayload] = await Promise.all([
      fetchJson(api.summary),
      fetchJson(api.runs),
      fetchJson(api.events)
    ]);
    const ready = Boolean(summary.readiness?.ready_for_thesis);
    setPill($('ready-pill'), ready, ready ? 'Thesis evidence ready' : 'Evidence incomplete');
    $('latest-run').textContent = summary.latest_run ? `${summary.latest_run.benchmark} ${summary.latest_run.timestamp || ''}` : 'No artifact';
    $('summary-note').textContent = ready
      ? 'Latest latency, reliability, and safety artifacts are present and pass/fail suites are green.'
      : 'Collect or rerun benchmark artifacts before using this as final thesis evidence.';
    renderLatency(summary);
    renderReliability(summary);
    renderSafety(summary);
    renderEvents(summary, eventsPayload.events || []);
    renderRuns(runsPayload.runs || []);
    renderRuntime(summary);
  }

  $('refresh').addEventListener('click', () => refresh().catch(showError));
  function showError(error) {
    $('summary-note').textContent = `Observability API error: ${error.message}`;
    setPill($('ready-pill'), false, 'API error');
  }
  refresh().catch(showError);
  setInterval(() => refresh().catch(showError), 10000);
})();
</script>
</body>
</html>
"""
