# Demo Outline

The demo should use the core safe tool surface, not the stretch features.

## Current demo path

1. Start PX4 SITL
2. Start the MCP server
3. Connect from an MCP client
4. Run a short sequence:
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

## Observation tools

- QGroundControl for visual monitoring
- terminal logs for MCP calls and safety decisions
