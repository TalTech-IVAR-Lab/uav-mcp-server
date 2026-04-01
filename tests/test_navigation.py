from uav_mcp_server.navigation import haversine_distance_m, offset_coordinate


def test_haversine_distance_is_zero_for_identical_points() -> None:
    assert haversine_distance_m(59.3948, 24.6614, 59.3948, 24.6614) == 0


def test_offset_coordinate_moves_north() -> None:
    latitude_deg, longitude_deg = offset_coordinate(59.3948, 24.6614, north_m=100, east_m=0)
    assert latitude_deg > 59.3948
    assert abs(longitude_deg - 24.6614) < 0.01
