# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Shared logging primitives used by HSYNC projects.

Provides the constants, rotation defaults, the canonical log-line grammar
(:data:`LOG_LINE_RE`, :func:`format_log_line`) and a configurable
:class:`BaseInterceptHandler` that bridges stdlib ``logging`` to
loguru. Project-specific format functions and ``setup_logging``
wrappers live in the consumer projects.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from loguru import logger

from hsync_common.text import escape_loguru_markup

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

#: Every severity a HSYNC component may emit, in increasing order of urgency.
#: The single vocabulary of the log-line grammar: a line whose level is not in
#: this tuple is not a HSYNC log line. Derived from :data:`LEVEL_STYLES` so a
#: level can never be colorized without being readable (or vice versa).
LOG_LEVELS: Final[tuple[str, ...]] = tuple(LEVEL_STYLES)

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

    - ``escape_markup``: when ``True``, neutralize loguru markup (``{`` / ``}``
      format placeholders and the ``<`` that opens a color tag) in the log
      message via :func:`escape_loguru_markup`. Useful when third-party
      libraries log JSON payloads, templated strings, or qualified names
      containing ``<locals>`` (e.g. tenacity retry messages).
    - ``bind_extra``: optional zero-argument callable returning a mapping of
      extra fields to bind to the loguru logger before emitting (e.g. a
      per-request correlation id).
    """

    def __init__(
        self,
        *,
        escape_markup: bool = False,
        bind_extra: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__()
        self._escape_markup = escape_markup
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
        if self._escape_markup:
            message = escape_loguru_markup(message)

        target = logger
        if self._bind_extra is not None:
            target = logger.bind(**self._bind_extra())

        target.opt(depth=depth, exception=record.exc_info).log(level, message)


# =============================================================================
# Record formatting
# =============================================================================


# =============================================================================
# The canonical log-line grammar
# =============================================================================

# Every component writes the same record shape, whatever its sink:
#
#     <timestamp> - [<pid>] [<correlation field> ...] LEVEL: <message>
#
# ``build_record_formatter`` renders it for the loguru sinks (CLI, server);
# ``format_log_line`` renders it for producers without a loguru stack (the
# Desktop, which prints the engine's output in a Qt widget). Consumers parse it
# with ``LOG_LINE_RE`` instead of re-encoding the shape: the Desktop colors the
# level from it (``hsync_desktop/log_style.py``) and harvests the client's last
# errors from it (``hsync_desktop/engine/process.py``).
#
# The ``Z`` suffix is only truthful when the rendered instant is UTC, so the
# timestamp is normalized (see ``_render_timestamp``).
LOG_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r" - (?P<fields>(?:\[[^\]\n]*\] ?)+)"
    r"(?P<level>" + "|".join(LOG_LEVELS) + r"): (?P<message>[^\n]*)"
)


def _render_timestamp(moment: datetime) -> str:
    """Render *moment* as ISO-8601 with milliseconds and a trailing ``Z``.

    An aware datetime is converted to UTC first, because the ``Z`` suffix must
    never label a local wall clock (that reads as a lie to whoever compares two
    lines of the same panel). A naive datetime is taken as UTC: callers holding
    a local clock must attach its zone instead of relying on the reader.
    """
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def format_log_line(
    level: str,
    message: str,
    *,
    fields: Iterable[str] = (),
    pid: int | None = None,
    timestamp: datetime | None = None,
) -> str:
    """Render one log line in the canonical HSYNC grammar.

    Produces ``<timestamp> - [<pid>] [<field> ...] LEVEL: <message>``: the exact
    shape :func:`build_record_formatter` renders for the loguru sinks, so a
    producer that does not log through loguru still emits lines a single reader
    understands. The correlation *fields* are what distinguishes the producers,
    not the layout: ``[<client_id>]`` for the client, ``[desktop]`` for the GUI
    (which has no client session and therefore no CID).

    Args:
        level: One of :data:`LOG_LEVELS` (upper case). An unknown level is
            rejected instead of being written as an unparseable line.
        message: Free-form message; newlines are kept verbatim (they are the
            continuation of the same record, e.g. a pretty-printed payload).
        fields: Correlation fields rendered after the pid, each in brackets.
        pid: Process id to render; defaults to the current process.
        timestamp: Instant to render, rendered in UTC. Defaults to now.

    Raises:
        ValueError: If *level* is not in :data:`LOG_LEVELS`.

    Consumers: ``hsync-desktop`` (``main_window/ui.py::UiBuildMixin._append_desktop_log``);
    the produced grammar is parsed by ``hsync-desktop/log_style.py::_fallback_runs``
    and ``hsync-desktop/engine/process.py::HsyncEngine._on_stdout`` through
    :data:`LOG_LINE_RE`.
    """
    if level not in LOG_LEVELS:
        raise ValueError(f"unknown log level {level!r}; expected one of {LOG_LEVELS}")

    moment = timestamp if timestamp is not None else datetime.now(UTC)
    prefix = f"[{os.getpid() if pid is None else pid}]"
    for field in fields:
        prefix += f" [{field}]"
    return f"{_render_timestamp(moment)} - {prefix} {level}: {message}"


def format_timestamp(record: Mapping[str, Any]) -> str:
    """Return an ISO-8601 millisecond timestamp with a trailing ``Z``."""
    return _render_timestamp(record["time"])


def build_record_formatter(
    *,
    colored: bool,
    extra_fields: Iterable[str] = (),
    message_transform: Callable[[Mapping[str, Any], str], str] | None = None,
    timestamp_formatter: Callable[[Mapping[str, Any]], str] | None = None,
) -> Callable[[Mapping[str, Any]], str]:
    """Build a loguru format function shared across projects.

    The produced function renders records as::

        <timestamp> - [<pid>] [<field> ...] <LEVEL>: <message>

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
        timestamp_formatter: Optional callback ``record -> timestamp`` used
            instead of :func:`format_timestamp` (e.g. to render the timestamp
            in a configured local timezone). Defaults to UTC.

    Returns:
        A callable suitable for the ``format`` argument of ``logger.add``.
    """
    fields = tuple(extra_fields)
    render_timestamp = timestamp_formatter or format_timestamp

    def _formatter(record: Mapping[str, Any]) -> str:
        timestamp = render_timestamp(record)
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
