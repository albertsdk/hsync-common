# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared pytest fixtures for the hsync-common test suite.

Provides ``autouse`` fixtures that guarantee a clean environment for every test,
preventing state leakage between tests.
"""

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _reset_active_ignore_matcher() -> Generator[None]:
    """Ensure the process-global IgnoreMatcher is cleared after each test.

    Tests in ``test_ignore.py`` set a process-wide matcher via
    ``set_active_matcher``; if a test fails before its ``finally`` block
    unsets it, subsequent tests would inherit a matcher from a stale bucket.
    Clearing it here gives every test a clean slate regardless of failures.
    """
    from hsync_common.ignore import set_active_matcher

    set_active_matcher(None)
    yield
    set_active_matcher(None)


@pytest.fixture(autouse=True)
def _sanitize_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent tests that call ``load_env_file`` from permanently polluting
    ``os.environ``.

    ``load_env_file`` writes to ``os.environ`` directly.  ``monkeypatch``
    cannot intercept those writes, so this fixture records the pre-test
    snapshot and restores any keys that were added (not just modified) by
    the test.
    """
    import os

    before = set(os.environ.keys())
    yield
    after = set(os.environ.keys())
    added = after - before
    for key in sorted(added):
        monkeypatch.delenv(key, raising=False)
