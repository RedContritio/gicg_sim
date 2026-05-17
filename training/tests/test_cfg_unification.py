"""Tests for cfg-schema-unification N1 + N2 invariants —
4 paradigm (AZ/BC/CFR/DMC) inherit ParadigmConfigBase + compose ObsShape.

PPO 暂不接 unification (per DECISIONS CC-206 / D-202 paired defer);
本 test 仅验证 4 paradigm。

Spec ref: config-schema/spec.md § 7 N1 (ObsShape SSOT) + N2
(ParadigmConfigBase compose).
"""

from __future__ import annotations

import pytest

from training.core.cfg import ObsShape, ParadigmConfigBase
from training.paradigms.az.config import AZParadigmConfig
from training.paradigms.az.config import AgentShapeCfg as AZAgentShapeCfg
from training.paradigms.bc.config import BCParadigmConfig
from training.paradigms.bc.config import AgentShapeCfg as BCAgentShapeCfg
from training.paradigms.cfr.config import CFRAgentShapeCfg, CFRParadigmConfig
from training.paradigms.dmc.config import DMCParadigmConfig
from training.paradigms.dmc.config import AgentShapeCfg as DMCAgentShapeCfg


# ---------- N2: ParadigmConfigBase inheritance ---------- #


@pytest.mark.parametrize(
    'cls,expected_paradigm',
    [
        (AZParadigmConfig, 'az'),
        (BCParadigmConfig, 'bc'),
        (CFRParadigmConfig, 'cfr'),
        (DMCParadigmConfig, 'dmc'),
    ],
)
def test_paradigm_config_inherits_paradigm_config_base(cls, expected_paradigm):
    """4 paradigm cfg classes inherit ParadigmConfigBase (N2.2)."""
    assert issubclass(cls, ParadigmConfigBase), f'{cls.__name__} must inherit ParadigmConfigBase'
    cfg = cls()
    assert cfg.paradigm == expected_paradigm, (
        f'{cls.__name__}.paradigm default = {cfg.paradigm!r}, expected {expected_paradigm!r}'
    )


@pytest.mark.parametrize(
    'cls',
    [AZParadigmConfig, BCParadigmConfig, CFRParadigmConfig, DMCParadigmConfig],
)
def test_paradigm_config_default_version(cls):
    """4 paradigm cfg default version = '1.0.0' (N2.1 / N3.1)."""
    cfg = cls()
    assert cfg.version == '1.0.0'


# ---------- N1: ObsShape SSOT ---------- #


@pytest.mark.parametrize(
    'cls',
    [AZParadigmConfig, BCParadigmConfig, CFRParadigmConfig, DMCParadigmConfig],
)
def test_paradigm_config_agent_is_obs_shape(cls):
    """4 paradigm cfg.agent is ObsShape instance (N1.1 unified type)."""
    cfg = cls()
    assert isinstance(cfg.agent, ObsShape), f'{cls.__name__}.agent is {type(cfg.agent).__name__}, expected ObsShape'


def test_agent_shape_cfg_alias_is_obs_shape():
    """4 paradigm AgentShapeCfg / CFRAgentShapeCfg = ObsShape alias (N1.3 / CC-202)."""
    assert AZAgentShapeCfg is ObsShape
    assert BCAgentShapeCfg is ObsShape
    assert CFRAgentShapeCfg is ObsShape
    assert DMCAgentShapeCfg is ObsShape


# ---------- N1.2: paradigm-specific d_model defaults ---------- #


def test_paradigm_config_agent_has_paradigm_specific_d_model():
    """Each paradigm cfg default agent d_model matches paradigm 历史 default."""
    assert AZParadigmConfig().agent.d_model == 128
    assert BCParadigmConfig().agent.d_model == 32
    assert CFRParadigmConfig().agent.d_model == 64
    assert DMCParadigmConfig().agent.d_model == 32


def test_paradigm_config_agent_has_paradigm_specific_n_cross_layers():
    """Each paradigm cfg default agent n_cross_layers matches 历史 default."""
    assert AZParadigmConfig().agent.n_cross_layers == 2
    assert BCParadigmConfig().agent.n_cross_layers == 1
    assert CFRParadigmConfig().agent.n_cross_layers == 2
    assert DMCParadigmConfig().agent.n_cross_layers == 1


# ---------- N1: shared base shape fields ---------- #


def test_paradigm_config_agent_shared_base_shape():
    """4 paradigm cfg.agent shares base shape fields (n_counter_slots etc.)."""
    for cls in (AZParadigmConfig, BCParadigmConfig, CFRParadigmConfig, DMCParadigmConfig):
        cfg = cls()
        assert cfg.agent.n_counter_slots == 2 * 6 * 128 + 2 * 140 + 16
        assert cfg.agent.n_hooks == 900
        assert cfg.agent.max_tokens_per_hook == 120
        assert cfg.agent.max_actions == 2048
