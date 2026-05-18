"""Tests for tools.runs.helpers — R1-R3 lock-free helpers (T-02).

Covers:
- normalize_repo_relative: in-tree / Windows-form / outside-root /
  absolute / already-relative
- cfg_checksum: known-bytes vector, identical-content equality,
  missing-file propagation
- extract_meta_field: present field, absent meta table, absent field,
  non-str raise, leaf-only (no extends resolution)
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from tools.runs import helpers


# --- normalize_repo_relative --------------------------------------------------


def test_normalize_in_tree(tmp_path: Path) -> None:
    sub = tmp_path / 'configs' / 'dmc'
    sub.mkdir(parents=True)
    cfg = sub / 'x.toml'
    cfg.write_text('', encoding='utf-8')
    assert helpers.normalize_repo_relative(cfg, tmp_path, 'cfg') == 'configs/dmc/x.toml'


def test_normalize_already_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = tmp_path / 'configs'
    sub.mkdir()
    cfg = sub / 'x.toml'
    cfg.write_text('', encoding='utf-8')
    # Use a relative path while cwd == tmp_path so `.resolve()` lands under repo_root.
    monkeypatch.chdir(tmp_path)
    rel = Path('configs/x.toml')
    assert helpers.normalize_repo_relative(rel, tmp_path, 'cfg') == 'configs/x.toml'


def test_normalize_windows_form_uses_forward_slash(tmp_path: Path) -> None:
    # Emulate the Windows-form normalization expectation without
    # depending on the host OS: hand-construct a posix path from a
    # backslash-separated Windows path, mkdir it, and verify
    # `.as_posix()` produces forward slashes (per plan T-02 TDD).
    win = PureWindowsPath('configs\\dmc\\x.toml')
    parts = win.parts  # ('configs', 'dmc', 'x.toml')
    sub = tmp_path.joinpath(*parts[:-1])
    sub.mkdir(parents=True)
    cfg = sub / parts[-1]
    cfg.write_text('', encoding='utf-8')
    result = helpers.normalize_repo_relative(cfg, tmp_path, 'cfg')
    assert '\\' not in result
    assert result == 'configs/dmc/x.toml'
    # Sanity: result is a valid posix-form path.
    assert PurePosixPath(result).parts == ('configs', 'dmc', 'x.toml')


def test_normalize_outside_root_raises_with_label(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    stray = other / 'x.toml'
    stray.write_text('', encoding='utf-8')
    with pytest.raises(ValueError, match='cfg path'):
        helpers.normalize_repo_relative(stray, repo, 'cfg')


def test_normalize_outside_root_label_appears_in_message(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    stray = other / 'x.toml'
    stray.write_text('', encoding='utf-8')
    with pytest.raises(ValueError) as ei:
        helpers.normalize_repo_relative(stray, repo, 'artifacts')
    assert 'artifacts path' in str(ei.value)


def test_normalize_absolute_path(tmp_path: Path) -> None:
    sub = tmp_path / 'a' / 'b'
    sub.mkdir(parents=True)
    cfg = sub / 'c.toml'
    cfg.write_text('', encoding='utf-8')
    assert helpers.normalize_repo_relative(cfg.resolve(), tmp_path, 'cfg') == 'a/b/c.toml'


# --- cfg_checksum -------------------------------------------------------------


def test_cfg_checksum_known_vector(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_bytes(b'hello')
    expected = 'sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    assert helpers.cfg_checksum(cfg) == expected


def test_cfg_checksum_empty_file(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_bytes(b'')
    expected_hex = hashlib.sha256(b'').hexdigest()
    assert helpers.cfg_checksum(cfg) == f'sha256:{expected_hex}'


def test_cfg_checksum_identical_content_different_path(tmp_path: Path) -> None:
    a = tmp_path / 'a.toml'
    b = tmp_path / 'sub' / 'b.toml'
    b.parent.mkdir()
    content = b'meta = "v"\nrun_label = "foo"\n'
    a.write_bytes(content)
    b.write_bytes(content)
    assert helpers.cfg_checksum(a) == helpers.cfg_checksum(b)


def test_cfg_checksum_format(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_bytes(b'whatever')
    result = helpers.cfg_checksum(cfg)
    assert result.startswith('sha256:')
    hex_part = result[len('sha256:') :]
    assert len(hex_part) == 64
    int(hex_part, 16)  # raises if not hex


def test_cfg_checksum_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        helpers.cfg_checksum(tmp_path / 'nonexistent.toml')


# --- extract_meta_field -------------------------------------------------------


def test_extract_meta_field_present(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_text('[meta]\nrun_label = "foo"\n', encoding='utf-8')
    assert helpers.extract_meta_field(cfg, 'run_label') == 'foo'


def test_extract_meta_field_no_meta_table(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_text('[shape]\nd_model = 128\n', encoding='utf-8')
    assert helpers.extract_meta_field(cfg, 'run_label') is None


def test_extract_meta_field_missing_field(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_text('[meta]\nparadigm = "dmc"\n', encoding='utf-8')
    assert helpers.extract_meta_field(cfg, 'run_label') is None


def test_extract_meta_field_non_str_raises(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_text('[meta]\nrun_label = 42\n', encoding='utf-8')
    with pytest.raises(TypeError, match='expected str, got int'):
        helpers.extract_meta_field(cfg, 'run_label')


def test_extract_meta_field_list_value_raises(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_text('[meta]\nrun_label = ["a", "b"]\n', encoding='utf-8')
    with pytest.raises(TypeError, match='expected str, got list'):
        helpers.extract_meta_field(cfg, 'run_label')


def test_extract_meta_field_leaf_only_no_extends_resolve(tmp_path: Path) -> None:
    # Leaf declares its own `meta.run_label`; an `extends` directive
    # pointing to a parent must NOT be followed (helper is leaf-only).
    parent = tmp_path / 'parent.toml'
    parent.write_text('[meta]\nrun_label = "from_parent"\n', encoding='utf-8')
    leaf = tmp_path / 'leaf.toml'
    leaf.write_text('[meta]\nextends = "parent.toml"\nrun_label = "from_leaf"\n', encoding='utf-8')
    assert helpers.extract_meta_field(leaf, 'run_label') == 'from_leaf'


def test_extract_meta_field_extends_present_field_absent_returns_none(tmp_path: Path) -> None:
    # Even if parent would have provided the field, helper must NOT
    # resolve extends — leaf is missing the field → None.
    parent = tmp_path / 'parent.toml'
    parent.write_text('[meta]\nrun_label = "from_parent"\n', encoding='utf-8')
    leaf = tmp_path / 'leaf.toml'
    leaf.write_text('[meta]\nextends = "parent.toml"\nparadigm = "dmc"\n', encoding='utf-8')
    assert helpers.extract_meta_field(leaf, 'run_label') is None


def test_extract_meta_field_empty_meta_table(tmp_path: Path) -> None:
    cfg = tmp_path / 'x.toml'
    cfg.write_text('[meta]\n', encoding='utf-8')
    assert helpers.extract_meta_field(cfg, 'run_label') is None


def test_extract_meta_field_paradigm(tmp_path: Path) -> None:
    # Spot-check a different field name (paradigm) for parametrization safety.
    cfg = tmp_path / 'x.toml'
    cfg.write_text('[meta]\nparadigm = "dmc"\nrun_label = "smoke"\n', encoding='utf-8')
    assert helpers.extract_meta_field(cfg, 'paradigm') == 'dmc'
    assert helpers.extract_meta_field(cfg, 'run_label') == 'smoke'


# --- RUN_DIR_RE (R8 — single-source run-dir name regex) ----------------------


def test_run_dir_re_matches_well_formed() -> None:
    # ``<YYYYMMDDHHMM>_<NNNNNN>_<label>`` — group 1 = NNN, group 2 = label.
    m = helpers.RUN_DIR_RE.match('202605180100_000001_az_smoke')
    assert m is not None
    assert m.group(1) == '000001'
    assert m.group(2) == 'az_smoke'


def test_run_dir_re_rejects_legacy_dirs() -> None:
    # Pre-redesign dirs (``r001_old``, ``pre_redesign_xxx``, bare lockfiles)
    # must not match; list.py / sync_scan.py depend on this filter.
    assert helpers.RUN_DIR_RE.match('r001_old') is None
    assert helpers.RUN_DIR_RE.match('pre_redesign_xxx') is None
    assert helpers.RUN_DIR_RE.match('.run_id_lock') is None
    # Wrong NNN width (5 digits) is also rejected.
    assert helpers.RUN_DIR_RE.match('202605180100_00001_x') is None
    # Missing trailing label rejected.
    assert helpers.RUN_DIR_RE.match('202605180100_000001_') is None
    # Wrong timestamp width (11 digits).
    assert helpers.RUN_DIR_RE.match('20260518010_000001_x') is None


def test_run_dir_re_label_accepts_underscores_and_dashes() -> None:
    # Labels can contain underscores / dashes / digits (slug-like).
    m = helpers.RUN_DIR_RE.match('202605180100_000099_dmc-smoke_v2')
    assert m is not None
    assert m.group(1) == '000099'
    assert m.group(2) == 'dmc-smoke_v2'
