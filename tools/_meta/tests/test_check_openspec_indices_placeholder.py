"""Tests for placeholder whitelist in :mod:`tools._meta.check_openspec_indices`.

Contract under test
-------------------
A main ``spec.md`` may contain illustrative ``## Subtopics`` entries whose
link target is a **placeholder meta-variable** rather than a real file,
e.g. ``./<file>.md``, ``./<name>.md``, ``./[ID].md``. These MUST NOT be
treated as dead links (R2).

Real broken links (no placeholder pattern) MUST still be flagged. The
whitelist is precise, not blanket.
"""

from __future__ import annotations

from pathlib import Path

from tools._meta.check_openspec_indices import check_capability_indices


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding='utf-8')


def test_placeholder_link_not_flagged_as_dead(tmp_path: Path) -> None:
    """``./<file>.md`` meta-variable inside ## Subtopics must be ignored."""
    cap = tmp_path / 'openspec' / 'specs' / 'dummy'
    spec = cap / 'spec.md'
    _write(
        spec,
        '\n'.join(
            [
                '# Dummy',
                '',
                '## Subtopics',
                '',
                '- [Placeholder example](./<file>.md) — illustration only',
                '- [Real](./other.md) — actual sibling',
                '',
            ]
        ),
    )
    _write(cap / 'other.md', '# Other\n')

    violations = check_capability_indices(spec)

    placeholder_hits = [v for v in violations if '<file>.md' in v.message]
    assert not placeholder_hits, (
        f'placeholder link ./<file>.md was mis-flagged: {[v.format() for v in placeholder_hits]}'
    )
    assert not violations, (
        f'expected zero violations for fixture with only placeholder + real link, got: '
        f'{[v.format() for v in violations]}'
    )


def test_real_broken_link_still_flagged(tmp_path: Path) -> None:
    """Plain ``./missing.md`` (no placeholder syntax) must remain a violation."""
    cap = tmp_path / 'openspec' / 'specs' / 'dummy'
    spec = cap / 'spec.md'
    _write(
        spec,
        '\n'.join(
            [
                '# Dummy',
                '',
                '## Subtopics',
                '',
                '- [Missing](./real_missing.md) — file does not exist',
                '',
            ]
        ),
    )

    violations = check_capability_indices(spec)

    missing_hits = [v for v in violations if 'real_missing.md' in v.message]
    assert missing_hits, (
        f'expected dead-link violation for ./real_missing.md, got none. '
        f'all violations: {[v.format() for v in violations]}'
    )


def test_bracket_id_placeholder_not_flagged(tmp_path: Path) -> None:
    """``./[ID].md`` square-bracket meta-variable must also be whitelisted."""
    cap = tmp_path / 'openspec' / 'specs' / 'dummy'
    spec = cap / 'spec.md'
    _write(
        spec,
        '\n'.join(
            [
                '# Dummy',
                '',
                '## Subtopics',
                '',
                '- [Template](./[ID].md) — illustration only',
                '',
            ]
        ),
    )

    violations = check_capability_indices(spec)
    assert not violations, (
        f'expected zero violations for fixture with only [ID].md placeholder, got: {[v.format() for v in violations]}'
    )


def test_mixed_placeholder_and_dead_link(tmp_path: Path) -> None:
    """In a mixed fixture: placeholder ignored, real dead link still caught."""
    cap = tmp_path / 'openspec' / 'specs' / 'dummy'
    spec = cap / 'spec.md'
    _write(
        spec,
        '\n'.join(
            [
                '# Dummy',
                '',
                '## Subtopics',
                '',
                '- [Template](./<name>.md) — placeholder',
                '- [Missing](./gone.md) — real dead link',
                '- [Real](./present.md) — exists',
                '',
            ]
        ),
    )
    _write(cap / 'present.md', '# Present\n')

    violations = check_capability_indices(spec)

    placeholder_hits = [v for v in violations if '<name>.md' in v.message]
    assert not placeholder_hits, f'placeholder ./<name>.md mis-flagged: {[v.format() for v in placeholder_hits]}'
    dead_hits = [v for v in violations if 'gone.md' in v.message]
    assert dead_hits, (
        f'expected dead-link violation for ./gone.md, got none. all violations: {[v.format() for v in violations]}'
    )
