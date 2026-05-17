"""Contract: `--paradigm dmc` dispatch resolves and loads a DMC config.

Pinned by FU-W4-DMC-pt2 follow-up: the registry entry in
`tools/eval/_paradigm.py` previously pointed at the deleted
`training.dmc.config_loader:load_config`, breaking both
`tools/eval/ckpt --paradigm dmc` and `tools/eval/daemon --paradigm dmc`
at runtime (ImportError on first registry lookup).

These tests verify the user-facing contract end-to-end via the same
resolve(...) call path the binaries use, against a real DMC TOML.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.eval._paradigm import resolve


REPO_ROOT = Path(__file__).resolve().parents[3]
# Post core-network-generic-promotion Phase 0: configs/smoke/ moved to
# configs/_archived/pre_redesign_2026_05_17/smoke/.
SMOKE_CFG = REPO_ROOT / 'configs' / '_archived' / 'pre_redesign_2026_05_17' / 'smoke' / 'dmc_stage3_smoke.toml'


def test_dmc_load_config_resolves():
    """Registry lookup must succeed without ImportError / AttributeError."""
    load_config = resolve('dmc', 'load_config')
    assert callable(load_config)


def test_dmc_load_config_returns_dmc_config():
    """Loader applied to a real DMC TOML returns a populated DmcConfig."""
    assert SMOKE_CFG.exists(), f'fixture cfg missing: {SMOKE_CFG}'
    load_config = resolve('dmc', 'load_config')
    cfg = load_config(str(SMOKE_CFG), data_dir='data')

    # Type contract: the eval pipeline (tools/eval/_dmc_evaluator.py) reads
    # cfg.scenario / cfg.eval / cfg.max_game_steps / cfg.seed off DmcConfig.
    from training.paradigms.dmc._run_config import DmcConfig

    assert isinstance(cfg, DmcConfig)
    # Smoke cfg overrides must be visible on the loaded dataclass.
    assert cfg.run_label == 'dmc_stage3_smoke'
    assert cfg.scenario.team_0 == ['赤蝶']
    assert cfg.scenario.team_1 == ['墨客']
    # nested override (eval.n_scenarios = 4 in smoke toml)
    assert cfg.eval.n_scenarios == 4
    assert cfg.eval.baselines == ['F1-D2']


def test_dmc_load_config_unknown_base_raises():
    """Unknown `base = ...` must raise ValueError (catches typos early)."""
    load_config = resolve('dmc', 'load_config')
    tmp = REPO_ROOT / 'tools' / 'eval' / 'tests' / '_tmp_bad_base.toml'
    tmp.write_text('base = "nonexistent_preset"\n', encoding='utf-8')
    try:
        with pytest.raises(ValueError, match='unknown base preset'):
            load_config(str(tmp), data_dir='data')
    finally:
        tmp.unlink(missing_ok=True)


def test_dmc_load_config_unknown_field_raises():
    """Unknown top-level field must raise ValueError (CS4-style strict schema)."""
    load_config = resolve('dmc', 'load_config')
    tmp = REPO_ROOT / 'tools' / 'eval' / 'tests' / '_tmp_bad_field.toml'
    tmp.write_text('base = "smoke"\nnonexistent_field = 1\n', encoding='utf-8')
    try:
        with pytest.raises(ValueError, match='unknown field'):
            load_config(str(tmp), data_dir='data')
    finally:
        tmp.unlink(missing_ok=True)
