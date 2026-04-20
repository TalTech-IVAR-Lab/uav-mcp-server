#!/usr/bin/env python3
"""Import a real-world terrain model into the repo's Gazebo Classic assets.

This script reuses the upstream gazebo_terrain_generator implementation in a
headless way. It clones the upstream repo into a local cache, downloads
orthophoto and DEM tiles for the selected area, and emits a Gazebo model/world
into ``sim/gazebo-classic``.

Pass ``--include-buildings`` to also generate 3-D building meshes. Building
footprints are fetched from the OpenStreetMap Overpass API (no API key needed)
and converted to a COLLADA mesh that Gazebo Classic can render.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import shutil
import subprocess
import sys
import threading
import types
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import urllib.request
import urllib.parse


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENERATOR_REPO = "https://github.com/saiaravind19/gazebo_terrain_generator.git"
DEFAULT_CACHE_DIR = REPO_ROOT / ".cache" / "external" / "gazebo_terrain_generator"
DEFAULT_WORK_DIR = REPO_ROOT / ".cache" / "terrain-import"
DEFAULT_MODEL_NAME = "taltech_campus"
DEFAULT_SOURCE_URL = "http://ecn.t0.tiles.virtualearth.net/tiles/a{quad}.jpeg?g=129&mkt=en&stl=H"

# OSM relation bounding box for Tallinna Tehnikaulikool with a small pad.
DEFAULT_BOUNDS = (24.6545, 59.3918, 24.6750, 59.3991)  # west, south, east, north
DEFAULT_LAUNCH = (24.6676189, 59.3949741)  # lon, lat
DEFAULT_ZOOM = 17
CLASSIC_SDF_VERSION = "1.6"
DEFAULT_SCENE_XML = """\
<scene>
  <ambient>0.58 0.6 0.68 1</ambient>
  <background>0.9 0.94 1 1</background>
  <shadows>true</shadows>
  <grid>false</grid>
</scene>
"""
DEFAULT_LIGHT_XML = """\
<light type="directional" name="sun">
  <cast_shadows>true</cast_shadows>
  <pose>0 0 10 0 0 0</pose>
  <diffuse>0.85 0.85 0.82 1</diffuse>
  <specular>0.25 0.25 0.25 1</specular>
  <attenuation>
    <range>1000</range>
    <constant>0.9</constant>
    <linear>0.01</linear>
    <quadratic>0.001</quadratic>
  </attenuation>
  <direction>-0.5 0.1 -0.9</direction>
</light>
"""


OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"


def _overpass_to_geojson(data: dict[str, Any]) -> dict[str, Any]:
    """Convert an Overpass API JSON response to a GeoJSON FeatureCollection.

    Handles closed ways (simple polygons) and multipolygon relations.
    """
    nodes: dict[int, tuple[float, float]] = {}
    for el in data.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])

    ways: dict[int, tuple[list[tuple[float, float]], dict[str, Any]]] = {}
    for el in data.get("elements", []):
        if el["type"] == "way":
            coords = [nodes[n] for n in el.get("nodes", []) if n in nodes]
            if len(coords) >= 3 and coords[0] != coords[-1]:
                coords.append(coords[0])
            ways[el["id"]] = (coords, el.get("tags", {}))

    features: list[dict[str, Any]] = []

    for el in data.get("elements", []):
        if el["type"] == "way":
            coords, tags = ways.get(el["id"], ([], {}))
            if len(coords) < 4:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": tags,
            })

        elif el["type"] == "relation":
            tags = el.get("tags", {})
            outer_rings: list[list[tuple[float, float]]] = []
            for member in el.get("members", []):
                if member.get("type") == "way" and member.get("role") == "outer":
                    coords, _ = ways.get(member["ref"], ([], {}))
                    if len(coords) >= 4:
                        outer_rings.append(coords)
            if outer_rings:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "MultiPolygon", "coordinates": [[ring] for ring in outer_rings]},
                    "properties": tags,
                })

    return {"type": "FeatureCollection", "features": features}


def _fetch_osm_buildings(bounds_array: list[float], model_output_dir: Path) -> Path:
    """Download OSM building footprints from Overpass API and save as buildings.geojson."""
    west, south, east, north = bounds_array
    query = (
        f"[out:json][timeout:120];\n"
        f"(\n"
        f'  way["building"]({south},{west},{north},{east});\n'
        f'  relation["building"]["type"="multipolygon"]({south},{west},{north},{east});\n'
        f");\n"
        f"out body;\n"
        f">;\n"
        f"out skel qt;\n"
    )
    print("Downloading OSM building footprints via Overpass API...")
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS_ENDPOINT, data=data, method="POST")
    req.add_header("User-Agent", "taltech-uav-mcp-server/import_gazebo_terrain")
    with urllib.request.urlopen(req, timeout=180) as resp:
        overpass_data = json.loads(resp.read())

    geojson = _overpass_to_geojson(overpass_data)
    dest = model_output_dir / "buildings.geojson"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Saved {len(geojson['features'])} building features → {dest}")
    return dest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a real-world Gazebo terrain into the repo.")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help="Output model/world name.")
    parser.add_argument("--west", type=float, default=DEFAULT_BOUNDS[0], help="West longitude.")
    parser.add_argument("--south", type=float, default=DEFAULT_BOUNDS[1], help="South latitude.")
    parser.add_argument("--east", type=float, default=DEFAULT_BOUNDS[2], help="East longitude.")
    parser.add_argument("--north", type=float, default=DEFAULT_BOUNDS[3], help="North latitude.")
    parser.add_argument("--launch-lon", type=float, default=DEFAULT_LAUNCH[0], help="Launch longitude.")
    parser.add_argument("--launch-lat", type=float, default=DEFAULT_LAUNCH[1], help="Launch latitude.")
    parser.add_argument("--zoom", type=int, default=DEFAULT_ZOOM, help="Orthophoto zoom level.")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="Raster tile URL template.")
    parser.add_argument(
        "--generator-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Local checkout path for the upstream terrain generator.",
    )
    parser.add_argument(
        "--generator-repo",
        default=DEFAULT_GENERATOR_REPO,
        help="Upstream generator repo used if the local checkout is missing.",
    )
    parser.add_argument(
        "--work-dir",
        default=str(DEFAULT_WORK_DIR),
        help="Working directory for downloaded tiles and DEM cache.",
    )
    parser.add_argument(
        "--include-buildings",
        action="store_true",
        help="Enable upstream building generation if the heavy geospatial deps are installed.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remove any existing model/world output before generation.",
    )
    return parser.parse_args()


def ensure_generator_checkout(path: Path, repo_url: str) -> Path:
    if (path / "README.md").is_file() and (path / "scripts" / "server.py").is_file():
        return path
    if (path / ".git").is_dir():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(path)],
        check=True,
        cwd=REPO_ROOT,
    )
    return path


def load_upstream_modules(
    generator_dir: Path,
    *,
    work_dir: Path,
    model_dir: Path,
    world_dir: Path,
    include_buildings: bool,
) -> dict[str, Any]:
    scripts_dir = generator_dir / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    # The upstream terrain-only path never actually uses rasterio, but the
    # module is imported unconditionally. Stub it out unless the user asked for
    # the heavier building stack and already has everything installed.
    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")

    if not include_buildings:
        dummy_buildings = types.ModuleType("utils.buildingsGenerator")

        class _GeoJSONToDAE:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("Building generation is disabled in this importer.")

        dummy_buildings.GeoJSONToDAE = _GeoJSONToDAE
        sys.modules["utils.buildingsGenerator"] = dummy_buildings

    from utils.demTilesDownloader import download_dem_data
    from utils.fileWriter import FileWriter
    from utils.gazeboWorldGenerator import GazeboTerrianGenerator
    from utils.maptileUtils import maptile_utiles
    from utils.param import globalParam
    from utils.utils import Utils

    globalParam.TEMP_PATH = str(work_dir / "temp")
    globalParam.OUTPUT_BASE_PATH = str(work_dir / "output")
    globalParam.GAZEBO_MODEL_PATH = str(model_dir)
    globalParam.GAZEBO_WORLD_PATH = str(world_dir)
    globalParam.DEM_PATH = str(work_dir / "dem")
    globalParam.BUILDING_PATH = str(work_dir / "streetmap")
    globalParam.TEMPORARY_SATELLITE_IMAGE = str(work_dir / "temporary_satellite")
    globalParam.TEMPLATE_DIR_PATH = str(generator_dir / "templates")

    return {
        "download_dem_data": download_dem_data,
        "FileWriter": FileWriter,
        "GazeboTerrianGenerator": GazeboTerrianGenerator,
        "maptile_utiles": maptile_utiles,
        "globalParam": globalParam,
        "Utils": Utils,
    }


def _download_orthophoto_tiles(
    *,
    tile_root: Path,
    bounds_array: list[float],
    zoom: int,
    source_url: str,
    maptile_utiles: Any,
    Utils: Any,
) -> None:
    tile_bounds = maptile_utiles.get_max_tilenumber(bounds_array, zoom)
    min_x = min(tile_bounds["southwest"][0], tile_bounds["northwest"][0])
    max_x = max(tile_bounds["southeast"][0], tile_bounds["northeast"][0])
    min_y = min(tile_bounds["northwest"][1], tile_bounds["northeast"][1])
    max_y = max(tile_bounds["southwest"][1], tile_bounds["southeast"][1])

    zoom_root = tile_root / str(zoom)
    zoom_root.mkdir(parents=True, exist_ok=True)
    total = (max_x - min_x + 1) * (max_y - min_y + 1)
    current = 0
    for x in range(min_x, max_x + 1):
        x_dir = zoom_root / str(x)
        x_dir.mkdir(parents=True, exist_ok=True)
        for y in range(min_y, max_y + 1):
            current += 1
            tile_path = x_dir / f"{y}.png"
            if tile_path.exists():
                continue
            code = Utils.downloadFileScaled(source_url, str(tile_path), x, y, zoom, 1)
            if code != 200 or not tile_path.exists():
                raise RuntimeError(f"Tile download failed for {zoom}/{x}/{y} with code {code}.")
            print(f"Downloaded orthophoto tile {current}/{total}: {zoom}/{x}/{y}")


def _write_classic_world(
    *,
    world_sdf_path: Path,
    world_path: Path,
    model_dir_world_path: Path,
    model_name: str,
) -> None:
    root = ET.fromstring(world_sdf_path.read_text(encoding="utf-8"))
    spherical = root.find("./world/spherical_coordinates")
    if spherical is None:
        raise RuntimeError(f"Generated world is missing spherical coordinates: {world_sdf_path}")

    generated_world = root.find("./world")
    if generated_world is None:
        raise RuntimeError(f"Generated world is missing a world node: {world_sdf_path}")

    classic_root = ET.Element("sdf", {"version": CLASSIC_SDF_VERSION})
    classic_world = ET.SubElement(classic_root, "world", {"name": model_name})
    classic_world.append(deepcopy(spherical))

    scene = generated_world.find("scene")
    if scene is None:
        scene = ET.fromstring(DEFAULT_SCENE_XML)
    classic_world.append(deepcopy(scene))

    light_nodes = generated_world.findall("light")
    if not light_nodes:
        light_nodes = [ET.fromstring(DEFAULT_LIGHT_XML)]
    for light in light_nodes:
        classic_world.append(deepcopy(light))

    include = ET.SubElement(classic_world, "include")
    ET.SubElement(include, "uri").text = f"model://{model_name}"

    physics = ET.SubElement(
        classic_world,
        "physics",
        {"name": "default_physics", "default": "0", "type": "ode"},
    )
    ET.SubElement(physics, "gravity").text = "0 0 -9.8066"
    ode = ET.SubElement(physics, "ode")
    solver = ET.SubElement(ode, "solver")
    ET.SubElement(solver, "type").text = "quick"
    ET.SubElement(solver, "iters").text = "10"
    ET.SubElement(solver, "sor").text = "1.3"
    ET.SubElement(solver, "use_dynamic_moi_rescaling").text = "0"
    constraints = ET.SubElement(ode, "constraints")
    ET.SubElement(constraints, "cfm").text = "0"
    ET.SubElement(constraints, "erp").text = "0.2"
    ET.SubElement(constraints, "contact_max_correcting_vel").text = "100"
    ET.SubElement(constraints, "contact_surface_layer").text = "0.001"
    ET.SubElement(physics, "max_step_size").text = "0.004"
    ET.SubElement(physics, "real_time_factor").text = "1"
    ET.SubElement(physics, "real_time_update_rate").text = "250"
    ET.SubElement(physics, "magnetic_field").text = "6.0e-6 2.3e-5 -4.2e-5"

    world_text = ET.tostring(classic_root, encoding="unicode")
    world_path.write_text(f'<?xml version="1.0" ?>\n{world_text}\n', encoding="utf-8")
    model_dir_world_path.write_text(f'<?xml version="1.0" ?>\n{world_text}\n', encoding="utf-8")


def _normalize_model_config(*, model_config_path: Path) -> None:
    root = ET.fromstring(model_config_path.read_text(encoding="utf-8"))
    sdf_node = root.find("./sdf")
    if sdf_node is None:
        raise RuntimeError(f"Generated model config is missing an <sdf> entry: {model_config_path}")
    sdf_node.set("version", CLASSIC_SDF_VERSION)
    sdf_node.text = "model.sdf"
    model_config_path.write_text(
        '<?xml version="1.0"?>\n\n' + ET.tostring(root, encoding="unicode") + "\n",
        encoding="utf-8",
    )


def _normalize_sdf_root_version(*, path: Path) -> None:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    root.set("version", CLASSIC_SDF_VERSION)
    path.write_text(f'<?xml version="1.0" ?>\n{ET.tostring(root, encoding="unicode")}\n', encoding="utf-8")


def _write_import_metadata(
    *,
    model_dir: Path,
    world_path: Path,
    model_name: str,
    bounds_array: list[float],
    launch_lon: float,
    launch_lat: float,
    zoom: int,
    include_buildings: bool,
    source_url: str,
) -> None:
    metadata = {
        "generator_repo": DEFAULT_GENERATOR_REPO,
        "model_name": model_name,
        "bounds": {
            "west": bounds_array[0],
            "south": bounds_array[1],
            "east": bounds_array[2],
            "north": bounds_array[3],
        },
        "launch_location": {
            "longitude_deg": launch_lon,
            "latitude_deg": launch_lat,
        },
        "zoom": zoom,
        "include_buildings": include_buildings,
        "source_url": source_url,
        "world_path": str(world_path.relative_to(REPO_ROOT)),
    }
    (model_dir / "import_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def run_import(args: argparse.Namespace) -> None:
    generator_dir = ensure_generator_checkout(Path(args.generator_dir), args.generator_repo)
    model_dir = REPO_ROOT / "sim" / "gazebo-classic" / "models"
    world_dir = REPO_ROOT / "sim" / "gazebo-classic" / "worlds"
    model_output_dir = model_dir / args.model_name
    world_sdf_path = world_dir / f"{args.model_name}.sdf"
    world_path = world_dir / f"{args.model_name}.world"
    work_dir = Path(args.work_dir)

    if args.force:
        shutil.rmtree(model_output_dir, ignore_errors=True)
        world_sdf_path.unlink(missing_ok=True)
        world_path.unlink(missing_ok=True)
        shutil.rmtree(work_dir, ignore_errors=True)

    bounds_array = [args.west, args.south, args.east, args.north]

    if args.include_buildings:
        geojson_dest = model_output_dir / "buildings.geojson"
        if not geojson_dest.exists():
            _fetch_osm_buildings(bounds_array, model_output_dir)
        else:
            print(f"Using existing buildings.geojson ({len(json.loads(geojson_dest.read_text())['features'])} features)")

    modules = load_upstream_modules(
        generator_dir,
        work_dir=work_dir,
        model_dir=model_dir,
        world_dir=world_dir,
        include_buildings=args.include_buildings,
    )

    FileWriter = modules["FileWriter"]
    GazeboTerrianGenerator = modules["GazeboTerrianGenerator"]
    Utils = modules["Utils"]
    download_dem_data = modules["download_dem_data"]
    maptile_utiles = modules["maptile_utiles"]
    globalParam = modules["globalParam"]

    tile_root = Path(globalParam.OUTPUT_BASE_PATH) / args.model_name
    tile_root.mkdir(parents=True, exist_ok=True)

    file_path = tile_root / "metadata.json"
    FileWriter.addMetadata(
        threading.Lock(),
        str(tile_root),
        str(file_path),
        args.model_name,
        "TalTech campus terrain import",
        "png",
        bounds_array,
        [(args.west + args.east) / 2.0, (args.south + args.north) / 2.0],
        json.dumps(
            {
                "west": args.west,
                "south": args.south,
                "east": args.east,
                "north": args.north,
            },
            sort_keys=True,
        ),
        args.zoom,
        launchLocation=[args.launch_lon, args.launch_lat],
    )

    print(f"Downloading orthophoto tiles for {args.model_name}...")
    _download_orthophoto_tiles(
        tile_root=tile_root,
        bounds_array=bounds_array,
        zoom=args.zoom,
        source_url=args.source_url,
        maptile_utiles=maptile_utiles,
        Utils=Utils,
    )

    print(f"Downloading DEM tiles for {args.model_name}...")
    true_boundaries = maptile_utiles.get_true_boundaries(bounds_array, args.zoom)
    download_dem_data(true_boundaries, globalParam.DEM_PATH)

    print(f"Generating Gazebo terrain model {args.model_name}...")
    generator = GazeboTerrianGenerator(str(tile_root), include_buildings=args.include_buildings)
    generator.generate_gazebo_world()

    if not world_sdf_path.exists():
        raise RuntimeError(f"Expected generated world file missing: {world_sdf_path}")
    if not (model_output_dir / "model.sdf").exists():
        raise RuntimeError(f"Expected generated model missing: {model_output_dir / 'model.sdf'}")

    _normalize_model_config(model_config_path=model_output_dir / "model.config")
    _normalize_sdf_root_version(path=world_sdf_path)
    _write_classic_world(
        world_sdf_path=world_sdf_path,
        world_path=world_path,
        model_dir_world_path=model_output_dir / f"{args.model_name}.world",
        model_name=args.model_name,
    )
    _write_import_metadata(
        model_dir=model_output_dir,
        world_path=world_path,
        model_name=args.model_name,
        bounds_array=bounds_array,
        launch_lon=args.launch_lon,
        launch_lat=args.launch_lat,
        zoom=args.zoom,
        include_buildings=args.include_buildings,
        source_url=args.source_url,
    )
    print(f"Generated model: {model_output_dir}")
    print(f"Generated world: {world_path}")


def main() -> None:
    args = parse_args()
    run_import(args)


if __name__ == "__main__":
    main()
