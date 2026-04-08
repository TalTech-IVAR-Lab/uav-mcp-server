# Evaluation Plan

The thesis evaluation will focus on three technical questions:

1. What latency does the MCP middleware introduce?
2. How reliable is the control path across repeated runs and failures?
3. Does the safety layer reject unsafe or invalid commands consistently?

## Planned metrics

- tool handling latency
- end-to-end command completion latency
- success and failure rates
- rejection rates for invalid commands
- recovery behavior after injected faults

## Current readiness

- the core control, safety, and MCP layers are implemented
- the live PX4 SITL environment still needs to be verified on the target Python 3.12 setup
- benchmark scripts should be added only after the live nominal path is stable

## Evaluation prerequisites

1. confirm the end-to-end SITL path: connect, arm, takeoff, move, land
2. add integration coverage for nominal and rejected commands
3. run benchmarks against the live stack, not the fake backend
4. keep evaluation runs on the target Python 3.12 runtime so dependency behavior matches the thesis runtime
