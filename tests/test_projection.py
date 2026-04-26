import pytest

from uav_mcp_server.projection import CameraParams, DronePose, pixel_to_world


def test_pixel_to_world_projects_downward_center_to_point_below_drone() -> None:
    point = pixel_to_world(
        160.0,
        120.0,
        CameraParams(
            width_px=320,
            height_px=240,
            hfov_rad=1.047,
            focal_length_px=277.191356,
            mount_pitch_deg=-90.0,
        ),
        DronePose(
            lat_deg=59.3948,
            lon_deg=24.6614,
            absolute_altitude_m=150.0,
            relative_altitude_m=10.0,
            home_absolute_altitude_m=140.0,
            yaw_deg=0.0,
            pitch_deg=0.0,
            roll_deg=0.0,
        ),
    )

    assert point.distance_m == pytest.approx(0.0, abs=0.1)
    assert point.absolute_altitude_m == pytest.approx(140.0)


def test_pixel_to_world_projects_forward_tilted_center_ahead_of_drone() -> None:
    point = pixel_to_world(
        160.0,
        120.0,
        CameraParams(
            width_px=320,
            height_px=240,
            hfov_rad=1.047,
            focal_length_px=277.191356,
        ),
        DronePose(
            lat_deg=59.3948,
            lon_deg=24.6614,
            absolute_altitude_m=150.0,
            relative_altitude_m=10.0,
            home_absolute_altitude_m=140.0,
            yaw_deg=0.0,
            pitch_deg=-45.0,
            roll_deg=0.0,
        ),
    )

    assert point.north_m == pytest.approx(10.0, abs=0.2)
    assert abs(point.east_m) < 0.1


def test_pixel_to_world_right_edge_offsets_eastward() -> None:
    point = pixel_to_world(
        320.0,
        120.0,
        CameraParams(
            width_px=320,
            height_px=240,
            hfov_rad=1.047,
            focal_length_px=277.191356,
            mount_pitch_deg=-90.0,
        ),
        DronePose(
            lat_deg=59.3948,
            lon_deg=24.6614,
            absolute_altitude_m=150.0,
            relative_altitude_m=10.0,
            home_absolute_altitude_m=140.0,
            yaw_deg=0.0,
            pitch_deg=0.0,
            roll_deg=0.0,
        ),
    )

    assert point.east_m > 0.0


def test_pixel_to_world_with_level_camera_and_yaw_projects_in_heading_direction() -> None:
    point = pixel_to_world(
        160.0,
        120.0,
        CameraParams(
            width_px=320,
            height_px=240,
            hfov_rad=1.047,
            focal_length_px=277.191356,
        ),
        DronePose(
            lat_deg=59.3948,
            lon_deg=24.6614,
            absolute_altitude_m=150.0,
            relative_altitude_m=10.0,
            home_absolute_altitude_m=140.0,
            yaw_deg=90.0,
            pitch_deg=-45.0,
            roll_deg=0.0,
        ),
    )

    assert point.north_m == pytest.approx(0.0, abs=0.2)
    assert point.east_m == pytest.approx(10.0, abs=0.2)
