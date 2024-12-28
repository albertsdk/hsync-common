# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the shared label SSOT (``hsync_common.labels``)."""

import pytest

from hsync_common.labels import (
    LABEL_CATEGORIES,
    LABEL_STYLES,
    ActionLabel,
    colorize_labels,
    resolve_label,
)


class TestLabelCategoryCoverage:
    """Every ActionLabel member must be mapped to a color category.

    A label present in the enum but missing from ``_LABEL_CATEGORY_MAP`` would
    silently print uncolored: this guard keeps the SSOT honest.
    """

    def test_every_label_has_a_style(self):
        """LABEL_STYLES contains an entry for every ActionLabel member."""
        for member in ActionLabel:
            assert str(member) in LABEL_STYLES, f"unmapped label: {member!r}"

    def test_every_category_is_known(self):
        """Every category referenced by LABEL_STYLES exists in LABEL_CATEGORIES."""
        for label, (start, end) in LABEL_STYLES.items():
            # Derive the category by looking it up against LABEL_CATEGORIES values.
            assert (start, end) in LABEL_CATEGORIES.values(), (
                f"label {label!r} references unknown color tags {start!r}/{end!r}"
            )

    def test_styles_are_derived_from_categories(self):
        """LABEL_STYLES values are exactly LABEL_CATEGORIES values."""
        assert set(LABEL_STYLES.values()) <= set(LABEL_CATEGORIES.values())


class TestSpecificLabelColors:
    """Pin the semantic color of representative labels (regression guard)."""

    def test_transfer_labels_are_cyan(self):
        assert LABEL_STYLES[str(ActionLabel.DOWNLOAD)] == ("<cyan>", "</cyan>")
        assert LABEL_STYLES[str(ActionLabel.RESUME)] == ("<cyan>", "</cyan>")

    def test_upload_labels_are_green(self):
        assert LABEL_STYLES[str(ActionLabel.UPLOAD)] == ("<green>", "</green>")
        assert LABEL_STYLES[str(ActionLabel.CLIENT_UP)] == ("<green>", "</green>")

    def test_create_labels_are_green(self):
        assert LABEL_STYLES[str(ActionLabel.CREATE)] == ("<green>", "</green>")
        assert LABEL_STYLES[str(ActionLabel.CLIENT_DIR)] == ("<green>", "</green>")

    def test_delete_labels_are_red(self):
        assert LABEL_STYLES[str(ActionLabel.DELETE)] == ("<red>", "</red>")
        assert LABEL_STYLES[str(ActionLabel.CLIENT_DEL)] == ("<red>", "</red>")

    def test_warning_labels_are_yellow(self):
        # ignore-del operations are advisory (deletions skipped), not no-ops.
        assert LABEL_STYLES[str(ActionLabel.IGNORE_DEL)] == ("<yellow>", "</yellow>")
        assert LABEL_STYLES[str(ActionLabel.CLIENT_IGN)] == ("<yellow>", "</yellow>")
        assert LABEL_STYLES[str(ActionLabel.LAN_IGNORE_DEL)] == ("<yellow>", "</yellow>")

    def test_in_sync_labels_are_dim(self):
        assert LABEL_STYLES[str(ActionLabel.IN_SYNC)] == ("<dim>", "</dim>")
        assert LABEL_STYLES[str(ActionLabel.SKIP)] == ("<dim>", "</dim>")

    def test_security_labels_are_red(self):
        assert LABEL_STYLES[str(ActionLabel.SECURITY)] == ("<red>", "</red>")
        assert LABEL_STYLES[str(ActionLabel.LAN_SECURITY)] == ("<red>", "</red>")

    def test_infrastructure_labels_are_magenta(self):
        assert LABEL_STYLES[str(ActionLabel.WS)] == ("<magenta>", "</magenta>")
        assert LABEL_STYLES[str(ActionLabel.LAN_ECHO)] == ("<magenta>", "</magenta>")


class TestColorizeLabels:
    def test_colorizes_known_label(self):
        result = colorize_labels('[DOWNLOAD] "file.txt" 1.2MB')
        assert "<cyan>[DOWNLOAD]</cyan>" in result

    def test_colorizes_multiple_labels(self):
        result = colorize_labels("[DOWNLOAD] then [UPLOAD]")
        assert "<cyan>[DOWNLOAD]</cyan>" in result
        assert "<green>[UPLOAD]</green>" in result

    def test_no_labels_unchanged(self):
        assert colorize_labels("plain message") == "plain message"

    def test_disabled_returns_message_unchanged(self):
        msg = '[DOWNLOAD] "file.txt"'
        assert colorize_labels(msg, use_colors=False) == msg

    def test_does_not_colorize_unknown_label(self):
        # An unregistered bracket tag is left untouched (no partial wrap).
        result = colorize_labels("[BOGUS] something")
        assert result == "[BOGUS] something"


class TestResolveLabel:
    def test_unprefixed_label(self):
        assert resolve_label("", "CREATE") == "[CREATE]"
        assert resolve_label("", "DELETE") == "[DELETE]"

    def test_prefixed_label(self):
        assert resolve_label("LAN ", "CREATE") == "[LAN CREATE]"
        assert resolve_label("LAN ", "RENAME") == "[LAN RENAME]"

    def test_multi_word_name(self):
        # "IGNORE DEL" resolves to IGNORE_DEL (unprefixed) and LAN_IGNORE_DEL
        # (LAN-prefixed), keeping ignore-del advisories colored as warnings.
        assert resolve_label("", "IGNORE DEL") == "[IGNORE DEL]"
        assert resolve_label("LAN ", "IGNORE DEL") == "[LAN IGNORE DEL]"

    def test_unknown_label_falls_back_to_interpolation(self):
        # Unknown labels print verbatim (uncolored) instead of raising.
        assert resolve_label("", "BOGUS") == "[BOGUS]"
        assert resolve_label("LAN ", "BOGUS") == "[LAN BOGUS]"

    def test_prefix_whitespace_normalized(self):
        # Leading/trailing spaces in the prefix are tolerated.
        assert resolve_label("  LAN  ", "DELETE") == "[LAN DELETE]"

    def test_resolved_labels_are_colorizable(self):
        # Every label resolve_label can produce for a known name is colorizable.
        for name in ("CREATE", "DELETE", "MODIFY", "RENAME", "SYMLINK", "IGNORE DEL"):
            label = resolve_label("", name)
            assert label in LABEL_STYLES, f"{label!r} is not colorizable"


class TestLabelValueFormat:
    """Multi-word label values use spaces, never underscores.

    The enum *member* names stay snake_case (Python convention); the displayed
    *values* (the strings emitted in logs and matched by ``colorize_labels``)
    are human-readable and use spaces. This is the cross-platform log contract
    shared with the Android client, so it is pinned here.
    """

    @pytest.mark.parametrize("member", list(ActionLabel))
    def test_value_has_no_underscore_inside(self, member):
        inner = str(member)[1:-1]  # strip the brackets
        assert "_" not in inner, f"label value {member!r} contains an underscore"

    def test_warning_label_values(self):
        assert str(ActionLabel.NO_MASTER) == "[NO MASTER]"
        assert str(ActionLabel.MASTER_CONFLICT) == "[MASTER CONFLICT]"
        assert str(ActionLabel.MASTER_TAKEOVER) == "[MASTER TAKEOVER]"
        assert str(ActionLabel.INSECURE_MASTER) == "[INSECURE MASTER]"
        assert str(ActionLabel.PAIRING_NEEDED) == "[PAIRING NEEDED]"
        assert str(ActionLabel.FINGERPRINT_CHANGED) == "[FINGERPRINT CHANGED]"
        assert str(ActionLabel.AUTH_REQUIRED) == "[AUTH REQUIRED]"

    def test_preview_label_values(self):
        assert str(ActionLabel.TO_DOWNLOAD) == "[TO DOWNLOAD]"
        assert str(ActionLabel.TO_UPLOAD) == "[TO UPLOAD]"
        assert str(ActionLabel.TO_DELETE) == "[TO DELETE]"
        assert str(ActionLabel.TO_RENAME) == "[TO RENAME]"

    def test_resolve_label_round_trips_spaced_names(self):
        # The spaced stems resolve back to the spaced values via the SSOT.
        assert resolve_label("", "NO MASTER") == "[NO MASTER]"
        assert resolve_label("", "TO DOWNLOAD") == "[TO DOWNLOAD]"
        assert resolve_label("", "AUTH REQUIRED") == "[AUTH REQUIRED]"
