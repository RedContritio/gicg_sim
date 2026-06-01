"""4 paradigm step_schedule async weight-sync bit — `pipeline-async-weight-sync` T3.

steady-train 分支按 `async_sync_weights_due(cfg, state, pcfg.sync_weights_every_train_steps)`
翻 `StepPlan.sync_weights`:async mode + cadence 边界 → True;serial 恒 False;
warm-up / done 分支恒 False(default)。

helper 真测(核心 cadence + mode gating)+ 4 paradigm wiring 真测(load smoke cfg +
override mode + steady state → step_schedule)。对称(per `feedback_symmetric_tests`):
parametrize 4 paradigm,新加 paradigm 只 register name + steady setup。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from training.core.config.loader import load_cfg
from training.core.protocols import PipelineState, async_sync_weights_due
from training.paradigms import resolve

_REPO = Path(__file__).resolve().parents[2]


# ----------------------------- helper unit ----------------------------- #


def _hstate(train_steps: int) -> PipelineState:
    s = PipelineState.fresh(seed=0)
    s.train_steps = train_steps
    return s


def _hcfg(mode: str) -> SimpleNamespace:
    return SimpleNamespace(pipeline=SimpleNamespace(mode=mode))


def test_helper_serial_always_false():
    """serial mode → 永不 sync(serial collector 无 async actor)。"""
    assert async_sync_weights_due(_hcfg('serial'), _hstate(0), 0) is False
    assert async_sync_weights_due(_hcfg('serial'), _hstate(10), 1) is False


def test_helper_async_cadence_zero_every_iter():
    """N=0 → max(1,0)=1 → train_steps % 1 == 0 恒真 → 每 train iter sync。"""
    assert async_sync_weights_due(_hcfg('async'), _hstate(0), 0) is True
    assert async_sync_weights_due(_hcfg('async'), _hstate(7), 0) is True


def test_helper_async_cadence_n_boundary():
    """N=10 → 仅 train_steps 在 10 倍数边界 sync。"""
    assert async_sync_weights_due(_hcfg('async'), _hstate(10), 10) is True
    assert async_sync_weights_due(_hcfg('async'), _hstate(5), 10) is False


def test_helper_missing_mode_defaults_serial():
    """cfg.pipeline 无 mode 字段 → getattr default 'serial' → False。"""
    cfg = SimpleNamespace(pipeline=SimpleNamespace())
    assert async_sync_weights_due(cfg, _hstate(0), 0) is False


# -------------------- per-paradigm wiring (steady branch) -------------- #


def _cfg_with_mode(paradigm: str, mode: str):
    # load serial smoke(valid)后强制 mode:async 的 CS1.1「需 [eval] section」是
    # 全-cfg 完整性校验,与本单测(step_schedule sync_weights 逻辑)正交,
    # object.__setattr__ 绕过该 load-time 校验直接构造 async 条件。
    cfg = load_cfg(_REPO / 'configs' / paradigm / 'smoke.toml')
    object.__setattr__(cfg.pipeline, 'mode', mode)
    return cfg


def _drive_to_steady(paradigm: str, state: PipelineState) -> None:
    # 各 paradigm steady 阈值(实读 smoke values 2026-06-01)。
    if paradigm == 'dmc':
        state.total_transitions = 100  # [batch_size 16, total_frames 1000)
    elif paradigm == 'az':
        state.total_transitions = 10  # >= min_buffer_before_train 4
        state.total_episodes = 0  # < total_games 2
    # cfr / ppo: fresh step=0 < n_iterations / total_iterations 1 → steady


@pytest.mark.parametrize('paradigm', ['dmc', 'az', 'cfr', 'ppo'])
def test_steady_sync_bit_async_true(paradigm):
    """async mode + steady + default cadence 0(每 iter due)→ sync_weights True。"""
    cfg = _cfg_with_mode(paradigm, 'async')
    p = resolve(paradigm)
    state = PipelineState.fresh(seed=cfg.meta.seed)
    _drive_to_steady(paradigm, state)
    plan = p.step_schedule(state, cfg)
    assert plan.train is True, f'{paradigm} 未进 steady 分支'
    assert plan.sync_weights is True


@pytest.mark.parametrize('paradigm', ['dmc', 'az', 'cfr', 'ppo'])
def test_steady_sync_bit_serial_false(paradigm):
    """serial mode → sync_weights 恒 False(serial collector 无 async actor)。"""
    cfg = _cfg_with_mode(paradigm, 'serial')
    p = resolve(paradigm)
    state = PipelineState.fresh(seed=cfg.meta.seed)
    _drive_to_steady(paradigm, state)
    plan = p.step_schedule(state, cfg)
    assert plan.train is True
    assert plan.sync_weights is False
