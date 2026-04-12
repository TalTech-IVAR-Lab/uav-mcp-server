from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "open_gazebo_gui.sh"


def write_fake_gazebo_setup(tmp_path: Path) -> Path:
    setup_path = tmp_path / "gazebo-setup.sh"
    setup_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "export GAZEBO_RESOURCE_PATH=/opt/gazebo/share:/existing/resources",
                "export GAZEBO_MODEL_PATH=/opt/gazebo/models",
                "export GAZEBO_PLUGIN_PATH=/opt/gazebo/plugins",
                "export LD_LIBRARY_PATH=/opt/gazebo/lib",
            ]
        ),
        encoding="utf-8",
    )
    setup_path.chmod(0o755)
    return setup_path


def run_bash(command: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    test_env = os.environ.copy()
    if env:
        test_env.update(env)
    return subprocess.run(
        ["bash", "-lc", f"source '{SCRIPT_PATH}' && {command}"],
        capture_output=True,
        text=True,
        env=test_env,
        check=False,
    )


def test_resolve_gazebo_gui_env_preserves_system_resources(tmp_path: Path) -> None:
    setup_path = write_fake_gazebo_setup(tmp_path)
    custom_root = tmp_path / "custom-gazebo"
    custom_models = custom_root / "models"
    px4_build = tmp_path / "px4-build"
    px4_models = tmp_path / "px4-models"

    custom_models.mkdir(parents=True)
    px4_build.mkdir()
    px4_models.mkdir()

    result = run_bash(
        "resolve_gazebo_gui_env",
        env={
            "GAZEBO_SETUP_SH_VALUE": str(setup_path),
            "CUSTOM_GAZEBO_ROOT": str(custom_root),
            "CUSTOM_GAZEBO_MODEL_DIR": str(custom_models),
            "PX4_GAZEBO_BUILD_DIR": str(px4_build),
            "PX4_GAZEBO_MODEL_DIR": str(px4_models),
        },
    )

    assert result.returncode == 0, result.stderr
    assert (
        f"GAZEBO_RESOURCE_PATH={custom_root}:/opt/gazebo/share:/existing/resources"
        in result.stdout
    )
    assert (
        f"GAZEBO_MODEL_PATH={custom_models}:{px4_models}:/opt/gazebo/models"
        in result.stdout
    )
    assert f"GAZEBO_PLUGIN_PATH={px4_build}:/opt/gazebo/plugins" in result.stdout
    assert f"LD_LIBRARY_PATH={px4_build}:/opt/gazebo/lib" in result.stdout
