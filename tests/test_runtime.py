"""Tests for hsync_common.runtime (container/TTY detection and cgroup limits)."""

import sys

import pytest

from hsync_common import runtime
from hsync_common.runtime import (
    ContainerInfo,
    color_output_enabled,
    detect_container,
    get_cpu_quota_cores,
    get_memory_limit_bytes,
    is_tty_interactive,
    runtime_summary,
)


@pytest.fixture(autouse=True)
def _isolated_probes(monkeypatch, tmp_path):
    """Redirect every probe to non-existent tmp paths and clear marker env vars.

    Guarantees hermetic tests regardless of the environment the suite runs in
    (bare metal, CI runner, or an actual container).
    """
    monkeypatch.delenv("container", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(runtime, "DOCKERENV_PATH", tmp_path / ".dockerenv")
    monkeypatch.setattr(runtime, "CONTAINERENV_PATH", tmp_path / ".containerenv")
    monkeypatch.setattr(runtime, "PROC_1_CGROUP_PATH", tmp_path / "proc_1_cgroup")
    return tmp_path


class _Tty:
    def isatty(self) -> bool:
        return True


class _NotTty:
    def isatty(self) -> bool:
        return False


class TestDetectContainer:
    """Container runtime detection precedence and markers."""

    def test_no_markers_not_container(self):
        info = detect_container()
        assert info == ContainerInfo(False)
        assert info.is_container is False
        assert info.runtime is None
        assert info.method is None

    def test_env_var_names_runtime(self, monkeypatch):
        monkeypatch.setenv("container", "podman")
        info = detect_container()
        assert info.is_container is True
        assert info.runtime == "podman"
        assert info.method == "env:container"

    def test_env_var_empty_is_ignored(self, monkeypatch):
        monkeypatch.setenv("container", "  ")
        assert detect_container().is_container is False

    def test_dockerenv_detects_docker(self, tmp_path):
        (tmp_path / ".dockerenv").touch()
        info = detect_container()
        assert info.is_container is True
        assert info.runtime == "docker"
        assert ".dockerenv" in (info.method or "")

    def test_containerenv_detects_podman(self, tmp_path):
        (tmp_path / ".containerenv").touch()
        info = detect_container()
        assert info.is_container is True
        assert info.runtime == "podman"
        assert ".containerenv" in (info.method or "")

    def test_env_var_beats_marker_files(self, monkeypatch, tmp_path):
        monkeypatch.setenv("container", "gvisor")
        (tmp_path / ".dockerenv").touch()
        assert detect_container().runtime == "gvisor"

    def test_marker_files_beat_cgroup(self, tmp_path):
        (tmp_path / ".dockerenv").touch()
        (tmp_path / "proc_1_cgroup").write_text("0::/kubepods/pod123\n")
        assert detect_container().runtime == "docker"

    @pytest.mark.parametrize(
        ("cgroup_content", "expected"),
        [
            ("0::/kubepods/burstable/podabc\n", "kubernetes"),
            ("0::/docker/0123456789abcdef\n", "docker"),
            ("0::/system.slice/containerd.service\n", "containerd"),
            ("0::/machine.slice/libpod-abc.scope\n", "podman"),
            ("1:name=systemd:/podman/abc\n", "podman"),
            ("0::/DOCKER/uppercase\n", "docker"),  # match is case-insensitive
        ],
    )
    def test_cgroup_markers(self, tmp_path, cgroup_content, expected):
        (tmp_path / "proc_1_cgroup").write_text(cgroup_content)
        info = detect_container()
        assert info.is_container is True
        assert info.runtime == expected

    def test_cgroup_without_markers_not_container(self, tmp_path):
        (tmp_path / "proc_1_cgroup").write_text("0::/init.scope\n")
        assert detect_container().is_container is False

    def test_unreadable_cgroup_is_skipped(self, tmp_path):
        missing = tmp_path / "no_such_file"
        assert runtime._detect_from_cgroup(missing) is None


class TestTtyDetection:
    def test_both_tty_is_interactive(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _Tty())
        monkeypatch.setattr(sys, "stdout", _Tty())
        assert is_tty_interactive() is True

    @pytest.mark.parametrize("stdin_tty", [True, False])
    @pytest.mark.parametrize("stdout_tty", [True, False])
    def test_matrix(self, monkeypatch, stdin_tty, stdout_tty):
        monkeypatch.setattr(sys, "stdin", _Tty() if stdin_tty else _NotTty())
        monkeypatch.setattr(sys, "stdout", _Tty() if stdout_tty else _NotTty())
        assert is_tty_interactive() is (stdin_tty and stdout_tty)

    def test_none_streams_are_not_tty(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", None)
        monkeypatch.setattr(sys, "stdout", None)
        assert is_tty_interactive() is False

    def test_closed_stream_is_not_tty(self, monkeypatch, tmp_path):
        closed = (tmp_path / "f").open("w")
        closed.close()
        monkeypatch.setattr(sys, "stdin", closed)
        monkeypatch.setattr(sys, "stdout", _Tty())
        assert is_tty_interactive() is False


class TestColorOutput:
    def test_tty_enables_colors(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", _Tty())
        assert color_output_enabled() is True

    def test_non_tty_disables_colors(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", _NotTty())
        assert color_output_enabled() is False

    def test_flag_disables_even_on_tty(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", _Tty())
        assert color_output_enabled(no_color=True) is False

    def test_no_color_env_disables(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", _Tty())
        monkeypatch.setenv("NO_COLOR", "1")
        assert color_output_enabled() is False

    def test_no_color_env_empty_is_ignored(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", _Tty())
        monkeypatch.setenv("NO_COLOR", "")
        assert color_output_enabled() is True


class TestMemoryLimit:
    def test_v2_numeric_limit(self, tmp_path):
        (tmp_path / "memory.max").write_text("536870912\n")
        assert get_memory_limit_bytes(tmp_path) == 536870912

    def test_v2_max_is_unlimited(self, tmp_path):
        (tmp_path / "memory.max").write_text("max\n")
        assert get_memory_limit_bytes(tmp_path) is None

    def test_v2_invalid_is_unlimited(self, tmp_path):
        (tmp_path / "memory.max").write_text("not-a-number\n")
        assert get_memory_limit_bytes(tmp_path) is None

    def test_v1_limit_used_when_v2_missing(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "memory.limit_in_bytes").write_text("1073741824\n")
        assert get_memory_limit_bytes(tmp_path) == 1073741824

    def test_v1_sentinel_is_unlimited(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "memory.limit_in_bytes").write_text("9223372036854771712\n")
        assert get_memory_limit_bytes(tmp_path) is None

    def test_v2_takes_precedence_over_v1(self, tmp_path):
        (tmp_path / "memory.max").write_text("268435456\n")
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "memory.limit_in_bytes").write_text("1073741824\n")
        assert get_memory_limit_bytes(tmp_path) == 268435456

    def test_missing_files_mean_unknown(self, tmp_path):
        assert get_memory_limit_bytes(tmp_path) is None


class TestCpuQuota:
    def test_v2_quota(self, tmp_path):
        (tmp_path / "cpu.max").write_text("150000 100000\n")
        assert get_cpu_quota_cores(tmp_path) == pytest.approx(1.5)

    def test_v2_max_is_unbounded(self, tmp_path):
        (tmp_path / "cpu.max").write_text("max 100000\n")
        assert get_cpu_quota_cores(tmp_path) is None

    def test_v2_malformed_is_unknown(self, tmp_path):
        (tmp_path / "cpu.max").write_text("garbage\n")
        assert get_cpu_quota_cores(tmp_path) is None

    def test_v1_quota(self, tmp_path):
        cpu_dir = tmp_path / "cpu"
        cpu_dir.mkdir()
        (cpu_dir / "cpu.cfs_quota_us").write_text("200000\n")
        (cpu_dir / "cpu.cfs_period_us").write_text("100000\n")
        assert get_cpu_quota_cores(tmp_path) == pytest.approx(2.0)

    def test_v1_unlimited_quota(self, tmp_path):
        cpu_dir = tmp_path / "cpu"
        cpu_dir.mkdir()
        (cpu_dir / "cpu.cfs_quota_us").write_text("-1\n")
        (cpu_dir / "cpu.cfs_period_us").write_text("100000\n")
        assert get_cpu_quota_cores(tmp_path) is None

    def test_missing_files_mean_unknown(self, tmp_path):
        assert get_cpu_quota_cores(tmp_path) is None


class TestRuntimeSummary:
    def test_compose_container_line(self, monkeypatch, tmp_path):
        """The summary must reflect real probe OUTPUTS, not just format them.

        The memory/CPU probes run against real cgroup files (``CGROUP_ROOT``
        is redirected to *tmp_path*, so the real parsing logic executes on
        hermetic inputs): only the environment-only feed (container marker,
        TTY) is stubbed. A summary function that ignored the probes and
        hardcoded values would fail here.
        """
        (tmp_path / "memory.max").write_text("536870912\n")
        (tmp_path / "cpu.max").write_text("150000 100000\n")
        # Rebinding the probes keeps the REAL cgroup parsing logic on the
        # real files in tmp_path (default parameter values were bound at
        # import time and ignore CGROUP_ROOT patches); the environment-only
        # feed (container marker, TTY) is stubbed.
        monkeypatch.setattr(
            runtime, "get_memory_limit_bytes", lambda: get_memory_limit_bytes(tmp_path)
        )
        monkeypatch.setattr(runtime, "get_cpu_quota_cores", lambda: get_cpu_quota_cores(tmp_path))
        monkeypatch.setattr(
            runtime, "detect_container", lambda: ContainerInfo(True, "docker", "/.dockerenv")
        )
        monkeypatch.setattr(sys, "stdin", _NotTty())
        monkeypatch.setattr(sys, "stdout", _NotTty())

        summary = runtime_summary()

        assert "container=docker (via /.dockerenv)" in summary
        # 536870912 B == 512 MiB -> format_bytes renders "512.0MB" (compact form).
        assert "mem_limit=512.0MB" in summary
        assert "cpu_quota=1.5 cores" in summary
        assert "tty=no" in summary

    def test_compose_host_line(self, monkeypatch, tmp_path):
        """Absent cgroup files under the redirected probes surface as 'unlimited'."""
        monkeypatch.setattr(
            runtime, "get_memory_limit_bytes", lambda: get_memory_limit_bytes(tmp_path)
        )
        monkeypatch.setattr(runtime, "get_cpu_quota_cores", lambda: get_cpu_quota_cores(tmp_path))
        monkeypatch.setattr(runtime, "detect_container", lambda: ContainerInfo(False))
        monkeypatch.setattr(sys, "stdin", _Tty())
        monkeypatch.setattr(sys, "stdout", _Tty())

        summary = runtime_summary()

        assert "container=no" in summary
        assert "mem_limit=unlimited" in summary
        assert "cpu_quota=unlimited" in summary
        assert "tty=yes" in summary

    def test_real_probes_do_not_raise(self):
        """Against the real environment the summary must always succeed."""
        assert runtime_summary().startswith("Runtime environment: ")
