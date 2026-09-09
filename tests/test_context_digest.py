"""Tests for aet.context_digest — the R-5 current-rules digest and insights."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aet.context_digest import (
    AdrCorpusReport,
    AdrEntry,
    TopNRecentSelector,
    audit_adr_entries,
    build_rules_digest,
    read_adr_entries,
    read_learnings,
    render_digest_section,
)


def _write_adr(
    adr_dir: Path,
    name: str,
    *,
    subject: str | None = None,
    supersedes: list[int] | None = None,
    relates: list[int] | None = None,
) -> Path:
    """Write a minimal ADR file with optional subject/supersedes/relates frontmatter."""
    lines = ["---"]
    if subject is not None:
        lines.append(f"subject: {subject}")
    if supersedes:
        lines.append(f"supersedes: [{', '.join(str(n) for n in supersedes)}]")
    if relates:
        lines.append(f"relates: [{', '.join(str(n) for n in relates)}]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    path = adr_dir / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _make_adr_dir(tmp_path: Path) -> Path:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    return adr_dir


class TestBuildRulesDigest(unittest.TestCase):
    """Unit tests for the ADR reader and chain resolution."""

    def test_adrs_without_subject_are_excluded(self):
        """ADRs lacking subject: frontmatter never appear in the digest."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "001-no-subject.md")
            _write_adr(adr_dir, "002-alpha.md", subject="alpha")

            rules = build_rules_digest(adr_dir)

            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["subject"], "alpha")
            self.assertEqual(rules[0]["status"], "live")
            self.assertEqual(rules[0]["live"], "002-alpha")

    def test_chain_resolution_picks_single_live_rule_with_lineage(self):
        """A supersedes chain resolves to the live ADR citing its lineage."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "010-old.md", subject="work-state")
            _write_adr(adr_dir, "011-new.md", subject="work-state", supersedes=[10])

            rules = build_rules_digest(adr_dir)

            self.assertEqual(len(rules), 1)
            rule = rules[0]
            self.assertEqual(rule["status"], "live")
            self.assertEqual(rule["live"], "011-new")
            self.assertEqual(rule["lineage"], ["010-old"])

    def test_multi_step_chain_cites_full_lineage_by_number(self):
        """A chain over several ADRs lists the superseded lineage ascending."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "034-a.md", subject="settled-ness")
            _write_adr(adr_dir, "054-b.md", subject="settled-ness")
            _write_adr(
                adr_dir, "055-c.md", subject="settled-ness", supersedes=[34, 54]
            )

            rules = build_rules_digest(adr_dir)

            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["live"], "055-c")
            self.assertEqual(rules[0]["lineage"], ["034-a", "054-b"])

    def test_digest_is_subject_sorted(self):
        """Rules render in stable subject order regardless of file order."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "001-zeta.md", subject="zeta")
            _write_adr(adr_dir, "002-alpha.md", subject="alpha")

            rules = build_rules_digest(adr_dir)

            self.assertEqual([r["subject"] for r in rules], ["alpha", "zeta"])

    def test_dual_live_subjects_render_conflict(self):
        """Two non-superseded ADRs on one subject render CONFLICT, never a pick."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "001-a.md", subject="alpha")
            _write_adr(adr_dir, "002-b.md", subject="alpha")

            rules = build_rules_digest(adr_dir)

            self.assertEqual(len(rules), 1)
            rule = rules[0]
            self.assertEqual(rule["status"], "conflict")
            self.assertIsNone(rule["live"])
            self.assertIn("dual-live", rule["conflict"])
            self.assertIn("001-a", rule["conflict"])
            self.assertIn("002-b", rule["conflict"])

    def test_dangling_supersedes_renders_conflict(self):
        """A supersedes ref to a nonexistent ADR renders CONFLICT."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "001-a.md", subject="alpha", supersedes=[99])

            rules = build_rules_digest(adr_dir)

            self.assertEqual(len(rules), 1)
            rule = rules[0]
            self.assertEqual(rule["status"], "conflict")
            self.assertIn("dangling supersedes: 99", rule["conflict"])

    def test_cycle_renders_conflict(self):
        """A supersedes cycle leaves no live ADR and renders CONFLICT."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "001-a.md", subject="alpha", supersedes=[2])
            _write_adr(adr_dir, "002-b.md", subject="alpha", supersedes=[1])

            rules = build_rules_digest(adr_dir)

            self.assertEqual(len(rules), 1)
            rule = rules[0]
            self.assertEqual(rule["status"], "conflict")
            self.assertIn("cycle", rule["conflict"])

    def test_missing_adr_dir_yields_empty_digest(self):
        """A missing ADR directory degrades to an empty digest, never an error."""
        rules = build_rules_digest(Path("/nonexistent/docs/adr"))
        self.assertEqual(rules, [])


class TestAuditAdrEntries(unittest.TestCase):
    """Unit tests for the ADR corpus integrity audit helper."""

    def test_duplicate_numbers_detected(self):
        """Entries sharing an ADR number are reported in duplicate_numbers."""
        entries = [
            AdrEntry(stem="072-a", number=72, subject="first", supersedes=[]),
            AdrEntry(stem="072-b", number=72, subject="second", supersedes=[]),
            AdrEntry(stem="073-c", number=73, subject="third", supersedes=[]),
        ]
        report = audit_adr_entries(entries)
        self.assertIn(72, report.duplicate_numbers)
        self.assertEqual(len(report.duplicate_numbers[72]), 2)
        self.assertNotIn(73, report.duplicate_numbers)

    def test_dangling_supersedes_detected(self):
        """A supersedes reference to a non-existent number is flagged as dangling."""
        entries = [
            AdrEntry(stem="010-a", number=10, subject="alpha", supersedes=[99]),
        ]
        report = audit_adr_entries(entries)
        self.assertEqual(report.dangling_supersedes, {"010-a": [99]})

    def test_dangling_relates_detected(self):
        """A relates reference to a non-existent number is flagged as dangling."""
        entries = [
            AdrEntry(stem="010-a", number=10, subject="alpha", supersedes=[], relates=[99]),
        ]
        report = audit_adr_entries(entries)
        self.assertEqual(report.dangling_relates, {"010-a": [99]})

    def test_relates_to_superseded_record_detected(self):
        """A relates reference to a superseded number is flagged as superseded_relates."""
        entries = [
            AdrEntry(stem="010-old", number=10, subject="state", supersedes=[]),
            AdrEntry(stem="011-new", number=11, subject="state", supersedes=[10]),
            AdrEntry(stem="012-user", number=12, subject="other", supersedes=[], relates=[10]),
        ]
        report = audit_adr_entries(entries)
        self.assertEqual(report.dangling_relates, {})
        self.assertEqual(report.superseded_relates, {"012-user": [10]})

    def test_clean_corpus_passes_audit(self):
        """A clean corpus has no duplicates, dangling refs, or superseded relations."""
        entries = [
            AdrEntry(stem="010-old", number=10, subject="state", supersedes=[]),
            AdrEntry(stem="011-new", number=11, subject="state", supersedes=[10]),
            AdrEntry(stem="012-user", number=12, subject="other", supersedes=[], relates=[11]),
        ]
        report = audit_adr_entries(entries)
        self.assertIsInstance(report, AdrCorpusReport)
        self.assertEqual(report.duplicate_numbers, {})
        self.assertEqual(report.dangling_supersedes, {})
        self.assertEqual(report.dangling_relates, {})
        self.assertEqual(report.superseded_relates, {})

    def test_read_adr_entries_populates_relates(self):
        """read_adr_entries parses and coerces the relates frontmatter key."""
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = _make_adr_dir(Path(tmp))
            _write_adr(adr_dir, "010-rel.md", subject="test", relates=[5, 6])

            entries = read_adr_entries(adr_dir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].relates, [5, 6])


class TestRenderDigestSection(unittest.TestCase):
    """Unit tests for the banner digest-section renderer."""

    def test_live_rules_render_with_lineage(self):
        """Live rules render subject, live ADR, and superseded lineage."""
        section = render_digest_section(
            [
                {
                    "subject": "work-state",
                    "status": "live",
                    "live": "011-new",
                    "lineage": ["010-old"],
                    "conflict": None,
                }
            ]
        )
        self.assertIn("Current rules:", section)
        self.assertIn("- work-state: 011-new (supersedes 010-old)", section)

    def test_conflicts_render_explicit_marker(self):
        """Conflict rules render a CONFLICT marker with the reason."""
        section = render_digest_section(
            [
                {
                    "subject": "alpha",
                    "status": "conflict",
                    "live": None,
                    "lineage": [],
                    "conflict": "dual-live: 001-a, 002-b",
                }
            ]
        )
        self.assertIn("- CONFLICT alpha: dual-live: 001-a, 002-b", section)

    def test_empty_digest_renders_empty_section(self):
        """An empty digest degrades to an explicit empty section."""
        self.assertEqual(render_digest_section([]), "Current rules: none")


def _write_learnings_file(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestDurableInsights(unittest.TestCase):
    """Unit tests for the learnings reader and TopNRecentSelector."""

    def test_selector_orders_by_recency_descending(self):
        """Entries sort by timestamp descending, tolerating legacy date."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".agents" / "learnings.jsonl"
            _write_learnings_file(
                path,
                [
                    '{"timestamp": "2026-08-01T10:00:00Z", "problem": "old"}',
                    '{"date": "2026-08-03", "problem": "newest-legacy"}',
                    '{"timestamp": "2026-08-02T10:00:00Z", "problem": "middle"}',
                ],
            )
            entries = read_learnings(path)
            self.assertEqual(
                [e["problem"] for e in entries],
                ["newest-legacy", "middle", "old"],
            )

    def test_top_n_selector_caps_at_n(self):
        """TopNRecentSelector keeps only the N most recent entries."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".agents" / "learnings.jsonl"
            _write_learnings_file(
                path,
                [
                    f'{{"timestamp": "2026-08-0{i}T10:00:00Z", "problem": "p{i}"}}'
                    for i in range(1, 8)
                ],
            )
            selected = TopNRecentSelector(n=5).select(read_learnings(path))
            self.assertEqual(len(selected), 5)
            self.assertEqual(selected[0]["problem"], "p7")
            self.assertEqual(selected[-1]["problem"], "p3")

    def test_malformed_lines_are_skipped(self):
        """Malformed JSONL lines and untimed entries degrade gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".agents" / "learnings.jsonl"
            _write_learnings_file(
                path,
                [
                    '{"timestamp": "2026-08-01T10:00:00Z", "problem": "ok"}',
                    "not-json",
                    '{"problem": "no-date"}',
                    '["a", "list"]',
                ],
            )
            entries = read_learnings(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["problem"], "ok")

    def test_missing_file_yields_empty(self):
        """A missing learnings file yields an empty list, never an error."""
        entries = read_learnings(Path("/nonexistent/.agents/learnings.jsonl"))
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
