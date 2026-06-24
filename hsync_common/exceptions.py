# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared base exception for the HSYNC ecosystem.

This module defines the canonical ``HSyncError`` base class used by both
``hsync-client`` and ``hsync-server`` exception hierarchies. Each project
keeps its own subclasses (with project-specific error codes and HTTP
mappings) but shares the same construction contract:

    * ``message``       - human-readable description (falls back to
                          ``default_message``).
    * ``error_code``    - unique stable identifier suitable for logs and
                          machine-readable error responses.
    * ``details``       - optional dictionary with structured context.
    * ``to_dict()``     - serialise the error to a plain ``dict`` suitable
                          for JSON responses.

Class attributes ``error_code`` and ``default_message`` are intended to be
overridden by subclasses.
"""

from typing import Any


class HSyncError(Exception):
    """
    Base exception for all HSYNC errors.

    Attributes:
        message: Human-readable error message.
        error_code: Unique error code for debugging (e.g., "HSYNC-1001").
        details: Optional additional error details.
    """

    error_code: str = "HSYNC-5000"
    default_message: str = "An unexpected error occurred"

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for JSON-style responses."""
        result: dict[str, Any] = {
            "error": self.error_code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


def format_exception(exc: Exception) -> str:
    """Format an exception for logging.

    Args:
        exc: The exception to format.

    Returns:
        Formatted string with exception type and message.
    """
    return f"{type(exc).__name__}: {exc}"


def log_exception(logger, exc: Exception, message: str | None = None) -> None:
    """Log an exception with context.

    A convenience function to log an exception with additional context.
    Logs at ERROR level by default.

    Args:
        logger: Logger instance (e.g., loguru logger).
        exc: The exception that was caught.
        message: Optional additional context message.
    """
    from traceback import format_exc

    msg = message or "An error occurred"
    logger.error(f"{msg}: {format_exception(exc)}")
    logger.debug(f"Full traceback:\n{format_exc()}")
