from uav_mcp_server.config import Settings
from uav_mcp_server.safety import SafetyValidator
from uav_mcp_server.types import DroneState, ErrorCode, TelemetrySnapshot, WaypointInput

DEFAULT_SETTINGS = Settings()


def _ready_snapshot(**overrides: object) -> TelemetrySnapshot:
    values = {
        "state": DroneState.READY,
        "connected": True,
        "battery_percent": 80.0,
        "is_global_position_ok": True,
        "is_home_position_ok": True,
        "is_gyrometer_calibration_ok": True,
        "is_accelerometer_calibration_ok": True,
        "latitude_deg": DEFAULT_SETTINGS.geofence_center_lat,
        "longitude_deg": DEFAULT_SETTINGS.geofence_center_lon,
        "absolute_altitude_m": 150.0,
        "relative_altitude_m": 10.0,
        "home_absolute_altitude_m": 140.0,
    }
    values.update(overrides)
    return TelemetrySnapshot(**values)


def test_arm_requires_preflight_readiness() -> None:
    validator = SafetyValidator(Settings())

    violation = validator.validate("arm", _ready_snapshot(is_global_position_ok=False))

    assert violation is not None
    assert violation.error_code is ErrorCode.PREFLIGHT_FAILED


def test_arm_requires_sensor_calibration() -> None:
    validator = SafetyValidator(Settings())

    violation = validator.validate("arm", _ready_snapshot(is_gyrometer_calibration_ok=False))

    assert violation is not None
    assert violation.error_code is ErrorCode.PREFLIGHT_FAILED


def test_arm_rejects_low_battery() -> None:
    validator = SafetyValidator(Settings(min_battery_percent=30))

    violation = validator.validate("arm", _ready_snapshot(battery_percent=20.0))

    assert violation is not None
    assert violation.error_code is ErrorCode.LOW_BATTERY


def test_wrong_state_is_rejected() -> None:
    validator = SafetyValidator(Settings())

    violation = validator.validate("takeoff", _ready_snapshot(state=DroneState.READY), altitude_m=10.0)

    assert violation is not None
    assert violation.error_code is ErrorCode.WRONG_STATE


def test_takeoff_checks_altitude_bounds() -> None:
    validator = SafetyValidator(Settings(min_altitude_m=2.0, max_altitude_m=50.0))

    violation = validator.validate("takeoff", _ready_snapshot(state=DroneState.ARMED), altitude_m=100.0)

    assert violation is not None
    assert violation.error_code is ErrorCode.INVALID_PARAMS


def test_goto_relative_rejects_targets_outside_geofence() -> None:
    validator = SafetyValidator(Settings(geofence_radius_m=30.0))

    violation = validator.validate(
        "goto_relative",
        _ready_snapshot(state=DroneState.AIRBORNE),
        north_m=100.0,
        east_m=0.0,
        altitude_m=20.0,
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.GEOFENCE_VIOLATION


def test_goto_relative_rejects_distance_beyond_command_limit() -> None:
    validator = SafetyValidator(Settings(max_relative_move_distance_m=20.0))

    violation = validator.validate(
        "goto_relative",
        _ready_snapshot(state=DroneState.AIRBORNE),
        north_m=30.0,
        east_m=0.0,
        altitude_m=20.0,
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.INVALID_PARAMS


def test_rate_limit_applies_to_action_commands_only() -> None:
    validator = SafetyValidator(Settings(command_rate_limit_per_sec=1))
    snapshot = _ready_snapshot(state=DroneState.ARMED)

    first = validator.validate("takeoff", snapshot, altitude_m=10.0)
    second = validator.validate("takeoff", snapshot, altitude_m=10.0)
    read_only = validator.validate("get_status", snapshot)

    assert first is None
    assert second is not None
    assert second.error_code is ErrorCode.RATE_LIMITED
    assert read_only is None


def test_invalid_command_does_not_consume_rate_limit_window() -> None:
    validator = SafetyValidator(Settings(command_rate_limit_per_sec=1, max_altitude_m=50.0))
    snapshot = _ready_snapshot(state=DroneState.ARMED)

    invalid = validator.validate("takeoff", snapshot, altitude_m=200.0)
    valid = validator.validate("takeoff", snapshot, altitude_m=20.0)

    assert invalid is not None
    assert invalid.error_code is ErrorCode.INVALID_PARAMS
    assert valid is None


def test_emergency_commands_are_rate_limit_exempt() -> None:
    validator = SafetyValidator(Settings(command_rate_limit_per_sec=1))
    snapshot = _ready_snapshot(state=DroneState.AIRBORNE)

    first = validator.validate("goto_relative", snapshot, north_m=5.0, east_m=0.0, altitude_m=20.0)
    emergency = validator.validate("rtl", snapshot)

    assert first is None
    assert emergency is None


def test_mission_checks_speed_and_geofence() -> None:
    validator = SafetyValidator(Settings(max_speed_m_s=10.0, geofence_radius_m=500.0))
    snapshot = _ready_snapshot(state=DroneState.AIRBORNE)

    violation = validator.validate(
        "run_mission",
        snapshot,
        waypoints=[
            WaypointInput(
                latitude_deg=DEFAULT_SETTINGS.geofence_center_lat,
                longitude_deg=DEFAULT_SETTINGS.geofence_center_lon,
                altitude_m=20.0,
                speed_m_s=20.0,
            )
        ],
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.INVALID_PARAMS


def test_orbit_rejects_radius_outside_bounds() -> None:
    validator = SafetyValidator(Settings(min_orbit_radius_m=10.0, max_orbit_radius_m=50.0))
    snapshot = _ready_snapshot(state=DroneState.AIRBORNE)

    violation = validator.validate(
        "orbit",
        snapshot,
        latitude_deg=DEFAULT_SETTINGS.geofence_center_lat,
        longitude_deg=DEFAULT_SETTINGS.geofence_center_lon,
        absolute_altitude_m=150.0,
        radius_m=5.0,
        velocity_m_s=3.0,
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.INVALID_PARAMS


def test_orbit_rejects_speed_above_maximum() -> None:
    validator = SafetyValidator(Settings(max_speed_m_s=4.0))
    snapshot = _ready_snapshot(state=DroneState.AIRBORNE)

    violation = validator.validate(
        "orbit",
        snapshot,
        latitude_deg=DEFAULT_SETTINGS.geofence_center_lat,
        longitude_deg=DEFAULT_SETTINGS.geofence_center_lon,
        absolute_altitude_m=150.0,
        radius_m=12.0,
        velocity_m_s=6.0,
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.INVALID_PARAMS


def test_orbit_rejects_path_that_exits_geofence() -> None:
    validator = SafetyValidator(Settings(geofence_radius_m=40.0))
    snapshot = _ready_snapshot(state=DroneState.AIRBORNE)

    violation = validator.validate(
        "orbit",
        snapshot,
        latitude_deg=DEFAULT_SETTINGS.geofence_center_lat + 0.0002,
        longitude_deg=DEFAULT_SETTINGS.geofence_center_lon,
        absolute_altitude_m=150.0,
        radius_m=25.0,
        velocity_m_s=3.0,
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.GEOFENCE_VIOLATION


def test_fault_state_allows_reconnect() -> None:
    validator = SafetyValidator(Settings())

    violation = validator.validate("connect", _ready_snapshot(state=DroneState.FAULT))

    assert violation is None
