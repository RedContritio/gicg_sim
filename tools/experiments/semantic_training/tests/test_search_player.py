"""SearchPlayer: determinism, env non-pollution, value-head smoke, registration."""

from dataclasses import replace

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.evaluate import _evaluated_checkpoint
from tools.experiments.semantic_training.player_loader import (
    FORMAT,
    load_semantic_agent,
    register_semantic_loader,
)
from tools.experiments.semantic_training.search_player import SearchPlayer
from tools.experiments.semantic_training.teams import with_teams
from tools.experiments.semantic_training.value_baseline import attach
from training.core.artifact_io import save_checkpoint
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.matchup.loaders import load_player
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def _make_env():
    """Small quiescent opening decision: fixed 8-omni dice, player 0 to act."""
    cfg = load_cfg('configs/dmc/native_starter.toml')
    others = [n for n in cfg.scenario.char_pool if n != '凯亚']
    cfg = with_teams(cfg, ['凯亚'] + others[:2], others[3:6])
    cfg = replace(cfg, scenario=replace(cfg.scenario, fix_dice=[0] * 7 + [8]))
    env = make_env_factory(cfg, None, 94620)(0, layout_seed=7)
    env.reset(seed=94621)
    while env.phase == 1 and not env.done:
        env.step(0)
    return env


def _make_agent(tmp_path):
    """Untrained semantic-Q agent persisted with a zero-init value head."""
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    value_head = attach(agent)
    ckpt = tmp_path / 'search_agent.pt'
    save_checkpoint(
        {
            'format': FORMAT,
            'shape': vars(shape),
            'net': agent.net.state_dict(),
            'value_head': value_head.state_dict(),
        },
        ckpt,
    )
    return load_semantic_agent(ckpt)


def test_fixed_seed_reproducible(tmp_path):
    env = _make_env()
    try:
        kinds, _ = env.get_legal_actions()
        first = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='value1p', seed=11)
        first.game_start(env.static_obs)
        a1 = first.select_action(env)
        second = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='value1p', seed=11)
        second.game_start(env.static_obs)
        a2 = second.select_action(env)
        assert a1 == a2
        assert 0 <= a1 < len(kinds)
    finally:
        env.close()


def test_candidate_enumeration_order_does_not_change_choice(tmp_path, monkeypatch):
    env = _make_env()
    try:
        original = SearchPlayer._candidates
        first = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='value1p', seed=17)
        first.game_start(env.static_obs)
        action_forward = first.select_action(env)
        monkeypatch.setattr(
            SearchPlayer, '_candidates', staticmethod(lambda current: list(reversed(original(current))))
        )
        second = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='value1p', seed=17)
        second.game_start(env.static_obs)
        assert second.select_action(env) == action_forward
    finally:
        env.close()


def test_seed_resets_search_rng(tmp_path):
    player = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='value1p', seed=1)
    player.seed(91)
    first = player.rng.getrandbits(63)
    player.seed(91)
    assert player.rng.getrandbits(63) == first


def test_search_converts_signed_value_to_probability(monkeypatch):
    class Agent:
        def observation(self, _env):
            return {'n_legal': 1}

    class Env:
        acting_player = 0

    monkeypatch.setattr(
        'tools.experiments.semantic_training.search_player.predict',
        lambda _agent, _obs: (None, -1.0),
    )
    player = SearchPlayer(Agent(), n_beliefs=1)
    assert player._value_me(Env(), 0) == 0.0
    Env.acting_player = 1
    assert player._value_me(Env(), 0) == 1.0


def test_player_spec_checkpoint_is_the_reported_checkpoint():
    assert _evaluated_checkpoint('positional.pt', {'type': 'az', 'ckpt': 'actual.pt'}) == 'actual.pt'
    assert _evaluated_checkpoint('positional.pt', {'type': 'random'}) is None


def test_select_action_does_not_pollute_env(tmp_path):
    env = _make_env()
    try:
        player = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='value1p', seed=12)
        player.game_start(env.static_obs)
        before = env.export_view()
        player.select_action(env)
        mid = env.export_view()
        player.select_action(env)
        after = env.export_view()
        assert mid == before
        assert after == before
        assert player.last_search_ms > 0.0
    finally:
        env.close()


def test_rollout_mode_returns_legal_action(tmp_path):
    env = _make_env()
    try:
        kinds, _ = env.get_legal_actions()
        player = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='rollout', rollout_plies=2, seed=13)
        player.game_start(env.static_obs)
        before = env.export_view()
        action = player.select_action(env)
        assert 0 <= action < len(kinds)
        assert env.export_view() == before
    finally:
        env.close()


def test_search_policy_loader_builds_and_selects(tmp_path):
    register_semantic_loader()
    env = _make_env()
    try:
        ckpt = tmp_path / 'loader_agent.pt'
        torch.set_num_threads(1)
        cfg = load_cfg('configs/dmc/native_starter.toml')
        shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
        agent = SemanticAgent(shape)
        value_head = attach(agent)
        save_checkpoint(
            {
                'format': FORMAT,
                'shape': vars(shape),
                'net': agent.net.state_dict(),
                'value_head': value_head.state_dict(),
            },
            ckpt,
        )
        kinds, _ = env.get_legal_actions()
        builder = load_player(
            {
                'type': 'search_policy',
                'ckpt': str(ckpt),
                'n_beliefs': 1,
                'mode': 'value1p',
                'rollout_plies': 2,
                'device': 'cpu',
            }
        )
        player = builder(seed=0)
        player.game_start(env.static_obs)
        action = player.select_action(env)
        assert 0 <= action < len(kinds)
    finally:
        env.close()


def test_playout_mode_returns_legal_action_without_pollution(tmp_path):
    env = _make_env()
    try:
        kinds, _ = env.get_legal_actions()
        player = SearchPlayer(_make_agent(tmp_path), n_beliefs=1, mode='playout', n_playouts=1, seed=14)
        player.game_start(env.static_obs)
        before = env.export_view()
        action = player.select_action(env)
        assert 0 <= action < len(kinds)
        assert env.export_view() == before
    finally:
        env.close()
