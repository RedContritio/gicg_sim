"""Original-cost ranking and a legal full-game skill-only evaluation baseline."""

from types import SimpleNamespace

import numpy as np
import pytest

from tools.experiments.skill_abuser import SkillAbuser, cost_rank, load_skill_catalog
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory


def cost(energy=0, fire=0, water=0, match=0, any=0):
    return {'Energy': energy, 'Dices': {'Specific': [fire, 0, water, 0, 0, 0, 0], 'Match': match, 'Any': any}}


@pytest.mark.parametrize(
    'higher,lower',
    [
        (cost(energy=1), cost(water=9)),
        (cost(water=1), cost(fire=9)),
        (cost(fire=1), cost(match=9)),
        (cost(water=2), cost(water=1, match=9)),
        (cost(match=2), cost(match=1, any=9)),
        (cost(any=2), cost(any=1)),
    ],
)
def test_lexicographic_original_cost(higher, lower):
    assert cost_rank(higher, 'fire') > cost_rank(lower, 'fire')


def test_cost_beats_payment_and_ties_use_declaration_order(monkeypatch):
    monkeypatch.setattr('tools.experiments.skill_abuser.filter_logical_actions', lambda env: [0, 1, 2])
    env = SimpleNamespace(
        has_pending=False,
        acting_player=0,
        get_legal_actions=lambda: (np.array([0, 0, 3]), np.array([9, 2, -1])),
        export_view=lambda: {'round': 1, 'players': [{'active_char': 0, 'chars': [{'name': 'x', 'element': 'fire'}]}]},
        get_action_labels=lambda: [('skill', 'A', -1), ('skill', 'B', -1), ('end', '-', -1)],
        # Discounted A is free, but its original cost still wins.
        get_legal_action_payments=lambda: np.array([[0] * 8, [3] + [0] * 7, [0] * 8]),
    )
    catalog = {('x', 'A'): {'ID': 9, 'Cost': cost(energy=2)}, ('x', 'B'): {'ID': 2, 'Cost': cost(fire=3)}}
    player = SkillAbuser(catalog)
    assert player.select_action(env) == 0
    catalog[('x', 'B')]['Cost'] = cost(energy=2)
    assert player.select_action(env) == 1


def test_end_instead_of_cards_switch_or_tune_and_complete_pending():
    player = SkillAbuser({})
    env = SimpleNamespace(has_pending=False, get_legal_actions=lambda: (np.array([1, 2, 4, 3]), None))
    assert player.select_action(env) == 3
    env.has_pending = True
    assert player.select_action(env) == 0


def test_engine_catalog_and_full_legal_game():
    cfg = load_cfg('configs/dmc/pre_rl_small.toml')
    catalog = load_skill_catalog(cfg)
    assert catalog[('赤蝶', '回火')]['Cost'] == cost(energy=3, fire=3)
    player = SkillAbuser(catalog)
    env = make_env_factory(cfg, None, 191)(0)
    seen = set()
    try:
        for _ in range(512):
            if env.done:
                break
            kinds, _ = env.get_legal_actions()
            previous = dict(player._used)
            old_round = player._round
            state = env.export_view()
            action = player.select_action(env)
            assert 0 <= action < len(kinds)
            if not env.has_pending and 0 in kinds:
                if kinds[action] == 3:
                    assert old_round == state['round']
                    view = state['players'][env.acting_player]
                    char = view['chars'][view['active_char']]['name']
                    labels = env.get_action_labels()
                    for i, kind in enumerate(kinds):
                        if kind == 0:
                            key = (env.acting_player, view['active_char'], catalog[(char, labels[i][1])]['ID'])
                            assert previous.get(key, 0) == 2
                else:
                    assert kinds[action] == 0
                assert all(count <= 2 for count in player._used.values())
            elif not env.has_pending and 3 in kinds:
                assert kinds[action] == 3
            seen.add(int(kinds[action]))
            env.step(action)
        assert env.done and 0 in seen and 3 in seen
    finally:
        env.close()


def test_two_uses_per_skill_round_and_character_and_game_reset(monkeypatch):
    monkeypatch.setattr('tools.experiments.skill_abuser.filter_logical_actions', lambda env: [0, 1, 2])
    state = {
        'round': 1,
        'players': [{'active_char': 0, 'chars': [{'name': 'x', 'element': 'fire'}, {'name': 'x', 'element': 'fire'}]}],
    }
    env = SimpleNamespace(
        has_pending=False,
        acting_player=0,
        get_legal_actions=lambda: (np.array([0, 0, 3]), None),
        export_view=lambda: state,
        get_action_labels=lambda: [('skill', 'A', -1), ('skill', 'B', -1), ('end', '-', -1)],
    )
    player = SkillAbuser({('x', 'A'): {'ID': 0, 'Cost': cost(energy=2)}, ('x', 'B'): {'ID': 1, 'Cost': cost(fire=3)}})
    assert [player.select_action(env) for _ in range(5)] == [0, 0, 1, 1, 2]
    state['players'][0]['active_char'] = 1
    assert player.select_action(env) == 0
    state['players'][0]['active_char'] = 0
    assert player.select_action(env) == 2
    env.has_pending = True
    before = dict(player._used)
    assert player.select_action(env) == 0 and player._used == before
    env.has_pending = False
    state['round'] = 2
    assert player.select_action(env) == 0
    player.game_start(None)
    assert player._used == {} and player.select_action(env) == 0
