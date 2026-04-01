# UAV MCP Server

This repository contains a thesis project scaffold for a simulation-first UAV control middleware based on the Model Context Protocol (MCP). The target system connects an AI agent to a PX4-based UAV running in Software-In-The-Loop (SITL), with safety checks between the MCP tool layer and the flight controller.

The initial repository is intentionally set up as a clean baseline: package layout, documentation structure, local development notes, and placeholders for the control, safety, testing, and evaluation modules. The implementation focus is the core UAV control path first; camera, POI, and web UI work are kept as stretch scope.

## Planned stack

- Python 3.12
- Official `mcp[cli]` SDK / FastMCP
- MAVSDK-Python
- PX4 SITL + Gazebo Harmonic
- Pydantic v2
- pytest + pytest-asyncio

## Repository layout

```text
docs/                  Project documentation intended for review
evaluation/            Benchmark and evaluation scripts
scripts/               Local helper scripts
src/uav_mcp_server/    Application package
tests/                 Unit and integration tests
```

## Current status

- Repository scaffold initialized
- Project docs added
- Python package structure created
- Local-only agent workspace separated through `.gitignore`

## Next steps

1. Finalize environment setup on Ubuntu 24.04.
2. Implement `types.py` and `config.py`.
3. Add the MAVSDK telemetry and control layer.
4. Build the safety layer before exposing MCP tools.

