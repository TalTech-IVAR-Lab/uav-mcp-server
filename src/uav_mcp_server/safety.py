"""Safety and policy checks for UAV commands."""

from __future__ import annotations

from uav_mcp_server.types import CommandResult


class SafetyValidator:
    """Placeholder for state, geofence, and rate checks."""

    def allow(self, command_name: str) -> CommandResult:
        return CommandResult(success=True, message=f"{command_name} is allowed in scaffold mode")

