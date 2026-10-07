# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

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
