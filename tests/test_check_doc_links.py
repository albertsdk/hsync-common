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
