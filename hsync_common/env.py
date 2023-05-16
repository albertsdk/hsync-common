# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Environment file loading utilities shared across HSYNC projects.

Provides a single implementation of ``.env`` file loading on top of
``python-dotenv``, with optional cache-invalidation callbacks so each
consumer can clear its own cached settings.
"""

from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv


def load_env_file(
    file_path: str | Path,
    on_loaded: Callable[[], None] | None = None,
) -> None:
    """
    Load environment variables from a file using python-dotenv.

    The file format supports:
    - KEY=value pairs (one per line)
    - Comments starting with #
    - Quoted values (single or double quotes)
    - export KEY=value syntax
    - Multiline values with quotes

    Environment variables already set (e.g., from CLI or shell) take
    precedence and are NOT overwritten by the file.

    Args:
        file_path: Path to the environment file.
        on_loaded: Optional callback invoked after a successful load,
            typically used to invalidate cached settings.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Environment file not found: {file_path}")

    # override=False ensures CLI/shell variables take precedence
    load_dotenv(dotenv_path=path, override=False)

    if on_loaded is not None:
        on_loaded()
