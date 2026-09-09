"""Declarative documentation governance rule engine for ``aet docs lint``.

Rules are data, parsed with ``yaml.safe_load``, and evaluated against the
checkout. The evaluator never executes rule content.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

from aet.context_digest import AdrEntry, audit_adr_entries

VALID_RULE_TYPES = frozenset(
    {
        "must_contain",
        "must_not_contain",
        "path_exists",
        "path_absent",
        "unique_live_subject",
        "adr_corpus_integrity",
        "code_anchor_resolves",
        "retired_path_absent",
    }
)

_ESCAPE_CLOSED_RE = re.compile(r"<!-- aet-lint: off -->.*?<!-- aet-lint: on -->", re.DOTALL)
_ESCAPE_UNCLOSED_RE = re.compile(r"<!-- aet-lint: off -->.*", re.DOTALL)


def strip_lint_escapes(text: str) -> str:
    """Remove escaped spans between ``<!-- aet-lint: off -->`` and ``<!-- aet-lint: on -->``.

    Treats an unclosed ``<!-- aet-lint: off -->`` as running to the end of the document.
    A document without markers is returned byte-identical.
    """
    if "<!-- aet-lint: off -->" not in text:
        return text
    stripped = _ESCAPE_CLOSED_RE.sub("", text)
    if "<!-- aet-lint: off -->" in stripped:
        stripped = _ESCAPE_UNCLOSED_RE.sub("", stripped)
    return stripped


_strip_lint_escapes = strip_lint_escapes


class DocsLintError(Exception):
    """Raised for unrecoverable rule-file errors."""


class RuleError(DocsLintError):
    """Raised when a single rule is malformed."""

    def __init__(self, index: int, message: str) -> None:
        self.index = index
        super().__init__(f"rule {index}: {message}")


def _relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _load_rules(rules_file: Path) -> list[dict]:
    """Load and return the raw rule list from *rules_file*."""
    if not rules_file.exists():
        raise DocsLintError(f"rules file not found: {rules_file}")
    try:
        data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DocsLintError(f"invalid YAML: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, dict):
        raise DocsLintError("top-level must be a mapping")
    rules = data.get("rules")
    if rules is None:
        return []
    if not isinstance(rules, list):
        raise DocsLintError("'rules' must be a list")
    return rules


def _normalize_values(value: object) -> list[str]:
    """Return *value* as a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise DocsLintError("'value' must be a string or list of strings")


def _extract_section(text: str, section: str) -> str | None:
    """Return the body under the first ATX heading matching *section*.

    The body runs from the line after the heading until the next heading of
    equal or higher level (fewer ``#`` characters).
    """
    text = strip_lint_escapes(text)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        hashes = stripped.split()[0]
        if not hashes or not all(ch == "#" for ch in hashes):
            continue
        level = len(hashes)
        title = stripped[level:].strip()
        if title == section:
            body_lines: list[str] = []
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                next_stripped = next_line.lstrip()
                if next_stripped.startswith("#"):
                    next_hashes = next_stripped.split()[0]
                    if next_hashes and all(ch == "#" for ch in next_hashes):
                        next_level = len(next_hashes)
                        if next_level <= level:
                            break
                body_lines.append(next_line)
            return "\n".join(body_lines)
    return None


def _adr_id_from_path(path: Path) -> str:
    """Return an ``ADR-NNN`` style identifier from *path*'s filename stem."""
    stem = path.stem
    number_part = stem.split("-", 1)[0]
    if number_part.isdigit():
        return f"ADR-{int(number_part):03d}"
    return stem


def _load_adr_frontmatter(path: Path) -> tuple[dict | None, str | None]:
    """Load YAML frontmatter from an ADR markdown file.

    Returns ``(data, error)``. *data* is ``None`` when the file has no
    frontmatter block. *error* is a non-empty diagnostic string when the
    frontmatter block exists but cannot be parsed.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, None
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return None, "missing closing frontmatter delimiter"
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        return None, f"malformed frontmatter: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "frontmatter must be a mapping"
    return data, None


def _normalize_adr_id(value: object) -> str | None:
    """Return an ``ADR-NNN`` identifier from a *supersedes* value."""
    if isinstance(value, int):
        return f"ADR-{value:03d}"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return f"ADR-{int(stripped):03d}"
        upper = stripped.upper()
        if upper.startswith("ADR-"):
            return upper
    return None


def _evaluate_unique_live_subject(
    target_path: Path, reason: str, repo_root: Path
) -> list[tuple[Path, str]]:
    """Evaluate the ``unique_live_subject`` rule against *target_path*."""
    violations: list[tuple[Path, str]] = []
    subjects: dict[str, list[tuple[str, Path]]] = {}
    superseded: set[str] = set()

    for md_path in sorted(target_path.glob("*.md")):
        if md_path.name in ("000-template.md", "README.md"):
            continue

        rel = _relative(md_path, repo_root)
        data, error = _load_adr_frontmatter(md_path)
        if error:
            violations.append((rel, f"{reason} ({error})"))
            continue
        if data is None:
            # ADRs without frontmatter have no subject and cannot participate
            # in subject uniqueness. The adr_corpus_integrity rule validates
            # frontmatter presence separately.
            continue

        adr_id = _adr_id_from_path(md_path)

        raw_subject = data.get("subject")
        if raw_subject is None:
            # Missing subject is validated by adr_corpus_integrity.
            continue
        if isinstance(raw_subject, str):
            subject_values = [raw_subject]
        elif isinstance(raw_subject, list) and all(isinstance(s, str) for s in raw_subject):
            subject_values = raw_subject
        else:
            violations.append((rel, f"{reason} ('subject' must be a string or list of strings)"))
            continue

        raw_supersedes = data.get("supersedes", [])
        if isinstance(raw_supersedes, (str, int)):
            raw_supersedes = [raw_supersedes]
        if not isinstance(raw_supersedes, list):
            violations.append((rel, f"{reason} ('supersedes' must be a list)"))
            continue

        for value in raw_supersedes:
            normalized = _normalize_adr_id(value)
            if normalized is None:
                violations.append((rel, f"{reason} (invalid 'supersedes' value: {value!r})"))
                continue
            superseded.add(normalized)

        for subject in subject_values:
            subjects.setdefault(subject, []).append((adr_id, rel))

    for subject, entries in sorted(subjects.items()):
        live = [(adr_id, rel) for adr_id, rel in entries if adr_id not in superseded]
        if len(live) > 1:
            ids = ", ".join(sorted(adr_id for adr_id, _ in live))
            first_path = live[0][1]
            violations.append((first_path, f"{reason} (subject '{subject}' has multiple live ADRs: {ids})"))

    return violations


def _normalize_adr_number(value: object) -> int | None:
    """Return an integer ADR number from a supersedes/relates reference."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip().lstrip("#")
        stripped = re.sub(r"(?i)^adr-?", "", stripped)
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _extract_adr_number(stem: str) -> int | None:
    """Extract leading integer from ADR filename stem."""
    number_part = stem.split("-", 1)[0]
    if number_part.isdigit():
        return int(number_part)
    return None


def _evaluate_adr_corpus_integrity(
    target_path: Path, reason: str, repo_root: Path
) -> list[tuple[Path, str]]:
    """Evaluate the ``adr_corpus_integrity`` rule against *target_path*."""
    violations: list[tuple[Path, str]] = []
    valid_entries: list[AdrEntry] = []
    entry_paths: dict[str, Path] = {}

    for md_path in sorted(target_path.glob("*.md")):
        if md_path.name in ("000-template.md", "README.md"):
            continue

        rel = _relative(md_path, repo_root)
        data, error = _load_adr_frontmatter(md_path)
        if error:
            violations.append((rel, f"{reason} ({error})"))
            continue
        if data is None:
            violations.append((rel, f"{reason} (missing 'subject')"))
            continue

        raw_subject = data.get("subject")
        if raw_subject is None:
            violations.append((rel, f"{reason} (missing 'subject')"))
            continue
        if isinstance(raw_subject, str):
            if not raw_subject.strip():
                violations.append((rel, f"{reason} (missing 'subject')"))
                continue
            subjects = [raw_subject.strip()]
        elif isinstance(raw_subject, list) and all(isinstance(s, str) for s in raw_subject):
            subjects = [s.strip() for s in raw_subject if s.strip()]
            if not subjects:
                violations.append((rel, f"{reason} (missing 'subject')"))
                continue
        else:
            violations.append((rel, f"{reason} ('subject' must be a string or list of strings)"))
            continue

        raw_supersedes = data.get("supersedes", [])
        if isinstance(raw_supersedes, (str, int)):
            raw_supersedes = [raw_supersedes]
        if not isinstance(raw_supersedes, list):
            violations.append((rel, f"{reason} ('supersedes' must be a list)"))
            continue

        supersedes_nums: list[int] = []
        has_supersedes_error = False
        for value in raw_supersedes:
            num = _normalize_adr_number(value)
            if num is None:
                violations.append((rel, f"{reason} (invalid 'supersedes' value: {value!r})"))
                has_supersedes_error = True
            else:
                supersedes_nums.append(num)

        raw_relates = data.get("relates", [])
        if isinstance(raw_relates, (str, int)):
            raw_relates = [raw_relates]
        if not isinstance(raw_relates, list):
            violations.append((rel, f"{reason} ('relates' must be a list)"))
            continue

        relates_nums: list[int] = []
        has_relates_error = False
        for value in raw_relates:
            num = _normalize_adr_number(value)
            if num is None:
                violations.append((rel, f"{reason} (invalid 'relates' value: {value!r})"))
                has_relates_error = True
            else:
                relates_nums.append(num)

        if not has_supersedes_error and not has_relates_error:
            entry_stem = md_path.stem
            entry_num = _extract_adr_number(entry_stem)
            valid_entries.append(
                AdrEntry(
                    stem=entry_stem,
                    number=entry_num,
                    subject=subjects[0],
                    supersedes=supersedes_nums,
                    relates=relates_nums,
                )
            )
            entry_paths[entry_stem] = rel

    report = audit_adr_entries(valid_entries)

    for num in sorted(report.duplicate_numbers):
        stems = report.duplicate_numbers[num]
        ids = ", ".join(stems)
        first_path = entry_paths[stems[0]]
        violations.append((first_path, f"{reason} (duplicate ADR number {num:03d}: {ids})"))

    for stem in sorted(report.dangling_supersedes):
        rel = entry_paths[stem]
        for num in report.dangling_supersedes[stem]:
            violations.append((rel, f"{reason} (dangling supersedes: ADR-{num:03d} does not exist)"))

    for stem in sorted(report.dangling_relates):
        rel = entry_paths[stem]
        for num in report.dangling_relates[stem]:
            violations.append((rel, f"{reason} (dangling relates: ADR-{num:03d} does not exist)"))

    for stem in sorted(report.superseded_relates):
        rel = entry_paths[stem]
        for num in report.superseded_relates[stem]:
            violations.append((rel, f"{reason} (relates to superseded ADR-{num:03d})"))

    return violations


_LINE_ANCHOR_RE = re.compile(
    r"""(?x)
    (?:^|[\s`(\[\"'])
    (?P<full_match>
        (?P<target>
            (?:[a-zA-Z0-9_.\-\/]+\.(?:py|sh|json|yaml|yml|md|toml|html|js|ts|rs|go|c|h|cpp))
            |
            (?:Makefile|Dockerfile|Containerfile)
            |
            (?:(?:src|skills|aet-work|scripts|docs|tests)/[a-zA-Z0-9_.\-\/]+)
            |
            (?:orchestrator|aet-state|queue|pipeline|telemetry|verifier)
        )
        :
        (?P<lines>\d+(?:[-–—]\d+)?(?:,\s*\d+(?:[-–—]\d+)?)*)
    )
    (?=[\s`\)\]\"',\.]|$)
    """
)

_PROSE_ANCHOR_RE = re.compile(
    r"""(?x)
    (?P<symbols>(?:`[a-zA-Z_][a-zA-Z0-9_.]*(?:\(\))?`(?:\s*(?:,|and)\s*)?)+)
    \s+(?:in|at)\s+
    `(?P<path>(?:[a-zA-Z0-9_.\-\/]+\.[a-zA-Z0-9]+)|Makefile|Dockerfile)`
    """
)

_PAREN_ANCHOR_RE = re.compile(
    r"""(?x)
    `(?P<sym>[a-zA-Z_][a-zA-Z0-9_.]*(?:\(\))?)`
    \s*
    \((?:in\s+)?`(?P<path>[a-zA-Z0-9_.\-\/]+\.[a-zA-Z0-9]+)`\)
    """
)


def _extract_target_names(node: ast.AST) -> list[str]:
    """Extract identifier names from an AST assignment target."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in node.elts:
            names.extend(_extract_target_names(elt))
        return names
    return []


def _collect_ast_symbols(node: ast.AST, prefix: str = "") -> set[str]:
    """Recursively collect defined symbol names from Python AST."""
    symbols: set[str] = set()
    for item in getattr(node, "body", []):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(item.name)
            if prefix:
                symbols.add(f"{prefix}.{item.name}")
            symbols.update(_collect_ast_symbols(item, prefix=f"{prefix}.{item.name}" if prefix else item.name))
        elif isinstance(item, ast.ClassDef):
            symbols.add(item.name)
            if prefix:
                symbols.add(f"{prefix}.{item.name}")
            symbols.update(_collect_ast_symbols(item, prefix=f"{prefix}.{item.name}" if prefix else item.name))
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                for name in _extract_target_names(target):
                    symbols.add(name)
                    if prefix:
                        symbols.add(f"{prefix}.{name}")
        elif isinstance(item, (ast.AnnAssign, ast.AugAssign)):
            target = getattr(item, "target", None)
            if target is not None:
                for name in _extract_target_names(target):
                    symbols.add(name)
                    if prefix:
                        symbols.add(f"{prefix}.{name}")
        elif isinstance(item, ast.Import):
            for alias in item.names:
                name = alias.asname or alias.name
                symbols.add(name)
                if prefix:
                    symbols.add(f"{prefix}.{name}")
        elif isinstance(item, ast.ImportFrom):
            for alias in item.names:
                if alias.asname:
                    symbols.add(alias.asname)
                symbols.add(alias.name)
                if prefix:
                    if alias.asname:
                        symbols.add(f"{prefix}.{alias.asname}")
                    symbols.add(f"{prefix}.{alias.name}")
    return symbols


def _extract_table_anchors(text: str) -> list[tuple[str, str]]:
    """Extract (symbol, target_module) pairs from markdown tables."""
    anchors: list[tuple[str, str]] = []
    lines = text.splitlines()
    in_table = False
    symbol_col = -1
    module_col = -1

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if not in_table:
                lower_cells = [c.lower() for c in cells]
                sym_indices = [i for i, c in enumerate(lower_cells) if "symbol" in c]
                mod_indices = [
                    i
                    for i, c in enumerate(lower_cells)
                    if any(k in c for k in ("module", "target", "file", "path"))
                ]
                if sym_indices and mod_indices:
                    in_table = True
                    symbol_col = sym_indices[0]
                    module_col = mod_indices[0]
                    continue
            else:
                if all(set(c).issubset({"-", ":", " "}) and c for c in cells):
                    continue
                if len(cells) > max(symbol_col, module_col):
                    sym_cell = cells[symbol_col]
                    mod_cell = cells[module_col]
                    raw_syms = re.split(r",", sym_cell)
                    mod = mod_cell.strip(" `\"'")
                    mod_tokens = [t.strip(" `\"'") for t in mod.split()]
                    target_mod = mod_tokens[0] if mod_tokens else ""
                    if not target_mod:
                        continue
                    for raw_s in raw_syms:
                        s = raw_s.strip(" `\"'()")
                        if s:
                            anchors.append((s, target_mod))
        else:
            in_table = False
    return anchors


def _extract_prose_anchors(text: str) -> list[tuple[str, str]]:
    """Extract (symbol, target_module) pairs from prose patterns."""
    anchors: list[tuple[str, str]] = []
    for m in _PROSE_ANCHOR_RE.finditer(text):
        path = m.group("path").strip()
        if "." in path or "/" in path or path == "Makefile":
            syms = [
                s.removesuffix("()")
                for s in re.findall(r"`([a-zA-Z_][a-zA-Z0-9_.]*(?:\(\))?)`", m.group("symbols"))
            ]
            for s in syms:
                if s:
                    anchors.append((s, path))
    for m in _PAREN_ANCHOR_RE.finditer(text):
        path = m.group("path").strip()
        sym = m.group("sym").removesuffix("()").strip()
        if sym and ("." in path or "/" in path or path == "Makefile"):
            anchors.append((sym, path))
    return anchors


def _check_doc_code_anchors(text: str, reason: str, repo_root: Path) -> list[str]:
    """Check code anchors within a single markdown document."""
    stripped = strip_lint_escapes(text)
    violations: list[str] = []

    # 1. Line anchor checks
    for m in _LINE_ANCHOR_RE.finditer(stripped):
        full_match = m.group("full_match")
        violations.append(f"{reason} (line anchor forbidden: '{full_match}')")

    # 2. Table and prose symbol anchors
    anchors = _extract_table_anchors(stripped) + _extract_prose_anchors(stripped)

    seen: set[tuple[str, str]] = set()
    unique_anchors: list[tuple[str, str]] = []
    for a in anchors:
        if a not in seen:
            seen.add(a)
            unique_anchors.append(a)

    for symbol, target_path_str in unique_anchors:
        target_path = Path(target_path_str)
        if not target_path.is_absolute():
            resolved_target = repo_root / target_path
        else:
            resolved_target = target_path

        if not resolved_target.exists() or resolved_target.is_dir():
            violations.append(f"{reason} (anchored file does not exist: '{target_path_str}')")
            continue

        if resolved_target.suffix == ".py":
            try:
                tree = ast.parse(resolved_target.read_text(encoding="utf-8"))
                py_symbols = _collect_ast_symbols(tree)
            except Exception as exc:
                violations.append(
                    f"{reason} (cannot parse Python file '{target_path_str}': {exc})"
                )
                continue
            if symbol not in py_symbols and ("." not in symbol or symbol.split(".")[-1] not in py_symbols):
                violations.append(
                    f"{reason} (symbol '{symbol}' does not resolve in '{target_path_str}')"
                )
        else:
            try:
                content = resolved_target.read_text(encoding="utf-8")
            except Exception as exc:
                violations.append(f"{reason} (cannot read file '{target_path_str}': {exc})")
                continue
            if symbol not in content:
                violations.append(
                    f"{reason} (symbol '{symbol}' not found in '{target_path_str}' (occurrence matching))"
                )

    return violations


def _evaluate_code_anchor_resolves(
    target_path: Path, reason: str, repo_root: Path
) -> list[tuple[Path, str]]:
    """Evaluate the ``code_anchor_resolves`` rule against *target_path*."""
    violations: list[tuple[Path, str]] = []

    if target_path.is_dir():
        md_files = sorted(target_path.rglob("*.md"))
        if not md_files:
            rel = _relative(target_path, repo_root)
            return [(rel, f"{reason} (no markdown files found in directory: {rel})")]
    elif target_path.is_file():
        md_files = [target_path]
    else:
        rel = _relative(target_path, repo_root)
        return [(rel, f"{reason} (target path missing: {rel})")]

    for md_path in md_files:
        rel = _relative(md_path, repo_root)
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append((rel, f"{reason} (cannot read file: {exc})"))
            continue

        doc_violations = _check_doc_code_anchors(text, reason, repo_root)
        for msg in doc_violations:
            violations.append((rel, msg))

    return violations


def _validate_rule(raw: object, index: int) -> dict:
    """Validate and normalize a single rule mapping."""
    if not isinstance(raw, dict):
        raise RuleError(index, "must be a mapping")
    rule = dict(raw)
    missing = [k for k in ("type", "target", "reason") if k not in rule]
    if missing:
        raise RuleError(index, f"missing required fields: {', '.join(missing)}")
    rtype = rule["type"]
    if rtype not in VALID_RULE_TYPES:
        raise RuleError(index, f"unknown type '{rtype}'")
    if rtype in ("must_contain", "must_not_contain"):
        if "value" not in rule:
            raise RuleError(index, f"'value' is required for {rtype}")
        rule["value"] = _normalize_values(rule["value"])
    no_value_rules = ("unique_live_subject", "adr_corpus_integrity", "code_anchor_resolves", "retired_path_absent")
    if rtype in no_value_rules and "value" in rule:
        raise RuleError(index, f"'value' is not allowed for {rtype}")
    severity = rule.get("severity", "error")
    if severity not in ("error", "warning"):
        raise RuleError(index, f"invalid severity '{severity}', must be 'error' or 'warning'")
    rule["severity"] = severity
    return rule


def _check_retired_paths(path: Path, text: str, rule: dict, reason: str) -> str | None:
    """Evaluate a ``retired_path_absent`` rule against *text*."""
    text = strip_lint_escapes(text)
    section = rule.get("section")
    haystack = text
    section_note = ""
    if section:
        section_body = _extract_section(text, section)
        if section_body is None:
            return f"{reason} (section not found: {section})"
        haystack = section_body
        section_note = f" in section '{section}'"

    from aet import worktree

    present = [p for p in sorted(worktree.AET_RETIRED_IGNORED_PATHS) if p in haystack]
    if present:
        plural = "" if len(present) == 1 else "s"
        return f"{reason} (found retired path{plural} {present!r}{section_note})"
    return None


def _check_text(path: Path, text: str, rule: dict, reason: str) -> str | None:
    """Evaluate a ``must_contain`` or ``must_not_contain`` rule against *text*."""
    text = strip_lint_escapes(text)
    section = rule.get("section")
    haystack = text
    section_note = ""
    if section:
        section_body = _extract_section(text, section)
        if section_body is None:
            return f"{reason} (section not found: {section})"
        haystack = section_body
        section_note = f" in section '{section}'"

    values = rule["value"]
    rtype = rule["type"]
    if rtype == "must_contain":
        missing = [v for v in values if v not in haystack]
        if missing:
            return f"{reason} (expected {missing!r}{section_note})"
    elif rtype == "must_not_contain":
        present = [v for v in values if v in haystack]
        if present:
            plural = "" if len(present) == 1 else "s"
            return f"{reason} (found forbidden substring{plural} {present!r}{section_note})"
    return None


def lint_docs(
    rules_file: Path, repo_root: Path, min_severity: str = "error"
) -> list[tuple[Path, str]]:
    """Evaluate the documentation rules file against the checkout.

    Returns a list of ``(relative_path, message)`` violations. An empty list
    means every rule passed.
    """
    rel_rules = _relative(rules_file, repo_root)
    try:
        raw_rules = _load_rules(rules_file)
    except DocsLintError as exc:
        return [(rel_rules, f"cannot load rules: {exc}")]

    rules: list[tuple[int, dict]] = []
    for idx, raw in enumerate(raw_rules, start=1):
        try:
            rule = _validate_rule(raw, idx)
        except DocsLintError as exc:
            return [(rel_rules, str(exc))]
        rules.append((idx, rule))

    violations: list[tuple[Path, str]] = []
    for _idx, rule in rules:
        rule_severity = rule.get("severity", "error")
        if min_severity == "error" and rule_severity == "warning":
            continue

        target = Path(rule["target"])
        if target.is_absolute():
            target_path = target
            rel_target = _relative(target_path, repo_root)
        else:
            target_path = repo_root / target
            rel_target = target

        rtype = rule["type"]
        reason = rule["reason"]

        if rtype in ("path_exists", "path_absent"):
            exists = target_path.exists()
            if rtype == "path_exists" and not exists:
                violations.append((rel_target, f"{reason} (expected path to exist: {target})"))
            elif rtype == "path_absent" and exists:
                violations.append((rel_target, f"{reason} (expected path to be absent: {target})"))
            continue

        if rtype == "unique_live_subject":
            if not target_path.exists():
                violations.append((rel_target, f"{reason} (target directory missing: {target})"))
            elif not target_path.is_dir():
                violations.append((rel_target, f"{reason} (target must be a directory: {target})"))
            else:
                violations.extend(_evaluate_unique_live_subject(target_path, reason, repo_root))
            continue

        if rtype == "adr_corpus_integrity":
            if not target_path.exists():
                violations.append((rel_target, f"{reason} (target directory missing: {target})"))
            elif not target_path.is_dir():
                violations.append((rel_target, f"{reason} (target must be a directory: {target})"))
            else:
                violations.extend(_evaluate_adr_corpus_integrity(target_path, reason, repo_root))
            continue

        if rtype == "code_anchor_resolves":
            if not target_path.exists():
                violations.append((rel_target, f"{reason} (target path missing: {target})"))
            else:
                violations.extend(_evaluate_code_anchor_resolves(target_path, reason, repo_root))
            continue

        if target_path.is_dir() and rtype in ("must_contain", "must_not_contain", "retired_path_absent"):
            found_any = False
            for md_path in sorted(target_path.rglob("*.md")):
                found_any = True
                rel_md = _relative(md_path, repo_root)
                try:
                    text = md_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    violations.append((rel_md, f"{reason} (cannot read file: {exc})"))
                    continue
                if rtype == "retired_path_absent":
                    message = _check_retired_paths(md_path, text, rule, reason)
                else:
                    message = _check_text(md_path, text, rule, reason)
                if message:
                    violations.append((rel_md, message))
            if not found_any:
                violations.append((rel_target, f"{reason} (no markdown files found in directory: {target})"))
            continue

        if not target_path.exists():
            violations.append((rel_target, f"{reason} (target file missing: {target})"))
            continue
        try:
            text = target_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append((rel_target, f"{reason} (cannot read file: {exc})"))
            continue

        if rtype == "retired_path_absent":
            message = _check_retired_paths(target_path, text, rule, reason)
        else:
            message = _check_text(target_path, text, rule, reason)
        if message:
            violations.append((rel_target, message))

    return violations
