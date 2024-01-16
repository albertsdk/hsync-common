# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared logging primitives used by HSYNC projects.

Provides the constants, rotation defaults and a configurable
:class:`BaseInterceptHandler` that bridges stdlib ``logging`` to
loguru. Project-specific format functions and ``setup_logging``
wrappers live in the consumer projects.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from loguru import logger

from hsync_common.text import escape_loguru_braces

# =============================================================================
# Color tags shared across projects
# =============================================================================

# Following industry-standard log coloring conventions:
# - Timestamps: dim/muted to reduce visual noise
# - DEBUG: gray/dim - low priority, verbose information
# - INFO: default/white - normal operational messages
# - SUCCESS: green - positive outcomes
# - WARNING: yellow - attention needed but not critical
# - ERROR: red - failures that need investigation
# - CRITICAL: bold red - severe issues requiring immediate action
LEVEL_STYLES: dict[str, tuple[str, str]] = {
    "DEBUG": ("<dim>", "</dim>"),
    "INFO": ("", ""),
    "SUCCESS": ("<green>", "</green>"),
    "WARNING": ("<yellow>", "</yellow>"),
    "ERROR": ("<red>", "</red>"),
    "CRITICAL": ("<bold><red>", "</red></bold>"),
}

# =============================================================================
# Log Rotation Defaults
# =============================================================================

# Default rotation: rotate when file reaches 10 MB
DEFAULT_LOG_ROTATION: Final[str] = "10 MB"

# Default retention: keep logs for 7 days
DEFAULT_LOG_RETENTION: Final[str] = "7 days"

# Default compression: xz (LZMA2) for better space efficiency than gz.
# xz achieves ~30-40 % better compression ratio at the cost of slightly more
# CPU during rotation — acceptable since rotation is infrequent.
# Both "xz" and "gz" are natively supported by loguru and Python's stdlib.
DEFAULT_LOG_COMPRESSION: Final[str] = "xz"


def get_rotation_config() -> dict[str, str | None]:
    """
    Read log rotation configuration from environment variables.

    Returns a dict suitable for passing to ``logger.add(...)``::

        rotation, retention, compression
    """
    return {
        "rotation": os.environ.get("HSYNC_LOG_ROTATION", DEFAULT_LOG_ROTATION),
        "retention": os.environ.get("HSYNC_LOG_RETENTION", DEFAULT_LOG_RETENTION),
        "compression": os.environ.get("HSYNC_LOG_COMPRESSION", DEFAULT_LOG_COMPRESSION),
    }


# =============================================================================
# Stdlib logging -> loguru bridge
# =============================================================================


class BaseInterceptHandler(logging.Handler):
    """
    Bridge stdlib :mod:`logging` records to loguru.

    Subclasses (or callers) can customize behavior via constructor flags:

    - ``escape_braces``: when ``True``, replace ``{`` and ``}`` in the log
      message with ``{{`` / ``}}`` to prevent loguru from interpreting them
      as format placeholders. Useful when third-party libraries log JSON
      payloads or templated strings.
    - ``bind_extra``: optional zero-argument callable returning a mapping of
      extra fields to bind to the loguru logger before emitting (e.g. a
      per-request correlation id).
    """

    def __init__(
        self,
        *,
        escape_braces: bool = False,
        bind_extra: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__()
        self._escape_braces = escape_braces
        self._bind_extra = bind_extra

    def emit(self, record: logging.LogRecord) -> None:
        """Redirect a stdlib log record to loguru."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the logged message originated
        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        message = record.getMessage()
        if self._escape_braces:
            message = escape_loguru_braces(message)

        target = logger
        if self._bind_extra is not None:
            target = logger.bind(**self._bind_extra())

        target.opt(depth=depth, exception=record.exc_info).log(level, message)


# =============================================================================
# Record formatting
# =============================================================================


def format_timestamp(record: Mapping[str, Any]) -> str:
    """Return an ISO-8601 millisecond timestamp with a trailing ``Z``."""
    return record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_record_formatter(
    *,
    colored: bool,
    extra_fields: Iterable[str] = (),
    message_transform: Callable[[Mapping[str, Any], str], str] | None = None,
) -> Callable[[Mapping[str, Any]], str]:
    """Build a loguru format function shared across projects.

    The produced function renders records as::

        <timestamp> - [<pid>][ <extra fields...>] <LEVEL>: <message>

    Args:
        colored: When True, wrap the timestamp in ``<dim>`` tags and the level
            name in the per-level color tags from :data:`LEVEL_STYLES` so
            loguru colorizes the output. When False, emit plain text.
        extra_fields: Names of ``record["extra"]`` keys to render, in order,
            each inside square brackets after the pid (e.g. ``"request_id"``).
            Missing values render as ``"N/A"``.
        message_transform: Optional callback ``(record, message) -> message``
            applied to the message before rendering (e.g. to colorize action
            labels or append a JSON payload).

    Returns:
        A callable suitable for the ``format`` argument of ``logger.add``.
    """
    fields = tuple(extra_fields)

    def _formatter(record: Mapping[str, Any]) -> str:
        timestamp = format_timestamp(record)
        level = record["level"].name
        message = record["message"]
        if message_transform is not None:
            message = message_transform(record, message)

        extra = record.get("extra", {})
        prefix = f"[{record['process'].id}]"
        for field in fields:
            prefix += f" [{extra.get(field, 'N/A')}]"

        if colored:
            level_start, level_end = LEVEL_STYLES.get(level, ("", ""))
            return f"<dim>{timestamp}</dim> - {prefix} {level_start}{level}{level_end}: {message}\n"
        return f"{timestamp} - {prefix} {level}: {message}\n"

    return _formatter


# =============================================================================
# Handler configuration
# =============================================================================


def configure_handlers(
    *,
    level: str,
    console_format: Callable[[Mapping[str, Any]], str] | str,
    colorize: bool,
    intercept_factory: Callable[[], logging.Handler],
    intercept_logger_names: Iterable[str],
    logfile: str | None = None,
    file_format: Callable[[Mapping[str, Any]], str] | str | None = None,
    serialize_console: bool = False,
) -> None:
    """Apply the common loguru handler setup shared by the projects.

    Removes existing handlers, adds a stdout handler (optionally a JSON
    serialized one), optionally a rotating file handler, and routes stdlib
    logging through ``intercept_factory`` for the given logger names.

    Args:
        level: Upper-case loguru level name (e.g. ``"INFO"``).
        console_format: Format function or string for the stdout handler.
        colorize: Whether to enable loguru color-tag processing on stdout.
        intercept_factory: Zero-argument callable returning a fresh intercept
            handler instance for stdlib logging.
        intercept_logger_names: Stdlib logger names to route through loguru.
        logfile: Optional path enabling a rotating file handler.
        file_format: Format for the file handler (defaults to ``console_format``).
        serialize_console: When True, emit JSON on stdout instead of using
            ``console_format`` (used by the server's JSON mode).
    """
    logger.remove()

    if serialize_console:
        logger.add(sys.stdout, level=level, format="{message}", serialize=True)
    else:
        logger.add(
            sys.stdout,
            level=level,
            format=console_format,  # type: ignore[arg-type]
            colorize=colorize,
        )

    if logfile:
        rotation_config = get_rotation_config()
        logger.add(
            logfile,
            level=level,
            format=file_format if file_format is not None else console_format,  # type: ignore[arg-type]
            colorize=False,
            encoding="utf-8",
            rotation=rotation_config["rotation"],
            retention=rotation_config["retention"],
            compression=rotation_config["compression"],
        )

    logging.basicConfig(handlers=[intercept_factory()], level=0, force=True)
    for logger_name in intercept_logger_names:
        logging.getLogger(logger_name).handlers = [intercept_factory()]
        logging.getLogger(logger_name).propagate = False
