from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sitl_profile.sh"


def write_fake_pkg_config(
    tmp_path: Path,
    *,
    list_all_output: str = "",
    gazebo_exists: bool = False,
) -> Path:
    script_path = tmp_path / "pkg-config"
    script_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -eu",
                'if [ "${1:-}" = "--list-all" ]; then',
                f"  cat <<'EOF'\n{list_all_output}\nEOF",
                "  exit 0",
                "fi",
                'if [ "${1:-}" = "--exists" ] && [ "${2:-}" = "gazebo" ]; then',
                f"  exit {0 if gazebo_exists else 1}",
                "fi",
                "exit 1",
            ]
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path


def run_bash(command: str, *, tmp_path: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    test_env = os.environ.copy()
    test_env["PATH"] = f"{tmp_path}:{test_env['PATH']}"
    if env:
        test_env.update(env)
    return subprocess.run(
        ["bash", "-lc", f"source '{SCRIPT_PATH}' && {command}"],
        capture_output=True,
        text=True,
        env=test_env,
        check=False,
    )


def test_resolve_px4_model_prefers_harmonic_when_available(tmp_path: Path) -> None:
    write_fake_pkg_config(
        tmp_path,
        list_all_output="\n".join(["gz-plugin", "gz-sensors", "gz-sim", "gz-transport"]),
        gazebo_exists=True,
    )

    result = run_bash('sitl_resolve_px4_model ""', tmp_path=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gz_x500"


def test_resolve_px4_model_falls_back_to_gazebo_classic(tmp_path: Path) -> None:
    write_fake_pkg_config(tmp_path, gazebo_exists=True)

    result = run_bash('sitl_resolve_px4_model ""', tmp_path=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gazebo-classic"


def test_make_target_uses_camera_airframe_for_gazebo_classic(tmp_path: Path) -> None:
    write_fake_pkg_config(tmp_path, gazebo_exists=True)

    result = run_bash('sitl_make_target "gazebo-classic"', tmp_path=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gazebo-classic_iris_fpv_cam"


def test_make_target_preserves_explicit_classic_camera_model(tmp_path: Path) -> None:
    write_fake_pkg_config(tmp_path, gazebo_exists=True)

    result = run_bash('sitl_make_target "gazebo-classic_iris_fpv_cam"', tmp_path=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gazebo-classic_iris_fpv_cam"


def test_resolve_px4_model_rejects_unsupported_explicit_model(tmp_path: Path) -> None:
    write_fake_pkg_config(tmp_path, gazebo_exists=True)

    result = run_bash('sitl_resolve_px4_model "gz_x500_depth"', tmp_path=tmp_path)

    assert result.returncode != 0
    assert "Supported PX4_MODEL values: gz_x500 gazebo-classic gazebo-classic_iris_fpv_cam" in result.stderr


def test_resolve_px4_model_rejects_harmonic_without_packages(tmp_path: Path) -> None:
    write_fake_pkg_config(tmp_path, gazebo_exists=True)

    result = run_bash('sitl_resolve_px4_model "gz_x500"', tmp_path=tmp_path)

    assert result.returncode != 0
    assert "requires the Gazebo Harmonic development packages" in result.stderr
