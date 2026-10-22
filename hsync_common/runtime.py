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
from enum import StrEnum
from pathlib import Path
from typing import IO, Final

from hsync_common.format import format_bytes


class ColorMode(StrEnum):
    """How colored log output is decided (``--color`` on the CLIs).

    Consumers: ``hsync-client`` and ``hsync-server`` (``color_output_enabled``)
    and ``hsync-desktop``, which forces ``always`` over the subprocess pipe so
    the in-app log panel can render the client's palette.
    """

    AUTO = "auto"  # colors only on a TTY, honouring NO_COLOR
    ALWAYS = "always"  # force colors, even when stdout is a pipe
    NEVER = "never"  # no colors


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

# The process's own cgroup membership (nested under the mount root for a systemd
# service or a non-namespaced container) and the kernel's memory statistics.
PROC_SELF_CGROUP_PATH: Final[Path] = Path("/proc/self/cgroup")
MEMINFO_PATH: Final[Path] = Path("/proc/meminfo")


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


def color_output_enabled(mode: ColorMode | str = ColorMode.AUTO) -> bool:
    """Whether colored log output should be emitted on stdout.

    ``auto`` follows the terminal (colors need a TTY) and honours the standard
    ``NO_COLOR`` environment variable (https://no-color.org): any non-empty value
    opts out. ``always`` forces colors even when stdout is a pipe — the Desktop
    asks for it so the in-app log panel can render the client's own palette —
    and is an explicit request, so it wins over ``NO_COLOR``. ``never`` disables
    colors. An unknown mode is rejected instead of falling back silently.
    """
    try:
        resolved = ColorMode(mode)
    except ValueError:
        raise ValueError(f"Unknown color mode: {mode!r}") from None
    if resolved is ColorMode.NEVER:
        return False
    if resolved is ColorMode.ALWAYS:
        return True
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


def _read_memory_limit_v1_dir(mem_dir: Path) -> int | None:
    """cgroup v1 memory limit in *mem_dir*; None when unlimited (sentinel)/unknown."""
    value = _read_int_file(mem_dir / "memory.limit_in_bytes")
    if value is None or value <= 0 or value >= _V1_UNLIMITED_THRESHOLD:
        return None
    return value


def _read_memory_limit_v1(root: Path) -> int | None:
    """cgroup v1 memory limit at the mount *root*; None when unlimited/unknown."""
    return _read_memory_limit_v1_dir(root / "memory")


def _process_cgroup_memory_limit(cgroup_root: Path, proc_self_cgroup: Path) -> int | None:
    """Memory limit of the process's *own* cgroup, or None when not capped.

    A systemd service and a container with a non-namespaced cgroup view run in a
    nested cgroup: the mount-root ``memory.max`` is often ``max`` while the
    enforced limit lives under the service's slice. The membership line names the
    hierarchy (``0::/path`` for cgroup v2, ``N:memory:/path`` for v1), so the
    candidate is resolved under ``cgroup_root`` and read with the matching parser.
    """
    raw = _read_cgroup_text(proc_self_cgroup)
    if raw is None:
        return None
    for line in raw.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            continue
        controllers, path = parts[1], parts[2].strip("/")
        if controllers == "":
            base = cgroup_root / path if path else cgroup_root
            limit = _read_memory_limit_v2(base)
        elif "memory" in controllers.split(","):
            base = cgroup_root / "memory" / path if path else cgroup_root / "memory"
            limit = _read_memory_limit_v1_dir(base)
        else:
            continue
        if limit is not None:
            return limit
    return None


def get_memory_limit_bytes(
    cgroup_root: Path = CGROUP_ROOT,
    proc_self_cgroup: Path = PROC_SELF_CGROUP_PATH,
) -> int | None:
    """Effective RAM limit for this process in bytes.

    The process's own (possibly nested) cgroup is consulted first, then the
    mount root: cgroup v2 is read via ``memory.max``, v1 via
    ``memory.limit_in_bytes``. Returns None when no limit is set or none can be
    determined.

    Consumers: hsync-client (``_get_optimal_workers`` bounds the parallel
    local-file scan/hash pool by this limit, alongside the CPU quota),
    hsync-bootnode (``resources.py`` sizes its in-memory ceilings),
    ``runtime_summary``.
    """
    limit = _process_cgroup_memory_limit(cgroup_root, proc_self_cgroup)
    if limit is not None:
        return limit
    limit = _read_memory_limit_v2(cgroup_root)
    if limit is not None:
        return limit
    return _read_memory_limit_v1(cgroup_root)


def total_memory_bytes() -> int | None:
    """Physical RAM visible to the process in bytes, or None when unknown."""
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError, AttributeError):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return pages * page_size


def available_memory_bytes(
    meminfo_path: Path = MEMINFO_PATH,
    cgroup_root: Path = CGROUP_ROOT,
    proc_self_cgroup: Path = PROC_SELF_CGROUP_PATH,
) -> int | None:
    """Currently available RAM in bytes, capped by the cgroup limit.

    ``MemAvailable`` is preferred when readable; the cgroup limit caps the
    result so a container cannot over-commit the host. Returns None when neither
    the statistics nor a limit can be read.
    """
    limit = get_memory_limit_bytes(cgroup_root, proc_self_cgroup)
    raw = _read_cgroup_text(meminfo_path)
    if raw is not None:
        for line in raw.splitlines():
            if not line.startswith("MemAvailable:"):
                continue
            try:
                available = int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                break
            if available > 0:
                return min(available, limit) if limit is not None else available
            break
    return limit


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
