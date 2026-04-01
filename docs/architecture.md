# Architecture

## Goal

The system exposes safe, bounded UAV control functions through MCP while keeping the actual flight stabilization and low-level control inside PX4.

## Core layers

1. MCP server
2. Safety and validation layer
3. Drone control layer built on MAVSDK
4. PX4 SITL + Gazebo

## Main data flow

```text
LLM / MCP client
    -> MCP tool call
    -> server.py
    -> safety.py
    -> drone.py / mission.py
    -> MAVSDK
    -> PX4 SITL
    -> telemetry.py
    -> MCP response
```

## Core scope

- connect
- arm
- disarm when safe
- takeoff
- land
- return-to-launch
- bounded point-to-point movement
- waypoint mission execution
- telemetry and status

## Stretch scope

- camera feed
- gimbal control
- point-of-interest workflow
- web UI for human-in-the-loop interaction

