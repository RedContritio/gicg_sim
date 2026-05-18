"""Paradigm-agnostic env factory — build GicgEnv from cfg.scenario.

Canonical 3-arg signature per `env-factory-unification` change (ship
2026-05-17). Replaces both the prior 2-arg orphan `core/env_factory.py`
form and the 1-arg `core/env_factory_legacy.py` (now removed). All
callers (AZ async_loop / tools.runs.train / tests) thread `obs_config_json`
+ `master_seed` explicitly — no magic seed extraction from cfg, no
implicit `cfg.obs.to_engine_json()` fallback.

Invariants (training-architecture/paradigm-onboarding.md PA-EF1..6):
- 3 arg 全 required, 无 default magic
- cfg 只读 cfg.scenario, 不耦合 cfg.obs / cfg.seed / cfg.meta.seed
- obs_config_json=None 合法 = engine 默认 (all-on shuffle)
- Returned closure: per-game seed = master_seed + game_idx, reset 后返回
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def make_env_factory(
    cfg: Any,
    obs_config_json: Optional[dict],
    master_seed: int,
) -> Callable[[int], object]:
    """Return env_factory(game_idx) -> GicgEnv with seeded reset.

    Args:
        cfg: Must expose ``cfg.scenario`` (ScenarioConfig from
            ``training.core.scenario``). No other cfg fields are read —
            paradigm-agnostic by construction.
        obs_config_json: ``ObsConfig.to_engine_json()`` dict, or ``None``.
            ``None`` = engine default (all-on shuffle +
            include_char_skill_refs). AZ caller passes
            ``cfg.obs.to_engine_json()``; DMC / CFR / BC caller passes
            ``None`` (those configs don't carry ObsConfig).
        master_seed: int base seed. Per-game seed = master_seed + game_idx.
            AZ pass ``cfg.seed`` (legacy schema); unified-pipeline pass
            ``cfg.meta.seed`` (new schema).

    Returns:
        Callable ``env_factory(game_idx: int) -> GicgEnv`` — fresh reset()-ed
        env per call, seeded deterministically by master_seed + game_idx.
    """
    from gicg_env import GicgEnv

    def env_factory(game_idx: int):
        seed = master_seed + int(game_idx)
        env = GicgEnv(
            cfg.scenario.team_0,
            cfg.scenario.team_1,
            card_pool=cfg.scenario.card_pool,
            seed=seed,
            data_dir=cfg.scenario.data_dir,
            obs_config=obs_config_json,
            max_rounds=cfg.scenario.max_rounds,
            fix_dice=cfg.scenario.fix_dice,
            obs_mask=cfg.scenario.obs_mask,
            deck_padding=cfg.scenario.deck_padding,
            pool=cfg.scenario.pool,
        )
        env.reset(seed=seed)
        return env

    return env_factory
