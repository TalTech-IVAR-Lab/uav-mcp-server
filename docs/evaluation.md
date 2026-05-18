# Evaluation And Observability

The thesis evaluation will focus on three technical questions:

1. What latency does the MCP middleware introduce?
2. How reliable is the control path across repeated runs and failures?
3. Does the safety layer reject unsafe or invalid commands consistently?

## Metrics

The observability dashboard separates thesis-core metrics from supporting demo
telemetry. Use the core metrics below for thesis estimates, tables, and figures.

### Latency

- **Tool-call latency**: elapsed time from `call_tool()` request to MCP result
  received by the HTTP evaluation client.
- **Confirmed action latency**: elapsed time from issuing a state-changing tool
  until telemetry confirms the expected state. The current benchmark uses
  confirmed `arm` and confirmed `disarm`.
- Report `n`, mean, p50, p95, p99, min, and max in milliseconds.
- Report both all-tool latency and per-tool latency. Do not mix read-only
  `get_status` / `get_telemetry` samples with confirmed action latency when
  explaining control-action delay.

### Reliability

- **Nominal mission success rate**: successful reliability iterations divided by
  attempted iterations.
- **Recovery-to-ready rate**: iterations that end connected, disarmed, not in
  air, and in `ready` state.
- **Run duration**: elapsed time for a full nominal sequence: reset, arm,
  takeoff, move, hold, land, and cleanup.
- Report iteration count, success rate, recovery-to-ready rate, mean duration,
  p95 duration, and failure categories.

### Safety

- **Safety rejection correctness rate**: scenarios where the command was rejected
  with the expected `error_code` divided by all safety scenarios.
- **False accept**: an unsafe command succeeds when an error was expected.
- **Wrong error code**: an unsafe command is rejected, but the returned
  `error_code` does not match the expected policy violation.
- **False reject**: a command expected to succeed is rejected.
- Report scenario count, passed scenarios, pass rate, false accepts, false
  rejects, wrong error-code count, and the scenario matrix.

### Evidence validity gates

The dashboard flags evidence that should not be cited without explanation:

- missing latency, reliability, or safety artifact
- failed latest reliability or safety benchmark
- artifact load errors
- mock/local backend instead of live PX4 SITL
- missing git commit or dirty git worktree
- low sample coverage: latency `n < 30`, reliability iterations `< 5`, or
  safety scenarios `< 5`

## Implemented benchmark runners

- `evaluation/latency_benchmark.py`
- `evaluation/reliability_benchmark.py`
- `evaluation/safety_benchmark.py`

Artifacts are written as JSON and CSV under `evaluation/results/`. New artifacts
also include reproducibility metadata: Python version, git commit, branch,
dirty state, and relevant environment settings.

## Observability dashboard

The server exposes a read-only thesis analysis page:

- `http://127.0.0.1:8000/dashboard/observability/`

The page is separate from the operator dashboard and focuses on evidence:

- first-screen thesis metric table with source run IDs and validity warnings
- latency percentiles and per-tool latency distributions
- reliability success rate, duration, and failure summaries
- safety scenario pass rate, false accepts, and live rejection/error-code distribution
- live command trace with duration, validation result, and telemetry context
- benchmark artifact explorer for JSON/CSV runs
- export endpoint at `/dashboard/api/observability/export`, including a
  `thesis_metrics` object for thesis tables and figure source data

## Evaluation prerequisites

1. confirm the end-to-end SITL path: connect, arm, takeoff, move, land
2. run benchmarks against the live stack, not the fake backend
3. keep evaluation runs on the target Python 3.12 runtime so dependency behavior matches the thesis runtime
4. inspect `/dashboard/observability/` and export the evidence bundle for thesis tables and figures
