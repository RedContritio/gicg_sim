"""Shared AZ diagnostic cfg builder — replaces the deleted
``fixed_1v1_config`` preset for the ``diag_*`` scripts.

The diag scripts consumed ``fixed_1v1_config`` only for three things:
the fixed_1v1 ``AgentConfig`` (d_model=128 production-scale net), the
赤蝶-mirror ``ScenarioConfig`` (team / pool / data_dir), and
``max_game_steps``. This reproduces exactly those, so the scripts stay
behaviorally identical after the preset was git-removed (I31 AZ mp-pool
unification 方向 C). Lives under ``tools/debug/`` (not
``training.tests``) — tools must not import test fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace

from training.core.network import AgentConfig
from training.core.scenario import ScenarioConfig


def diag_agent_config() -> AgentConfig:
    """AgentConfig matching the old fixed_1v1_config().agent (d_model=128)."""
    return AgentConfig(
        n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
        n_hooks=900,
        max_ops_per_hook=64,
        max_actions=2048,
        d_model=128,
        n_cross_layers=2,
        dropout=0.0,
    )


# F4: union eligibility > 15 fail-louds now — pin the truncation-era
# composition (probe 2026-06-12, byte order). Duplicated from
# training/tests/smoke_template.SMOKE_MIRROR_DECK because tools must
# not import test fixtures (see module docstring).
_DIAG_MIRROR_DECK = [
    '乘胜追击',
    '以攻代守',
    '以牙还牙',
    '伏兵之术',
    '佛跳墙',
    '占星',
    '反制',
    '测试卡_增幅',
    '测试卡_碎片',
    '测试卡_神秘水流',
    '清洁时间',
    '玄冰',
    '瞬身之术',
    '美味烧鸡',
    '荷花酥',
]


def diag_scenario(data_dir: str = 'data') -> ScenarioConfig:
    """ScenarioConfig matching the old fixed_1v1_config().scenario
    (赤蝶 mirror 1v1, v_legacy+test_basic pool, 15-slot deck padding)."""
    return ScenarioConfig(
        team_0=['赤蝶'],
        team_1=['赤蝶'],
        card_pool=None,
        data_dir=data_dir,
        deck_padding={'card': '碌碌无为', 'target_size': 15},
        pool=['v_legacy', 'test_basic'],
        deck_0=list(_DIAG_MIRROR_DECK),
        deck_1=list(_DIAG_MIRROR_DECK),
    )


def diag_cfg(data_dir: str = 'data') -> SimpleNamespace:
    """Minimal cfg stub exposing ``.agent`` / ``.scenario`` /
    ``.max_game_steps`` — the only attributes the diag scripts read off
    the old ``fixed_1v1_config()`` object."""
    return SimpleNamespace(
        agent=diag_agent_config(),
        scenario=diag_scenario(data_dir),
        max_game_steps=400,
    )
