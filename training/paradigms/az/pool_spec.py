"""Per-player CardPoolSpec resolver — public (no underscore) because
both the collector parent process and the spawned actors (via
``mp_factories``) need it.
"""

from __future__ import annotations

from gicg_env import GicgEnv

from training.core.scenario import decks_arg


def resolve_pool_refs(scenario) -> dict[int, list[int]]:
    """Build per-player SharedFixedPool ref lists from the scenario's
    actual deck composition."""
    env = GicgEnv(
        scenario.team_0,
        scenario.team_1,
        card_pool=scenario.card_pool,
        seed=0,
        data_dir=scenario.data_dir,
        max_rounds=scenario.max_rounds,
        fix_dice=scenario.fix_dice,
        obs_mask=scenario.obs_mask,
        deck_padding=scenario.deck_padding,
        pool=scenario.pool,
        decks=decks_arg(getattr(scenario, 'deck_0', None), getattr(scenario, 'deck_1', None)),
    )
    try:
        env.reset(seed=0)
        while env.phase == 1:
            env.step(0)
            if env.done:
                break
        engine = env._engine
        return {p: list(engine.hand_refs(p)) + list(engine.deck_refs(p)) for p in (0, 1)}
    finally:
        env.close()


def make_pool_spec(scenario, pool_by_player: dict[int, list[int]]):
    """Pick the right CardPoolSpec for a scenario."""
    from training.paradigms.az.determinize import PerOpponentPool, SharedFixedPool

    if getattr(scenario, 'disjoint_teams', False):
        return PerOpponentPool(pool_by_player)
    return SharedFixedPool(pool_by_player[0])
