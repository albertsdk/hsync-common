"""Tests for hsync_common.logger."""

import logging

from hsync_common.logger import (
    DEFAULT_LOG_COMPRESSION,
    DEFAULT_LOG_RETENTION,
    DEFAULT_LOG_ROTATION,
    LEVEL_STYLES,
    BaseInterceptHandler,
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
        # O3: upgraded from gz to xz for better compression ratio (~30-40 %)
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

    def test_default_escape_braces_false(self):
        h = BaseInterceptHandler()
        assert h._escape_braces is False

    def test_escape_braces_true(self):
        h = BaseInterceptHandler(escape_braces=True)
        assert h._escape_braces is True

    def test_bind_extra_none_by_default(self):
        h = BaseInterceptHandler()
        assert h._bind_extra is None

    def test_bind_extra_callable(self):
        def fn():
            return {"request_id": "abc"}

        h = BaseInterceptHandler(bind_extra=fn)
        assert h._bind_extra is fn

    def test_emit_plain_message(self):
        """emit() should forward messages to loguru without raising."""
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
        # Should not raise
        h.emit(record)

    def test_emit_with_escape_braces(self):
        h = BaseInterceptHandler(escape_braces=True)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg='{"key": "value"}',
            args=(),
            exc_info=None,
        )
        h.emit(record)

    def test_emit_unknown_level_falls_back_to_levelno(self):
        """An unmapped levelname must fall back to the numeric level (no raise)."""
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
        h.emit(record)

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
