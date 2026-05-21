"""Tests for ``pipeline.actor_backend`` cfg field (I29 P2.X)。

Verifies cfg loader correctly parses 'python' (default) | 'go' (I29 Go-native
actor pool)+ rejects invalid values。 走 extends 复用 dmc/smoke.toml 实际 cfg。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from training.core.config.loader import load_cfg


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_CFG = _REPO_ROOT / 'configs' / 'dmc' / 'smoke.toml'


def _write_extends(tmp_path: Path, pipeline_overrides: str = '') -> Path:
    p = tmp_path / 'cfg.toml'
    p.write_text(
        f"""
[meta]
extends = "{_BASE_CFG.resolve()}"

[pipeline]
{pipeline_overrides}
"""
    )
    return p


def test_actor_backend_defaults_to_python():
    """无显式字段 → default 'python'(向后兼容现 production cfg)。"""
    cfg = load_cfg(_BASE_CFG)
    assert cfg.pipeline.actor_backend == 'python'


def test_actor_backend_explicit_python(tmp_path):
    """显式 'python' 合法。"""
    cfg = load_cfg(_write_extends(tmp_path, 'actor_backend = "python"'))
    assert cfg.pipeline.actor_backend == 'python'


def test_actor_backend_explicit_go(tmp_path):
    """'go' 合法 — I29 Go-native actor pool。"""
    cfg = load_cfg(_write_extends(tmp_path, 'actor_backend = "go"'))
    assert cfg.pipeline.actor_backend == 'go'


def test_actor_backend_invalid_raises(tmp_path):
    """非 'python' / 'go' fail loud — 防 typo 'gO' / 'Go' 静默 fallback 走旧路径。"""
    with pytest.raises(ValueError, match='actor_backend must be'):
        load_cfg(_write_extends(tmp_path, 'actor_backend = "rust"'))
