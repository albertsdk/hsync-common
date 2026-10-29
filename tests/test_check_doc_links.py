"""Tests for the docs relative-link checker (scripts/dev/check_doc_links.py)."""

import importlib.util
from pathlib import Path

import pytest

# The checker lives under scripts/dev/ and is not an importable package, so we
# load it directly from its file path.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev" / "check_doc_links.py"
_spec = importlib.util.spec_from_file_location("check_doc_links", _SCRIPT)
assert _spec and _spec.loader
cdl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdl)


class TestExtractTargets:
    def test_extracts_links_and_images(self):
        text = "see [a](a.md) and ![img](pic.png) plus [b](b.md)"
        assert cdl.extract_targets(text) == ["a.md", "pic.png", "b.md"]

    def test_strips_link_title(self):
        assert cdl.extract_targets('[x](path.md "the title")') == ["path.md"]

    def test_no_links(self):
        assert cdl.extract_targets("plain text, no links here") == []


class TestIsCheckable:
    @pytest.mark.parametrize(
        "target",
        [
            "https://example.com",
            "http://example.com",
            "mailto:a@b.c",
            "tel:123",
            "#anchor",
            "//cdn",
            "/abs/path.md",
            "",
        ],
    )
    def test_skipped(self, target):
        assert cdl.is_checkable(target) is False

    @pytest.mark.parametrize("target", ["a.md", "../b.md", "dir/c.md", "d.md#frag"])
    def test_checkable(self, target):
        assert cdl.is_checkable(target) is True


class TestResolve:
    def test_strips_anchor_and_query(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        resolved = cdl.resolve(md, "other.md#section?x=1")
        assert resolved == (tmp_path / "other.md").resolve()


class TestIterMarkdownFiles:
    def test_skips_excluded_dirs(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("x")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "b.md").write_text("x")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "c.md").write_text("x")
        (tmp_path / ".kilo" / "worktrees" / "wt").mkdir(parents=True)
        (tmp_path / ".kilo" / "worktrees" / "wt" / "d.md").write_text("x")

        found = {p.name for p in cdl.iter_markdown_files(tmp_path)}
        assert found == {"a.md"}


class TestFindBrokenLinks:
    def test_detects_broken_and_counts_valid(self, tmp_path: Path):
        (tmp_path / "target.md").write_text("ok")
        (tmp_path / "doc.md").write_text(
            "valid [t](target.md), broken [m](missing.md), "
            "external [e](https://x.y), anchor [a](#s)"
        )

        broken, checked = cdl.find_broken_links(tmp_path)

        # Only the two relative links are counted; the missing one is broken.
        assert checked == 2
        assert len(broken) == 1
        md_file, target = broken[0]
        assert md_file.name == "doc.md"
        assert target == "missing.md"

    def test_directory_target_is_valid(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "doc.md").write_text("see [s](sub)")

        broken, checked = cdl.find_broken_links(tmp_path)

        assert checked == 1
        assert broken == []

    def test_cross_root_link_is_skipped(self, tmp_path: Path):
        # A link escaping the scanned root (a sibling project) is skipped:
        # neither counted nor flagged, even though it does not exist under root.
        root = tmp_path / "repo"
        root.mkdir()
        (root / "doc.md").write_text("[x](../sibling/llm-wiki/README.md)")

        broken, checked = cdl.find_broken_links(root)

        assert checked == 0
        assert broken == []

    def test_in_root_link_still_checked_alongside_cross_root(self, tmp_path: Path):
        # In-root links are still validated when mixed with skipped cross-root ones.
        root = tmp_path / "repo"
        root.mkdir()
        (root / "ok.md").write_text("ok")
        (root / "doc.md").write_text("[in](ok.md) and [out](../sibling/x.md) and [miss](nope.md)")

        broken, checked = cdl.find_broken_links(root)

        assert checked == 2
        assert [t for _, t in broken] == ["nope.md"]


class TestMain:
    def test_returns_zero_when_all_valid(self, tmp_path: Path, capsys):
        (tmp_path / "target.md").write_text("ok")
        (tmp_path / "doc.md").write_text("[t](target.md)")

        rc = cdl.main([str(tmp_path)])

        assert rc == 0
        assert "docs-link-check OK" in capsys.readouterr().out

    def test_returns_one_and_reports_broken(self, tmp_path: Path, capsys):
        (tmp_path / "doc.md").write_text("[m](missing.md)")

        rc = cdl.main([str(tmp_path)])

        assert rc == 1
        out = capsys.readouterr().out
        assert "Broken relative links" in out
        assert "missing.md" in out

    def test_scans_multiple_roots(self, tmp_path: Path):
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        root_a.mkdir()
        root_b.mkdir()
        (root_a / "t.md").write_text("ok")
        (root_a / "doc.md").write_text("[t](t.md)")
        (root_b / "doc.md").write_text("[m](missing.md)")

        rc = cdl.main([str(root_a), str(root_b)])

        assert rc == 1


class TestFindBrokenAnchors:
    def _make_wiki(self, root: Path, name: str = "hsync-common"):
        project = root / name
        wiki = project / "llm-wiki"
        wiki.mkdir(parents=True)
        (project / "hsync_common").mkdir(parents=True, exist_ok=True)
        return project, wiki

    def test_valid_anchor_passes(self, tmp_path: Path):
        project, wiki = self._make_wiki(tmp_path)
        (project / "hsync_common" / "constants.py").write_text("HSYNC_VERSION = '1.0.0'\n")
        (wiki / "README.md").write_text("v `hsync_common/constants.py::HSYNC_VERSION`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 1

    def test_missing_symbol_fails(self, tmp_path: Path):
        project, wiki = self._make_wiki(tmp_path)
        (project / "hsync_common" / "constants.py").write_text("OTHER = 1\n")
        (wiki / "README.md").write_text("v `hsync_common/constants.py::GONE`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1
        assert "GONE" in errors[0][1]

    def test_missing_file_fails(self, tmp_path: Path):
        _, wiki = self._make_wiki(tmp_path)
        (wiki / "README.md").write_text("v `hsync_common/nope.py::Nope`")

        errors, _, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1

    def test_package_relative_anchor_resolves(self, tmp_path: Path):
        # Anchors written relative to the package dir (no hsync_common/ prefix).
        project, wiki = self._make_wiki(tmp_path)
        proto_dir = project / "hsync_common" / "protocol"
        proto_dir.mkdir(parents=True, exist_ok=True)
        (proto_dir / "handshake.py").write_text("PROTOCOL_VERSION_REST = 'api/1'\n")
        (wiki / "modules").mkdir(parents=True, exist_ok=True)
        (wiki / "modules" / "protocol.md").write_text(
            "v `protocol/handshake.py::PROTOCOL_VERSION_REST`"
        )

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 1

    def test_sibling_anchor_skipped(self, tmp_path: Path):
        _, wiki = self._make_wiki(tmp_path)
        (wiki / "README.md").write_text("v `hsync_client/constants.py::ActionLabel`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 0

    def test_legacy_line_anchor_is_fatal_in_hsync_common(self, tmp_path: Path):
        _, wiki = self._make_wiki(tmp_path)
        (wiki / "README.md").write_text("v `hsync_common/constants.py:24`")

        errors, warnings, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1
        assert warnings == []

    def test_legacy_line_anchor_is_warning_in_sibling(self, tmp_path: Path):
        # A not-yet-migrated wiki on line anchors: warning, not fatal.
        sibling = tmp_path / "hsync-legacy"
        wiki = sibling / "llm-wiki"
        wiki.mkdir(parents=True)
        (wiki / "README.md").write_text("v `constants.py:24`")

        errors, warnings, _ = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert len(warnings) == 1

    def test_sibling_symbol_anchor_not_validated(self, tmp_path: Path):
        # Symbol anchors in not-yet-migrated wikis are not enforced.
        sibling = tmp_path / "hsync-legacy"
        wiki = sibling / "llm-wiki"
        wiki.mkdir(parents=True)
        (wiki / "README.md").write_text("v `constants.py::GONE`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 0

    def _make_py_wiki(self, root: Path, project: str, package: str):
        proj = root / project
        wiki = proj / "llm-wiki"
        wiki.mkdir(parents=True)
        pkg = proj / package
        pkg.mkdir(parents=True, exist_ok=True)
        return proj, wiki, pkg

    def test_hsync_server_is_enforced(self, tmp_path: Path):
        _, wiki, pkg = self._make_py_wiki(tmp_path, "hsync-server", "hsync_server")
        (pkg / "config.py").write_text("def get_port() -> int:\n    return 1\n")
        (wiki / "README.md").write_text("v `config.py::get_port`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 1

    def test_hsync_server_broken_symbol_fails(self, tmp_path: Path):
        _, wiki, pkg = self._make_py_wiki(tmp_path, "hsync-server", "hsync_server")
        (pkg / "config.py").write_text("def get_port() -> int:\n    return 1\n")
        (wiki / "README.md").write_text("v `config.py::GONE`")

        errors, _, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1

    def test_hsync_server_legacy_line_is_fatal(self, tmp_path: Path):
        _, wiki, _ = self._make_py_wiki(tmp_path, "hsync-server", "hsync_server")
        (wiki / "README.md").write_text("v `config.py:10`")

        errors, warnings, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1
        assert warnings == []

    def test_cross_project_anchor_in_enforced_wiki_skipped(self, tmp_path: Path):
        # An hsync-server wiki anchor pointing at hsync-client is not validated.
        _, wiki, _ = self._make_py_wiki(tmp_path, "hsync-server", "hsync_server")
        (wiki / "README.md").write_text("v `hsync_client/constants.py::ActionLabel`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 0

    def test_hsync_rendezvous_legacy_line_is_fatal(self, tmp_path: Path):
        proj = tmp_path / "hsync-rendezvous"
        wiki = proj / "llm-wiki"
        wiki.mkdir(parents=True)
        (wiki / "README.md").write_text("v `python/src/hsync_rendezvous/protocol.py:10`")

        errors, warnings, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1
        assert warnings == []

    def test_hsync_rendezvous_full_path_anchor_resolves(self, tmp_path: Path):
        proj = tmp_path / "hsync-rendezvous"
        wiki = proj / "llm-wiki"
        wiki.mkdir(parents=True)
        pkg = proj / "python" / "src" / "hsync_rendezvous"
        pkg.mkdir(parents=True)
        (pkg / "protocol.py").write_text("class RdvRegister:\n    pass\n")
        (wiki / "README.md").write_text("v `python/src/hsync_rendezvous/protocol.py::RdvRegister`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 1

    def test_hsync_client_is_enforced(self, tmp_path: Path):
        _, wiki, pkg = self._make_py_wiki(tmp_path, "hsync-client", "hsync_client")
        (pkg / "sync.py").write_text("def sync() -> None:\n    pass\n")
        (wiki / "README.md").write_text("v `sync.py::sync`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 1

    def test_hsync_client_broken_symbol_fails(self, tmp_path: Path):
        _, wiki, pkg = self._make_py_wiki(tmp_path, "hsync-client", "hsync_client")
        (pkg / "sync.py").write_text("def sync() -> None:\n    pass\n")
        (wiki / "README.md").write_text("v `sync.py::GONE`")

        errors, _, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1

    def test_hsync_desktop_is_enforced(self, tmp_path: Path):
        _, wiki, pkg = self._make_py_wiki(tmp_path, "hsync-desktop", "hsync_desktop")
        (pkg / "engine.py").write_text("class HsyncEngine:\n    pass\n")
        (wiki / "README.md").write_text("v `engine.py::HsyncEngine`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 1

    def test_hsync_desktop_broken_symbol_fails(self, tmp_path: Path):
        _, wiki, pkg = self._make_py_wiki(tmp_path, "hsync-desktop", "hsync_desktop")
        (pkg / "engine.py").write_text("class HsyncEngine:\n    pass\n")
        (wiki / "README.md").write_text("v `engine.py::GONE`")

        errors, _, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1

    def test_suffix_resolution_prefers_main_over_test(self, tmp_path: Path):
        # Android sources live under app/src/main/java/<package>/; a
        # package-relative anchor resolves there, preferring main over test.
        proj = tmp_path / "hsync-android"
        wiki = proj / "llm-wiki"
        wiki.mkdir(parents=True)
        main = proj / "app" / "src" / "main" / "java" / "com" / "hsync" / "android" / "p2p"
        test = proj / "app" / "src" / "test" / "java" / "com" / "hsync" / "android" / "p2p"
        main.mkdir(parents=True)
        test.mkdir(parents=True)
        (main / "Election.kt").write_text("class Election\n")
        (test / "Election.kt").write_text("class Election\n")
        (wiki / "README.md").write_text("v `p2p/Election.kt::Election`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 1

    def test_non_wiki_md_not_checked(self, tmp_path: Path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "README.md").write_text("v `hsync_common/constants.py::GONE`")

        errors, warnings, checked = cdl.find_broken_anchors(tmp_path)

        assert errors == []
        assert warnings == []
        assert checked == 0

    def test_definition_shape_required(self, tmp_path: Path):
        # A symbol only mentioned in a docstring does not count as defined.
        project, wiki = self._make_wiki(tmp_path)
        (project / "hsync_common" / "constants.py").write_text('"""mentions GONE"""\nX = 1\n')
        (wiki / "README.md").write_text("v `hsync_common/constants.py::GONE`")

        errors, _, _ = cdl.find_broken_anchors(tmp_path)

        assert len(errors) == 1
