"""PX4 / MAVSDK integration layer.

This module is intentionally a scaffold. The concrete MAVSDK integration is added
in later phases once the environment is verified.
"""

from __future__ import annotations

from uav_mcp_server.types import CommandResult


class DroneController:
    """High-level UAV control interface."""

    async def connect(self, connection_string: str) -> CommandResult:
        raise NotImplementedError

    async def arm(self) -> CommandResult:
        raise NotImplementedError

    async def takeoff(self, altitude_m: float) -> CommandResult:
        raise NotImplementedError

    async def land(self) -> CommandResult:
        raise NotImplementedError

