"""Unit tests for ``tools.eval.ckpt._ckpt_label``.

T-06 ckpts/ subdir 后,run_label = ckpt 的 grandparent。flat 路径被拒
(clean-slate,不留 backward compat)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.eval.ckpt import _ckpt_label


def test_ckpt_label_parses_grandparent_for_ckpts_subdir_path():
    """T-06 layout: ckpt 在 <run>/ckpts/ 下,label = grandparent name."""
    p = Path('/x/y/202605181019_000069_dmc_stage3_pilot/ckpts/latest.pt')
    assert _ckpt_label(p) == '202605181019_000069_dmc_stage3_pilot'


def test_ckpt_label_parses_ckpt_step_files():
    """ckpt_<step>.pt(非 latest.pt)同 layout 适用。"""
    p = Path('/a/b/202605181019_000123_az_stage1/ckpts/ckpt_300.pt')
    assert _ckpt_label(p) == '202605181019_000123_az_stage1'


def test_ckpt_label_parses_gauntlet_files():
    """gauntlet_g<g>.pt 也在 ckpts/ 下(spec 行 606-613)。"""
    p = Path('/a/b/202605181019_000007_az_smoke/ckpts/gauntlet_g4.pt')
    assert _ckpt_label(p) == '202605181019_000007_az_smoke'


def test_ckpt_label_rejects_flat_path():
    """Flat ckpt path(parent.name != 'ckpts')必须 raise — T-06 clean-slate
    不留兼容,silent fallback 会导致 label 错误派生。"""
    p = Path('/x/y/202605151019_dmc_legacy/latest.pt')
    with pytest.raises(ValueError, match='ckpts/ subdir'):
        _ckpt_label(p)


def test_ckpt_label_rejects_root_path():
    """退化 path(只剩 latest.pt 名)也必须 raise。"""
    p = Path('latest.pt')
    with pytest.raises(ValueError, match='ckpts/ subdir'):
        _ckpt_label(p)


def test_ckpt_label_rejects_arbitrary_subdir():
    """parent 是其他名(e.g. 'archive')也 raise — 防意外 typo
    悄悄派生错误 label。"""
    p = Path('/a/b/202605181019_000001_run/archive/latest.pt')
    with pytest.raises(ValueError, match="parent='archive'"):
        _ckpt_label(p)
