"""T-27 — Windows path normalization edge tests for tools.runs.helpers.

Spec §测试矩阵 §Windows path tests 行 412-415:
    Windows-form path `configs\\dmc\\x.toml` → `normalize_repo_relative`
    返 forward-slash (`.as_posix()`).

The baseline assertion (Windows-form input → forward-slash output) is
already covered by T-02's :func:`test_normalize_windows_form_uses_forward_slash`
in ``test_helpers_basic.py``. This file adds **cross-platform pure-path
edge cases** that the baseline does not exercise:

- ``PureWindowsPath`` parsed segments with explicit single-backslash
  literal in source (``'configs\\dmc\\x.toml'``) — documents that the
  conversion contract holds for raw literal Windows-form strings, not
  just hand-constructed ``Path`` objects.
- ``PurePosixPath`` round-trip sanity — confirms POSIX-form inputs are
  preserved unchanged (separator already ``/``).
- ``PureWindowsPath`` mixed-separator (``configs/dmc\\x.toml``) — Windows
  tolerates both; ``.parts`` still segments correctly, output must still
  be forward-slash.
- Deep nesting (4+ segments) — guards against any per-segment join logic
  that might lose intermediate slashes.

Implementation note: we never call ``Path()`` directly on Windows-form
strings, because on POSIX hosts ``Path('configs\\dmc\\x.toml')`` is a
single-segment opaque path. Instead we use ``PureWindowsPath().parts``
to extract the platform-correct segments, then ``tmp_path.joinpath(*parts)``
to materialize the file under the repo root. This makes the test
deterministic on both POSIX and Windows runners.
"""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from tools.runs.helpers import normalize_repo_relative


# --- PureWindowsPath inputs (cross-platform) ---------------------------------


def test_windows_form_literal_backslash_string(tmp_path: Path) -> None:
    # Literal Windows-form string in source — `'configs\\dmc\\x.toml'`
    # is the 3-char-segment path `configs\dmc\x.toml`. Use PureWindowsPath
    # to platform-portably extract segments.
    win_form = 'configs\\dmc\\x.toml'
    parts = PureWindowsPath(win_form).parts
    assert parts == ('configs', 'dmc', 'x.toml')

    (tmp_path / 'configs' / 'dmc').mkdir(parents=True)
    cfg = tmp_path.joinpath(*parts)
    cfg.write_text('', encoding='utf-8')

    result = normalize_repo_relative(cfg, tmp_path, 'cfg')
    assert result == 'configs/dmc/x.toml'
    assert '\\' not in result


def test_windows_form_mixed_separators(tmp_path: Path) -> None:
    # Windows tolerates mixed forward/backward separators. PureWindowsPath
    # normalizes both during `.parts` extraction; normalize_repo_relative
    # output must still be all forward-slash.
    mixed = 'configs/dmc\\x.toml'
    parts = PureWindowsPath(mixed).parts
    assert parts == ('configs', 'dmc', 'x.toml')

    (tmp_path / 'configs' / 'dmc').mkdir(parents=True)
    cfg = tmp_path.joinpath(*parts)
    cfg.write_text('', encoding='utf-8')

    result = normalize_repo_relative(cfg, tmp_path, 'cfg')
    assert result == 'configs/dmc/x.toml'
    assert '\\' not in result


def test_windows_form_deep_nesting(tmp_path: Path) -> None:
    # 4+ segment depth — guards against any join logic that drops
    # intermediate separators when re-emitting as posix.
    win_form = 'a\\b\\c\\d\\e\\leaf.toml'
    parts = PureWindowsPath(win_form).parts
    assert parts == ('a', 'b', 'c', 'd', 'e', 'leaf.toml')

    (tmp_path / 'a' / 'b' / 'c' / 'd' / 'e').mkdir(parents=True)
    cfg = tmp_path.joinpath(*parts)
    cfg.write_text('', encoding='utf-8')

    result = normalize_repo_relative(cfg, tmp_path, 'cfg')
    assert result == 'a/b/c/d/e/leaf.toml'
    assert '\\' not in result
    # Sanity: result is a valid posix-form path.
    assert PurePosixPath(result).parts == ('a', 'b', 'c', 'd', 'e', 'leaf.toml')


# --- PurePosixPath inputs (POSIX-form preserved) -----------------------------


def test_posix_form_preserved_unchanged(tmp_path: Path) -> None:
    # POSIX-form input — separator already `/`; normalize must preserve.
    posix_form = 'configs/dmc/x.toml'
    parts = PurePosixPath(posix_form).parts
    assert parts == ('configs', 'dmc', 'x.toml')

    (tmp_path / 'configs' / 'dmc').mkdir(parents=True)
    cfg = tmp_path.joinpath(*parts)
    cfg.write_text('', encoding='utf-8')

    result = normalize_repo_relative(cfg, tmp_path, 'cfg')
    assert result == 'configs/dmc/x.toml'


# --- Platform-specific guards ------------------------------------------------


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX-only test')
def test_posix_host_native_path_uses_forward_slash(tmp_path: Path) -> None:
    # On POSIX hosts, native Path construction always uses `/`. Document
    # that normalize preserves it without surprise transforms.
    (tmp_path / 'configs').mkdir()
    cfg = tmp_path / 'configs' / 'x.toml'
    cfg.write_text('', encoding='utf-8')

    result = normalize_repo_relative(cfg, tmp_path, 'cfg')
    assert result == 'configs/x.toml'
    assert '\\' not in result


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows-only test')
def test_windows_host_native_path_converts_to_forward_slash(tmp_path: Path) -> None:
    # On Windows hosts, native Path construction uses `\`. Document that
    # normalize's `.as_posix()` call converts to `/` for cross-host
    # metadata sync (POSIX receivers cannot resolve backslash paths).
    (tmp_path / 'configs').mkdir()
    cfg = tmp_path / 'configs' / 'x.toml'
    cfg.write_text('', encoding='utf-8')

    result = normalize_repo_relative(cfg, tmp_path, 'cfg')
    assert result == 'configs/x.toml'
    assert '\\' not in result
