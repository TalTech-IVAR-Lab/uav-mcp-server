#!/usr/bin/env python3
"""Resolve GUI session environment variables for the current user.

This helps launcher scripts start Gazebo GUI components from an SSH shell by
discovering DISPLAY/XAUTHORITY values from an already running desktop session.
"""

from __future__ import annotations

import glob
import os
import sys
from collections.abc import Iterable


ENV_KEYS = ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR")


def parse_environ_blob(blob: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in blob.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        values[key.decode("utf-8", errors="ignore")] = value.decode(
            "utf-8",
            errors="ignore",
        )
    return values


def iter_process_envs(proc_root: str = "/proc") -> Iterable[tuple[int, int, dict[str, str]]]:
    for environ_path in glob.glob(os.path.join(proc_root, "[0-9]*", "environ")):
        try:
            pid = int(environ_path.split(os.sep)[-2])
            stat = os.stat(environ_path)
            with open(environ_path, "rb") as handle:
                env = parse_environ_blob(handle.read())
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError, OSError):
            continue
        yield pid, stat.st_uid, env


def score_candidate(env: dict[str, str], *, pid: int) -> tuple[int, int, int, int, int]:
    xauthority = env.get("XAUTHORITY", "")
    runtime_dir = env.get("XDG_RUNTIME_DIR", "")
    return (
        int(bool(xauthority) and os.path.exists(xauthority)),
        int(bool(runtime_dir) and os.path.isdir(runtime_dir)),
        int(bool(env.get("WAYLAND_DISPLAY"))),
        int(env.get("DISPLAY", "").startswith(":")),
        -pid,
    )


def choose_desktop_session_env(
    process_envs: Iterable[tuple[int, int, dict[str, str]]],
    *,
    uid: int,
) -> dict[str, str] | None:
    best_env: dict[str, str] | None = None
    best_score: tuple[int, int, int, int, int] | None = None

    for pid, proc_uid, env in process_envs:
        if proc_uid != uid or not env.get("DISPLAY"):
            continue

        candidate = {key: env[key] for key in ENV_KEYS if env.get(key)}
        score = score_candidate(candidate, pid=pid)

        if best_score is None or score > best_score:
            best_env = candidate
            best_score = score

    return best_env


def main() -> int:
    resolved = choose_desktop_session_env(iter_process_envs(), uid=os.getuid())
    if resolved is None:
        return 1

    for key in ENV_KEYS:
        value = resolved.get(key)
        if value:
            print(f"{key}={value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
