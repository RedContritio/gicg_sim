"""I29 — AZ/PPO make_collector guard against actor_backend='go'。

`cfg.pipeline.actor_backend`(python|go)由 DMC paradigm dispatch;AZ/PPO 的
Go actor port 是 I29 Phase 2 工作。 在 Phase 2 完成前,AZ/PPO 收到
`actor_backend='go'` 必须 fail loud,而非静默忽略走 Python 路径
(意外输入必须抛异常)。

两个 paradigm 共享同一 guard 语义 → 对称测试合一处。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from training.paradigms.az.paradigm import AZParadigm
from training.paradigms.ppo.paradigm import PPOParadigm


def _go_backend_cfg() -> SimpleNamespace:
    """Minimal cfg stub — guard 在 make_collector 开头读 cfg.pipeline.actor_backend,
    在任何 paradigm-specific 逻辑之前 raise,故只需 pipeline 段。"""
    return SimpleNamespace(pipeline=SimpleNamespace(mode='async', actor_backend='go'))


def test_az_make_collector_rejects_go_actor_backend():
    """AZ 无 Go actor backend(I29 Phase 2 pending)— actor_backend='go' 必须 raise。"""
    with pytest.raises(ValueError, match='actor_backend'):
        AZParadigm().make_collector(_go_backend_cfg(), env_factory=None, network=None, opp_pool=None)


def test_ppo_make_collector_rejects_go_actor_backend():
    """PPO 无 Go actor backend(I29 Phase 2 pending)— actor_backend='go' 必须 raise。"""
    with pytest.raises(ValueError, match='actor_backend'):
        PPOParadigm().make_collector(_go_backend_cfg(), env_factory=None, network=None, opp_pool=None)
