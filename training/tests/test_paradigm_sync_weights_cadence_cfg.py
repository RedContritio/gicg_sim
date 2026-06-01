"""4 paradigm 统一 `sync_weights_every_train_steps` cadence 字段 — `pipeline-
async-weight-sync` T2。

DMC 把 `weight_sync_every_steps` rename 为 `sync_weights_every_train_steps`;
AZ/CFR/PPO ParadigmConfig 新增同名字段。default 沿用 DMC 现值 **0**(D-c —
0/1 = 每 train iter sync,保持 DMC 行为不变)。step_schedule (T3) 读它 × driver
honor (T1) 构成 async weight republish cadence。

对称测试(per `feedback_symmetric_tests`):parametrize 4 paradigm,新加 paradigm
只 register cfg class。
"""

from __future__ import annotations

import dataclasses

import pytest

from training.paradigms.az.config import AZParadigmConfig
from training.paradigms.cfr.config import CFRParadigmConfig
from training.paradigms.dmc.config import DMCParadigmConfig
from training.paradigms.ppo.config import PPOParadigmConfig

_PARADIGM_CFGS = [AZParadigmConfig, CFRParadigmConfig, DMCParadigmConfig, PPOParadigmConfig]


@pytest.mark.parametrize('cfg_cls', _PARADIGM_CFGS, ids=lambda c: c.__name__)
def test_sync_weights_cadence_field_exists_default_zero(cfg_cls):
    """4 paradigm ParadigmConfig 均暴露 sync_weights_every_train_steps,default 0。"""
    cfg = cfg_cls()
    assert hasattr(cfg, 'sync_weights_every_train_steps'), f'{cfg_cls.__name__} missing sync_weights_every_train_steps'
    assert cfg.sync_weights_every_train_steps == 0, f'{cfg_cls.__name__} default != 0 (D-c 沿用 DMC)'


def test_dmc_weight_sync_every_steps_renamed():
    """DMC 旧字段名 weight_sync_every_steps 已 rename — dataclass 无该 field。"""
    field_names = {f.name for f in dataclasses.fields(DMCParadigmConfig)}
    assert 'weight_sync_every_steps' not in field_names, 'DMC 旧字段名未 rename'
    assert 'sync_weights_every_train_steps' in field_names


def test_dmc_old_field_name_rejected_by_strict_loader():
    """DMC from_dict 拿旧名 weight_sync_every_steps → strict unknown-key raise
    (T2 risk:strict loader unknown-key fail — 旧 cfg toml 用旧名会 loud fail)。"""
    with pytest.raises(ValueError, match='unknown paradigm key'):
        DMCParadigmConfig.from_dict({'weight_sync_every_steps': 5})
