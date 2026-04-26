# Evaluation And Observability

The thesis evaluation will focus on three technical questions:

1. What latency does the MCP middleware introduce?
2. How reliable is the control path across repeated runs and failures?
3. Does the safety layer reject unsafe or invalid commands consistently?

## Metrics

- tool handling latency
- end-to-end command completion latency
- success and failure rates
- rejection rates for invalid commands
- recovery behavior after injected faults

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

- latency percentiles and per-tool latency distributions
- reliability success rate, duration, and failure summaries
- safety scenario pass rate and live rejection/error-code distribution
- live command trace with duration, validation result, and telemetry context
- benchmark artifact explorer for JSON/CSV runs
- export endpoint at `/dashboard/api/observability/export`

## Evaluation prerequisites

1. confirm the end-to-end SITL path: connect, arm, takeoff, move, land
2. run benchmarks against the live stack, not the fake backend
3. keep evaluation runs on the target Python 3.12 runtime so dependency behavior matches the thesis runtime
4. inspect `/dashboard/observability/` and export the evidence bundle for thesis tables and figures
