"""Tests for tools.runs.helpers.resolve_nnn_to_dir — R7 (T-05).

Covers spec §CLI show 细则 HIGH-1-C + §CLI mark 细则 HIGH-6-A + spec §用户友好 error message prescribed error wording:

- shorthand ``69`` / ``069`` / ``000069`` all resolve identically.
- 0 match → ``LookupError('NNN not found')``.
- ≥2 match → ``LookupError('multiple dirs match <NNN>: <list>;
  please pass full dir path')`` with sorted candidate list.
- input validation: empty / >6 digits / non-digit / 5-digit (still OK
  via zfill).
- non-NNN artifacts entries (legacy ``r001_*``, ``pre_redesign_*``,
  ``.run_id_lock`` file) silently ignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.runs import helpers


# --- Test fixtures ------------------------------------------------------------


def _mk_artifact_dir(repo: Path, ts: str, nnn: int, label: str) -> Path:
    """Create an artifacts subdir matching the canonical naming regex
    ``<ts>_<NNNNNN>_<label>``. ``ts`` is a 12-digit timestamp string.
    """
    artifacts = repo / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    d = artifacts / f'{ts}_{nnn:06d}_{label}'
    d.mkdir()
    return d


# --- Single match -------------------------------------------------------------


def test_single_match_full_6digit(tmp_path: Path) -> None:
    d = _mk_artifact_dir(tmp_path, '202605181230', 69, 'dmc')
    assert helpers.resolve_nnn_to_dir(tmp_path, '000069') == d


def test_single_match_shorthand_2digit(tmp_path: Path) -> None:
    d = _mk_artifact_dir(tmp_path, '202605181230', 69, 'dmc')
    assert helpers.resolve_nnn_to_dir(tmp_path, '69') == d


def test_single_match_shorthand_3digit(tmp_path: Path) -> None:
    d = _mk_artifact_dir(tmp_path, '202605181230', 69, 'dmc')
    assert helpers.resolve_nnn_to_dir(tmp_path, '069') == d


def test_single_match_shorthand_5digit(tmp_path: Path) -> None:
    """``'00069'`` is 5 digits — still valid (zfill pads to 6)."""
    d = _mk_artifact_dir(tmp_path, '202605181230', 69, 'dmc')
    assert helpers.resolve_nnn_to_dir(tmp_path, '00069') == d


def test_single_match_nnn_1(tmp_path: Path) -> None:
    """Edge: shorthand ``'1'`` resolves to NNN 000001."""
    d = _mk_artifact_dir(tmp_path, '202605181230', 1, 'az')
    assert helpers.resolve_nnn_to_dir(tmp_path, '1') == d


def test_single_match_nnn_999999(tmp_path: Path) -> None:
    """Edge: 6-digit max NNN."""
    d = _mk_artifact_dir(tmp_path, '202605181230', 999999, 'ppo')
    assert helpers.resolve_nnn_to_dir(tmp_path, '999999') == d


# --- Zero matches -------------------------------------------------------------


def test_empty_artifacts_raises_lookup(tmp_path: Path) -> None:
    """No artifacts/ dir at all → raise."""
    with pytest.raises(LookupError, match='not found'):
        helpers.resolve_nnn_to_dir(tmp_path, '69')


def test_artifacts_exists_but_empty_raises(tmp_path: Path) -> None:
    (tmp_path / 'artifacts').mkdir()
    with pytest.raises(LookupError, match='not found'):
        helpers.resolve_nnn_to_dir(tmp_path, '69')


def test_other_nnn_present_but_not_target_raises(tmp_path: Path) -> None:
    _mk_artifact_dir(tmp_path, '202605181230', 42, 'dmc')
    _mk_artifact_dir(tmp_path, '202605181231', 100, 'az')
    with pytest.raises(LookupError, match='not found'):
        helpers.resolve_nnn_to_dir(tmp_path, '69')


def test_zero_match_error_contains_padded_nnn(tmp_path: Path) -> None:
    """Error message must include the zero-padded NNN for clarity."""
    (tmp_path / 'artifacts').mkdir()
    with pytest.raises(LookupError, match='000069'):
        helpers.resolve_nnn_to_dir(tmp_path, '69')


# --- Multi-match -------------------------------------------------------------


def test_two_matches_raises_with_candidates(tmp_path: Path) -> None:
    """Cross-host sync collision: 2 dirs share NNN — must raise + list."""
    d1 = _mk_artifact_dir(tmp_path, '202605181230', 69, 'dmc')
    d2 = _mk_artifact_dir(tmp_path, '202605181231', 69, 'az')
    with pytest.raises(LookupError) as exc_info:
        helpers.resolve_nnn_to_dir(tmp_path, '69')
    msg = str(exc_info.value)
    assert 'multiple' in msg
    assert '000069' in msg
    assert d1.name in msg
    assert d2.name in msg
    assert 'please pass full dir path' in msg


def test_multi_match_candidates_sorted(tmp_path: Path) -> None:
    """Candidate list must be sorted for deterministic output."""
    # Create in reverse-sorted order on purpose
    _mk_artifact_dir(tmp_path, '202605181231', 69, 'zzz')
    _mk_artifact_dir(tmp_path, '202605181230', 69, 'aaa')
    with pytest.raises(LookupError) as exc_info:
        helpers.resolve_nnn_to_dir(tmp_path, '69')
    msg = str(exc_info.value)
    # The earlier-ts name sorts first lexicographically
    pos_aaa = msg.find('202605181230_000069_aaa')
    pos_zzz = msg.find('202605181231_000069_zzz')
    assert pos_aaa != -1 and pos_zzz != -1
    assert pos_aaa < pos_zzz


def test_three_matches_all_listed(tmp_path: Path) -> None:
    d1 = _mk_artifact_dir(tmp_path, '202605181230', 69, 'a')
    d2 = _mk_artifact_dir(tmp_path, '202605181231', 69, 'b')
    d3 = _mk_artifact_dir(tmp_path, '202605181232', 69, 'c')
    with pytest.raises(LookupError) as exc_info:
        helpers.resolve_nnn_to_dir(tmp_path, '69')
    msg = str(exc_info.value)
    for d in (d1, d2, d3):
        assert d.name in msg


# --- Input validation --------------------------------------------------------


def test_empty_string_raises_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='1-6 digit'):
        helpers.resolve_nnn_to_dir(tmp_path, '')


def test_seven_digits_raises_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='1-6 digit'):
        helpers.resolve_nnn_to_dir(tmp_path, '1234567')


def test_non_digit_raises_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='1-6 digit'):
        helpers.resolve_nnn_to_dir(tmp_path, 'abc')


def test_mixed_digit_alpha_raises_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='1-6 digit'):
        helpers.resolve_nnn_to_dir(tmp_path, '69a')


def test_negative_sign_raises_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='1-6 digit'):
        helpers.resolve_nnn_to_dir(tmp_path, '-69')


def test_whitespace_raises_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='1-6 digit'):
        helpers.resolve_nnn_to_dir(tmp_path, ' 69')


@pytest.mark.parametrize('bad_input', ['٦٩', '六', '①②③'])
def test_unicode_digit_raises_value_error(tmp_path: Path, bad_input: str) -> None:
    """Unicode digits (Arabic-Indic, Chinese numerals, circled digits) must
    raise ``ValueError``, not silently fall through to ``LookupError``.

    Python's ``\\d`` regex class matches Unicode digit chars by default,
    which would let e.g. ``'٦٩'`` pass the input shape check, then
    ``zfill(6)`` → ``'0000٦٩'`` would never match any ASCII artifacts
    dir name and silently raise ``LookupError('not found')`` — masking
    the real bug (caller passed non-ASCII input). ``[0-9]{1,6}`` ASCII-
    only regex catches this at the input-validation boundary.
    """
    with pytest.raises(ValueError, match='1-6 digit'):
        helpers.resolve_nnn_to_dir(tmp_path, bad_input)


# --- Non-NNN entries don't interfere -----------------------------------------


def test_legacy_r001_dir_skipped(tmp_path: Path) -> None:
    """Pre-redesign ``r001_old/`` style dirs must not match the new regex."""
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    (artifacts / 'r001_old_dmc').mkdir()
    (artifacts / 'pre_redesign_dump').mkdir()
    target = _mk_artifact_dir(tmp_path, '202605181230', 69, 'dmc')
    assert helpers.resolve_nnn_to_dir(tmp_path, '69') == target


def test_lockfile_skipped(tmp_path: Path) -> None:
    """The ``.run_id_lock`` file under artifacts/ must not be considered."""
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    (artifacts / '.run_id_lock').write_text('')
    target = _mk_artifact_dir(tmp_path, '202605181230', 69, 'dmc')
    assert helpers.resolve_nnn_to_dir(tmp_path, '69') == target


def test_random_file_in_artifacts_skipped(tmp_path: Path) -> None:
    """Files (not dirs) must not be considered candidates even if name matches."""
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    # A regular file with a name that would match the NNN regex if it were a dir
    (artifacts / '202605181230_000069_dmc').write_text('not a dir')
    with pytest.raises(LookupError, match='not found'):
        helpers.resolve_nnn_to_dir(tmp_path, '69')


def test_partial_nnn_prefix_does_not_match(tmp_path: Path) -> None:
    """Asking for ``'69'`` must not match a dir containing NNN ``000692`` —
    zero-pad + anchored regex prevents prefix collision.
    """
    _mk_artifact_dir(tmp_path, '202605181230', 692, 'dmc')
    with pytest.raises(LookupError, match='not found'):
        helpers.resolve_nnn_to_dir(tmp_path, '69')


def test_partial_nnn_suffix_does_not_match(tmp_path: Path) -> None:
    """Asking for ``'69'`` must not match NNN ``000169`` (zero-pad + anchor)."""
    _mk_artifact_dir(tmp_path, '202605181230', 169, 'dmc')
    with pytest.raises(LookupError, match='not found'):
        helpers.resolve_nnn_to_dir(tmp_path, '69')


# --- Public API surface ------------------------------------------------------


def test_resolver_exported_from_helpers() -> None:
    """R7 must be in the public ``__all__`` of tools.runs.helpers."""
    assert 'resolve_nnn_to_dir' in helpers.__all__
    assert callable(helpers.resolve_nnn_to_dir)
