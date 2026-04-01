"""Telemetry subscription and caching layer."""

from __future__ import annotations

from uav_mcp_server.types import TelemetrySnapshot


class TelemetryManager:
    """Caches the latest telemetry values from the UAV backend."""

    def __init__(self) -> None:
        self._snapshot = TelemetrySnapshot()

    def get_snapshot(self) -> TelemetrySnapshot:
        return self._snapshot

