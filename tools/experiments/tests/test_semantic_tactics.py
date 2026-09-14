"""Real-engine tactical deck coverage and shared-deck configuration guards."""

from collections import Counter

import pytest

from tools.experiments.semantic_training.teams import eval_cases, with_teams
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.scenario import check_char_pool_deck_exclusive


def test_tactical_decks_cover_every_matchup_and_reset():
    cfg = load_cfg('configs/dmc/semantic_duo_tactics.toml')
    expected = Counter({name: 2 for name in cfg.scenario.card_pool})
    assert len(expected) == 8
    assert not {'碌碌无为', '以逸待劳', '速速茶点'} & expected.keys()
    for case in eval_cases(cfg, 164000, 15):
        env = make_env_factory(with_teams(cfg, case.team_0, case.team_1), None, case.env_seed)(0)
        try:
            for seed in (164001, 164002):
                env.reset(seed=seed)
                names = env._engine.get_card_names()
                for player in (0, 1):
                    refs = list(env._engine.hand_refs(player)) + list(env._engine.deck_refs(player))
                    assert Counter(names[ref] for ref in refs) == expected
        finally:
            env.close()


def test_random_teams_reject_asymmetric_decks():
    with pytest.raises(ValueError, match='incompatible'):
        check_char_pool_deck_exclusive(['赤蝶', '墨客'], ['佛跳墙'], ['荷花酥'])
