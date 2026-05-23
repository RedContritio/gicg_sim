"""DmcAgent.load_net_only auto-strip `net.` 前缀 — 兼 DMCNetwork.state_dict() 输入。

2026-05-23 task #3 Phase 1 add_snapshot wiring 触发:pipeline 推 `network.
state_dict()` 进 opp_pool ring,DMCNetwork wrap ActorCritic 在 `self.net` 子
模块,state_dict keys 全 `net.` 前缀;historical_factory 调 load_net_only
期 raw ActorCritic state_dict 无前缀 → RuntimeError missing/unexpected key
(test_dmc_smoke_full 2026-05-23 实测 fail)。 修法:auto-strip 前缀 兼两种
input format。
"""

from __future__ import annotations

import torch

from training.core.cfg import make_dmc_default_shape
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.network import DMCNetwork


def _build_cfg() -> AgentConfig:
    shape = make_dmc_default_shape()
    return AgentConfig(
        n_counter_slots=shape.n_counter_slots,
        n_hooks=shape.n_hooks,
        max_ops_per_hook=shape.max_ops_per_hook,
        max_actions=shape.max_actions,
        d_model=8,
        n_cross_layers=1,
        dropout=0.0,
    )


def _build_agent() -> tuple[DmcAgent, AgentConfig]:
    cfg = _build_cfg()
    return DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0), cfg


def test_load_net_only_accepts_raw_actor_critic_sd():
    """传统 path — 直接 raw ActorCritic.state_dict() 无前缀,正常 load。"""
    src, _ = _build_agent()
    raw_sd = src.net.state_dict()
    # 无 net. 前缀
    assert all(not k.startswith('net.') for k in raw_sd.keys())

    dst, _ = _build_agent()
    dst.load_net_only(raw_sd)
    # 验 weights 一致
    for k in raw_sd:
        assert torch.equal(raw_sd[k], dst.net.state_dict()[k])


def test_load_net_only_accepts_dmc_network_sd_with_net_prefix():
    """Phase 1 add_snapshot path — DMCNetwork.state_dict() 全 net. 前缀,
    load_net_only 应 auto-strip 前缀 后 load 进 内部 ActorCritic。"""
    cfg = _build_cfg()
    src_net = DMCNetwork(cfg, device='cpu', epsilon=0.0)
    prefixed_sd = src_net.state_dict()
    # 全 net. 前缀
    assert all(k.startswith('net.') for k in prefixed_sd.keys()), 'DMCNetwork.state_dict 不再 全 net. 前缀,test 假设失效'

    dst, _ = _build_agent()
    dst.load_net_only(prefixed_sd)
    # 验 strip 后 内部 ActorCritic weights 与 源 一致
    src_raw = src_net._agent.net.state_dict()
    for k in src_raw:
        assert torch.equal(src_raw[k], dst.net.state_dict()[k])


def test_load_net_only_mixed_prefix_does_not_silently_strip():
    """sanity:若 sd keys 含 net. 与 非 net. 混合(不该发生),不 触发 strip,
    raise from underlying torch.load_state_dict — fail-loud。"""
    src, _ = _build_agent()
    raw_sd = dict(src.net.state_dict())
    # 篡改:加一个 net. 前缀键 但 其他不变
    first_key = next(iter(raw_sd))
    raw_sd['net.spurious'] = raw_sd[first_key]
    # 因 not all start with net.,不 strip → torch load_state_dict raise
    dst, _ = _build_agent()
    try:
        dst.load_net_only(raw_sd)
        raise AssertionError('expected torch RuntimeError unexpected key')
    except RuntimeError as e:
        assert 'Unexpected' in str(e) or 'unexpected' in str(e)
