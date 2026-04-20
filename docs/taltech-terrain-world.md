# TalTech Terrain World

This repo includes a reproducible import path for generating a Gazebo Classic
terrain world around Tallinn University of Technology (TalTech) by reusing the
upstream [`gazebo_terrain_generator`](https://github.com/saiaravind19/gazebo_terrain_generator)
pipeline headlessly.

## What gets generated

- `sim/gazebo-classic/models/taltech_campus/`
- `sim/gazebo-classic/worlds/taltech_campus.world`

The current repo integration intentionally imports:
- real DEM terrain
- orthophoto imagery

It does not enable upstream building extrusion by default. That path requires a
much heavier geospatial toolchain and was kept out of the default repo workflow.

## Generate or refresh the world

Install the light terrain-import dependencies:

```bash
cd <workspace>/taltech-uav-mcp-server
. .venv312/bin/activate
pip install -e ".[terrain]"
```

Generate the TalTech terrain world:

```bash
cd <workspace>/taltech-uav-mcp-server
.venv312/bin/python scripts/import_gazebo_terrain.py --model-name taltech_campus --force
```

The defaults target the TalTech campus relation area with a small pad:
- launch longitude: `24.6676189`
- launch latitude: `59.3949741`
- zoom: `17`

You can override the bounds or launch point with CLI flags if you want a larger
or shifted import.

## Launch the live stack on the TalTech world

Use the wrapper so the world path, home coordinates, and spawn pose stay aligned:

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/launch_taltech_live_stack.sh
```

That wrapper exports:
- `SIM_CLASSIC_WORLD_NAME=taltech_campus`
- `GEOFENCE_CENTER_LAT=59.3949741`
- `GEOFENCE_CENTER_LON=24.6676189`
- `PX4_GZ_MODEL_POSE_X=0.0`
- `PX4_GZ_MODEL_POSE_Y=0.0`
- `PX4_GZ_MODEL_POSE_Z=1.0`
- `PX4_GZ_MODEL_POSE_YAW=0.0`

If you prefer the regular launcher, set those variables manually before calling
`scripts/launch_live_stack.sh`.
