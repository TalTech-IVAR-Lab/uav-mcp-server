from uav_mcp_server.config import (
    IRIS_FPV_CAM_PROFILE,
    TYPHOON_H480_PROFILE,
    Settings,
)


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.backend_mode == "live"
    assert settings.px4_model == ""
    assert settings.px4_home_lat is None
    assert settings.px4_home_lon is None
    assert settings.geofence_center_lat == 59.3949741
    assert settings.geofence_center_lon == 24.6676189
    assert settings.sim_classic_world_name == "taltech_campus"
    assert settings.sim_classic_spawn_x_m == 0.0
    assert settings.sim_classic_spawn_y_m == 0.0
    assert settings.sim_classic_spawn_z_m == 0.0
    assert settings.sim_classic_spawn_yaw_rad == 0.0
    assert settings.preflight_wait_timeout_s == 30.0
    assert settings.telemetry_rate_hz == 5
    assert settings.command_rate_limit_per_sec == 2
    assert settings.assistant_enabled is True
    assert settings.assistant_model == "gemini-2.5-flash"
    assert settings.assistant_preview_default is True
    assert settings.assistant_bypass_available is True
    assert settings.assistant_mcp_url is None
    assert settings.manual_control_translation_step_m == 10.0
    assert settings.manual_control_altitude_step_m == 1.5
    assert settings.manual_control_yaw_step_deg == 15.0
    assert settings.manual_control_gimbal_pitch_step_deg == 10.0
    assert settings.manual_control_supports_yaw is True
    assert settings.manual_control_supports_gimbal_pitch is True
    assert settings.default_takeoff_altitude_m == 10.0
    assert settings.default_mission_speed_m_s == 6.0
    assert settings.camera_width_px == 640
    assert settings.camera_height_px == 480
    assert settings.camera_hfov_rad == 1.047
    assert settings.camera_focal_length_px == 554.382712
    assert settings.camera_stabilized is False


def test_settings_accept_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_MODE", "local")
    monkeypatch.setenv("MAX_SPEED_M_S", "9")
    monkeypatch.setenv("MIN_BATTERY_PERCENT", "35")
    monkeypatch.setenv("MAX_RELATIVE_MOVE_DISTANCE_M", "75")

    settings = Settings()

    assert settings.backend_mode == "local"
    assert settings.max_speed_m_s == 9
    assert settings.min_battery_percent == 35
    assert settings.max_relative_move_distance_m == 75


def test_settings_apply_typhoon_profile_for_gazebo_classic_alias() -> None:
    settings = Settings(_env_file=None, px4_model="gazebo-classic")

    assert settings.px4_model == TYPHOON_H480_PROFILE.model
    assert settings.camera_gazebo_topic_suffix == TYPHOON_H480_PROFILE.camera_gazebo_topic_suffix
    assert settings.camera_width_px == TYPHOON_H480_PROFILE.camera_width_px
    assert settings.camera_height_px == TYPHOON_H480_PROFILE.camera_height_px
    assert settings.camera_hfov_rad == TYPHOON_H480_PROFILE.camera_hfov_rad
    assert settings.camera_focal_length_px == TYPHOON_H480_PROFILE.camera_focal_length_px
    assert settings.camera_stabilized is True
    assert settings.manual_control_supports_gimbal_pitch is True


def test_settings_apply_iris_profile_when_requested_explicitly() -> None:
    settings = Settings(_env_file=None, px4_model="gazebo-classic_iris_fpv_cam")

    assert settings.px4_model == IRIS_FPV_CAM_PROFILE.model
    assert settings.camera_gazebo_topic_suffix == IRIS_FPV_CAM_PROFILE.camera_gazebo_topic_suffix
    assert settings.camera_width_px == IRIS_FPV_CAM_PROFILE.camera_width_px
    assert settings.camera_height_px == IRIS_FPV_CAM_PROFILE.camera_height_px
    assert settings.camera_hfov_rad == IRIS_FPV_CAM_PROFILE.camera_hfov_rad
    assert settings.camera_focal_length_px == IRIS_FPV_CAM_PROFILE.camera_focal_length_px
    assert settings.camera_stabilized is False
    assert settings.manual_control_supports_gimbal_pitch is False


def test_settings_preserve_explicit_camera_overrides_across_profile_application() -> None:
    settings = Settings(
        _env_file=None,
        px4_model="gazebo-classic",
        camera_width_px=1280,
        camera_height_px=720,
        camera_stabilized=False,
        manual_control_supports_gimbal_pitch=False,
    )

    assert settings.px4_model == TYPHOON_H480_PROFILE.model
    assert settings.camera_width_px == 1280
    assert settings.camera_height_px == 720
    assert settings.camera_stabilized is False
    assert settings.manual_control_supports_gimbal_pitch is False
