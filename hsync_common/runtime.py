# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Runtime environment detection shared across HSYNC projects.

Detects whether the process runs inside a container (Docker, Podman,
Kubernetes, containerd), whether stdin/stdout are attached to an
interactive terminal, and the effective cgroup resource limits (memory
and CPU quota) so that consumers can adapt their behaviour: disable
colored output, refuse interactive prompts when no operator is present,
warn about container networking pitfalls, and log the available
resources at startup.

All probes are read-only, never raise on missing/unreadable files, and
are designed to be called once at process startup.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

from hsync_common.format import format_bytes

# =============================================================================
# Probe locations
# =============================================================================
# Module-level constants (not function defaults) so tests can monkeypatch them.

# Created by Docker at container start (also by some compat runtimes).
DOCKERENV_PATH: Final[Path] = Path("/.dockerenv")

# Created by Podman (and other OCI runtimes) at container start.
CONTAINERENV_PATH: Final[Path] = Path("/run/.containerenv")

# cgroup membership of PID 1: inside a container the paths carry the
# runtime marker (``docker/<id>``, ``kubepods/...``, ``libpod-<id>`` …).
PROC_1_CGROUP_PATH: Final[Path] = Path("/proc/1/cgroup")

# Unified cgroup v2 mount; v1 controllers live in subdirectories below it.
CGROUP_ROOT: Final[Path] = Path("/sys/fs/cgroup")

# Environment variable set by Podman (``container=podman``) and by several
# OCI base images; its value names the runtime directly.
CONTAINER_ENV_VAR: Final[str] = "container"

# Standard opt-out for colored output, see https://no-color.org.
NO_COLOR_ENV_VAR: Final[str] = "NO_COLOR"

# Substrings marking a containerized PID 1 in /proc/1/cgroup, mapped to the
# runtime name. Order matters: check the most specific markers first.
_CGROUP_RUNTIME_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("kubepods", "kubernetes"),
    ("containerd", "containerd"),
    ("libpod", "podman"),
    ("podman", "podman"),
    ("docker", "docker"),
)

# cgroup v1 reports an uncapped memory limit as a huge sentinel
# (0x7FFFFFFFFFFFF000 on x86_64); anything at/above 2^62 means "unlimited".
_V1_UNLIMITED_THRESHOLD: Final[int] = 1 << 62


# =============================================================================
# Container detection
# =============================================================================


@dataclass(frozen=True)
class ContainerInfo:
    """Result of container runtime detection.

    Attributes:
        is_container: True when a container runtime was detected.
        runtime: Runtime name (``docker``, ``podman``, ``kubernetes``,
            ``containerd``) or None when not containerized.
        method: Human-readable probe that produced the verdict
            (e.g. ``"/.dockerenv"``), None when not containerized.
    """

    is_container: bool
    runtime: str | None = None
    method: str | None = None


def _detect_from_cgroup(proc_cgroup: Path) -> ContainerInfo | None:
    """Detect the runtime from PID 1 cgroup membership markers."""
    try:
        content = proc_cgroup.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return None
    for marker, runtime in _CGROUP_RUNTIME_MARKERS:
        if marker in content:
            return ContainerInfo(True, runtime, f"{proc_cgroup} ({marker})")
    return None


def detect_container() -> ContainerInfo:
    """Detect whether the process runs inside a container.

    Probes, in order of precedence:

    1. the ``container`` environment variable (set by Podman and several
       OCI base images; its value names the runtime);
    2. ``/.dockerenv`` (Docker);
    3. ``/run/.containerenv`` (Podman);
    4. runtime markers in ``/proc/1/cgroup``.

    Never raises: unreadable probes are simply skipped.
    """
    env_runtime = os.environ.get(CONTAINER_ENV_VAR, "").strip()
    if env_runtime:
        return ContainerInfo(True, env_runtime, f"env:{CONTAINER_ENV_VAR}")

    if DOCKERENV_PATH.exists():
        return ContainerInfo(True, "docker", str(DOCKERENV_PATH))

    if CONTAINERENV_PATH.exists():
        return ContainerInfo(True, "podman", str(CONTAINERENV_PATH))

    cgroup_info = _detect_from_cgroup(PROC_1_CGROUP_PATH)
    if cgroup_info is not None:
        return cgroup_info

    return ContainerInfo(False)


# =============================================================================
# Terminal / color detection
# =============================================================================


def _isatty(stream: IO[str] | None) -> bool:
    """Safe ``isatty``: False for None, closed or non-file streams."""
    if stream is None:
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def is_tty_interactive() -> bool:
    """True when both stdin and stdout are attached to a terminal.

    False inside containers started without ``-t``, under systemd units,
    cron jobs, pipes and redirects — i.e. whenever no operator can answer
    an interactive prompt.
    """
    return _isatty(sys.stdin) and _isatty(sys.stdout)


def color_output_enabled(*, no_color: bool = False) -> bool:
    """Whether colored log output should be emitted on stdout.

    Colors require an interactive terminal and are disabled by the
    ``--no-color`` flag or by the standard ``NO_COLOR`` environment
    variable (https://no-color.org): any non-empty value opts out.
    """
    if no_color:
        return False
    if os.environ.get(NO_COLOR_ENV_VAR):
        return False
    return _isatty(sys.stdout)


# =============================================================================
# cgroup resource limits
# =============================================================================


def _read_cgroup_text(path: Path) -> str | None:
    """Read a cgroup pseudo-file as ASCII, returning None on any I/O failure."""
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None


def _read_int_file(path: Path) -> int | None:
    """Read an integer from a cgroup pseudo-file; None on any failure."""
    raw = _read_cgroup_text(path)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _read_memory_limit_v2(root: Path) -> int | None:
    """cgroup v2 memory limit (``memory.max``); None when ``max``/unknown."""
    raw = _read_cgroup_text(root / "memory.max")
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _read_memory_limit_v1(root: Path) -> int | None:
    """cgroup v1 memory limit; None when unlimited (sentinel)/unknown."""
    value = _read_int_file(root / "memory" / "memory.limit_in_bytes")
    if value is None or value <= 0 or value >= _V1_UNLIMITED_THRESHOLD:
        return None
    return value


def get_memory_limit_bytes(cgroup_root: Path = CGROUP_ROOT) -> int | None:
    """Effective RAM limit for this process in bytes.

    Reads cgroup v2 first, then falls back to v1. Returns None when no
    limit is set or the limit cannot be determined.

    Consumers: hsync-client (``_get_optimal_workers`` bounds the parallel
    local-file scan/hash pool by this limit, alongside the CPU quota).
    """
    limit = _read_memory_limit_v2(cgroup_root)
    if limit is not None:
        return limit
    return _read_memory_limit_v1(cgroup_root)


def _read_cpu_quota_v2(root: Path) -> float | None:
    """cgroup v2 CPU quota in cores (``cpu.max``); None when ``max``/unknown."""
    try:
        fields = (root / "cpu.max").read_text(encoding="ascii", errors="replace").split()
    except OSError:
        return None
    if len(fields) != 2 or fields[0] == "max":
        return None
    try:
        quota, period = int(fields[0]), int(fields[1])
    except ValueError:
        return None
    if quota <= 0 or period <= 0:
        return None
    return quota / period


def _read_cpu_quota_v1(root: Path) -> float | None:
    """cgroup v1 CPU quota in cores (cfs quota/period); None when unbounded."""
    quota = _read_int_file(root / "cpu" / "cpu.cfs_quota_us")
    period = _read_int_file(root / "cpu" / "cpu.cfs_period_us")
    if quota is None or period is None or quota <= 0 or period <= 0:
        # quota -1 means "no limit" in cgroup v1
        return None
    return quota / period


def get_cpu_quota_cores(cgroup_root: Path = CGROUP_ROOT) -> float | None:
    """Effective CPU quota in cores (e.g. ``1.5``).

    Reads cgroup v2 first, then falls back to v1. Returns None when no
    quota is set or it cannot be determined. Unlike ``os.cpu_count()``,
    this reflects container limits instead of host hardware.
    """
    quota = _read_cpu_quota_v2(cgroup_root)
    if quota is not None:
        return quota
    return _read_cpu_quota_v1(cgroup_root)


# =============================================================================
# Startup summary
# =============================================================================


def runtime_summary() -> str:
    """One-line human-readable summary of the runtime environment.

    Intended for startup logs, e.g.::

        Runtime environment: container=docker (via /.dockerenv), mem_limit=512.0 MB, cpu_quota=1.5 cores, tty=no
    """
    info = detect_container()
    container = f"{info.runtime or 'unknown'} (via {info.method})" if info.is_container else "no"

    mem_limit = get_memory_limit_bytes()
    mem_str = format_bytes(mem_limit) if mem_limit is not None else "unlimited"

    cpu_quota = get_cpu_quota_cores()
    cpu_str = f"{cpu_quota:.3g} cores" if cpu_quota is not None else "unlimited"

    tty = "yes" if is_tty_interactive() else "no"

    return (
        f"Runtime environment: container={container}, "
        f"mem_limit={mem_str}, cpu_quota={cpu_str}, tty={tty}"
    )
