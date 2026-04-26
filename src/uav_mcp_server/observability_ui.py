"""Self-contained observability dashboard page."""

OBSERVABILITY_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UAV MCP Observability</title>
</head>
<body>
<main>
  <h1>UAV MCP Observability</h1>
  <p id="observability-status">Loading observability data...</p>
</main>
<script>
(async function(){
  const status = document.getElementById('observability-status');
  try {
    const response = await fetch('/dashboard/api/observability/summary');
    const data = await response.json();
    status.textContent = `${data.run_count || 0} benchmark runs indexed.`;
  } catch (error) {
    status.textContent = 'Observability data is unavailable.';
  }
})();
</script>
</body>
</html>
"""
