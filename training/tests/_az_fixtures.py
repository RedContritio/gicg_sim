"""Shared AZ test fixtures — replaces the deleted ``AZConfig`` presets.

``smoke_config`` / ``fixed_1v1_config`` / ``random_1v1_config`` were
git-removed in the I31 AZ mp-pool unification (方向 C). Production-adjacent
tests consumed those presets only for two cfg sub-objects: the
``AgentConfig`` (to build + save an AZ ``Agent`` ckpt) and the
``ScenarioConfig`` (team / pool for eval matchup). These builders
reproduce the old ``smoke_config`` values exactly so the migrated tests
stay behaviorally identical (same tiny net + same 赤蝶-mirror scenario).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from training.core.network import AgentConfig
from training.core.scenario import ScenarioConfig


def az_smoke_agent_config() -> AgentConfig:
    """AgentConfig matching the old ``smoke_config().agent`` — d_model=16
    tiny net for fast ckpt round-trip in eval / baseline tests."""
    return AgentConfig(
        n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
        n_hooks=900,
        max_ops_per_hook=64,
        max_actions=2048,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )


def az_smoke_scenario(data_dir: Optional[str] = None) -> ScenarioConfig:
    """ScenarioConfig matching the old ``smoke_config().scenario`` —
    赤蝶 mirror 1v1, v_legacy+test_basic pool, 15-slot deck padding."""
    return ScenarioConfig(
        team_0=['赤蝶'],
        team_1=['赤蝶'],
        card_pool=None,
        data_dir=data_dir,
        deck_padding={'card': '碌碌无为', 'target_size': 15},
        pool=['v_legacy', 'test_basic'],
    )


def az_smoke_cfg(data_dir: Optional[str] = None) -> SimpleNamespace:
    """Minimal cfg stub exposing ``.agent`` + ``.scenario`` — the only
    attributes the migrated eval_service tests read off the old
    ``smoke_config()`` object."""
    return SimpleNamespace(
        agent=az_smoke_agent_config(),
        scenario=az_smoke_scenario(data_dir),
    )
