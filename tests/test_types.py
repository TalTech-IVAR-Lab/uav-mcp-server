from uav_mcp_server.types import DroneState, TelemetrySnapshot, WaypointInput


def test_telemetry_snapshot_defaults() -> None:
    snapshot = TelemetrySnapshot()
    assert snapshot.state is DroneState.DISCONNECTED
    assert snapshot.armed is False
    assert snapshot.in_air is False


def test_waypoint_validation_accepts_valid_values() -> None:
    waypoint = WaypointInput(latitude_deg=59.4, longitude_deg=24.6, altitude_m=10.0)
    assert waypoint.altitude_m == 10.0

