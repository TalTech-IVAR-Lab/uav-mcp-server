# Handoff — TalTech UAV MCP simulator integration

Captures everything touched across recent sessions on `feature/observability-dashboard`, what's verified working, and the open problems. Read this before continuing.

## Latest session (yaw rebound, dashboard layout, assistant + orbit)

Four operator-reported issues addressed this session:

1. **Yaw rebound (PID experiment 4).** Root cause: `yaw_relative` repositions via
   `goto_location`, so PX4 slews heading with the *autonomous* yaw trajectory, but
   `MPC_YAWRAUTO_ACC` (the decel limit) was never set — the rate held max until the
   target then slammed to zero, and the airframe's momentum carried past. Fix in
   `scripts/configure_sitl_params.py`: set `MPC_YAWRAUTO_ACC=18` (gentle decel into
   target), drop `MC_YAW_P` 3.2→2.5 (high P was *causing* overshoot), trim inner-loop
   D 0.05→0.02. `MPC_YAWRAUTO_MAX=10` unchanged. Needs in-sim confirmation that a 90°
   turn settles within ~1° with no springback.
2. **Pilot dashboard layout.** Bottom row (Manual / Command Execution / Telemetry) now
   resizes its three panel widths independently of the top row (Visual / Map); only the
   row-height divider is shared. Restructured the single grid into two nested
   `.dashboard-row` grids with 4 resizers (`dashboard_ui.py`). Added a header **Save
   Layout** button → persists `{topRight, botLeft, botRight, rowBottom}` to localStorage
   (`uav.dashboard.layout.v2`), restored on load; double-click resets to default.
3. **Assistant camera-target resolution.** Two bugs: (a) the empty
   `"…could not resolve…: "` was an `asyncio.TimeoutError` (str() == '') from an 8 s
   `wait_for` that was shorter than the Gemini retry budget — added
   `assistant_vision_timeout_s` (default 25 s) and an explicit timeout message;
   (b) "orbit the selected target" with nothing selected was handed to the vision model
   (→ "ambiguous"). The UI now actually sends the selected target
   (`buildSelectedTargetPayload`, previously the payload was just `{text}`), and
   `needs_camera_target_resolution` no longer routes bare selection-references to vision.
4. **Orbit starts in place.** `_target_orbit_call` now uses the *current* horizontal
   standoff as the radius and holds current altitude (was fixed 12 m + target altitude),
   so PX4 circles immediately instead of approaching first. Dashboard orbit paths already
   did this via `_resolve_target_orbit` (max(requested, current_distance)).

Regression tests added in `tests/test_assistant.py`; full `test_assistant`/`test_dashboard`
suites pass. Items below are the *earlier* open problems, still outstanding.

### Follow-up session — magnetic field root cause (projection bug #2 + yaw oscillation)

**`sim/gz/worlds/taltech_campus.world` `<magnetic_field>` was wrong.** It held the
Tallinn field as the NED triple `1.67e-05 3.0e-06 5.07e-05` (north, east, down) but the
element is **ENU** `(East, North, Up)` — confirmed against PX4's stock `default.sdf`
(`6e-06 2.3e-05 -4.2e-05` = small East, large North, **negative** Up). So the sim's field
had its dominant horizontal component in East (magnetic north rotated ~70°) and inclination
inverted (Up positive). Corrected to `3.0e-06 1.67e-05 -5.07e-05`.

This single bug explains **two** long-standing symptoms:
- **Projection bug #2 (wrong angular bearing, error growing with range).** The projection
  pinhole/FRD math is actually correct (verified the double-180° gimbal+sensor SDF rotation
  cancels through gz's FLU camera convention → FRD). The bearing error was a constant EKF
  *yaw bias* from the rotated magnetic north, not a projection-math error. The `mount_yaw`/
  `gimbal_yaw_frame` knobs were red herrings.
- **Yaw oscillation** ("back, forward, back, settles"). GotoControl's HeadingSmoothing
  feed-forward can't overshoot, so the ringing was the attitude loop chasing a wobbling yaw
  *estimate* — the inverted inclination makes EKF mag fusion fight the gyro.

**Must re-test with `./scripts/stop_live_stack.sh --force --reset-px4`** so the EKF discards
the mag state learned against the bad field and re-converges. Also nudged the yaw loop for
damping margin (configure_sitl_params experiment 5: `MC_YAW_P` 2.5→2.2, `MC_YAWRATE_I`
0.10→0.06, `MC_YAWRATE_D` 0.02→0.03). Verify against the dashboard heading line: click the
camera-frame centre with gimbal pitched down and confirm the projection lands on the dashed
ray (per bug-#2 next-step #1).

---

## TL;DR

Sim stack (PX4 SITL + Gazebo Harmonic + TalTech world + controllable gimbal) is solid and takeoff-stable. Flight tuning has been iterated through three PID experiments (latest: yaw-overshoot clamp + above-default outer P). The Gemini-powered LLM assistant flow now has dimension-agnostic coordinates, transient-503 retry, and end-to-end diagnostic logging — accuracy still needs verification in-sim against the new logs.

Open problems re-confirmed by the user (no recent attempt to resolve since the last sim session):

1. **Legend/map symbology mismatch.** Hue-rotate scoping didn't fully fix it.
2. **Camera target projection lands at the wrong angular bearing.** Survives live intrinsics, live gimbal attitude, terrain-aware projection, and ill-conditioning guards. With the new diagnostic logs in `ae20ac3` the gimbal-yaw-frame hypothesis can now be confirmed or ruled out from one log line.
3. **Camera target marker drifts on zoom** — `pitch: 0` was not enough.
4. **Gemini target selection accuracy on the camera feed** — the assistant's pixel pick was occasionally drifting. Three-layer fix landed in `ae20ac3`; needs in-sim verification.

Sections below detail what's confirmed working, what was added in recent commits, and the suspected causes + concrete next steps for each open bug.

---

## Recent commits (most recent first, on `feature/observability-dashboard`)

```
ae20ac3 assistant vision: robust pixel coords + JPEG dim verification + diag log
abe7711 assistant: retry Gemini calls with exponential backoff on transient 503s
45ab03f PID experiment 3: clamp yaw momentum + above-default outer P
83a48d1 PID experiment 2: kill yaw overshoot, keep smoothness
685f49c PID experiment 1: damp attitude rate loops; tame yaw
fb05112 restore dashed heading ray on the map
5a58764 faster vertical + harder rebound suppression
2385332 restore cruise speed; keep rebound suppression independent
0372101 tighten MPC tuning + gimbal PID for no-rebound, stabilized feel
70b41ab TalTech world sim, terrain-aware projection, gimbal stability fixes
```

### What landed in each, briefly

- **`ae20ac3` assistant vision robustness** — _Most recent. See "Gemini target accuracy" section below._
  - `_GeminiVisionTarget` accepts `(u_norm, v_norm)` in [0,1] alongside pixel `(u, v)`; prompt asks for both and the assistant prefers the normalised pair (dimension-agnostic, immune to Gemini's internal preprocess resize).
  - `_decode_jpeg_dimensions()` uses Pillow to read the JPEG bytes' true dimensions and warns + rebuilds the prompt with JPEG-true dims if they disagree with `camera_params.width_px / height_px`.
  - Two new INFO logs: one in `assistant.py` for the Gemini-side coordinate decode (`source=u_norm`, clamped values, image dims, anchor), one in `server.py` for the world-side projection (`lat/lon/distance/bearing` from drone). Lets you tell "Gemini pick was wrong" from "projection of correct pick was wrong" from a single log line.
  - Prompt strengthened: explicit dims, origin/orientation, ground-footpoint vs centroid disambiguation, bbox_norm field.
- **`abe7711` Gemini 503 retry** — wraps Gemini calls in exponential backoff (settings in `config.py`). Empirically the API throws transient 503s a couple of times per session; retries kept the assistant usable.
- **`45ab03f / 83a48d1 / 685f49c` PID experiments** — three iterations on yaw-overshoot and rate-loop damping. The current state is experiment 3 (clamp yaw momentum + above-default outer P). Compare param sets via `scripts/configure_sitl_params.py` git history.
- **`fb05112`** — re-added the dashed cyan heading line to the map (5 km projection in the drone's `yaw_deg` direction). Critical for **next-steps #1 under the projection bug** below.

---

## What's verified working

### Simulation stack
- TalTech Harmonic world (`sim/gz/worlds/taltech_campus.world`) loads correctly via PX4 SITL.
  - World name attribute now matches `PX4_GZ_WORLD=taltech_campus`.
  - `<magnetic_field>`, `<atmosphere>`, `<world_frame_orientation>ENU</world_frame_orientation>` declared so the sensor plugins from PX4's `server.config` produce data.
  - Symlinks created at `PX4-Autopilot/Tools/simulation/gz/worlds/taltech_campus.sdf` → `sim/gz/worlds/taltech_campus.world` and a `terrain_data` symlink alongside, so PX4's hardcoded absolute path lookup finds our world.
- PX4 reports the correct GPS origin (lat 59.3958679, lon 24.6665428, ~28 m AMSL) — not the Zurich default.
- `gz_x500_gimbal` is the active model. PX4 was rebuilt for that target; works on subsequent launches.

### Launcher / process hygiene
- `scripts/launch_taltech_live_stack.sh` now:
  - Reads `PX4_MODEL`, `PX4_GZ_WORLD`, `SIM_GZ_WORLD_NAME`, `SIM_GZ_SPAWN_*` from `.env` when not already in the environment (previously `PX4_MODEL` from `.env` was silently ignored).
  - Exports both `PX4_GZ_MODEL_POSE_X/Y/Z` (Classic-patch convention) **and** `PX4_GZ_MODEL_POSE="x,y,z"` (stock Harmonic `px4-rc.gzsim` convention). The Harmonic path was previously ignoring our spawn pose entirely; the drone always spawned at world (0,0,0).
- `scripts/start_sitl.sh` prepends `$SIM_GZ_ROOT/models` to `GZ_SIM_RESOURCE_PATH` so repo-local model overrides win over PX4's stock models.
- `scripts/stop_live_stack.sh` got a `--reset-px4` flag that wipes `parameters.bson`, `parameters_backup.bson`, `dataman`, `log/`, `eeprom/`. Safety guard refuses to reset while a px4 process still has the rootfs open. Use after a crash / tip / failsafe poisoned the persisted state.
- `scripts/configure_sitl_params.py` applies smoother-flight PX4 params at runtime (`MPC_XY_VEL_MAX=3`, `MPC_ACC_HOR_MAX=2`, `MPC_JERK_MAX=4`, `MPC_YAWRAUTO_MAX=30`, etc.). Each value re-checked; missing params on a given firmware are skipped non-fatally.

### Settings / env
- `pydantic-settings` `extra="ignore"` so the shared `.env` can carry shell-only keys without crashing the server.
- `.env` switched to `PX4_MODEL=gz_x500_gimbal`, camera params retuned to 1280×720 / hfov 2.0 / focal 410.94, topic suffix `/camera_link/sensor/camera/image`. Manual control step reduced 10 → 3 m.

### Lightweight gimbal
- `sim/gz/models/gimbal/model.sdf` shadows PX4's stock gimbal. Link masses 0.1 → 0.001 kg, inertias scaled to match, joint damping 0.1 → **0.5** (was 5.0 in an earlier iteration, slowed the gimbal too much), camera-link collision sphere removed (it landed first and bounced the drone). PID `cmd_max` bumped 0.3 → 3.0 for snappier response. `meshes/` is a symlink to PX4's stock STL files.
- Result: x500 flies essentially like the gimbal-less plain x500, MAVSDK reports gimbal as available, pitch commands round-trip end-to-end (MCP → MAVSDK → MAVLink → PX4 MNT driver → gz topic → joint controller). Verified by reading `/model/.../command/gimbal_pitch` while issuing MCP `gimbal_pitch_relative`.

### Spawn / takeoff stability
- `SIM_GZ_SPAWN_Z_M=1.5` in `.env`. Higher (5 m) caused the drone to tumble onto its back on landing; lower (<1 m) embedded it in the heightmap.
- After 1.5 m drop, EKF2 attitude estimate can briefly read `roll≈±180°` for ~5–10 s while reconverging. `state` flips to `ready` *before* EKF is fully settled — don't arm during that window. ~30 s settle is enough.
- Verified end-to-end: arm → takeoff to 8 m / 12 m / 15 m → land → disarm. Roll/pitch within ±2° during climb (was 12° with the heavy stock gimbal).

### Camera target projection — partial
- `src/uav_mcp_server/terrain.py` — heightmap sampler. **Critical fix**: heightmap `<pos>.z` is the BOTTOM of the height range, not the centre (verified empirically: pixel 17 380 at world origin → Z = `pos_z + (raw/max)·size_z = -8.01 + 0.265·30.2 ≈ 0 m`, which matches the actual home elevation). My first attempt centred the range around `pos_z` and produced terrain Z ≈ -15 m everywhere; that's what made post-terrain projection *worse* than flat-ground.
- `src/uav_mcp_server/projection.py` — terrain-aware fixed-point iteration. Ill-conditioning guards: skip terrain iteration when the camera ray is shallower than ~12° from horizon (`down_component < 0.2`); reject iterations that try to jump the projection distance >3× in one step. Diagnostic block returned in API response: `terrain_used`, `terrain_iterations`, `terrain_elevation_m`, `flat_ground_distance_m`.
- `src/uav_mcp_server/camera_intrinsics.py` (new) — shells out to `gz topic --echo` at server startup to read the camera_info K matrix from the running sim, overrides `CameraParams` so the projection uses what gz is actually rendering with rather than the `.env` numbers. Confirmed `fx=410.93925` from gz matches the `.env` (so the override doesn't change values today, but it'll catch SDF drift).
- `src/uav_mcp_server/drone.py` — added a background asyncio task in `MavsdkBackend` that consumes `system.gimbal.attitude()` and updates `_actual_gimbal_pitch_deg` / `_actual_gimbal_yaw_deg`. `current_gimbal_pitch_deg()` now prefers the live joint angle over the last-commanded target, removing PID-lag projection error after a pitch command.

### Camera click → image mapping
- `src/uav_mcp_server/dashboard_ui.py` — `.camera-stream` CSS changed from `object-fit: cover` (crops) to `object-fit: contain` (letterbox). The JS pixel-mapping math was always for `contain`; the prior `cover` produced silent click offsets.
- `mapContainerToImagePixel` rewritten to clean `min(scaleX, scaleY)` contain math; returns `null` when the click lands on a letterbox bar (rejected with a notice in the UI instead of silently clamping). Sensor dimensions are now resolved from `img.naturalWidth/Height` first, with `appState.config.camera.params` as fallback, so the JS and the server always agree on the frame dimensions used for projection.

---

## What's still broken

### 1. Symbology mismatch between legend and map markers

**Symptom (user-confirmed at end of session)**: legend swatches and map markers display in different colors.

**What I tried**:
- Identified that `#map { filter: ... hue-rotate(180deg) ... }` was inverting hues on every child of `#map`, including the HTML marker `<div>`s. Legend swatches are outside `#map` so they keep their declared colors → 180° hue difference between legend and map.
- Scoped the filter to `#map .maplibregl-canvas-container, #map .maplibregl-canvas` only.

**Why it likely still isn't right**:
- maplibre-gl-js may render markers using `transform: translate(...)` containers that are *children* of `.maplibregl-canvas-container`, not siblings. If they are, my new selector still tints them.
- Or the user is seeing color mismatch from a *different* source (legend swatch CSS uses theme vars like `var(--warning)`, `var(--success)`, while the actual icon CSS hardcodes hex values like `#ec5f8f`). The two should be unified.

**Next steps**:
1. Open the dashboard in a browser, inspect `.maplibregl-marker` DOM to confirm its computed `filter` is `none` after my change. If a parent of the marker still has the filter, narrow the selector further — e.g., apply `filter: none` directly to `.maplibregl-marker { filter: none !important; }`.
2. Align the colour palette: replace hex literals in `.target-icon`, `.projection-icon`, etc. with the theme variables already used in the legend swatches (`var(--warning)`, `var(--accent)`, etc.) so they're guaranteed identical.
3. Verify with a screenshot test: page loaded + projection visible → eyedropper on legend swatch and map marker should give the same hex.

Files: `src/uav_mcp_server/dashboard_ui.py:315-397` (CSS), `:680-685` (legend HTML).

### 2. Camera target projection lands at the wrong angular bearing

**Symptom**: click a target visible in the camera, the projected lat/lon appears on the map at a noticeably wrong bearing from the drone — not just "tens of metres off" (which terrain noise could explain) but "wrong direction".

**What I tried**:
- Confirmed gz `camera_info` K matrix matches `.env` → intrinsics are not the issue.
- Confirmed pinhole math, FRD rotations, and `offset_coordinate` are internally consistent (traced through yaw=0/90/180 cases manually).
- Switched gimbal pitch source from "last commanded target" to "live MAVSDK attitude stream" so PID-lag isn't lying about the joint angle.
- Added bound on per-iteration scale jump in the terrain iteration (caps pathological 1× → 30× jumps caused by sampling a low-elevation pixel mid-ray).

**What I haven't verified — the prime suspects**:
- **MAVSDK gimbal yaw frame convention**. The gimbal SDF is yaw-rotated 180° (`<include><pose>0 0 0.26 0 0 3.14</pose></include>`), and the camera sensor inside it is also yaw-rotated 180°. The two cancel for the optical axis pointing forward — but PX4's `MNT_*` driver may report gimbal yaw in the gimbal frame, not the body frame. If so, a `yaw_deg=0` from MAVSDK means "camera aligned with gimbal forward", which after the 180° rotation is **backward** in the body frame. The projection would then be 180° off in azimuth.
  - Quick test: with drone facing north (`yaw_deg=0`) and gimbal `yaw_deg=0`, click the camera centre. Projection should land **due north** of the drone. If it lands due south → the gimbal-yaw frame is inverted.
- **`drone_pose.yaw_deg` sign**. MAVSDK reports yaw in NED (clockwise from north). The projection's `_rotate_frd` uses positive yaw as clockwise around Z (down). Should match. But a sign flip somewhere along the telemetry chain is plausible — a 180° error in yaw produces exactly the "everything's mirrored" pattern.
- **Camera ray axis convention inside the body frame**. The current code does `ray_camera = (1, (u-cx)/f, (v-cy)/f)` then applies `_rotate_frd` with `mount_yaw_deg`/`mount_pitch_deg`/`mount_roll_deg`. This implicitly assumes camera FRD = (forward, right, down). If the gz camera actually publishes images such that +u in the image is the *left* side of the body (because of that 180° SDF rotation), then `(u-cx)/f` becomes the wrong sign and the result mirrors across the body Y-axis.

**Next steps** (in order):
1. **Use the heading line as ground truth** (restored in `fb05112`). Take off, hover with the gimbal pitched down 30–45° and gimbal yaw 0. Click the *exact centre* of the camera frame. The projection should land on the heading line. If it doesn't — the gimbal yaw frame is the bug; subtract the angular offset from `mount_yaw_deg` in the projection and check whether it's a consistent 180°, -90°, +90° shift (that tells you the frame transform you need).
2. **Read the new `assistant_vision:` log line** (added in `ae20ac3`). It prints the projected `lat/lon/distance/bearing≈X° from drone`. Compare `bearing` against the visible heading-line angle in the gz GUI. A consistent 180° / ±90° delta = frame transform bug. A small (<5°) noisy delta = EKF yaw bias.
3. **Manually verify drone yaw direction first**. Move the drone forward in the gz GUI. Confirm the heading-line cyan dashes point in the same direction the drone is physically going. If the line is 180° off → the dashboard's drone-yaw display path is inverted; investigate `rotateDroneMarker` and the heading-line code in `dashboard_ui.py`.
4. **If gimbal yaw is the culprit**, the fix lives in `src/uav_mcp_server/drone.py`'s gimbal-attitude consumer: apply a frame offset before storing `_actual_gimbal_yaw_deg`. Likely `yaw_deg + 180`, modulo 360.

Files: `src/uav_mcp_server/projection.py` (math), `src/uav_mcp_server/drone.py:96-160` (gimbal attitude consumer), `sim/gz/models/gimbal/model.sdf` (the 180° rotations that may be mis-modelled by the MNT driver).

### 3. Camera target marker drifts when zooming the map

**Symptom**: the projection target marker visually moves relative to ground features as the user zooms in/out, even when no new projection has been issued.

**What I tried**:
- Theorised this was the 3D perspective at `pitch: 45` — at oblique pitch, markers anchored to lat/lon look like they slide relative to nearby ground features at different zooms because the screen-to-world projection changes with zoom level.
- Reduced map `pitch: 45 → 0` (top-down).

**Why that wasn't enough**:
- User confirmed drift persists at pitch 0. So this isn't a perspective artifact.
- Possible real causes:
  - The marker's HTML element has a fixed `width`/`height`/`border` and `anchor: 'center'` does what we want at one zoom level but the icon's pseudo-elements (`.projection-icon::before`, `::after` — the crosshair lines) have absolute positions inside a transformed container; if maplibre applies a CSS transform to the marker for retina or DPR reasons, the offset can scale with zoom.
  - We re-create the popup on every projection update (`appState.targetMarker.setPopup(new maplibregl.Popup(...))`) which may re-anchor the marker DOM each time and reset some internal offset.
  - There's a possibility that the lat/lon being passed to `setLngLat` is being recomputed elsewhere using stale drone pose during pan events.

**Next steps**:
1. Open the running dashboard, set a projection target, and use the browser devtools to inspect `.maplibregl-marker` containing the projection icon. Watch its `transform` style attribute while zooming. If the `translate(x, y)` values change consistently with zoom (correct), the marker is fine — the drift is visual. If the transform freezes during zoom and then snaps, that's a re-render bug.
2. Pin the marker to lat/lon explicitly each frame: in the telemetry update loop, after a projection has been set, call `appState.targetMarker.setLngLat([proj.lon, proj.lat])` again — defends against any state being clobbered by other DOM events.
3. Try `anchor: 'top-left'` with a manual pixel offset instead of `anchor: 'center'`. Some maplibre versions have a subtle bug with `center` and odd-pixel-width icons.
4. Last resort: stop using HTML marker for the projection and render it as a maplibre `symbol` layer backed by a tiny GeoJSON source — symbol layers project through the WebGL canvas pipeline, so they're guaranteed to track terrain features pixel-perfectly across zooms.

Files: `src/uav_mcp_server/dashboard_ui.py:1206-1212` (marker creation), `:1363-1376` (marker update on projection).

### 4. Gemini target selection accuracy on the camera feed

**Symptom**: when the dashboard assistant is asked to localise a visible target (e.g. "the small building on the left"), the projected map marker was sometimes drifting from the actual feature. Distinct from bug 2: even after a perfect projection chain, Gemini's pixel pick itself could be off.

**Root causes identified**:
- Gemini's internal preprocess resize sometimes returned pixel coordinates in its own working resolution rather than the dimensions we declared in the prompt.
- The `image_width_px / height_px` we put in the prompt came from `camera_params` (probed at server startup). If the gz camera publishes a different resolution after startup, or the bridge resizes, the JPEG bytes and the prompt dimensions diverge silently.

**What landed (`ae20ac3`)**:
- Normalised `(u_norm, v_norm)` is now the primary signal — multiplied on our side by the actual image dimensions. Dimension-agnostic by construction.
- `_decode_jpeg_dimensions()` decodes the JPEG bytes and rebuilds the prompt with the true dims if they disagree with `camera_params`. Logs a warning when this triggers.
- Two new diagnostic logs (INFO level):
  - `Gemini vision target: source=... u=... v=... → clamped=(...) in WxH (raw_u=... u_norm=... anchor=... label='...')` — tells you exactly which coord field Gemini returned and how it decoded.
  - `assistant_vision: 'label' → pixel=(u, v) anchor=... → lat=... lon=... dist=...m bearing≈...° from drone` — the world-side projection.

**Next steps for verification** (this is the active item):
1. Launch the stack, take off, ask the assistant to localise something visible (e.g. "fly to the big building straight ahead"). Find both log lines in `/tmp/launcher.out`.
2. Cross-check the pixel coords against where you'd click manually on the same target — that diagnoses Gemini vs projection.
3. If Gemini's pixel is right but the marker is wrong → bug 2 (projection / gimbal-yaw frame). Use the bearing in the new log to determine the angular offset.
4. If Gemini's pixel is wrong → tighten the prompt further. The `bbox_norm` field is already accepted; could be used as a sanity-check on the point pick.
5. If the "JPEG dims disagree with camera_params" warning fires, that's a configuration drift worth fixing at the source (`.env` vs gz camera SDF vs bridge config).

Files: `src/uav_mcp_server/assistant.py` (Gemini call, prompt, decode), `src/uav_mcp_server/server.py:1689-1710` (server-side projection log), `src/uav_mcp_server/config.py` (Gemini retry settings).

---

## How to launch / reproduce

```bash
cd /home/ed/thesis/taltech-uav-mcp-server
./scripts/stop_live_stack.sh --force --reset-px4    # only after a crash/tip
./scripts/launch_taltech_live_stack.sh              # add HEADLESS=1 for no GUI
# wait ~30 s after spawn, then arm + takeoff in the dashboard
```

Dashboard at `http://127.0.0.1:8000/dashboard/`.

The MCP HTTP endpoint is at `/mcp`. Useful diagnostic endpoints:
- `GET /dashboard/api/telemetry` — current drone state
- `POST /dashboard/api/project_pixel` `{u, v}` — full projection diagnostic including `terrain_used`, `terrain_iterations`, `terrain_elevation_m`, `flat_ground_distance_m`, `gimbal.tracked_pitch_deg`, `gimbal.tracked_yaw_deg`, `camera.effective.focal_length_px`. Use this to debug angular offsets — every error contributor is in the response.

`scripts/configure_sitl_params.py` runs automatically during the launcher and logs each MPC override it applied. Check `/tmp/launcher.out` to confirm they took.

---

## Files touched (cheat-sheet)

```
.env                                                # PX4 model, camera params, spawn pose, manual step
pyproject.toml                                      # pillow + numpy added to [terrain] extras
scripts/launch_taltech_live_stack.sh                # .env propagation, PX4_GZ_MODEL_POSE
scripts/start_sitl.sh                               # GZ_SIM_RESOURCE_PATH for repo models
scripts/sitl_profile.sh                             # gz_x500_gimbal in supported list
scripts/stop_live_stack.sh                          # --reset-px4 flag
scripts/configure_sitl_params.py                    # MPC smoothing overrides

sim/gz/worlds/taltech_campus.world                  # world name, magnetic_field, atmosphere, ENU
sim/gz/models/gimbal/model.sdf                      # lightweight override of PX4 stock gimbal
sim/gz/models/gimbal/model.config                   # model metadata
sim/gz/models/gimbal/meshes                         # symlink to PX4 stock meshes

src/uav_mcp_server/config.py                        # X500_GIMBAL_PROFILE; SettingsConfigDict extra='ignore'; Gemini retry settings
src/uav_mcp_server/terrain.py                       # NEW: heightmap sampler
src/uav_mcp_server/camera_intrinsics.py             # NEW: gz camera_info probe
src/uav_mcp_server/projection.py                    # terrain iteration; ill-conditioning guards
src/uav_mcp_server/drone.py                         # live gimbal attitude consumer
src/uav_mcp_server/server.py                        # wire up terrain sampler + intrinsics probe; assistant_vision diag log
src/uav_mcp_server/dashboard_ui.py                  # object-fit: contain, pitch 0, heading line, filter scoping
src/uav_mcp_server/assistant.py                     # u_norm/v_norm primary, JPEG dim verification, diag log, Gemini retry

PX4-Autopilot/Tools/simulation/gz/worlds/
    taltech_campus.sdf        → symlink to sim/gz/worlds/taltech_campus.world
    terrain_data              → symlink to sim/gz/worlds/terrain_data
```
