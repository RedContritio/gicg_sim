"""Contract tests for training/dmc/config.py — preset sanity + EvalConfig defaults."""

from __future__ import annotations

from training.paradigms.dmc._run_config import DmcConfig, EvalConfig, smoke_config, stage3_config


def test_smoke_config_max_rounds_is_10():
    """max_rounds 全栈统一 10(timeout.lua 在 round 10 做先手判负 tiebreak)。
    Stage 不作为 max_rounds 差分轴。"""
    cfg = smoke_config()
    assert cfg.scenario.max_rounds == 10


def test_stage3_config_max_rounds_is_10():
    cfg = stage3_config()
    assert cfg.scenario.max_rounds == 10


def test_eval_config_enabled_default_true():
    """In-process eval default ON; cfg toml 可关。"""
    ec = EvalConfig()
    assert ec.enabled is True


def test_smoke_config_has_eval_enabled_true():
    cfg = smoke_config()
    assert cfg.eval.enabled is True


def test_stage3_config_inherits_eval_enabled_true_by_default():
    """stage3_config() 默认仍 True; Stage 3 toml override 为 False 走 Mac daemon。"""
    cfg = stage3_config()
    assert cfg.eval.enabled is True


def test_smoke_opponent_pool_weights_sum_to_one():
    cfg = smoke_config()
    op = cfg.opponent_pool
    s = op.random + op.f1d2 + op.f1d4 + op.historical
    assert abs(s - 1.0) < 1e-6


def test_smoke_config_basic_fields():
    """Type / structural sanity, catches accidental field renames."""
    cfg = smoke_config()
    assert isinstance(cfg, DmcConfig)
    assert cfg.total_frames > 0
    assert cfg.batch_size > 0
    assert cfg.buffer_cap > 0
    assert cfg.agent.max_actions > 0
    assert cfg.agent.n_counter_slots > 0
    assert cfg.scenario.team_0 and cfg.scenario.team_1
