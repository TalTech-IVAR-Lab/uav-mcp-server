from uav_mcp_server.types import CommandResult, DroneState, ErrorCode, TelemetrySnapshot, WaypointInput


def test_telemetry_snapshot_defaults() -> None:
    snapshot = TelemetrySnapshot()
    assert snapshot.state is DroneState.DISCONNECTED
    assert snapshot.armed is False
    assert snapshot.in_air is False


def test_waypoint_validation_accepts_valid_values() -> None:
    waypoint = WaypointInput(latitude_deg=59.4, longitude_deg=24.6, altitude_m=10.0)
    assert waypoint.altitude_m == 10.0


def test_command_result_helpers_create_expected_shapes() -> None:
    success = CommandResult.ok("ok", data={"value": 1})
    failure = CommandResult.fail("bad", ErrorCode.INVALID_PARAMS)

    assert success.success is True
    assert success.data == {"value": 1}
    assert failure.success is False
    assert failure.error_code is ErrorCode.INVALID_PARAMS


def test_telemetry_snapshot_can_infer_home_altitude() -> None:
    snapshot = TelemetrySnapshot(absolute_altitude_m=155.0, relative_altitude_m=15.0)
    assert snapshot.inferred_home_absolute_altitude_m() == 140.0
