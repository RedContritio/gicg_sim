"""PPO gauntlet player lifecycle tests."""

from __future__ import annotations

from types import SimpleNamespace

from training.paradigms.ppo._player_loader import _PpoArgmaxPlayer


class _Agent:
    def __init__(self) -> None:
        self.game_starts = 0

    def game_start(self, static_obs) -> None:
        self.game_starts += 1

    def act(self, env, rng, *, deterministic: bool):
        return 0, {}


def test_ppo_player_starts_once_for_same_env():
    agent = _Agent()
    player = _PpoArgmaxPlayer(agent)
    env = SimpleNamespace(static_obs=object())

    assert player.select_action(env) == 0
    assert player.select_action(env) == 0
    assert agent.game_starts == 1


def test_ppo_player_starts_again_for_new_env():
    agent = _Agent()
    player = _PpoArgmaxPlayer(agent)

    assert player.select_action(SimpleNamespace(static_obs=object())) == 0
    assert player.select_action(SimpleNamespace(static_obs=object())) == 0
    assert agent.game_starts == 2
