"""Engine-derived eligible card sets and reproducible bounded random decks."""

from pathlib import Path

from gicg_env import GicgEnv
from training.core.deck_sampling import random_deck as random_deck


def card_grades():
    return {
        path.stem: int(path.parent.name[1:]) for path in sorted(Path('data/pools/v_legacy/cards').glob('L[1-6]/*.lua'))
    }


def eligible_cards(cfg, teams):
    """Ask the engine, rather than reimplement weapon/talent rules in Python."""
    scenario = cfg.scenario
    env = GicgEnv(
        list(teams[0]),
        list(teams[1]),
        card_pool=scenario.card_pool,
        pool=scenario.pool,
        data_dir=scenario.data_dir,
        max_rounds=scenario.max_rounds,
        deck_padding=None,
    )
    try:
        names = env._engine.get_card_names()
        allowed = set(scenario.card_pool)
        return tuple(
            sorted({names[ref] for ref in list(env._engine.hand_refs(p)) + list(env._engine.deck_refs(p))} & allowed)
            for p in (0, 1)
        )
    finally:
        env.close()
