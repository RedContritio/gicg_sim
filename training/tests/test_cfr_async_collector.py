"""Unit tests for CFRAsyncCollector + CFRParadigm.make_collector async dispatch
(I31 #88 CFR T4 + T5).

Mock-light at the spawn boundary only: a fake Runtime captures
``start_actors`` kwargs WITHOUT spawning, but the WeightsSHM publish + 2-net
blueprint + collect drain run against real objects (tiny real CFRNetwork +
real owner-side WeightsSHM + real _CFRRunnerOutput / CFRGameBatch). The full
real-spawn e2e lives in test_cfr_async_mp_e2e.py (smoke_full, deferred to T7).

Covers:
  1. __init__ publishes 2 SHM slots (cfr_adv_p0/p1) + 2-net blueprint tempfile;
     the live network's device is untouched (deepcopy-cpu correctness point).
  2. __init__ wires start_actors with provider_kwargs (weights_shm_info +
     network_blueprint_path) AND episode_runner_factory_path (…build_cfr_traversal_runner)
     AND push_episode_record=True.
  3. collect drains _CFRRunnerOutput items → CollectorOutput matching the
     serial shape (transitions==[], runtime_metrics['cfr_batches'] populated,
     n_units = sum of batch.n_samples()).
  4. sync_weights bumps version + re-publishes both slots.
  5. make_collector dispatch: async → CFRAsyncCollector; serial/absent →
     CFRTraversalCollector; unknown → ValueError; async + env_factory=None
     does NOT raise.
"""

from __future__ import annotations

import pickle

import numpy as np
import pytest
import torch

from training.core.actor.weights_shm import WeightsSHM
from training.paradigms.cfr.network import CFRNetwork
from training.paradigms.cfr.strategy_net import CFRNetConfig

# Tiny shapes — fast net construction (parity with test_cfr_mp_factories.py).
_NET_CFG = CFRNetConfig(
    n_counter_slots=64,
    n_hooks=8,
    max_ops_per_hook=4,
    max_actions=8,
    d_model=8,
    n_cross_layers=1,
    dropout=0.0,
)


class _Pipeline:
    mode = 'async'
    num_actors = 2


class _Meta:
    seed = 123
    device = 'cpu'


class _Scenario:
    team_0 = ['赤蝶']
    team_1 = ['墨客']
    card_pool = None
    data_dir = 'data'
    max_rounds = 3
    deck_padding = None
    pool = ['v_legacy', 'test_basic']
    fix_dice = None


class _Cfg:
    """Minimal cfg stub (avoids TOML load + GicgEnv touch). ``paradigm`` is a
    dict in the mp-spawn shape that CFRParadigmConfig.from_dict accepts."""

    pipeline = _Pipeline()
    meta = _Meta()
    scenario = _Scenario()
    paradigm = {
        'version': '1.0.0',
        'paradigm': 'cfr',
        'agent': {
            'n_counter_slots': _NET_CFG.n_counter_slots,
            'n_hooks': _NET_CFG.n_hooks,
            'max_ops_per_hook': _NET_CFG.max_ops_per_hook,
            'max_actions': _NET_CFG.max_actions,
            'd_model': _NET_CFG.d_model,
            'n_cross_layers': _NET_CFG.n_cross_layers,
            'dropout': _NET_CFG.dropout,
        },
        'traversal': {'sampling_mode': 'os', 'epsilon': 0.1, 'max_game_steps': 400},
        'traversals_per_iteration': 4,
    }


class _FakeRuntime:
    """Stand-in for core.actor.runtime.Runtime — captures start_actors kwargs
    instead of spawning. close() is a no-op flag."""

    last = None  # class-level capture of the most recent instance

    def __init__(self, cfg, weights_shm=None):
        self.cfg = cfg
        self.weights_shm = weights_shm
        self.start_kwargs = None
        self.actor_kwargs = None
        self.closed = False
        _FakeRuntime.last = self

    def start_actors(self, n_actors, actor_kwargs_factory=None, actor_kwargs=None):
        self.start_kwargs = {'n_actors': n_actors}
        # Materialize the per-actor kwargs the parent would hand each actor.
        self.actor_kwargs = actor_kwargs_factory(0) if actor_kwargs_factory is not None else dict(actor_kwargs)
        return []

    def close(self):
        self.closed = True


def _patch_runtime(monkeypatch) -> None:
    monkeypatch.setattr('training.core.actor.runtime.Runtime', _FakeRuntime)


def _make_network() -> CFRNetwork:
    torch.manual_seed(0)
    return CFRNetwork(_NET_CFG, device='cpu')


def _build_collector(monkeypatch, cfg=None, env_factory=None):
    from training.paradigms.cfr._async import CFRAsyncCollector
    from training.paradigms.cfr.config import CFRParadigmConfig

    _patch_runtime(monkeypatch)
    cfg = cfg if cfg is not None else _Cfg()
    pcfg = CFRParadigmConfig.from_dict(cfg.paradigm)
    net = _make_network()
    col = CFRAsyncCollector(cfg, pcfg, net, env_factory)
    return col, net


# ---------- T4: __init__ SHM publish + blueprint ---------- #


def test_init_publishes_two_slots_and_blueprint(monkeypatch):
    col, net = _build_collector(monkeypatch)
    try:
        # Both advantage slots are warm + shapes match the live heads.
        for p in (0, 1):
            sd, ver = col._weights_shm.read(f'cfr_adv_p{p}')
            assert sd is not None, f'cfr_adv_p{p} cold after __init__'
            assert ver == 1
            live = net.advantage_head(p).state_dict()
            assert set(sd.keys()) == set(live.keys())
            for k in sd:
                assert sd[k].shape == live[k].shape
        # Blueprint tempfile holds exactly 2 nets.
        with open(col._tmpdir / 'cfr_adv_nets.pkl', 'rb') as f:
            nets_bp = pickle.load(f)
        assert isinstance(nets_bp, list) and len(nets_bp) == 2
    finally:
        col.close()


def test_init_does_not_mutate_live_network_device(monkeypatch):
    """deepcopy-cpu correctness point: blueprint built from independent CPU
    copies, so the live training network's modules stay on their device
    (PPO's in-place .cpu() would migrate them)."""
    col, net = _build_collector(monkeypatch)
    try:
        for p in (0, 1):
            for prm in net.advantage_head(p).parameters():
                assert prm.device.type == 'cpu'  # was cpu; must remain cpu, unchanged
        assert net.device == torch.device('cpu')
    finally:
        col.close()


def test_init_wires_start_actors_kwargs(monkeypatch):
    col, _ = _build_collector(monkeypatch)
    try:
        rt = _FakeRuntime.last
        assert rt.start_kwargs['n_actors'] == 2
        kw = rt.actor_kwargs
        # AB13 provider_kwargs carries both handoff fields.
        pk = kw['provider_kwargs']
        assert set(pk.keys()) == {'weights_shm_info', 'network_blueprint_path'}
        assert pk['network_blueprint_path'].endswith('cfr_adv_nets.pkl')
        assert set(pk['weights_shm_info']['slots'].keys()) == {'cfr_adv_p0', 'cfr_adv_p1'}
        # AB14 episode_runner_factory_path → traversal runner.
        assert kw['episode_runner_factory_path'].endswith('build_cfr_traversal_runner')
        # Full object pushed (carries cfr_batch).
        assert kw['push_episode_record'] is True
        # Builders resolve to the CFR mp_factories.
        m = 'training.paradigms.cfr.mp_factories'
        assert kw['build_provider_path'] == f'{m}.build_provider'
        assert kw['spec_sampler_path'] == f'{m}.cfr_spec_sampler'
    finally:
        col.close()


def test_init_raises_on_zero_actors(monkeypatch):
    from training.paradigms.cfr._async import CFRAsyncCollector
    from training.paradigms.cfr.config import CFRParadigmConfig

    _patch_runtime(monkeypatch)

    class _BadCfg(_Cfg):
        class pipeline:
            mode = 'async'
            num_actors = 0

    pcfg = CFRParadigmConfig.from_dict(_Cfg.paradigm)
    with pytest.raises(ValueError, match='num_actors must be ≥ 1'):
        CFRAsyncCollector(_BadCfg(), pcfg, _make_network())


# ---------- T4: collect drain ---------- #


class _MockQueue:
    """Hands back pre-seeded items once, then raises Empty (drain stops)."""

    def __init__(self, items):
        self._items = list(items)

    def get(self, timeout=None):
        import queue as _q

        if self._items:
            return self._items.pop(0)
        raise _q.Empty()

    def close(self):
        pass


def _runner_output(traverser_player, n_adv, n_strat, n_val):
    """Build a real _CFRRunnerOutput carrying a real CFRGameBatch. One game
    per collector (the drain invariant), with the requested sample counts on
    the traverser side. Mirrors CFRTraversalRunner.run's drain path."""
    from training.paradigms.cfr._collect_helpers import CollectorBuffer, drain_single_traversal
    from training.paradigms.cfr.mp_factories import _CFRRunnerOutput

    adv_cols = [CollectorBuffer(), CollectorBuffer()]
    strat_col = CollectorBuffer()
    val_col = CollectorBuffer()

    def _static():
        return {
            'hook_ir': np.zeros((_NET_CFG.n_hooks, _NET_CFG.max_ops_per_hook, 5), dtype=np.int32),
            'hook_mask': np.ones((_NET_CFG.n_hooks,), dtype=bool),
            'counter_sids': np.zeros((_NET_CFG.n_counter_slots,), dtype=np.int64),
            'active_slot_mask': np.ones((_NET_CFG.n_counter_slots,), dtype=bool),
            'char_skill_refs': np.full((2, 4), -1, dtype=np.int64),
            'definition_links': np.full((1, 2), -1, dtype=np.int64),
        }

    def _dynamic():
        return {
            'counter_values': np.zeros((_NET_CFG.n_counter_slots,), dtype=np.float32),
            'buffs': np.zeros((128, 16), dtype=np.float32),
            'meta': np.zeros((8,), dtype=np.float32),
            'card_buckets': np.zeros((4,), dtype=np.float32),
            'enemy_sizes': np.zeros((2,), dtype=np.float32),
            'action_refs': np.zeros((_NET_CFG.max_actions, 3), dtype=np.int64),
            'action_payments': np.zeros((_NET_CFG.max_actions, 8), dtype=np.float32),
            'legal_mask': np.ones((_NET_CFG.max_actions,), dtype=bool),
            'structural_values': np.zeros((4,), dtype=np.float32),
        }

    zeros = np.zeros((_NET_CFG.max_actions,), dtype=np.float32)
    # Exactly one game per collector; N samples added under that game id.
    adv_gid = adv_cols[traverser_player].register_game(_static())
    for _ in range(n_adv):
        adv_cols[traverser_player].add_sample(adv_gid, _dynamic(), zeros, 0)
    strat_gid = strat_col.register_game(_static())
    for _ in range(n_strat):
        strat_col.add_sample(strat_gid, _dynamic(), zeros, 0)
    val_gid = val_col.register_game(_static())
    for _ in range(n_val):
        val_col.add_sample(val_gid, _dynamic(), 0.5, 0)

    batch = drain_single_traversal(adv_cols, strat_col, val_col, traverser_player=traverser_player)
    return _CFRRunnerOutput(transitions=[], cfr_batch=batch)


def _unspawned_collector(pcfg, queue, timeout=2.0):
    from training.paradigms.cfr._async import CFRAsyncCollector

    c = CFRAsyncCollector.__new__(CFRAsyncCollector)
    c.pcfg = pcfg
    c._iter_seq = 0
    c._weights_version = 1
    c._drain_timeout_s = timeout
    c._queue = queue
    return c


def test_collect_drains_runner_outputs_matches_serial_shape():
    from training.paradigms.cfr.config import CFRParadigmConfig

    pcfg = CFRParadigmConfig.from_dict(_Cfg.paradigm)
    # One traversal per side: P0 with 2 adv samples, P1 with 3 adv samples.
    items = [_runner_output(0, 2, 1, 1), _runner_output(1, 3, 1, 0)]
    c = _unspawned_collector(pcfg, _MockQueue(items))
    out = c.collect(n_units=2, provider=None)

    assert out.transitions == []
    assert len(out.runtime_metrics['cfr_batches']) == 2
    assert out.runtime_metrics['cfr_iteration'] == 1
    # n_units = sum over both batches of (n_adv0+n_adv1+n_strat+n_val).
    assert out.n_units == (2 + 0 + 1 + 1) + (0 + 3 + 1 + 0)
    # episode_stats per batch (serial parity shape).
    assert len(out.episode_stats) == 2
    assert out.episode_stats[0]['n_adv'] == 2 and out.episode_stats[1]['n_adv'] == 3


def test_collect_timeout_returns_empty():
    import time

    from training.paradigms.cfr.config import CFRParadigmConfig

    class _EmptyQ:
        def get(self, timeout=None):
            import queue as _q

            raise _q.Empty()

    pcfg = CFRParadigmConfig.from_dict(_Cfg.paradigm)
    c = _unspawned_collector(pcfg, _EmptyQ(), timeout=0.5)
    t0 = time.time()
    out = c.collect(n_units=2, provider=None)
    assert (time.time() - t0) < 2.0
    assert out.n_units == 0 and out.runtime_metrics['cfr_batches'] == []


def test_collect_n_units_zero_uses_pcfg_default():
    from training.paradigms.cfr.config import CFRParadigmConfig

    pcfg = CFRParadigmConfig.from_dict(_Cfg.paradigm)  # traversals_per_iteration=4
    # Seed only 1 item; drain stops on Empty (target=4 but queue dries up).
    c = _unspawned_collector(pcfg, _MockQueue([_runner_output(0, 1, 1, 1)]), timeout=0.5)
    out = c.collect(n_units=0, provider=None)
    assert len(out.runtime_metrics['cfr_batches']) == 1


# ---------- T4: sync_weights ---------- #


def test_sync_weights_bumps_version_and_republishes(monkeypatch):
    col, net = _build_collector(monkeypatch)
    try:
        assert col._weights_version == 1
        # Mutate the live nets so the republished bytes differ.
        with torch.no_grad():
            for p in (0, 1):
                for prm in net.advantage_head(p).parameters():
                    prm.add_(1.0)
        col.sync_weights(net)
        assert col._weights_version == 2
        for p in (0, 1):
            sd, ver = col._weights_shm.read(f'cfr_adv_p{p}')
            assert ver == 2
            live = net.advantage_head(p).state_dict()
            for k in sd:
                assert torch.equal(sd[k], live[k].detach().cpu())
    finally:
        col.close()


# ---------- T5: make_collector dispatch ---------- #


def test_make_collector_async_returns_async(monkeypatch):
    from training.paradigms.cfr._async import CFRAsyncCollector
    from training.paradigms.cfr.paradigm import CFRParadigm

    _patch_runtime(monkeypatch)
    p = CFRParadigm()
    net = _make_network()
    col = p.make_collector(_Cfg(), env_factory=None, network=net, opp_pool=None)
    assert isinstance(col, CFRAsyncCollector)
    col.close()


def test_make_collector_serial_returns_serial(monkeypatch):
    from training.paradigms.cfr.collector import CFRTraversalCollector
    from training.paradigms.cfr.paradigm import CFRParadigm

    class _SerialCfg(_Cfg):
        class pipeline:
            mode = 'serial'
            num_actors = 1

    p = CFRParadigm()
    net = _make_network()
    col = p.make_collector(_SerialCfg(), env_factory=lambda s: None, network=net, opp_pool=None)
    assert isinstance(col, CFRTraversalCollector)


def test_make_collector_mode_absent_defaults_serial():
    from training.paradigms.cfr.collector import CFRTraversalCollector
    from training.paradigms.cfr.paradigm import CFRParadigm

    class _NoModeCfg(_Cfg):
        class pipeline:
            num_actors = 1  # no `mode` attr → defaults to 'serial'

    p = CFRParadigm()
    col = p.make_collector(_NoModeCfg(), env_factory=lambda s: None, network=_make_network(), opp_pool=None)
    assert isinstance(col, CFRTraversalCollector)


def test_make_collector_unknown_mode_raises():
    from training.paradigms.cfr.paradigm import CFRParadigm

    class _BogusCfg(_Cfg):
        class pipeline:
            mode = 'bogus'
            num_actors = 1

    p = CFRParadigm()
    with pytest.raises(ValueError, match="must be 'serial' or 'async'"):
        p.make_collector(_BogusCfg(), env_factory=None, network=_make_network(), opp_pool=None)


def test_make_collector_serial_requires_env_factory():
    from training.paradigms.cfr.paradigm import CFRParadigm

    class _SerialCfg(_Cfg):
        class pipeline:
            mode = 'serial'
            num_actors = 1

    p = CFRParadigm()
    with pytest.raises(ValueError, match='env_factory required'):
        p.make_collector(_SerialCfg(), env_factory=None, network=_make_network(), opp_pool=None)


def test_make_collector_async_none_env_factory_ok(monkeypatch):
    """async-mode with env_factory=None must NOT raise (actors rebuild env)."""
    from training.paradigms.cfr._async import CFRAsyncCollector
    from training.paradigms.cfr.paradigm import CFRParadigm

    _patch_runtime(monkeypatch)
    p = CFRParadigm()
    col = p.make_collector(_Cfg(), env_factory=None, network=_make_network(), opp_pool=None)
    assert isinstance(col, CFRAsyncCollector)
    col.close()


# ---------- robustness: short-drain observability + SHM lifecycle ---------- #


def test_collect_short_drain_reports_metrics(monkeypatch):
    """Short drain at the deadline surfaces n_drained/target in runtime_metrics
    (observability parity with PPO) instead of a silent under-feed."""
    col, _ = _build_collector(monkeypatch)
    col._drain_timeout_s = 0.05  # immediate deadline, queue empty
    try:
        out = col.collect(n_units=5, provider=None)
        assert out.runtime_metrics['n_drained'] == 0
        assert out.runtime_metrics['target_traversals'] == 5
        assert out.runtime_metrics['cfr_batches'] == []
    finally:
        col.close()


def test_close_releases_owner_shm(monkeypatch):
    """close() releases the owner WeightsSHM. Runtime was handed the shm
    (owns_shm=False) so Runtime.close does NOT unlink it — the collector must,
    or the POSIX segment leaks. close() is idempotent."""
    col, _ = _build_collector(monkeypatch)
    shm = col._weights_shm
    assert shm._slots, 'slots should be live before close'
    col.close()
    assert not shm._slots, 'owner SHM slots not released on close'
    col.close()  # idempotent — second close must not raise


def test_init_failure_tears_down_partial_resources(monkeypatch):
    """A failure during __init__ (after SHM/queue/runtime built) must self-clean
    — the driver constructs the collector OUTSIDE its close() try/finally, so a
    leaked SHM / actor pool would otherwise survive the failed construction."""
    from training.paradigms.cfr._async import CFRAsyncCollector
    from training.paradigms.cfr.config import CFRParadigmConfig

    class _BoomRuntime(_FakeRuntime):
        def start_actors(self, *a, **k):
            raise RuntimeError('spawn boom')

    monkeypatch.setattr('training.core.actor.runtime.Runtime', _BoomRuntime)
    cfg = _Cfg()
    pcfg = CFRParadigmConfig.from_dict(cfg.paradigm)
    with pytest.raises(RuntimeError, match='spawn boom'):
        CFRAsyncCollector(cfg, pcfg, _make_network(), None)
    rt = _BoomRuntime.last
    assert rt.closed is True, 'Runtime.close not called on init-failure teardown'
    assert not rt.weights_shm._slots, 'owner SHM not released on init-failure teardown'
