# Testing Strategy

## Unit tests

Unit tests should cover:

- schema validation
- config loading
- safety policy
- mission request validation
- result formatting

## Integration tests

Integration tests should run against PX4 SITL and cover:

- connect
- arm
- takeoff
- movement
- return-to-launch
- landing
- failure handling

## Priority

The safety layer is the highest-priority area for test coverage.

