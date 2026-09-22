"""Tests for ``tools/_meta/check_openspec_indices.py``.

Covers R1 (主 spec Subtopics 索引完整) + R2 (索引链有效)
+ R3 (change 三件套) + R5 (subtopic 文件不被当主 spec 扫描).

Tests use ``tmp_path`` fixtures to be xdist-safe with four workers.
The final test runs against the real repo ``openspec/`` tree as a
smoke test that the policy spec itself is index-clean.
"""

from __future__ import annotations

from pathlib import Path

from tools._meta.check_openspec_indices import (
    REPO_ROOT,
    check_capability_indices,
    check_change_triplet,
    check_full_tree,
    check_paths,
    parse_subtopics,
)


def _write(path: Path, body: str) -> None:
    """Helper: ensure parent exists, write file with utf-8 + trailing nl."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not body.endswith('\n'):
        body += '\n'
    path.write_text(body, encoding='utf-8')


def _make_capability(cap_dir: Path, subtopics_list: str, sibling_files: list[str]) -> Path:
    """Create a fake ``<cap>/spec.md`` with given Subtopics body, plus
    actual sibling .md files. Returns the spec.md path."""
    spec_md = cap_dir / 'spec.md'
    _write(
        spec_md,
        f"""# Fake Capability

## 1. Purpose

Fake.

## 2. Subtopics

{subtopics_list}

## 3. Status

stub.
""",
    )
    for fname in sibling_files:
        _write(cap_dir / fname, f'# {fname}\n\nstub subtopic.\n')
    return spec_md


# ---------------------------------------------------------------------------
# R1 / R2 — capability index
# ---------------------------------------------------------------------------


def test_r1_pass_complete_index(tmp_path: Path) -> None:
    """All siblings listed, all links valid → no violations."""
    cap = tmp_path / 'openspec' / 'specs' / 'foo'
    spec_md = _make_capability(
        cap,
        '- [A](./a.md) — first\n- [B](./b.md) — second\n- [C](./c.md) — third',
        sibling_files=['a.md', 'b.md', 'c.md'],
    )
    assert check_capability_indices(spec_md) == []


def test_r1_fail_missing_index_entry(tmp_path: Path) -> None:
    """sibling c.md exists but not listed → R1 violation."""
    cap = tmp_path / 'openspec' / 'specs' / 'foo'
    spec_md = _make_capability(
        cap,
        '- [A](./a.md) — first\n- [B](./b.md) — second',
        sibling_files=['a.md', 'b.md', 'c.md'],
    )
    violations = check_capability_indices(spec_md)
    assert len(violations) == 1
    v = violations[0]
    assert 'c.md' in v.message
    assert 'missing Subtopics index entry' in v.message
    assert v.line is not None  # points at Subtopics header


def test_r2_fail_dead_link(tmp_path: Path) -> None:
    """index lists c.md but file doesn't exist → R2 violation."""
    cap = tmp_path / 'openspec' / 'specs' / 'foo'
    spec_md = _make_capability(
        cap,
        '- [A](./a.md) — first\n- [B](./b.md) — second\n- [C](./c.md) — missing!',
        sibling_files=['a.md', 'b.md'],
    )
    violations = check_capability_indices(spec_md)
    assert len(violations) == 1
    v = violations[0]
    assert 'c.md' in v.message
    assert 'dead Subtopics link' in v.message


def test_subtopics_header_with_number_prefix(tmp_path: Path) -> None:
    """Real repo uses '## 4. Subtopics'; parser must accept numeric prefix."""
    cap = tmp_path / 'openspec' / 'specs' / 'foo'
    _write(
        cap / 'spec.md',
        """# Cap

## 1. Purpose

stub.

## 4. Subtopics

- [A](./a.md) — first

## 5. Other

stub.
""",
    )
    _write(cap / 'a.md', '# a\n')
    entries, header_line = parse_subtopics(cap / 'spec.md')
    assert [t for t, _ in entries] == ['a.md']
    assert header_line is not None
    assert check_capability_indices(cap / 'spec.md') == []


def test_subtopics_section_ends_at_next_h2(tmp_path: Path) -> None:
    """Links after the next ## header must NOT be counted as Subtopics entries."""
    cap = tmp_path / 'openspec' / 'specs' / 'foo'
    _write(
        cap / 'spec.md',
        """# Cap

## Subtopics

- [A](./a.md) — first

## Cross-references

- [B](./b.md) — should not be counted
""",
    )
    _write(cap / 'a.md', '# a\n')
    # b.md does not exist; if parser incorrectly captured the link in
    # Cross-references, we'd get a dead-link violation. Verify clean.
    entries, _ = parse_subtopics(cap / 'spec.md')
    assert [t for t, _ in entries] == ['a.md']
    assert check_capability_indices(cap / 'spec.md') == []


# ---------------------------------------------------------------------------
# R3 — change triplet
# ---------------------------------------------------------------------------


def test_r3_pass_all_three_flat(tmp_path: Path) -> None:
    """proposal.md + design.md + tasks.md all present → clean."""
    chg = tmp_path / 'changes' / 'foo'
    _write(chg / 'proposal.md', '# p\n')
    _write(chg / 'design.md', '# d\n')
    _write(chg / 'tasks.md', '# t\n')
    assert check_change_triplet(chg) == []


def test_r3_fail_missing_proposal(tmp_path: Path) -> None:
    """Only design + tasks present → R3 violation for proposal."""
    chg = tmp_path / 'changes' / 'foo'
    _write(chg / 'design.md', '# d\n')
    _write(chg / 'tasks.md', '# t\n')
    violations = check_change_triplet(chg)
    assert len(violations) == 1
    assert "'proposal.md'" in violations[0].message


def test_r3_pass_with_subdir_for_design_and_tasks(tmp_path: Path) -> None:
    """proposal.md + design/ dir + tasks/ dir → accepted (R3 三件套
    permits subdir form for design/tasks)."""
    chg = tmp_path / 'changes' / 'foo'
    _write(chg / 'proposal.md', '# p\n')
    _write(chg / 'design' / 'architecture.md', '# arch\n')
    _write(chg / 'tasks' / 'phase1.md', '# tasks\n')
    assert check_change_triplet(chg) == []


def test_r3_fail_missing_design_and_tasks(tmp_path: Path) -> None:
    """proposal.md alone → 2 violations (design + tasks)."""
    chg = tmp_path / 'changes' / 'foo'
    _write(chg / 'proposal.md', '# p\n')
    violations = check_change_triplet(chg)
    assert len(violations) == 2
    msgs = ' '.join(v.message for v in violations)
    assert "'design.md'" in msgs
    assert "'tasks.md'" in msgs


# ---------------------------------------------------------------------------
# R5 — subtopic files are NOT scanned as main spec
# ---------------------------------------------------------------------------


def test_r5_subtopic_with_placeholder_link_is_not_scanned(tmp_path: Path) -> None:
    """A subtopic file (e.g. file-layout.md) may contain ``./bar.md``
    placeholders referring to non-existent files. ``check_full_tree``
    only scans ``<cap>/spec.md``, so the subtopic's placeholders must
    NOT be flagged as dead links.
    """
    cap = tmp_path / 'openspec' / 'specs' / 'foo'
    _write(
        cap / 'spec.md',
        """# Cap

## Subtopics

- [Layout](./file-layout.md) — layout rules
""",
    )
    # file-layout.md exists, but contains a placeholder dead link.
    _write(
        cap / 'file-layout.md',
        """# Layout

See [example](./bar.md) — but bar.md does NOT exist; this is a placeholder.
""",
    )
    # full_tree should find zero violations (subtopic body not scanned).
    violations = check_full_tree(tmp_path / 'openspec')
    assert violations == [], f'expected no violations, got {[v.format() for v in violations]}'


def test_r5_subtopic_path_passed_explicitly_is_ignored(tmp_path: Path) -> None:
    """Even if user passes a subtopic .md to ``check_paths``, it's not a
    main spec → no scan. (Subtopic only validated indirectly via its
    parent spec.md.)"""
    cap = tmp_path / 'openspec' / 'specs' / 'foo'
    _write(
        cap / 'spec.md',
        '# Cap\n\n## Subtopics\n\n- [Sub](./sub.md) — stub\n',
    )
    sub = cap / 'sub.md'
    _write(sub, '# Sub\n\n[dead](./nope.md) placeholder\n')
    # Pass the subtopic file: nothing to check.
    assert check_paths([sub]) == []


# ---------------------------------------------------------------------------
# Full-tree smoke: real repo openspec/ must be clean
# ---------------------------------------------------------------------------


def test_real_openspec_tree_is_clean() -> None:
    """Real ``openspec/`` tree (as of P0-T5) must pass all checks.

    This is the reference implementation of the policy; if it fails,
    something regressed in the spec files themselves (and the hook
    would block all commits to openspec/).
    """
    openspec_root = REPO_ROOT / 'openspec'
    assert openspec_root.is_dir(), 'openspec/ should exist (P0-T1)'
    violations = check_full_tree(openspec_root)
    assert violations == [], 'real openspec/ tree has index violations:\n  ' + '\n  '.join(
        v.format() for v in violations
    )


def test_check_paths_with_real_spec_md() -> None:
    """Passing the real openspec-policy spec.md path explicitly → clean."""
    spec_md = REPO_ROOT / 'openspec' / 'specs' / 'openspec-policy' / 'spec.md'
    if not spec_md.exists():
        return  # skip if T3 hasn't landed yet
    assert check_paths([spec_md]) == []
