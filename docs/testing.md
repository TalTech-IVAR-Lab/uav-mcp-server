# Testing Strategy

## Fast local tests

The fast suite should run without PX4 SITL and covers:

- schema validation
- config loading
- navigation math
- telemetry caching
- control layer behavior through a fake backend
- safety policy
- mission request validation
- FastMCP tool wiring and structured responses

## Integration tests

Integration tests should run against PX4 SITL and cover:

- connect
- arm
- takeoff
- movement
- return-to-launch
- landing
- failure handling

Mark live tests with `@pytest.mark.integration` and keep them out of the default fast run.

## Current status

- fast unit and component coverage is implemented
- server behavior is verified against the real `mcp` package
- live SITL integration tests still need to be added and run on Ubuntu 24.04 with Python 3.12

## Priority

The safety layer is the highest-priority area for test coverage.
