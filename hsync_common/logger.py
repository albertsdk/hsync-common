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
from typing import Callable, Final

from loguru import logger

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

# Default compression: gzip for space efficiency
DEFAULT_LOG_COMPRESSION: Final[str] = "gz"


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
            message = message.replace("{", "{{").replace("}", "}}")

        target = logger
        if self._bind_extra is not None:
            target = logger.bind(**self._bind_extra())

        target.opt(depth=depth, exception=record.exc_info).log(level, message)
