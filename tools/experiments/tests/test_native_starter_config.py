from collections import Counter
from dataclasses import replace
from itertools import combinations
from pathlib import Path
import pytest

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from tools.experiments.semantic_training.teams import eval_cases, sample_config, with_teams, matchup_key
from tools.runs._host import load_remote_from_cfg


def test_native_evaluation_covers_every_roster_pair_and_mirror(tmp_path):
    cfg = load_cfg('configs/dmc/native_starter.toml')
    assert cfg.scenario.pool == 'native_latest'
    assert not cfg.scenario.fix_dice
    assert cfg.scenario.deck_padding is None
    registry = tmp_path / 'hosts.toml'
    registry.write_text('[gpu-win]\nssh = "dev@host"\nroot = "D:/gicg_dev"\nos = "windows"\nhostname = "DEV-PC"\n')
    remote = load_remote_from_cfg(Path('configs/dmc/native_starter.toml'), registry)
    assert remote is not None and remote.ssh == 'dev@host'
    cases = eval_cases(cfg, 8101, 110)
    counts = Counter(matchup_key(c.team_0, c.team_1) for c in cases)
    assert len(counts) == 55 and set(counts.values()) == {2}
    assert sum(set(c.team_0) == set(c.team_1) for c in cases) == 20
    assert cases == eval_cases(cfg, 8101, 110)
    assert cases != eval_cases(cfg, 8102, 110)
    for seed in range(30):
        sampled = sample_config(cfg, seed).scenario
        assert len(set(sampled.team_0)) == len(set(sampled.team_1)) == 3


def test_native_random_30_card_decks_cover_all_cards_with_own_talents_only():
    cfg = load_cfg('configs/dmc/native_starter.toml')
    talent_owner = {
        '冷血之剑': '凯亚',
        '流火焦灼': '迪卢克',
        '光辉的季节': '芭芭拉',
        '混元熵增论': '砂糖',
        '噬星魔鸦': '菲谢尔',
    }
    coverage = Counter()
    rosters = list(combinations(cfg.scenario.char_pool, 3))
    for index, own in enumerate(rosters):
        other = rosters[(index + 3) % len(rosters)]
        game_cfg = with_teams(cfg, own, other)
        for seed in range(3):
            env = make_env_factory(game_cfg, None, 9100 + 10 * index + seed)(0)
            try:
                names = env._engine.get_card_names()
                for side, team in enumerate((own, other)):
                    deck = Counter(
                        names[r] for r in list(env._engine.hand_refs(side)) + list(env._engine.deck_refs(side))
                    )
                    assert sum(deck.values()) == 30 and max(deck.values()) <= 2
                    assert all(talent_owner[name] in team for name in deck if name in talent_owner)
                    coverage.update(deck)
            finally:
                env.close()
    assert set(coverage) == set(cfg.scenario.card_pool)


def test_native_random_deck_rejects_missing_names_and_undersized_pool():
    cfg = load_cfg('configs/dmc/native_starter.toml')
    for names, error in [(['最好的伙伴'], 'unknown candidate'), (['甜甜花酿鸡'], 'insufficient legal')]:
        broken = replace(cfg, scenario=replace(cfg.scenario, card_pool=names))
        with pytest.raises(ValueError, match=error):
            make_env_factory(broken, None, 9100)(0)
