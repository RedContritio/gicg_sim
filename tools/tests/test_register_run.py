"""Unit tests for tools._meta.register_run.

DEPRECATED (core-network-generic-promotion Phase 5): the
``tools/_meta/register_run.py`` tool drives the legacy
``docs/4_runs/registry.md`` workflow which Phase 0 archived to
``docs/5_history/runs_pre_redesign_2026_05_17.md``. The replacement is
the new ``tools/runs/`` CLI suite (register / list / show / complete /
sync). These tests are kept as historical reference; the underlying
production code remains for any orphan caller but the contract these
tests assert (registry.md schema + NNN allocation policy) is no longer
load-bearing on any active workflow.

TODO: when register_run.py is finally git-rm'd, delete this test file
in the same commit."""

from __future__ import annotations

import pytest
from pathlib import Path

from tools._meta.register_run import register

# Skip the entire module — register_run.py is deprecated. See module
# docstring above for context.
pytestmark = pytest.mark.skip(
    reason='register_run.py deprecated by tools/runs/ CLI in '
    'core-network-generic-promotion Phase 5; tests kept as historical '
    'reference. TODO: rewrite against tools/runs/ or remove with the '
    'register_run.py source file.'
)


REGISTRY_TEMPLATE = """# Run Registry

## Whatever

### Bench / smoke (`s`)

| id | label | started | config | status | result |
|---|---|---|---|---|---|
| s001 | s001_foo | 2026-04-19 06:00 | smoke 100g | **done** | wall=46min |
| s002 | s002_bar | 2026-04-19 06:56 | smoke 100g | **done** | wall=37min |

### Runs (`r`)

| id | label | started | config | status | result |
|---|---|---|---|---|---|
| r001 | r001_baseline | 2026-04-19 07:44 | 400g | **done** | win_rate=0.55 |
| r002 | r002_faster | 2026-04-19 17:13 | 400g fast | **done** | win_rate=0.30 |
"""


@pytest.fixture
def registry(tmp_path) -> Path:
    p = tmp_path / 'registry.md'
    p.write_text(REGISTRY_TEMPLATE, encoding='utf-8')
    return p


def test_register_run_allocates_next_r(registry: Path):
    rid = register('r', 'r003_new', 'test config', registry_path=registry)
    assert rid == 'r003'
    text = registry.read_text()
    assert '| r003 | r003_new |' in text
    assert '**pending**' in text


def test_register_run_allocates_next_s(registry: Path):
    rid = register('s', 's003_new', 'bench', registry_path=registry)
    assert rid == 's003'
    text = registry.read_text()
    # s003 should land in the bench section, before the Runs section
    bench_idx = text.index('### Bench')
    runs_idx = text.index('### Runs')
    s003_idx = text.index('| s003 |')
    assert bench_idx < s003_idx < runs_idx


def test_register_run_rejects_duplicate_label(registry: Path):
    with pytest.raises(RuntimeError, match='already registered'):
        register('r', 'r001_baseline', 'whatever', registry_path=registry)


def test_register_run_uses_supplied_timestamp(registry: Path):
    register('r', 'r999_ts', 'x', started='2099-01-01 00:00', registry_path=registry)
    text = registry.read_text()
    assert '| r999_ts | 2099-01-01 00:00 |' in text


def test_register_run_rejects_bad_type(registry: Path):
    with pytest.raises(ValueError, match='type_prefix'):
        register('x', 'x001_bad', 'cfg', registry_path=registry)


def test_register_run_missing_section(tmp_path: Path):
    p = tmp_path / 'empty.md'
    p.write_text('# Registry\n\nNo sections here.\n', encoding='utf-8')
    with pytest.raises(RuntimeError, match='section not found'):
        register('r', 'r999_x', 'cfg', registry_path=p)


def test_register_run_status_override(registry: Path):
    register('r', 'r777_busy', 'cfg', status='in-flight', registry_path=registry)
    text = registry.read_text()
    assert '| r777_busy |' in text
    assert '**in-flight**' in text
