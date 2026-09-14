"""Seeded legal deck composition, independent of observation layout and shuffling."""

from collections import Counter
import random

from training.core.episode_seeds import derive_seed


def random_deck(eligible, seed, size=30):
    if size < 1 or not eligible or len(set(eligible)) != len(eligible):
        raise ValueError('positive size and unique nonempty eligible cards required')
    copies = [name for name in sorted(eligible) for _ in range(2)]
    deck = random.Random(seed).sample(copies, min(size, len(copies)))
    assert max(Counter(deck).values()) <= 2
    return deck


def sample_decks(scenario, seed):
    from gicg_env import GicgEnv

    if scenario.deck_0 is not None or scenario.deck_1 is not None:
        raise ValueError('random deck mode cannot also specify explicit decks')
    if not scenario.card_pool:
        raise ValueError('random deck mode requires an explicit candidate card pool')
    env = GicgEnv(
        scenario.team_0,
        scenario.team_1,
        card_pool=scenario.card_pool,
        pool=scenario.pool,
        data_dir=scenario.data_dir,
        deck_padding=None,
    )
    try:
        names = env._engine.get_card_names()
        allowed = set(scenario.card_pool)
        unknown = allowed - set(names.values())
        if unknown and scenario.char_pool:
            # Character-restricted definitions absent from both current teams
            # are omitted by the loader. Resolve against the full character
            # curriculum to distinguish legitimate talents from misspellings.
            catalog = GicgEnv(
                scenario.char_pool,
                scenario.char_pool,
                card_pool=scenario.card_pool,
                pool=scenario.pool,
                data_dir=scenario.data_dir,
                deck_padding=None,
            )
            try:
                unknown -= set(catalog._engine.get_card_names().values())
            finally:
                catalog.close()
        if unknown:
            raise ValueError(f'unknown candidate card names: {sorted(unknown)}')
        eligible = [
            sorted({names[r] for r in list(env._engine.hand_refs(p)) + list(env._engine.deck_refs(p))} & allowed)
            for p in (0, 1)
        ]
        for side, cards in enumerate(eligible):
            if 2 * len(cards) < scenario.random_deck_size:
                raise ValueError(f'player {side} has insufficient legal cards for size {scenario.random_deck_size}')
        return [
            random_deck(cards, derive_seed(seed, 'deck-composition', p), scenario.random_deck_size)
            for p, cards in enumerate(eligible)
        ]
    finally:
        env.close()
