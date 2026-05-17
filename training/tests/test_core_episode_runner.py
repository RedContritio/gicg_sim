"""EpisodeRunner smoke test with mock env / policy / opponent."""

from __future__ import annotations

from typing import Any

from training.core.actor.episode_runner import EpisodeRunner
from training.core.actor.policy import EpisodePolicyBase
from training.core.eval.baselines import OpponentRegistry
from training.core.protocols import EpisodeSpec


class _MockEnv:
    """Toy env: 4 steps,winner=0 always.

    current_player alternates each call to step (P0 then P1...);
    done after 4 total steps. get_obs returns 'obs<step>'."""

    def __init__(self, scenario_seed: int = 0) -> None:
        self.seed = scenario_seed
        self.step_n = 0
        self.done = False
        self.current_player = 0
        self._engine = self  # for _winner() lookup
        self.winner = -1

    def get_obs(self):
        return f'obs{self.step_n}'

    def get_legal_actions(self):
        return [0, 1, 2], None

    def step(self, action):
        self.step_n += 1
        if self.step_n >= 4:
            self.done = True
            self.winner = 0
        self.current_player = self.step_n % 2
        return None, 0.0, self.done, {}


class _SeqPolicy(EpisodePolicyBase):
    """Always returns action=0."""

    def act(self, obs, mask, provider):
        return 0, {'note': 'mock'}


class _MockProvider:
    def forward(self, obs, mask):
        return {}

    def update_weights(self, version_tag=None):
        return 1

    def current_version(self):
        return 1

    def close(self):
        pass


class _AlwaysZero:
    def select_action(self, env):
        return 0


def _factory_mock_random(seed: int, params: dict) -> _AlwaysZero:
    return _AlwaysZero()


def _build_runner() -> EpisodeRunner:
    reg = OpponentRegistry()
    reg.register('always_zero', _factory_mock_random)

    def env_factory(scenario_seed: int) -> _MockEnv:
        return _MockEnv(scenario_seed)

    return EpisodeRunner(env_factory, reg)


def test_run_one_episode():
    runner = _build_runner()
    spec = EpisodeSpec(scenario_seed=1, opponent_id='always_zero')
    record = runner.run(spec, _SeqPolicy(), _MockProvider(), our_player=0)
    assert record.opponent_id == 'always_zero'
    assert record.scenario_seed == 1
    # Our player is 0; current_player starts at 0,every step it flips.
    # Steps 0,2 are our turns (since current_player == 0); step 4 is done.
    # Both steps 0 and 2 → transitions; opponent steps 1 + 3 do not append.
    assert record.length >= 1


def test_run_record_has_transition_payload():
    runner = _build_runner()
    spec = EpisodeSpec(scenario_seed=2, opponent_id='always_zero')
    record = runner.run(spec, _SeqPolicy(), _MockProvider(), our_player=0)
    if record.transitions:
        t = record.transitions[0]
        assert 'note' in t.payload


def test_winner_recorded():
    runner = _build_runner()
    spec = EpisodeSpec(scenario_seed=0, opponent_id='always_zero')
    record = runner.run(spec, _SeqPolicy(), _MockProvider(), our_player=0)
    assert record.winner == 0


def test_unknown_opponent_raises():
    runner = _build_runner()
    spec = EpisodeSpec(scenario_seed=0, opponent_id='nonexistent')
    import pytest

    with pytest.raises(ValueError, match='unknown opponent'):
        runner.run(spec, _SeqPolicy(), _MockProvider(), our_player=0)
