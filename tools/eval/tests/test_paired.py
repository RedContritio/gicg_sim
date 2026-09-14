import random
from types import SimpleNamespace

import pytest

from tools.eval.paired import play, score_interval
from training.core.matchup.outcome import terminal_outcome


@pytest.mark.parametrize('side', [0, 1])
def test_terminal_draw_is_neither_players_loss(side):
    assert terminal_outcome(2, side) == 0
    assert terminal_outcome(side, side) == 1
    assert terminal_outcome(1 - side, side) == -1
    with pytest.raises(ValueError, match='terminal'):
        terminal_outcome(-1, side)


def test_draw_scores_and_paired_interval():
    assert score_interval([0, 0, 0, 0]) == (0.5, 0.5)
    assert score_interval([1, -1, 1, -1]) == (0.5, 0.5)
    assert score_interval([1, 1]) == (1.0, 1.0)


def test_random_epsilon_preserved_and_nonterminal_not_silently_drawn():
    class Env:
        done = False
        acting_player = 0
        static_obs = None
        _engine = SimpleNamespace(winner=0)

        def reset(self, **kw):
            self.done = False

        def get_action_refs(self):
            return [0]

        def step(self, action):
            self.done = True

    class Player:
        epsilon = 1.0
        rng = random.Random(1)

        def select_action(self, env):
            assert self.epsilon == 1.0
            return 0

    scenario = SimpleNamespace(env_seed=1, deck_seed_p0=2, deck_seed_p1=3)
    assert play(Env(), scenario, Player(), Player(), 0, 1) == 1
    Env._engine.winner = 2
    assert play(Env(), scenario, Player(), Player(), 0, 1) == 0
    assert play(Env(), scenario, Player(), Player(), 1, 1) == 0
    with pytest.raises(RuntimeError, match='step limit'):
        play(Env(), scenario, Player(), Player(), 0, 0)


def test_real_engine_round_cap_draw_is_half_score_for_both_sides():
    from gicg_env.engine import ACTION_END_TURN
    from training.core.config.loader import load_cfg
    from training.core.env_factory import make_env_factory

    cfg = load_cfg('configs/dmc/readiness_base.toml', overrides=['scenario.max_rounds=1'])
    env = make_env_factory(cfg, None, 41)(0)

    class EndPlayer:
        def select_action(self, env):
            kinds, _ = env.get_legal_actions()
            return next((i for i, kind in enumerate(kinds) if kind == ACTION_END_TURN), 0)

    scenario = SimpleNamespace(env_seed=41, deck_seed_p0=42, deck_seed_p1=43)
    try:
        for side in (0, 1):
            assert play(env, scenario, EndPlayer(), EndPlayer(), side, 8) == 0
            assert env.done and env.winner == 2
    finally:
        env.close()
