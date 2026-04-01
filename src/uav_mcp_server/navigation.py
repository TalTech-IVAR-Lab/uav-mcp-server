"""Navigation helpers shared by control and safety layers."""

from __future__ import annotations

from math import asin, atan2, cos, degrees, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_m(
    latitude_deg_a: float,
    longitude_deg_a: float,
    latitude_deg_b: float,
    longitude_deg_b: float,
) -> float:
    lat_a = radians(latitude_deg_a)
    lon_a = radians(longitude_deg_a)
    lat_b = radians(latitude_deg_b)
    lon_b = radians(longitude_deg_b)
    delta_lat = lat_b - lat_a
    delta_lon = lon_b - lon_a

    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * asin(sqrt(haversine))


def offset_coordinate(
    latitude_deg: float,
    longitude_deg: float,
    north_m: float,
    east_m: float,
) -> tuple[float, float]:
    latitude_rad = radians(latitude_deg)
    longitude_rad = radians(longitude_deg)
    angular_distance = sqrt(north_m**2 + east_m**2) / EARTH_RADIUS_M

    if angular_distance == 0:
        return latitude_deg, longitude_deg

    bearing = atan2(east_m, north_m)
    target_latitude = asin(
        sin(latitude_rad) * cos(angular_distance)
        + cos(latitude_rad) * sin(angular_distance) * cos(bearing)
    )
    target_longitude = longitude_rad + atan2(
        sin(bearing) * sin(angular_distance) * cos(latitude_rad),
        cos(angular_distance) - sin(latitude_rad) * sin(target_latitude),
    )
    return degrees(target_latitude), degrees(target_longitude)


def relative_to_absolute_altitude_m(
    home_absolute_altitude_m: float,
    relative_altitude_m: float,
) -> float:
    return home_absolute_altitude_m + relative_altitude_m
