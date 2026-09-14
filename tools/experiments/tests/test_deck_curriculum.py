"""Full L1-L6 deck eligibility, copy limits and reproducibility."""

from collections import Counter
from dataclasses import replace
from itertools import combinations

from gicg_env import GicgEnv
from tools.experiments.semantic_training.deck_curriculum import card_grades, eligible_cards, random_deck
from training.core.config.loader import load_cfg


def test_full_pool_random_decks_are_legal_and_cover_all_cards():
    cfg = load_cfg('configs/dmc/semantic_duo.toml')
    grades = card_grades()
    assert len(grades) == 26 and set(grades.values()) == set(range(1, 7))
    cfg = replace(cfg, scenario=replace(cfg.scenario, card_pool=sorted(grades), deck_padding=None))
    coverage = Counter()
    for i, team in enumerate(combinations(cfg.scenario.char_pool, 2)):
        other = [c for c in cfg.scenario.char_pool if c not in team][:2]
        eligible = eligible_cards(cfg, (team, other))
        assert all(len(cards) >= 15 for cards in eligible)
        for seed in range(4):
            decks = [random_deck(cards, i * 100 + seed * 2 + side) for side, cards in enumerate(eligible)]
            for side, deck in enumerate(decks):
                assert len(deck) == 30
                assert max(Counter(deck).values()) <= 2
                assert deck == random_deck(eligible[side], i * 100 + seed * 2 + side)
                coverage.update(deck)
            env = GicgEnv(
                list(team),
                other,
                card_pool=sorted(grades),
                pool=cfg.scenario.pool,
                data_dir=cfg.scenario.data_dir,
                decks=decks,
                deck_padding=None,
            )
            env.close()
    assert set(coverage) == set(grades)


def test_factory_random_decks_are_layout_independent_and_reset_stable():
    from training.core.env_factory import make_env_factory

    cfg = load_cfg('configs/dmc/curriculum_l6.toml')
    factory = make_env_factory(cfg, None, 171001)
    observed = []
    for layout in (1, 2):
        env = factory(0, layout_seed=layout)
        try:

            def composition():
                names = env._engine.get_card_names()
                return [
                    Counter(names[r] for r in list(env._engine.hand_refs(p)) + list(env._engine.deck_refs(p)))
                    for p in (0, 1)
                ]

            before = composition()
            assert all(sum(deck.values()) == 30 and max(deck.values()) <= 2 for deck in before)
            env.reset(seed=171002)
            assert composition() == before
            observed.append(before)
        finally:
            env.close()
    assert observed[0] == observed[1]
