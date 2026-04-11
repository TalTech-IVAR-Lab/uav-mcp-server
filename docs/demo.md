# Demo Outline

The demo should use the core safe tool surface, not the stretch features.

## Current demo path

1. Start the live stack with `scripts/launch_live_stack.sh`
2. Connect from an MCP client
3. Run a short sequence:
   - connect
   - arm
   - takeoff
   - `goto_relative` to a bounded target
   - hold or return to launch
   - land
   - disarm if safe

## Recommended tool surface

- `connect`
- `arm`
- `takeoff`
- `goto_relative`
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

- QGroundControl for visual monitoring
- terminal logs for MCP calls and safety decisions
- `scripts/smoke_http.py --mode flight` for an automated end-to-end flight smoke over HTTP
- `docs/new-system-workflow.md` for full machine setup before the demo day
