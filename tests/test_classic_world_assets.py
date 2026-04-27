from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TALTECH_MODEL_DIR = REPO_ROOT / "sim" / "gazebo-classic" / "models" / "taltech_campus"
TALTECH_WORLD_PATH = REPO_ROOT / "sim" / "gazebo-classic" / "worlds" / "taltech_campus.world"
TUM_MODEL_DIR = REPO_ROOT / "sim" / "gazebo-classic" / "models" / "tum_campus_lod3"
TUM_WORLD_PATH = REPO_ROOT / "sim" / "gazebo-classic" / "worlds" / "tum_map.world"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"


def test_taltech_terrain_world_assets_exist() -> None:
    assert (TALTECH_MODEL_DIR / "model.config").is_file()
    assert (TALTECH_MODEL_DIR / "model.sdf").is_file()
    assert (TALTECH_MODEL_DIR / "textures" / "taltech_campus_aerial.png").is_file()
    assert (TALTECH_MODEL_DIR / "textures" / "taltech_campus_height_map.tif").is_file()
    assert TALTECH_WORLD_PATH.is_file()


def test_taltech_terrain_model_has_heightmap_collision_and_visual() -> None:
    root = ET.fromstring((TALTECH_MODEL_DIR / "model.sdf").read_text(encoding="utf-8"))
    link = root.find("./model/link")

    assert link is not None
    assert link.find("./collision/geometry/heightmap") is not None
    assert link.find("./visual/geometry/heightmap") is not None


def test_taltech_model_config_targets_gazebo_classic_sdf_version() -> None:
    root = ET.fromstring((TALTECH_MODEL_DIR / "model.config").read_text(encoding="utf-8"))
    sdf_node = root.find("./sdf")

    assert sdf_node is not None
    assert sdf_node.get("version") == "1.6"


def test_taltech_world_references_local_model_and_spherical_coords() -> None:
    root = ET.fromstring(TALTECH_WORLD_PATH.read_text(encoding="utf-8"))

    assert root.find("./world/spherical_coordinates/latitude_deg") is not None
    assert root.find("./world/spherical_coordinates/longitude_deg") is not None
    assert root.find("./world/scene") is not None
    assert root.find("./world/light[@name='sun']") is not None

    include_uris = [node.text for node in root.findall("./world/include/uri")]
    assert "model://taltech_campus" in include_uris


def test_tum_map_world_assets_exist() -> None:
    assert (TUM_MODEL_DIR / "model.config").is_file()
    assert (TUM_MODEL_DIR / "model.sdf").is_file()
    assert (TUM_MODEL_DIR / "meshes" / "TUM_CentralCampus.obj").is_file()
    assert TUM_WORLD_PATH.is_file()


def test_tum_map_world_references_model_and_spherical_coords() -> None:
    root = ET.fromstring(TUM_WORLD_PATH.read_text(encoding="utf-8"))

    assert root.find("./world/spherical_coordinates/latitude_deg") is not None
    assert root.find("./world/spherical_coordinates/longitude_deg") is not None

    include_uris = [node.text for node in root.findall("./world/include/uri")]
    assert "model://tum_campus_lod3" in include_uris


def test_tum_map_world_origin_uses_live_operator_calibration() -> None:
    env_values: dict[str, str] = {}
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_values[key] = value

    root = ET.fromstring(TUM_WORLD_PATH.read_text(encoding="utf-8"))
    origin_lat = float(root.findtext("./world/spherical_coordinates/latitude_deg", "nan"))
    origin_lon = float(root.findtext("./world/spherical_coordinates/longitude_deg", "nan"))

    assert float(env_values["GEOFENCE_CENTER_LAT"]) == pytest.approx(48.14767)
    assert float(env_values["GEOFENCE_CENTER_LON"]) == pytest.approx(11.56960)
    assert float(env_values["PX4_HOME_LAT"]) == pytest.approx(48.148559)
    assert float(env_values["PX4_HOME_LON"]) == pytest.approx(11.567946)
    assert origin_lat == pytest.approx(48.14968500457427)
    assert origin_lon == pytest.approx(11.56549696798252)


def test_tum_map_model_config_targets_sdf_version() -> None:
    root = ET.fromstring((TUM_MODEL_DIR / "model.config").read_text(encoding="utf-8"))
    sdf_node = root.find("./sdf")
    assert sdf_node is not None
    assert sdf_node.get("version") == "1.6"
