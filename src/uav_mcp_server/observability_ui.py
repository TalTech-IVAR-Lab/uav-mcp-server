"""Self-contained observability dashboard page."""

OBSERVABILITY_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UAV MCP Observability</title>
<meta name="description" content="Latency, reliability, safety, and runtime observability dashboard for the UAV MCP thesis system.">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  :root {
    /* Grafana Dark Theme Colors */
    --bg: #111217;
    --panel-bg: #181b1f;
    --panel-border: #22252b;
    --panel-header: #141619;
    --text-main: #cdd9e5;
    --text-muted: #8e99a8;
    
    --green: #73bf69;
    --red: #f2495c;
    --yellow: #fade2a;
    --blue: #5794f2;
    --orange: #ff9830;
    --purple: #b877d9;
    
    --font-main: 'Inter', system-ui, sans-serif;
    --font-mono: 'Fira Code', monospace;
    --radius: 4px;
    --shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }
  
  html, body { 
    margin: 0; min-height: 100vh; background: var(--bg); color: var(--text-main); font-family: var(--font-main); 
    font-size: 13px; line-height: 1.5;
  }
  
  a { color: var(--blue); text-decoration: none; }
  a:hover { text-decoration: underline; }
  
  /* Topbar */
  .topbar {
    display: flex; justify-content: space-between; align-items: center;
    background: var(--panel-header); border-bottom: 1px solid var(--panel-border);
    padding: 12px 24px;
  }
  .topbar-left { display: flex; align-items: center; gap: 16px; }
  .logo { font-weight: 700; font-size: 16px; color: #fff; letter-spacing: -0.5px; }
  .topbar-right { display: flex; align-items: center; gap: 12px; }
  
  .btn {
    background: transparent; border: 1px solid var(--panel-border); color: var(--text-main);
    padding: 6px 12px; border-radius: var(--radius); font-size: 12px; cursor: pointer; font-family: var(--font-main);
    font-weight: 500; transition: background 0.2s;
  }
  .btn:hover { background: rgba(255,255,255,0.05); }
  .btn.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
  .btn.primary:hover { background: #4384e6; }
  
  /* Status Pill */
  .status-pill {
    display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; text-transform: uppercase;
    padding: 4px 8px; border-radius: 12px; background: rgba(255,255,255,0.05); border: 1px solid var(--panel-border);
  }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted); }
  .status-pill.ok .status-dot { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .status-pill.warn .status-dot { background: var(--yellow); box-shadow: 0 0 8px var(--yellow); }
  .status-pill.err .status-dot { background: var(--red); box-shadow: 0 0 8px var(--red); }
  
  /* Dashboard Grid */
  .dashboard {
    padding: 16px; display: grid; gap: 12px;
    grid-template-columns: repeat(12, 1fr);
  }
  
  /* Panels */
  .panel {
    background: var(--panel-bg); border: 1px solid var(--panel-border);
    border-radius: var(--radius); box-shadow: var(--shadow);
    display: flex; flex-direction: column; overflow: hidden;
  }
  .panel-header {
    padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;
    border-bottom: 1px solid transparent;
  }
  .panel-title { font-size: 12px; font-weight: 600; color: var(--text-main); }
  .panel-body { padding: 12px; flex: 1; display: flex; flex-direction: column; min-height: 0; }
  
  /* Grid Sizes */
  .col-3 { grid-column: span 3; }
  .col-4 { grid-column: span 4; }
  .col-6 { grid-column: span 6; }
  .col-8 { grid-column: span 8; }
  .col-12 { grid-column: span 12; }
  
  @media (max-width: 1200px) {
    .col-3, .col-4 { grid-column: span 6; }
  }
  @media (max-width: 768px) {
    .col-3, .col-4, .col-6, .col-8 { grid-column: span 12; }
  }
  
  /* Stat Value */
  .stat-panel { align-items: center; justify-content: center; text-align: center; position: relative; }
  .stat-value { font-size: 48px; font-weight: 500; font-family: var(--font-mono); line-height: 1; margin: 10px 0; }
  .stat-sub { font-size: 12px; color: var(--text-muted); }
  
  .color-green { color: var(--green); }
  .color-blue { color: var(--blue); }
  .color-yellow { color: var(--yellow); }
  .color-red { color: var(--red); }
  .color-orange { color: var(--orange); }
  
  /* Sparkline Container inside Stat Panel */
  .sparkline-container {
    position: absolute; bottom: 0; left: 0; right: 0; height: 40px; opacity: 0.3; pointer-events: none;
  }
  
  /* Chart Containers */
  .chart-container { position: relative; height: 220px; width: 100%; }
  
  /* Tables & Lists */
  .table-container { overflow-x: auto; max-height: 300px; overflow-y: auto; }
  table { width: 100%; border-collapse: collapse; text-align: left; }
  th { 
    position: sticky; top: 0; background: var(--panel-bg); 
    padding: 8px 12px; font-size: 11px; text-transform: uppercase; color: var(--text-muted); 
    font-weight: 600; border-bottom: 1px solid var(--panel-border);
  }
  td { padding: 8px 12px; border-bottom: 1px solid var(--panel-border); font-size: 12px; }
  tr:last-child td { border-bottom: none; }
  .font-mono { font-family: var(--font-mono); font-size: 11px; }
  
  .log-row { display: flex; padding: 4px 8px; border-bottom: 1px solid rgba(255,255,255,0.02); font-family: var(--font-mono); font-size: 11px; }
  .log-row:hover { background: rgba(255,255,255,0.02); }
  .log-time { color: var(--text-muted); width: 80px; flex-shrink: 0; }
  .log-level { width: 60px; flex-shrink: 0; text-transform: uppercase; font-weight: 600; }
  .log-level.info { color: var(--blue); }
  .log-level.warn { color: var(--yellow); }
  .log-level.error { color: var(--red); }
  .log-level.success { color: var(--green); }
  .log-cmd { color: var(--orange); width: 140px; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .log-msg { color: var(--text-main); flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .log-dur { color: var(--text-muted); width: 60px; text-align: right; flex-shrink: 0; }
  
  /* Horizontal Bar Gauge */
  .bar-gauge-row { display: flex; align-items: center; margin-bottom: 8px; }
  .bar-gauge-label { width: 120px; font-size: 11px; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar-gauge-track { flex: 1; height: 12px; background: rgba(255,255,255,0.05); border-radius: 2px; overflow: hidden; margin: 0 12px; }
  .bar-gauge-fill { height: 100%; border-radius: 2px; }
  .bar-gauge-value { width: 50px; text-align: right; font-size: 11px; font-family: var(--font-mono); color: var(--text-muted); }
  
  /* Scrollbars */
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: #3b4048; border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: #505662; }
</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-left">
    <div class="logo">UAV MCP Observability</div>
    <div id="ready-pill" class="status-pill warn"><span class="status-dot"></span><span>Loading</span></div>
  </div>
  <div class="topbar-right">
    <div style="display: flex; gap: 8px; align-items: center; margin-right: 12px;">
      <select id="time-window" class="btn" style="padding: 4px 8px;">
        <option value="15">Last 30s</option>
        <option value="30">Last 1m</option>
        <option value="150" selected>Last 5m</option>
        <option value="300">Last 10m</option>
      </select>
      <select id="refresh-rate" class="btn" style="padding: 4px 8px;">
        <option value="0">Off (Pause)</option>
        <option value="1000">1s</option>
        <option value="2000" selected>2s</option>
        <option value="5000">5s</option>
      </select>
    </div>
    <button id="refresh" class="btn" title="Force Refresh Data">Refresh</button>
    <a href="/dashboard/" class="btn primary">Operator Dashboard</a>
  </div>
</header>

<main class="dashboard">
  <!-- ROW 1: KPIs -->
  <div class="panel col-3 stat-panel">
    <div class="panel-header"><div class="panel-title">API Latency (P95)</div></div>
    <div class="panel-body">
      <div id="m-latency" class="stat-value color-blue">--</div>
      <div id="m-latency-sub" class="stat-sub">Waiting for data...</div>
    </div>
  </div>
  
  <div class="panel col-3 stat-panel">
    <div class="panel-header"><div class="panel-title">System Reliability</div></div>
    <div class="panel-body">
      <div id="m-reliability" class="stat-value color-green">--</div>
      <div id="m-reliability-sub" class="stat-sub">Waiting for data...</div>
    </div>
  </div>
  
  <div class="panel col-3 stat-panel">
    <div class="panel-header"><div class="panel-title">Safety Check Pass Rate</div></div>
    <div class="panel-body">
      <div id="m-safety" class="stat-value color-orange">--</div>
      <div id="m-safety-sub" class="stat-sub">Waiting for data...</div>
    </div>
  </div>
  
  <div class="panel col-3 stat-panel">
    <div class="panel-header"><div class="panel-title">Runtime Context</div></div>
    <div class="panel-body">
      <div id="m-runtime-state" class="stat-value" style="font-size: 24px; margin: 5px 0;">--</div>
      <div id="m-runtime-sub" class="stat-sub" style="display:flex; flex-direction:column; gap:4px; align-items:center;">
        <span id="m-runtime-airframe">--</span>
        <span id="m-runtime-flags" style="font-size: 10px;">--</span>
      </div>
    </div>
  </div>
  
  <!-- ROW 1.5: AI Metrics -->
  <div class="panel col-6 stat-panel" style="border-top: 2px solid var(--purple);">
    <div class="panel-header"><div class="panel-title">AI Plan Latency (P95)</div></div>
    <div class="panel-body">
      <div id="ai-latency" class="stat-value color-purple">--</div>
      <div id="ai-latency-sub" class="stat-sub">Waiting for AI calls...</div>
    </div>
  </div>
  
  <div class="panel col-6 stat-panel" style="border-top: 2px solid var(--purple);">
    <div class="panel-header"><div class="panel-title">AI Plan Success Rate</div></div>
    <div class="panel-body">
      <div id="ai-success" class="stat-value color-purple">--</div>
      <div id="ai-success-sub" class="stat-sub">Waiting for AI calls...</div>
    </div>
  </div>
  
  <!-- ROW 2: Charts -->
  <div class="panel col-6">
    <div class="panel-header"><div class="panel-title">Command Latency Over Time</div></div>
    <div class="panel-body">
      <div class="chart-container">
        <canvas id="latencyChart"></canvas>
      </div>
    </div>
  </div>
  
  <div class="panel col-6">
    <div class="panel-header"><div class="panel-title">Command Throughput & Status</div></div>
    <div class="panel-body">
      <div class="chart-container">
        <canvas id="throughputChart"></canvas>
      </div>
    </div>
  </div>
  
  <!-- ROW 3: Distributions -->
  <div class="panel col-6">
    <div class="panel-header"><div class="panel-title">Per-Tool Latency (P95)</div></div>
    <div class="panel-body" style="justify-content: flex-start; overflow-y: auto; max-height: 250px;">
      <div id="tool-latency-bars" style="width: 100%;">
        <div style="text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 20px;">No latency data available.</div>
      </div>
    </div>
  </div>
  
  <div class="panel col-6">
    <div class="panel-header"><div class="panel-title">Live Safety Rejections by Code</div></div>
    <div class="panel-body" style="justify-content: center;">
      <div id="safety-error-bars">
        <div style="text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 20px;">No rejections recorded.</div>
      </div>
    </div>
  </div>
  
  <!-- ROW 4: Tables / Logs -->
  <div class="panel col-12">
    <div class="panel-header"><div class="panel-title">Live Command Trace</div></div>
    <div class="panel-body" style="padding: 0;">
      <div class="table-container" style="max-height: 240px; background: #0b0c10;">
        <div id="log-explorer">
          <div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px;">No events recorded.</div>
        </div>
      </div>
    </div>
  </div>

  <div class="panel col-12">
    <div class="panel-header">
      <div class="panel-title">Benchmark Artifact Explorer</div>
      <span id="run-count" style="font-size: 11px; color: var(--text-muted);">0 runs</span>
    </div>
    <div class="panel-body" style="padding: 0;">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Benchmark</th>
              <th>Headline</th>
              <th>Records</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody id="runs-table">
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No benchmark artifacts found.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
  
</main>

<script>
(function() {
  'use strict';
  
  // --- Styling Constants for Charts ---
  const colors = {
    bg: '#111217',
    text: '#8e99a8',
    grid: '#22252b',
    blue: '#5794f2',
    green: '#73bf69',
    red: '#f2495c',
    yellow: '#fade2a',
    orange: '#ff9830',
    purple: '#b877d9'
  };
  
  Chart.defaults.color = colors.text;
  Chart.defaults.font.family = "'Inter', sans-serif";
  Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(20, 22, 25, 0.9)';
  Chart.defaults.plugins.tooltip.titleColor = '#fff';
  Chart.defaults.plugins.tooltip.bodyColor = '#cdd9e5';
  Chart.defaults.plugins.tooltip.borderColor = colors.grid;
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 4;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  
  // --- Data History for Time-Series ---
  const MAX_HISTORY_POINTS = 300;
  let currentDisplayPoints = 150;
  
  const history = {
    timestamps: [],
    latencyP95: [],
    latencyMean: [],
    throughputSuccess: [],
    throughputError: []
  };
  
  // --- Initialize Charts ---
  let latencyChart, throughputChart;
  
  function initCharts() {
    const commonScales = {
      x: { 
        grid: { color: colors.grid, drawBorder: false },
        ticks: { maxTicksLimit: 8, maxRotation: 0 }
      },
      y: {
        grid: { color: colors.grid, drawBorder: false },
        beginAtZero: true
      }
    };
    
    // Latency Line Chart
    const ctxLatency = document.getElementById('latencyChart').getContext('2d');
    latencyChart = new Chart(ctxLatency, {
      type: 'line',
      data: {
        labels: history.timestamps,
        datasets: [
          {
            label: 'P95 Latency (ms)',
            data: history.latencyP95,
            borderColor: colors.blue,
            backgroundColor: 'rgba(87, 148, 242, 0.1)',
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: true,
            tension: 0.3
          },
          {
            label: 'Mean Latency (ms)',
            data: history.latencyMean,
            borderColor: colors.green,
            backgroundColor: 'transparent',
            borderWidth: 2,
            borderDash: [5, 5],
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: false,
            tension: 0.3
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: commonScales,
        plugins: {
          legend: { position: 'top', align: 'end' }
        }
      }
    });
    
    // Throughput Stacked Bar Chart
    const ctxThroughput = document.getElementById('throughputChart').getContext('2d');
    throughputChart = new Chart(ctxThroughput, {
      type: 'bar',
      data: {
        labels: history.timestamps,
        datasets: [
          {
            label: 'Success',
            data: history.throughputSuccess,
            backgroundColor: colors.green,
            borderRadius: 2
          },
          {
            label: 'Rejection/Error',
            data: history.throughputError,
            backgroundColor: colors.red,
            borderRadius: 2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { stacked: true, grid: { color: colors.grid, drawBorder: false }, ticks: { maxTicksLimit: 8 } },
          y: { stacked: true, grid: { color: colors.grid, drawBorder: false }, beginAtZero: true }
        },
        plugins: {
          legend: { position: 'top', align: 'end' }
        }
      }
    });
  }

  // --- Helpers ---
  const $ = (id) => document.getElementById(id);
  function fmtMs(v) { return Number.isFinite(v) ? `${v.toFixed(v >= 100 ? 0 : 1)} ms` : '--'; }
  function fmtPct(v) { return Number.isFinite(v) ? `${(v * 100).toFixed(0)}%` : '--'; }
  function text(v, fallback='--') { return v === null || v === undefined || v === '' ? fallback : String(v); }
  
  function setPill(el, ok, label) {
    el.className = `status-pill ${ok ? 'ok' : 'err'}`;
    el.innerHTML = `<span class="status-dot"></span><span>${label}</span>`;
  }

  // --- Rendering Functions ---
  function renderKPIs(summary) {
    // Latency
    const latency = summary.benchmarks?.latency;
    const lStats = latency?.derived?.latency_ms || {};
    const p95 = Number(lStats.p95);
    $('m-latency').textContent = Number.isFinite(p95) ? p95.toFixed(0) + ' ms' : '--';
    $('m-latency').className = `stat-value ${p95 > 200 ? 'color-orange' : 'color-blue'}`;
    $('m-latency-sub').textContent = latency ? `Mean ${fmtMs(Number(lStats.mean))}` : 'No latency artifact';
    
    // Reliability
    const rel = summary.benchmarks?.reliability;
    const sr = Number(rel?.derived?.success_rate ?? rel?.summary?.success_rate);
    $('m-reliability').textContent = fmtPct(sr);
    $('m-reliability').className = `stat-value ${sr < 0.95 ? 'color-yellow' : 'color-green'}`;
    $('m-reliability-sub').textContent = rel ? rel.headline : 'No reliability artifact';
    
    // Safety
    const saf = summary.benchmarks?.safety;
    const pr = Number(saf?.derived?.pass_rate);
    $('m-safety').textContent = fmtPct(pr);
    $('m-safety').className = `stat-value ${pr < 1.0 ? 'color-red' : 'color-orange'}`;
    $('m-safety-sub').textContent = saf ? saf.headline : 'No safety artifact';
    
    // Runtime
    const rt = summary.runtime || {};
    const mode = text(rt.backend_mode, 'UNKNOWN').toUpperCase();
    $('m-runtime-state').textContent = mode;
    $('m-runtime-state').className = `stat-value ${mode === 'MOCK' ? 'color-purple' : 'color-green'}`;
    
    const airframe = text(rt.airframe?.label, 'Unknown Airframe');
    $('m-runtime-airframe').textContent = airframe;
    
    const flags = rt.readiness?.flags || {};
    const readyCount = Object.values(flags).filter(Boolean).length;
    const totalCount = Object.keys(flags).length;
    $('m-runtime-flags').innerHTML = totalCount > 0 ? 
      `<span style="color:${readyCount===totalCount?colors.green:colors.yellow}">${readyCount}/${totalCount} Systems Ready</span>` : 
      'No flag data';
  }

  function renderAIMetrics(summary) {
    const ai = summary.events?.assistant_metrics;
    if (ai && ai.plan_count > 0) {
      const aiP95 = Number(ai.latency_ms?.p95);
      $('ai-latency').textContent = Number.isFinite(aiP95) ? aiP95.toFixed(0) + ' ms' : '--';
      $('ai-latency-sub').textContent = `Mean ${fmtMs(Number(ai.latency_ms?.mean))} (${ai.plan_count} calls)`;
      
      const aiSr = Number(ai.success_rate);
      $('ai-success').textContent = fmtPct(aiSr);
      $('ai-success').className = `stat-value ${aiSr < 0.95 ? 'color-orange' : 'color-purple'}`;
      $('ai-success-sub').textContent = `Based on ${ai.plan_count} tracked plans`;
    }
  }

  function renderBarGauges(summary) {
    // Tool Latency
    const byTool = summary.events?.by_command_latency || summary.by_command_latency || {};
    const toolEntries = Object.entries(byTool).sort((a,b) => Number(b[1].p95 || 0) - Number(a[1].p95 || 0));
    
    if (toolEntries.length > 0) {
      const maxL = Math.max(...toolEntries.map(e => Number(e[1].p95 || 0)));
      $('tool-latency-bars').innerHTML = toolEntries.map(([tool, stats]) => {
        const val = Number(stats.p95 || 0);
        const pct = Math.min(100, (val / maxL) * 100);
        const color = val > 150 ? colors.orange : colors.blue;
        return `
          <div class="bar-gauge-row">
            <div class="bar-gauge-label" title="${tool}">${tool}</div>
            <div class="bar-gauge-track">
              <div class="bar-gauge-fill" style="width: ${pct}%; background: ${color};"></div>
            </div>
            <div class="bar-gauge-value">${val.toFixed(0)}ms</div>
          </div>
        `;
      }).join('');
    } else {
      $('tool-latency-bars').innerHTML = `<div style="text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 20px;">No tool latency data.</div>`;
    }

    // Safety Errors
    const errors = summary.events?.by_error_code || {};
    const errEntries = Object.entries(errors).filter(([k]) => k !== 'none').sort((a,b) => b[1] - a[1]);
    
    if (errEntries.length > 0) {
      const maxE = Math.max(...errEntries.map(e => Number(e[1])));
      $('safety-error-bars').innerHTML = errEntries.slice(0, 5).map(([code, count]) => {
        const pct = Math.min(100, (count / maxE) * 100);
        return `
          <div class="bar-gauge-row">
            <div class="bar-gauge-label" title="${code}">${code}</div>
            <div class="bar-gauge-track">
              <div class="bar-gauge-fill" style="width: ${pct}%; background: ${colors.red};"></div>
            </div>
            <div class="bar-gauge-value">${count}</div>
          </div>
        `;
      }).join('');
    } else {
      $('safety-error-bars').innerHTML = `<div style="text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 20px;">No rejections recorded.</div>`;
    }
  }

  function renderLogs(events) {
    if (!events || events.length === 0) {
      $('log-explorer').innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px;">No events recorded.</div>`;
      return;
    }
    
    $('log-explorer').innerHTML = events.map(e => {
      const isSuccess = e.success !== false;
      const level = isSuccess ? 'info' : 'error';
      const levelText = isSuccess ? 'INFO' : 'ERR';
      const time = e.timestamp ? new Date(e.timestamp).toLocaleTimeString([], {hour12:false}) : '--:--:--';
      
      return `
        <div class="log-row">
          <div class="log-time">${time}</div>
          <div class="log-level ${level}">${levelText}</div>
          <div class="log-cmd" title="${text(e.command, e.action)}">${text(e.command, e.action)}</div>
          <div class="log-msg" title="${text(e.message)}">${text(e.message)}</div>
          <div class="log-dur">${Number.isFinite(e.duration_ms) ? e.duration_ms.toFixed(0)+'ms' : ''}</div>
        </div>
      `;
    }).join('');
  }

  function renderRuns(runs) {
    $('run-count').textContent = `${runs.length} runs`;
    
    if (runs.length === 0) {
      $('runs-table').innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No benchmark artifacts found.</td></tr>`;
      return;
    }
    
    $('runs-table').innerHTML = runs.map(run => {
      const result = run.passed === true ? `<span style="color:${colors.green}">PASS</span>` : 
                     run.passed === false ? `<span style="color:${colors.red}">FAIL</span>` : 
                     `<span style="color:${colors.text}">N/A</span>`;
      const time = run.timestamp ? new Date(run.timestamp).toLocaleString() : '--';
      
      return `
        <tr>
          <td class="font-mono">${time}</td>
          <td>${text(run.benchmark)}</td>
          <td>${text(run.headline)}</td>
          <td class="font-mono">${text(run.record_count, '0')}</td>
          <td>${result}</td>
        </tr>
      `;
    }).join('');
  }

  // --- Data Fetching and Update Cycle ---
  let lastEventCount = 0;
  
  async function updateData() {
    try {
      const [summaryReq, runsReq, eventsReq] = await Promise.all([
        fetch('/dashboard/api/observability/summary', { headers: { 'Accept': 'application/json' } }),
        fetch('/dashboard/api/observability/runs', { headers: { 'Accept': 'application/json' } }),
        fetch('/dashboard/api/observability/events?limit=50', { headers: { 'Accept': 'application/json' } })
      ]);
      
      if (!summaryReq.ok) throw new Error('API Error');
      
      const summary = await summaryReq.json();
      const runsData = await runsReq.json();
      const eventsData = await eventsReq.json();
      
      // Update Readiness Pill
      const ready = Boolean(summary.readiness?.ready_for_thesis);
      setPill($('ready-pill'), ready, ready ? 'Thesis Ready' : 'Incomplete Evidence');
      
      // Render Static Panels
      renderKPIs(summary);
      renderAIMetrics(summary);
      renderBarGauges(summary);
      renderLogs(eventsData.events || []);
      renderRuns(runsData.runs || []);
      
      // Update Time-Series History
      if (summary.events?.timeseries) {
        const ts = summary.events.timeseries;
        history.timestamps = ts.timestamps.map(iso => {
          const d = new Date(iso);
          return d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit', hour12:false});
        });
        history.latencyP95 = ts.latencyP95;
        history.latencyMean = ts.latencyMean;
        history.throughputSuccess = ts.throughputSuccess;
        history.throughputError = ts.throughputError;
      }
      
      // Update Charts
      if (latencyChart && throughputChart) {
        latencyChart.data.labels = history.timestamps.slice(-currentDisplayPoints);
        latencyChart.data.datasets[0].data = history.latencyP95.slice(-currentDisplayPoints);
        latencyChart.data.datasets[1].data = history.latencyMean.slice(-currentDisplayPoints);
        latencyChart.update('none');
        
        throughputChart.data.labels = history.timestamps.slice(-currentDisplayPoints);
        throughputChart.data.datasets[0].data = history.throughputSuccess.slice(-currentDisplayPoints);
        throughputChart.data.datasets[1].data = history.throughputError.slice(-currentDisplayPoints);
        throughputChart.update('none');
      }
      
    } catch (e) {
      console.error("Dashboard update failed:", e);
      setPill($('ready-pill'), false, 'API Offline');
    }
  }

  // --- Interval & Controls ---
  let fetchIntervalId = null;
  function setRefreshInterval(ms) {
    if (fetchIntervalId) clearInterval(fetchIntervalId);
    if (ms > 0) {
      fetchIntervalId = setInterval(updateData, ms);
    }
  }
  
  $('refresh-rate').addEventListener('change', (e) => {
    setRefreshInterval(Number(e.target.value));
  });
  
  $('time-window').addEventListener('change', (e) => {
    currentDisplayPoints = Number(e.target.value);
    updateData();
  });

  // --- Boot ---
  initCharts();
  updateData();
  
  $('refresh').addEventListener('click', updateData);
  setRefreshInterval(2000);
  
})();
</script>
</body>
</html>
"""
