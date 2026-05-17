"""Smoke for PPO rollout collector — structural backbone path.

Runs one tiny collect call end-to-end against a real GicgEnv to guard
against shape mismatches, dead imports, or rng-derivation regressions
that unit tests on the loss / policy / network surface alone wouldn't
catch.

Per ``ppo-structural-backbone-migration``: PPO collector now emits
structured Transition payload (``dyn_obs / refs / payments / n_legal /
log_prob / value / advantage / return``) — no longer flat obs vector.
"""

from __future__ import annotations

import numpy as np

from training.core.network import AgentConfig
from training.paradigms.ppo.collector import (
    PPORolloutCollector,
    _make_rollout_opponent,
)
from training.paradigms.ppo.config import PPOParadigmConfig
from training.paradigms.ppo.network import PPONetwork


class _Scen:
    team_0 = ('测试角色D',)
    team_1 = ('测试角色D',)
    card_pool = ()
    fix_dice = (2, 2, 2, 2, 0, 0, 0, 0)
    max_rounds = 2
    data_dir = 'data'
    obs_mask = ()
    deck_padding = {'card': '碌碌无为', 'target_size': 15}
    pool = ['v_legacy', 'test_basic']


class _Pipeline:
    mode = 'serial'


class _Meta:
    seed = 0
    device = 'cpu'


class _Cfg:
    scenario = _Scen()
    pipeline = _Pipeline()
    meta = _Meta()


def _real_env_agent_cfg(max_actions: int = 64, d_model: int = 16) -> AgentConfig:
    """AgentConfig sized to a real GicgEnv obs. Engine pins
    n_counter_slots / n_hooks to production values; smoke must match
    so encode_static / parse_dynamic_single accept the obs vector.
    """
    return AgentConfig(
        n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
        n_hooks=900,
        max_tokens_per_hook=120,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=1,
        dropout=0.0,
    )


def test_collector_self_play_emits_transitions_with_gae() -> None:
    """Self-play rollout produces transitions with structured payload."""
    pcfg = PPOParadigmConfig.from_dict(
        {
            'agent': {
                'n_counter_slots': 128,
                'n_hooks': 4,
                'max_tokens_per_hook': 8,
                'max_actions': 64,
                'd_model': 16,
                'n_cross_layers': 1,
            },
            'rollout': {'n_games_per_iter': 2, 'max_steps_per_game': 80, 'rollout_opponent': 'self'},
        }
    )
    agent_cfg = _real_env_agent_cfg(max_actions=64, d_model=16)
    net = PPONetwork(agent_cfg)
    coll = PPORolloutCollector(_Cfg(), pcfg, net, env_factory=lambda i: None)
    out = coll.collect(n_units=0, provider=None)

    assert out.n_units > 0, 'no transitions collected'
    assert len(out.episode_stats) == 2
    assert all('winner' in s and 'rounds' in s for s in out.episode_stats)
    # Each transition has the PPO payload (dyn_obs / refs / payments /
    # n_legal / log_prob / value / advantage / return). obs/legal_mask
    # deprecated (set None / None).
    for t in out.transitions:
        for k in ('dyn_obs', 'refs', 'payments', 'n_legal', 'log_prob', 'value', 'advantage', 'return'):
            assert k in t.payload, f'missing payload key {k}'
        assert t.obs is None, 'PPO Transition.obs SHALL be None (structural in payload)'


def test_collector_asymmetric_random_opponent_only_collects_p0() -> None:
    """rollout_opponent='random' → only P0 trajectory; n_games × roughly half steps."""
    pcfg = PPOParadigmConfig.from_dict(
        {
            'agent': {
                'n_counter_slots': 128,
                'n_hooks': 4,
                'max_tokens_per_hook': 8,
                'max_actions': 64,
                'd_model': 16,
                'n_cross_layers': 1,
            },
            'rollout': {'n_games_per_iter': 2, 'max_steps_per_game': 80, 'rollout_opponent': 'random'},
        }
    )
    agent_cfg = _real_env_agent_cfg(max_actions=64, d_model=16)
    net = PPONetwork(agent_cfg)
    coll = PPORolloutCollector(_Cfg(), pcfg, net, env_factory=lambda i: None)
    out = coll.collect(n_units=0, provider=None)
    assert out.n_units > 0
    assert len(out.episode_stats) == 2


def test_make_rollout_opponent_unknown_spec_raises() -> None:
    """Bad spec must raise (no silent fall-through to default)."""
    import pytest

    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match='unknown rollout_opponent'):
        _make_rollout_opponent('garbage', rng)


def test_make_rollout_opponent_random_returns_callable() -> None:
    rng = np.random.default_rng(0)
    fn = _make_rollout_opponent('random', rng)
    assert callable(fn)


def test_collector_env_factory_none_raises() -> None:
    """env_factory contract: None must raise at construction."""
    import pytest

    pcfg = PPOParadigmConfig.from_dict({})
    agent_cfg = _real_env_agent_cfg(max_actions=4, d_model=8)
    net = PPONetwork(agent_cfg)
    with pytest.raises(ValueError, match='env_factory required'):
        PPORolloutCollector(_Cfg(), pcfg, net, env_factory=None)


def test_collector_transition_loss_round_trip() -> None:
    """End-to-end: collect → buffer.push → buffer.sample → loss.compute.

    Verifies the production path A (RolloutBuffer.sample → 'transitions'
    list → PPOLoss collates internally) works under structural backbone.
    """
    from training.core.buffer.rollout import RolloutBuffer
    from training.paradigms.ppo.loss import PPOLoss

    pcfg = PPOParadigmConfig.from_dict(
        {
            'agent': {
                'n_counter_slots': 128,
                'n_hooks': 4,
                'max_tokens_per_hook': 8,
                'max_actions': 64,
                'd_model': 16,
                'n_cross_layers': 1,
            },
            'rollout': {'n_games_per_iter': 1, 'max_steps_per_game': 40, 'rollout_opponent': 'self'},
        }
    )
    agent_cfg = _real_env_agent_cfg(max_actions=64, d_model=16)
    net = PPONetwork(agent_cfg)
    coll = PPORolloutCollector(_Cfg(), pcfg, net, env_factory=lambda i: None)
    out = coll.collect(n_units=0, provider=None)
    buf = RolloutBuffer(capacity=1000)
    buf.push(out)
    bs = min(4, len(buf))
    if bs == 0:
        return  # empty collect — game ended at step 0; skip silently
    batch = buf.sample(bs, rng=np.random.default_rng(0))
    loss_fn = PPOLoss(pcfg)
    res = loss_fn.compute(net, batch)
    assert 'loss' in res.breakdown
    assert res.breakdown['loss'] == res.breakdown['loss']  # NaN guard
    assert 0.0 <= res.breakdown['clip_frac'] <= 1.0
