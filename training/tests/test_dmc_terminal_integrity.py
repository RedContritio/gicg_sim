"""No incomplete episode may become a draw-labelled training example."""

import random
from types import SimpleNamespace

import pytest

from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.paradigms.dmc._episode import play_one_episode, terminal_z
from training.paradigms.dmc._mp_internal import _terminal_z
from training.paradigms.dmc._opponent import RandomPlayer
from training.paradigms.dmc.policy import DMCEpisodePolicy


@pytest.mark.parametrize('winner', [-1, None, 3])
def test_serial_and_mp_reject_unknown_terminal_targets(winner):
    for outcome in (terminal_z, _terminal_z):
        with pytest.raises(ValueError, match='terminal'):
            outcome(winner, 0)
    with pytest.raises(ValueError, match='terminal'):
        DMCEpisodePolicy().finalize_episode([], winner)


@pytest.mark.parametrize('side', [0, 1])
def test_draw_is_a_valid_zero_target_for_both_players(side):
    assert terminal_z(2, side) == _terminal_z(2, side) == 0


def test_nonterminal_cutoff_and_illegal_opponent_cannot_enter_buffer():
    cfg = load_cfg('configs/dmc/readiness_base.toml')
    env = make_env_factory(cfg, None, 41)(0)
    agent = SimpleNamespace(game_start=lambda obs: None)
    try:
        with pytest.raises(RuntimeError, match='before terminal'):
            play_one_episode(env, agent, RandomPlayer(1), agent_side=1, max_steps=0, rng_action=random.Random(1))
        bad = SimpleNamespace(select_action=lambda env: 999999)
        with pytest.raises(ValueError, match='illegal'):
            play_one_episode(env, agent, bad, agent_side=1, max_steps=1, rng_action=random.Random(1))
    finally:
        env.close()
