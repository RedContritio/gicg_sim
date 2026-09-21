"""Async mp fixed_opponent (ExIt) — actor-side pool + ring broadcast tests.

Design (docs/3_plans/cards/exit_az.md「async 多进程设计草案」): the
FixedOpponentPool NEVER crosses a process boundary. Each actor rebuilds
its own pool locally from ``FixedOpponentCfg`` (in the pickled cfg);
historical ring snapshots ride a WeightsSHM slot (``az_hist_ring``) that
the parent's ``AZAsyncCollector.sync_weights`` republishes — the same
cadence/channel as the InferenceServer weight pushes. Actors refresh
their ring in ``provider.update_weights()`` (called by actor_main
between episodes) and rebuild snapshot players lazily at sample time.

Coverage:
- in-proc: actor pool construction + ring refresh against a real
  WeightsSHM owner/worker pair (no spawn).
- in-proc: ``make_collector`` async+fixed branch wires the pool.
- smoke_full: real-spawn 2-actor e2e — drained games carry
  ``opponent_kind='greedy'`` (proves the actor pool drove the opponent
  seat), ring version advances on sync_weights, clean shutdown.
"""

from __future__ import annotations

import os
import time

import pytest
import torch

from training.paradigms.az import AZParadigm
from training.paradigms.az._opponent import AZSnapshotPlayer, FixedOpponentPool, RandomPlayer
from training.paradigms.az.config import AZParadigmConfig
from training.tests.smoke_template import SMOKE_MIRROR_DECK

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
SELFPLAY_DECK = list(SMOKE_MIRROR_DECK)


def _make_env(seed: int = 0):
    from gicg_env import GicgEnv

    env = GicgEnv(
        ['赤蝶'],
        ['赤蝶'],
        seed=seed,
        data_dir=DATA_DIR,
        deck_padding={'card': '碌碌无为', 'target_size': 15},
        pool=['v_legacy', 'test_basic'],
        decks=[SELFPLAY_DECK, SELFPLAY_DECK],
    )
    env.reset(seed=seed)
    return env


def _build_cfg(paradigm_updates: dict | None = None):
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    paradigm = {
        'lr': 1e-3,
        'batch_size': 8,
        'buffer_cap': 500,
        'max_game_steps': 100,
        'agent': {
            'n_counter_slots': N_COUNTER_SLOTS,
            'n_hooks': 900,
            'max_ops_per_hook': 128,
            'max_actions': 512,
            'd_model': 16,
            'n_cross_layers': 1,
        },
        'mcts': {'n_rollouts': 2, 'max_rollout_depth': 30, 'profile': False},
    }
    if paradigm_updates:
        paradigm.update(paradigm_updates)
    return TrainingConfig(
        meta=MetaCfg(seed=42, paradigm='az', run_label='test_az_async_fixed', device='cpu'),
        pipeline=PipelineCfg(mode='async', num_actors=2),
        scenario=ScenarioCfg(
            team_0=['赤蝶'],
            team_1=['赤蝶'],
            pool=['v_legacy', 'test_basic'],
            max_rounds=10,
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            data_dir=DATA_DIR,
            deck_0=SELFPLAY_DECK,
            deck_1=SELFPLAY_DECK,
        ),
        paradigm=paradigm,
        checkpoint=CheckpointCfg(save_every=1000, keep_last_n=3, artifacts_root='artifacts'),
    )


class _StubClient:
    """InferenceClient stand-in — provider construction only stores it."""

    current_weight_version = 0

    def game_start(self, *a, **k):
        raise AssertionError('stub')

    def eval_state(self, *a, **k):
        raise AssertionError('stub')

    def game_end(self):
        raise AssertionError('stub')


def test_actor_pool_ring_refresh_in_proc():
    """Actor-side pool + WeightsSHM ring refresh, no spawn: version-gated
    load_snapshots replaces the ring; historical samples then build
    AZSnapshotPlayer from the broadcast snapshot."""
    from training.core.actor.weights_shm import WeightsSHM
    from training.paradigms.az._async import RING_TAG
    from training.paradigms.az.mp_factories import _build_actor_opponent_pool, _AZRemoteProvider

    cfg = _build_cfg(
        {
            'fixed_opponent': {
                'depth': 1,
                'random': 0.0,
                'greedy': 0.0,
                'historical': 1.0,  # ring-only pool: cold start → random fallback
            }
        }
    )
    torch.manual_seed(0)
    network = AZParadigm().make_network(cfg)
    provider = _AZRemoteProvider(cfg, actor_id=0, client=_StubClient())

    owner = WeightsSHM()
    owner.write(RING_TAG, {'snapshots': []}, version=0)
    ring_info = owner.serialize_for_worker([RING_TAG])

    pool = _build_actor_opponent_pool(cfg, provider, ring_info)
    provider.attach_opponent_pool(pool)
    assert isinstance(pool, FixedOpponentPool)
    assert provider._opp_ring_version == -1

    # Cold ring → historical falls back to random.
    provider.update_weights()
    assert provider._opp_ring_version == 0
    assert isinstance(pool.sample(), RandomPlayer)
    assert pool.last_kind == 'random'

    # Broadcast a real snapshot → ring refresh → historical builds a
    # snapshot player (MCTS over the broadcast weights).
    snapshot = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
    owner.write(RING_TAG, {'snapshots': [snapshot]}, version=7)
    provider.update_weights()
    assert provider._opp_ring_version == 7
    assert pool.snapshots() and len(pool.snapshots()) == 1
    player = pool.sample()
    assert isinstance(player, AZSnapshotPlayer)

    owner.close()


def test_actor_historical_factory_is_cpu_only(monkeypatch):
    from training.paradigms.az import _opponent
    from training.paradigms.az.mp_factories import _AZRemoteProvider, _build_actor_opponent_pool

    cfg = _build_cfg({'fixed_opponent': {'depth': 1}})
    object.__setattr__(cfg.meta, 'device', 'cuda')
    provider = _AZRemoteProvider(cfg, actor_id=0, client=_StubClient())
    captured = {}

    def capture(agent_cfg, device, mcts_cfg, card_pool_spec, seed=0):
        captured['device'] = device
        return lambda state_dict: state_dict

    monkeypatch.setattr(_opponent, 'make_snapshot_factory', capture)
    _build_actor_opponent_pool(cfg, provider, None)
    assert captured['device'] == 'cpu'


def test_async_specs_alternate_agent_seat():
    from training.paradigms.az import mp_factories

    cfg = _build_cfg({'fixed_opponent': {'depth': 1}})
    mp_factories._SPEC_COUNTERS.clear()
    first = mp_factories.az_spec_sampler(cfg, actor_id=0)
    second = mp_factories.az_spec_sampler(cfg, actor_id=0)
    assert (first.starting_player, second.starting_player) == (0, 1)


def test_make_collector_async_fixed_wires_pool():
    """make_collector async+fixed branch: AZAsyncCollector gets the pool
    (construction only — no processes until first collect)."""
    from training.paradigms.az._async import AZAsyncCollector

    cfg = _build_cfg({'fixed_opponent': {'depth': 1}})
    paradigm = AZParadigm()
    network = paradigm.make_network(cfg)
    collector = paradigm.make_collector(cfg, None, network, opp_pool=None)
    assert isinstance(collector, AZAsyncCollector)
    assert isinstance(collector._opponent_pool, FixedOpponentPool)
    collector.close()  # nothing bootstrapped — must be a safe no-op


def test_local_provider_loads_weights_from_slot():
    """_AZLocalProvider (local_inference, the default): update_weights
    loads a newer WeightsSHM slot version into the local CPU net; the
    evaluator protocol runs in-proc (game_start/eval_state/game_end)."""
    from training.core.actor.weights_shm import WeightsSHM
    from training.paradigms.az.mp_factories import WEIGHTS_TAG, _AZLocalProvider
    from training.paradigms.az.network import Agent, AgentConfig

    agent_cfg = AgentConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=900,
        max_ops_per_hook=128,
        max_actions=512,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )
    torch.manual_seed(0)
    agent = Agent(agent_cfg, device='cpu')
    torch.manual_seed(1)
    other = Agent(agent_cfg, device='cpu')

    owner = WeightsSHM()
    owner.write(WEIGHTS_TAG, {k: v.detach().cpu().clone() for k, v in agent.net.state_dict().items()}, version=1)
    info = owner.serialize_for_worker([WEIGHTS_TAG])

    cfg = _build_cfg({'fixed_opponent': {'depth': 1}})
    provider = _AZLocalProvider(cfg, actor_id=0, agent=agent, weights_shm_info=info)
    provider.update_weights()
    assert provider.current_version() == 1

    # In-proc evaluator protocol against a real env.
    env = _make_env(seed=8)
    try:
        provider.game_start(env.static_obs)
        kinds, _ = env.get_legal_actions()
        prior, value = provider.eval_state(env._get_obs(), env.get_action_refs(), env.get_legal_action_payments())
        provider.game_end()
        assert prior.shape[0] == len(kinds)
        assert isinstance(float(value), float)
    finally:
        env.close()

    # Publish a DIFFERENT net at v2 → provider loads it → params match.
    owner.write(WEIGHTS_TAG, {k: v.detach().cpu().clone() for k, v in other.net.state_dict().items()}, version=2)
    provider.update_weights()
    assert provider.current_version() == 2
    for k, v in other.net.state_dict().items():
        assert torch.equal(v, agent.net.state_dict()[k]), f'local net not updated at {k}'

    owner.close()


@pytest.mark.smoke_full
def test_az_async_fixed_mp_spawn_e2e():
    """Real-spawn e2e: 2 actors × fixed F1-D1 opponent. Drained games must
    carry opponent_kind='greedy' (the actor pool drove the opponent
    seat), ring version advances on sync_weights, clean shutdown, no
    orphans."""
    from training.paradigms.az._async import RING_TAG, AZAsyncCollector

    cfg = _build_cfg(
        {
            'fixed_opponent': {'depth': 1, 'dice_greedy': True, 'random': 0.0, 'greedy': 1.0},
        }
    )
    AZParadigmConfig.from_dict(cfg.paradigm)
    paradigm = AZParadigm()
    network = paradigm.make_network(cfg)

    collector = paradigm.make_collector(cfg, None, network, opp_pool=None)
    assert isinstance(collector, AZAsyncCollector)

    t_start = time.time()
    try:
        # First collect bootstraps: InferenceServer + WeightsSHM ring +
        # 2-actor spawn via provider_kwargs handoff.
        deadline = t_start + 60.0
        total_pulled = 0
        kinds: list = []
        winners: list = []
        last_out = None
        while time.time() < deadline and total_pulled < 2:
            last_out = collector.collect(n_episodes=4, provider=None)
            total_pulled += last_out.runtime_metrics['n_pulled']
            kinds.extend(s.get('opponent_kind') for s in last_out.episode_stats)
            winners.extend(s['winner'] for s in last_out.episode_stats)
            if total_pulled < 2:
                time.sleep(1.5)

        assert total_pulled >= 1, 'no async fixed-opponent game finished within 60s'
        # The opponent seat was driven by the actor-local pool — this is
        # the load-bearing assertion (mirror games would report None).
        assert all(k == 'greedy' for k in kinds if k is not None), f'unexpected opponent kinds: {kinds}'
        assert any(k == 'greedy' for k in kinds), f'opponent_kind never reported: {kinds}'
        assert all(w in (0, 1, 2) for w in winners)
        assert last_out is not None and last_out.transitions == []
        trajectories = last_out.runtime_metrics['az_trajectories']
        assert all(len(steps) > 0 for _gs, steps in trajectories)

        # Ring broadcast: feed the parent pool a snapshot, sync, and read
        # the owner-side slot back (actors' refresh is covered in-proc
        # above — actor internals are not visible from the parent).
        collector._opponent_pool.add_snapshot({k: v.detach().cpu().clone() for k, v in network.state_dict().items()})
        _, ver_before = collector._opp_ring_shm.read(RING_TAG)
        v = collector.sync_weights(network)
        payload, ver_after = collector._opp_ring_shm.read(RING_TAG)
        assert ver_after == v and ver_after > ver_before
        assert len(payload['snapshots']) == 1
    finally:
        t_close = time.time()
        collector.close()
        assert (time.time() - t_close) < 12.0, 'close hung (> 12s)'

    # No orphans: inference server + both actors must be gone.
    assert collector._inference_server is None
    assert collector._opp_ring_shm is None
    assert all(not ap.is_alive() for ap in collector.runtime.actor_procs())


@pytest.mark.smoke_full
def test_az_async_local_inference_determinism_e2e():
    """Two identical 1-actor local-inference runs produce byte-identical
    trajectories — per-actor seeding + in-proc CPU eval are deterministic
    (the property production per-actor reproducibility relies on)."""
    import numpy as np

    def _run_one():
        cfg = _build_cfg({'fixed_opponent': {'depth': 1, 'dice_greedy': True, 'random': 0.0, 'greedy': 1.0}})
        object.__setattr__(cfg.pipeline, 'num_actors', 1)
        torch.manual_seed(123)  # same initial weights in both runs
        p = AZParadigm()
        network = p.make_network(cfg)
        coll = p.make_collector(cfg, None, network, opp_pool=None)
        try:
            deadline = time.time() + 60.0
            while time.time() < deadline:
                out = coll.collect(n_episodes=1, provider=None)
                if out.runtime_metrics['n_pulled'] >= 1:
                    return out.runtime_metrics['az_trajectories'][0]
                time.sleep(1.0)
            raise AssertionError('no game drained within 60s')
        finally:
            coll.close()

    gs1, steps1 = _run_one()
    gs2, steps2 = _run_one()
    assert set(gs1) == set(gs2)
    for k in gs1:
        assert np.array_equal(np.asarray(gs1[k]), np.asarray(gs2[k])), f'game_static[{k}] differs'
    assert len(steps1) == len(steps2) and len(steps1) > 0
    for i, (s1, s2) in enumerate(zip(steps1, steps2)):
        assert set(s1) == set(s2), f'step {i} key mismatch'
        for k in s1:
            assert np.array_equal(np.asarray(s1[k]), np.asarray(s2[k])), f'step {i} field {k} differs'
