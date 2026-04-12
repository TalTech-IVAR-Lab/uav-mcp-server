# Demo Outline

The preferred demo path now includes the operator dashboard, not just raw MCP tool calls.

## Current demo path

1. Start the live stack with `scripts/launch_live_stack.sh`
2. Open `http://127.0.0.1:8000/dashboard/`
3. Run a short operator sequence:
   - connect
   - arm
   - takeoff
   - confirm telemetry and map updates
   - use `goto_relative` or a projected target approach
   - use orbit on a selected target when the camera/projection path is available
   - hold or return to launch
   - land

## Recommended tool surface

- `connect`
- `arm`
- `takeoff`
- `goto_relative`
- `orbit`
- `hold`
- `rtl`
- `land`
- `disarm`
- `get_status`
- `get_telemetry`

Current runtime defaults exposed through the safety resource:

- default takeoff altitude: `10 m`
- default mission speed: `6 m/s`
- max relative move distance per command: `150 m`

## Observation tools

- dashboard telemetry, map, camera panel, and event log
- QGroundControl for independent visual monitoring if desired
- terminal logs for MCP calls and safety decisions
- `scripts/smoke_http.py --mode flight` for an automated end-to-end flight smoke over HTTP
- `docs/new-system-workflow.md` for full machine setup before the demo day
