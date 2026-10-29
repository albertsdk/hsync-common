"""Tests for hsync_common.logger."""

import logging
import os
from datetime import UTC, datetime, timedelta, timezone

import pytest

from hsync_common.logger import (
    DEFAULT_LOG_COMPRESSION,
    DEFAULT_LOG_RETENTION,
    DEFAULT_LOG_ROTATION,
    LEVEL_STYLES,
    LOG_LEVELS,
    LOG_LINE_RE,
    BaseInterceptHandler,
    build_record_formatter,
    format_log_line,
    get_rotation_config,
)


class TestLevelStyles:
    def test_all_standard_levels_present(self):
        for level in ("DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
            assert level in LEVEL_STYLES, f"{level} missing from LEVEL_STYLES"

    def test_each_entry_is_tuple_of_two_strings(self):
        for level, style in LEVEL_STYLES.items():
            assert isinstance(style, tuple), f"{level} style is not a tuple"
            assert len(style) == 2, f"{level} style tuple should have 2 elements"
            assert all(isinstance(s, str) for s in style)

    def test_info_has_empty_tags(self):
        # INFO should have no markup tags (plain text)
        assert LEVEL_STYLES["INFO"] == ("", "")

    def test_error_has_red_tags(self):
        open_tag, close_tag = LEVEL_STYLES["ERROR"]
        assert "red" in open_tag

    def test_critical_has_bold_red(self):
        open_tag, _ = LEVEL_STYLES["CRITICAL"]
        assert "bold" in open_tag
        assert "red" in open_tag


class TestRotationDefaults:
    def test_rotation_is_string(self):
        assert isinstance(DEFAULT_LOG_ROTATION, str)

    def test_retention_is_string(self):
        assert isinstance(DEFAULT_LOG_RETENTION, str)

    def test_compression_is_string(self):
        assert isinstance(DEFAULT_LOG_COMPRESSION, str)

    def test_rotation_mentions_mb(self):
        assert "MB" in DEFAULT_LOG_ROTATION

    def test_retention_mentions_days(self):
        assert "days" in DEFAULT_LOG_RETENTION

    def test_compression_is_xz(self):
        # Upgraded from gz to xz for better compression ratio (~30-40 %)
        assert DEFAULT_LOG_COMPRESSION == "xz"


class TestGetRotationConfig:
    def test_returns_dict(self):
        cfg = get_rotation_config()
        assert isinstance(cfg, dict)

    def test_has_required_keys(self):
        cfg = get_rotation_config()
        assert "rotation" in cfg
        assert "retention" in cfg
        assert "compression" in cfg

    def test_defaults_when_no_env(self, monkeypatch):
        monkeypatch.delenv("HSYNC_LOG_ROTATION", raising=False)
        monkeypatch.delenv("HSYNC_LOG_RETENTION", raising=False)
        monkeypatch.delenv("HSYNC_LOG_COMPRESSION", raising=False)
        cfg = get_rotation_config()
        assert cfg["rotation"] == DEFAULT_LOG_ROTATION
        assert cfg["retention"] == DEFAULT_LOG_RETENTION
        assert cfg["compression"] == DEFAULT_LOG_COMPRESSION

    def test_env_overrides_defaults(self, monkeypatch):
        monkeypatch.setenv("HSYNC_LOG_ROTATION", "50 MB")
        monkeypatch.setenv("HSYNC_LOG_RETENTION", "30 days")
        monkeypatch.setenv("HSYNC_LOG_COMPRESSION", "bz2")
        cfg = get_rotation_config()
        assert cfg["rotation"] == "50 MB"
        assert cfg["retention"] == "30 days"
        assert cfg["compression"] == "bz2"


class TestBaseInterceptHandler:
    def test_is_logging_handler(self):
        h = BaseInterceptHandler()
        assert isinstance(h, logging.Handler)

    def test_emit_plain_message(self, monkeypatch):
        """emit() should forward messages to loguru with correct level and message."""
        from unittest.mock import MagicMock

        from hsync_common import logger as logger_module

        h = BaseInterceptHandler()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )

        mock_log = MagicMock()
        mock_opt = MagicMock()
        mock_opt.log = mock_log
        monkeypatch.setattr(logger_module.logger, "opt", lambda **kw: mock_opt)

        h.emit(record)

        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == "INFO"
        assert mock_log.call_args[0][1] == "hello"

    def test_emit_with_escape_markup(self, monkeypatch):
        """emit() with escape_markup=True must escape loguru markup in the message."""
        from unittest.mock import MagicMock

        from hsync_common import logger as logger_module

        h = BaseInterceptHandler(escape_markup=True)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg='{"key": "value"} <locals>',
            args=(),
            exc_info=None,
        )

        mock_log = MagicMock()
        mock_opt = MagicMock()
        mock_opt.log = mock_log
        monkeypatch.setattr(logger_module.logger, "opt", lambda **kw: mock_opt)

        h.emit(record)

        # The message must have curly braces doubled and angle brackets escaped
        logged_msg = mock_log.call_args[0][1]
        assert logged_msg == r'{{"key": "value"}} \<locals>'

    def test_emit_unknown_level_falls_back_to_levelno(self, monkeypatch):
        """An unmapped levelname must fall back to the numeric level (no raise)."""
        from unittest.mock import MagicMock

        from hsync_common import logger as logger_module

        h = BaseInterceptHandler()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="weird",
            args=(),
            exc_info=None,
        )
        record.levelname = "NOTALEVEL"

        mock_log = MagicMock()
        mock_opt = MagicMock()
        mock_opt.log = mock_log
        monkeypatch.setattr(logger_module.logger, "opt", lambda **kw: mock_opt)

        h.emit(record)

        # Fallback: numeric level (20 for INFO) is used instead of the string name
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == logging.INFO
        assert mock_log.call_args[0][1] == "weird"

    def test_emit_invokes_bind_extra(self):
        """bind_extra callable is invoked and its mapping bound before logging."""
        calls = []

        def _extra():
            calls.append(True)
            return {"request_id": "abc"}

        h = BaseInterceptHandler(bind_extra=_extra)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="bound",
            args=(),
            exc_info=None,
        )
        h.emit(record)
        assert calls == [True]


class TestLogLineGrammar:
    """The canonical ``<ts> - [pid] [fields] LEVEL: msg`` shape every producer writes."""

    _STAMP = datetime(2026, 10, 29, 10, 46, 23, 187000, tzinfo=UTC)

    @staticmethod
    def _record(level: str = "INFO", message: str = "hello", client_id: str = "cid1"):
        """Build a loguru-shaped record mapping (what a sink formatter receives)."""
        from types import SimpleNamespace

        return {
            "time": TestLogLineGrammar._STAMP,
            "level": SimpleNamespace(name=level),
            "message": message,
            "process": SimpleNamespace(id=4242),
            "extra": {"client_id": client_id},
        }

    def test_client_renderer_and_grammar_agree(self):
        # Anti-drift: what the loguru sinks emit must be parseable by LOG_LINE_RE.
        formatter = build_record_formatter(colored=False, extra_fields=("client_id",))

        line = formatter(self._record(message="[READY] ready")).rstrip("\n")

        assert line == "2026-10-29T10:46:23.187Z - [4242] [cid1] INFO: [READY] ready"
        parsed = LOG_LINE_RE.match(line)
        assert parsed is not None
        assert parsed.group("level") == "INFO"
        assert parsed.group("fields") == "[4242] [cid1] "
        assert parsed.group("message") == "[READY] ready"

    def test_desktop_line_has_the_client_layout(self):
        line = format_log_line(
            "WARNING", "Peer not trusted.", fields=("desktop",), pid=7, timestamp=self._STAMP
        )

        assert line == "2026-10-29T10:46:23.187Z - [7] [desktop] WARNING: Peer not trusted."
        parsed = LOG_LINE_RE.match(line)
        assert parsed is not None
        assert parsed.group("level") == "WARNING"
        assert parsed.group("message") == "Peer not trusted."

    def test_several_fields_keep_their_order(self):
        line = format_log_line(
            "INFO", "m", fields=("desktop", "req-1"), pid=1, timestamp=self._STAMP
        )

        assert line == "2026-10-29T10:46:23.187Z - [1] [desktop] [req-1] INFO: m"

    def test_aware_timestamp_is_rendered_in_utc(self):
        local = self._STAMP.astimezone(timezone(timedelta(hours=2)))

        line = format_log_line("INFO", "m", pid=1, timestamp=local)

        assert line.startswith("2026-10-29T10:46:23.187Z - ")

    def test_default_timestamp_is_utc_now(self):
        line = format_log_line("INFO", "m", pid=1)

        parsed = LOG_LINE_RE.match(line)
        assert parsed is not None
        stamp = datetime.fromisoformat(parsed.group("timestamp"))
        assert abs((datetime.now(UTC) - stamp).total_seconds()) < 5

    def test_pid_defaults_to_the_current_process(self):
        line = format_log_line("INFO", "m", timestamp=self._STAMP)

        assert line.startswith(f"2026-10-29T10:46:23.187Z - [{os.getpid()}] INFO: m")

    def test_multiline_message_is_one_record(self):
        line = format_log_line("ERROR", 'boom\n{\n  "k": 1\n}', pid=1, timestamp=self._STAMP)

        assert line.endswith('ERROR: boom\n{\n  "k": 1\n}')
        parsed = LOG_LINE_RE.match(line)
        assert parsed is not None
        # The grammar describes the record header; the payload follows as-is.
        assert parsed.group("message") == "boom"

    def test_message_that_starts_with_a_label_is_not_read_as_a_level(self):
        parsed = LOG_LINE_RE.match(
            format_log_line("INFO", "[DELETE] gone.txt", pid=1, timestamp=self._STAMP)
        )

        assert parsed is not None
        assert parsed.group("level") == "INFO"
        assert parsed.group("message") == "[DELETE] gone.txt"

    def test_unknown_level_is_rejected(self):
        with pytest.raises(ValueError, match="unknown log level"):
            format_log_line("NOTICE", "m", pid=1)

    def test_levels_cover_the_shared_palette(self):
        assert tuple(LEVEL_STYLES) == LOG_LEVELS
