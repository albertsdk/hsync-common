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

    def test_create_labels_are_green(self):
        assert LABEL_STYLES[str(ActionLabel.CREATE)] == ("<green>", "</green>")
        assert LABEL_STYLES[str(ActionLabel.LOCAL_CREATE)] == ("<green>", "</green>")
        assert LABEL_STYLES[str(ActionLabel.REMOTE_CREATE)] == ("<green>", "</green>")

    def test_delete_labels_are_red(self):
        assert LABEL_STYLES[str(ActionLabel.DELETE)] == ("<red>", "</red>")
        assert LABEL_STYLES[str(ActionLabel.LOCAL_DELETE)] == ("<red>", "</red>")
        assert LABEL_STYLES[str(ActionLabel.REMOTE_DELETE)] == ("<red>", "</red>")

    def test_warning_labels_are_yellow(self):
        # ignore-del operations are advisory (deletions skipped), not no-ops.
        assert LABEL_STYLES[str(ActionLabel.LOCAL_IGNORE_DEL)] == ("<yellow>", "</yellow>")
        assert LABEL_STYLES[str(ActionLabel.REMOTE_IGNORE_DEL)] == ("<yellow>", "</yellow>")

    def test_in_sync_labels_are_dim(self):
        assert LABEL_STYLES[str(ActionLabel.IN_SYNC)] == ("<dim>", "</dim>")
        assert LABEL_STYLES[str(ActionLabel.SKIP)] == ("<dim>", "</dim>")
        assert LABEL_STYLES[str(ActionLabel.LOCAL_KEEP)] == ("<dim>", "</dim>")

    def test_security_labels_are_red(self):
        assert LABEL_STYLES[str(ActionLabel.SECURITY)] == ("<red>", "</red>")
        assert LABEL_STYLES[str(ActionLabel.REMOTE_SECURITY)] == ("<red>", "</red>")

    def test_infrastructure_labels_are_magenta(self):
        assert LABEL_STYLES[str(ActionLabel.WS)] == ("<magenta>", "</magenta>")
        assert LABEL_STYLES[str(ActionLabel.REMOTE_ECHO)] == ("<magenta>", "</magenta>")


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

    def test_prefixed_label_not_corrupted_by_shorter_counterpart(self):
        """Regression: [DOWNLOAD] inside [REMOTE DOWNLOAD] must not corrupt."""
        result = colorize_labels("[REMOTE DOWNLOAD] file.pdf")
        assert result == "<cyan>[REMOTE DOWNLOAD]</cyan> file.pdf"

    def test_local_create_not_corrupted_by_create(self):
        """Regression: [CREATE] inside [LOCAL CREATE] must not corrupt."""
        result = colorize_labels("[LOCAL CREATE] document.txt")
        assert result == "<green>[LOCAL CREATE]</green> document.txt"

    def test_prefixed_and_unprefixed_labels_coexist(self):
        """Unprefixed label alongside its prefixed variant — both colored."""
        result = colorize_labels("[DOWNLOAD] started -> [REMOTE DOWNLOAD] file.pdf")
        assert "<cyan>[DOWNLOAD]</cyan>" in result
        assert "<cyan>[REMOTE DOWNLOAD]</cyan>" in result

    def test_multiple_prefixed_labels_independently_colored(self):
        """Each prefixed label gets its own color category, not the short label's."""
        result = colorize_labels("[LOCAL DELETE] secret.txt  [REMOTE CREATE] new.txt")
        assert "<red>[LOCAL DELETE]</red>" in result
        assert "<green>[REMOTE CREATE]</green>" in result

    def test_security_label_not_corrupted(self):
        """[SECURITY] inside [LOCAL SECURITY] / [REMOTE SECURITY] must not corrupt."""
        result = colorize_labels("[LOCAL SECURITY] blocked path")
        assert "<red>[LOCAL SECURITY]</red>" in result
        result = colorize_labels("[REMOTE SECURITY] blocked path")
        assert "<red>[REMOTE SECURITY]</red>" in result

    def test_modify_label_not_corrupted(self):
        """[MODIFY] inside [LOCAL MODIFY] / [REMOTE MODIFY] must not corrupt."""
        result = colorize_labels("[LOCAL MODIFY] data.json")
        assert "<blue>[LOCAL MODIFY]</blue>" in result
        result = colorize_labels("[REMOTE MODIFY] data.json")
        assert "<blue>[REMOTE MODIFY]</blue>" in result

    def test_ignore_del_label_not_corrupted(self):
        """[IGNORE DEL] is matched as a complete spaced value."""
        result = colorize_labels("[LOCAL IGNORE DEL] temp.bak")
        assert "<yellow>[LOCAL IGNORE DEL]</yellow>" in result
        result = colorize_labels("[REMOTE IGNORE DEL] temp.bak")
        assert "<yellow>[REMOTE IGNORE DEL]</yellow>" in result


class TestResolveLabel:
    def test_unprefixed_label(self):
        assert resolve_label("", "CREATE") == "[CREATE]"
        assert resolve_label("", "DELETE") == "[DELETE]"

    def test_prefixed_label(self):
        assert resolve_label("LOCAL ", "CREATE") == "[LOCAL CREATE]"
        assert resolve_label("REMOTE ", "RENAME") == "[REMOTE RENAME]"

    def test_multi_word_name(self):
        # "IGNORE DEL" resolves to the LOCAL_/REMOTE_ prefixed members,
        # keeping ignore-del advisories colored as warnings.
        assert resolve_label("LOCAL ", "IGNORE DEL") == "[LOCAL IGNORE DEL]"
        assert resolve_label("REMOTE ", "IGNORE DEL") == "[REMOTE IGNORE DEL]"

    def test_unknown_label_falls_back_to_interpolation(self):
        # Unknown labels print verbatim (uncolored) instead of raising.
        assert resolve_label("", "BOGUS") == "[BOGUS]"
        assert resolve_label("REMOTE ", "BOGUS") == "[REMOTE BOGUS]"

    def test_prefix_whitespace_normalized(self):
        # Leading/trailing spaces in the prefix are tolerated.
        assert resolve_label("  REMOTE  ", "DELETE") == "[REMOTE DELETE]"

    def test_resolved_labels_are_colorizable(self):
        # Matrix guard against resolve_label's silent verbatim fallback:
        # every (prefix, stem) pair actually emitted by the code must resolve
        # to a registered, colorizable label.
        matrix = {
            "": ("MOVE", "DELETE", "CREATE", "MODIFY", "RENAME", "SYMLINK", "SECURITY"),
            "LOCAL ": (
                "CREATE",
                "MODIFY",
                "RENAME",
                "DELETE",
                "SYMLINK",
                "IGNORE DEL",
                "KEEP",
            ),
            "REMOTE ": (
                "CREATE",
                "MODIFY",
                "RENAME",
                "DELETE",
                "SYMLINK",
                "IGNORE DEL",
                "SECURITY",
                "ECHO",
                "DOWNLOAD",
            ),
        }
        for prefix, stems in matrix.items():
            for stem in stems:
                label = resolve_label(prefix, stem)
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
