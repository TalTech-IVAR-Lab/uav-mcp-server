# Evaluation

This directory is reserved for benchmark and evaluation scripts used in the thesis.

Current status:

- the control, safety, and FastMCP layers are implemented
- live SITL verification is available through the repo-managed launcher and the HTTP MCP surface
- benchmark scripts target the live PX4 path, not the fake test backend
- benchmark artifacts are written under `evaluation/results/` as both JSON and CSV

Implemented benchmark runners:

- `latency_benchmark.py`
- `reliability_benchmark.py`
- `safety_benchmark.py`

Current workflow:

1. Start the live stack with `scripts/launch_live_stack.sh`
   - For the safety benchmark, use a tighter temporary test geofence so the benchmark can trigger a geofence rejection within the normal single-command move limit:

```bash
GEOFENCE_RADIUS_M=60 scripts/launch_live_stack.sh
```

2. Run one or more benchmark scripts, for example:

```bash
PYTHONPATH=src .venv312/bin/python evaluation/latency_benchmark.py
PYTHONPATH=src .venv312/bin/python evaluation/reliability_benchmark.py --iterations 3
PYTHONPATH=src .venv312/bin/python evaluation/safety_benchmark.py
```

3. Inspect the generated JSON and CSV files under `evaluation/results/`

Still deferred:

- LLM-driven scenario execution
- image-level Docker verification on a Docker-capable host
