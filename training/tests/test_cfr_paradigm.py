"""Unit tests for CFR paradigm adapter (P4-CFR).

Covers Paradigm protocol conformance + policy/loss/buffer/network shape
+ traversal collector wiring (mocked traverser; no Go-engine calls).

CFR is frozen-research tier (paradigm-cfr/spec.md C6.1) — these tests
verify the adapter shape only, not algorithmic correctness (that is
covered by the existing ``training/tests/test_cfr_*`` suite which the
adapter does not modify).
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from training.core.protocols import Batch, CollectorOutput, LossComputer, PipelineState
from training.paradigms.cfr.config import (
    CFRAgentShapeCfg,
    CFRParadigmConfig,
    CFRTraversalCfg,
)
from training.paradigms.cfr.loss import CFRLoss, cfr_advantage_mse, cfr_strategy_mse
from training.paradigms.cfr.network import CFRNetwork
from training.paradigms.cfr._async import CFRAsyncCollector
from training.paradigms.cfr.paradigm import CFRParadigm, _CFRBufferBundle
from training.paradigms.cfr.policy import CFREpisodePolicy


# ---------- Config from_dict ---------- #


def test_cfr_paradigm_config_from_dict_minimal():
    cfg = CFRParadigmConfig.from_dict({})
    assert cfg.advantage_lr == 1e-3
    assert cfg.traversals_per_iteration == 64
    assert cfg.tier == 'frozen-research'
    assert isinstance(cfg.agent, CFRAgentShapeCfg)
    assert isinstance(cfg.traversal, CFRTraversalCfg)


def test_cfr_paradigm_config_from_dict_full():
    cfg = CFRParadigmConfig.from_dict(
        {
            'advantage_lr': 5e-4,
            'strategy_lr': 5e-4,
            'fit_batch_size': 64,
            'advantage_buffer_capacity': 50_000,
            'agent': {'d_model': 32, 'n_cross_layers': 1},
            'traversal': {'sampling_mode': 'os', 'epsilon': 0.05},
        }
    )
    assert cfg.advantage_lr == 5e-4
    assert cfg.agent.d_model == 32
    assert cfg.traversal.epsilon == 0.05


def test_cfr_paradigm_config_from_dict_unknown_key_raises():
    with pytest.raises(ValueError, match='unknown paradigm key'):
        CFRParadigmConfig.from_dict({'no_such_field': 1})


# ---------- CFREpisodePolicy (stub) ---------- #


def test_cfr_episode_policy_act_raises():
    """CFR traversal bypasses act — calling it MUST raise (no silent default)."""
    pol = CFREpisodePolicy(seed=0)
    with pytest.raises(RuntimeError, match='does not rollout episodes'):
        pol.act(obs=None, mask=None, provider=None)


def test_cfr_episode_policy_finalize_raises():
    pol = CFREpisodePolicy(seed=0)
    with pytest.raises(RuntimeError, match='does not rollout episodes'):
        pol.finalize_episode([], winner=0)


def test_cfr_episode_policy_reset_is_noop():
    pol = CFREpisodePolicy(seed=0)
    assert pol.reset() is None


# ---------- CFRLoss ---------- #


def test_cfr_loss_advantage_mse():
    # pred == target → zero loss on legal actions only.
    pred = torch.tensor([[1.0, 2.0, 3.0]], dtype=torch.float32)
    target = torch.tensor([[1.0, 2.0, 3.0]], dtype=torch.float32)
    legal = torch.tensor([[True, True, False]], dtype=torch.bool)
    batch = Batch(
        data={'head': 'advantage', 'pred': pred, 'target': target, 'legal_mask': legal},
        size=1,
    )
    loss_fn = CFRLoss(paradigm_cfg=None)
    res = loss_fn.compute(network=None, batch=batch)
    assert res.loss.item() == pytest.approx(0.0, abs=1e-6)
    assert 'advantage_loss' in res.breakdown


def test_cfr_loss_advantage_mse_nonzero():
    # Predicted regret off by 1 on legal action 0 → loss = 1/n_legal=1/1=1.
    pred = torch.tensor([[2.0, 0.0, 0.0]], dtype=torch.float32)
    target = torch.tensor([[1.0, 0.0, 0.0]], dtype=torch.float32)
    legal = torch.tensor([[True, False, False]], dtype=torch.bool)
    batch = Batch(
        data={'head': 'advantage', 'pred': pred, 'target': target, 'legal_mask': legal},
        size=1,
    )
    res = CFRLoss().compute(network=None, batch=batch)
    assert res.loss.item() == pytest.approx(1.0, abs=1e-6)


def test_cfr_loss_strategy_mse():
    pred = torch.tensor([[0.5, 0.5]], dtype=torch.float32)
    target = torch.tensor([[1.0, 0.0]], dtype=torch.float32)
    legal = torch.tensor([[True, True]], dtype=torch.bool)
    batch = Batch(
        data={'head': 'strategy', 'pred': pred, 'target': target, 'legal_mask': legal},
        size=1,
    )
    res = CFRLoss().compute(network=None, batch=batch)
    # Per-sample mean of (0.5-1)^2 + (0.5-0)^2 over 2 legal = 0.25.
    assert res.loss.item() == pytest.approx(0.25, abs=1e-6)
    assert 'strategy_loss' in res.breakdown


def test_cfr_loss_missing_keys_raises():
    batch = Batch(data={'head': 'advantage', 'pred': torch.zeros(1, 1)}, size=1)
    with pytest.raises(ValueError, match='missing required keys'):
        CFRLoss().compute(network=None, batch=batch)


def test_cfr_loss_unknown_head_raises():
    batch = Batch(
        data={
            'head': 'bogus',
            'pred': torch.zeros(1, 1),
            'target': torch.zeros(1, 1),
            'legal_mask': torch.ones(1, 1, dtype=torch.bool),
        },
        size=1,
    )
    with pytest.raises(ValueError, match='advantage'):
        CFRLoss().compute(network=None, batch=batch)


def test_cfr_loss_shape_mismatch_raises():
    batch = Batch(
        data={
            'head': 'advantage',
            'pred': torch.zeros(1, 3),
            'target': torch.zeros(1, 2),
            'legal_mask': torch.ones(1, 3, dtype=torch.bool),
        },
        size=1,
    )
    with pytest.raises(ValueError, match='shape'):
        CFRLoss().compute(network=None, batch=batch)


def test_cfr_advantage_strategy_mse_functional():
    pred = torch.tensor([[1.0, 2.0]], dtype=torch.float32)
    target = torch.tensor([[1.0, 2.0]], dtype=torch.float32)
    legal = torch.ones(1, 2, dtype=torch.bool)
    assert cfr_advantage_mse(pred, target, legal).item() == pytest.approx(0.0)
    assert cfr_strategy_mse(pred, target, legal).item() == pytest.approx(0.0)


# ---------- CFRNetwork ---------- #


def _small_agent_cfg() -> CFRAgentShapeCfg:
    """Tiny shape for cheap unit tests (encoder builds <1s)."""
    return CFRAgentShapeCfg(
        n_counter_slots=64,
        n_hooks=8,
        max_ops_per_hook=4,
        max_actions=4,
        d_model=8,
        dropout=0.0,
        n_cross_layers=1,
    )


def test_cfr_paradigm_make_network():
    """Heads = (avg_policy, advantage) — spec C4.1."""
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    net = p.make_network(cfg)
    assert isinstance(net, CFRNetwork)
    assert net.HEAD_NAMES == ('avg_policy', 'advantage')
    # avg_policy head is the CFRStrategyNet (production-inference deliverable).
    from training.paradigms.cfr.strategy_net import CFRStrategyNet

    assert isinstance(net.avg_policy_head, CFRStrategyNet)
    # Two advantage heads (one per traverser_player — spec C1.2).
    assert net.advantage_head(0) is not net.advantage_head(1)
    with pytest.raises(ValueError, match='traverser_player'):
        net.advantage_head(2)
    # parameters() walks all 3 submodules → optimizer covers them.
    n_params = sum(1 for _ in net.parameters())
    assert n_params > 0
    # forward() is not used directly; must raise (avoid silent paths).
    with pytest.raises(NotImplementedError):
        net.forward()


# ---------- CFRParadigm protocol surface ---------- #


def _paradigm_dict_small() -> dict:
    """Cheap paradigm-cfg dict used for unit-test cfg fixture."""
    return {
        'n_iterations': 10,
        'traversals_per_iteration': 4,
        'advantage_fit_steps_per_iter': 2,
        'fit_batch_size': 4,
        'advantage_buffer_capacity': 32,
        'strategy_buffer_capacity': 32,
        'value_buffer_capacity': 32,
        'agent': {
            'n_counter_slots': 64,
            'n_hooks': 8,
            'max_ops_per_hook': 4,
            'max_actions': 4,
            'd_model': 8,
            'n_cross_layers': 1,
        },
        'traversal': {'sampling_mode': 'os', 'epsilon': 0.1},
    }


class _MinimalCfg:
    """Minimal TrainingConfig surrogate — only the fields the paradigm reads.

    The driver's TrainingConfig is rich (cfg.checkpoint / cfg.scenario / …),
    but the paradigm-internals exercised by this unit suite only need
    .meta.seed / .meta.device + .paradigm.
    """

    class _Meta:
        seed: int = 0
        device: str = 'cpu'

    class _Pipeline:
        mode: str = 'serial'

    def __init__(self, paradigm: dict) -> None:
        self.meta = _MinimalCfg._Meta()
        self.paradigm = paradigm
        self.pipeline = _MinimalCfg._Pipeline()


def test_cfr_paradigm_name_and_protocol():
    p = CFRParadigm()
    assert p.name == 'cfr'
    assert p.requires_network_in_collect is True


def test_cfr_paradigm_make_buffer():
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    buf = p.make_buffer(cfg)
    assert isinstance(buf, _CFRBufferBundle)
    # Two advantage buffers (per spec C1.2 — one per traverser_player).
    assert len(buf.advantage_buffers) == 2
    # All three reservoirs empty at start.
    assert len(buf) == 0
    # Protocol-level sample is ambiguous and SHALL raise.
    with pytest.raises(RuntimeError, match='3-headed'):
        buf.sample(batch_size=1)


def test_cfr_paradigm_make_loss_returns_loss_computer():
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    loss = p.make_loss(cfg)
    assert isinstance(loss, LossComputer)


def test_cfr_paradigm_make_optimizer_covers_all_heads():
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    net = p.make_network(cfg)
    opt = p.make_optimizer(cfg, net)
    assert isinstance(opt, torch.optim.AdamW)
    # AdamW should hold *all* params (strategy_net + 2 advantage_nets).
    opt_params = sum(p.numel() for g in opt.param_groups for p in g['params'])
    net_params = sum(p.numel() for p in net.parameters())
    assert opt_params == net_params


def test_cfr_paradigm_make_episode_policy():
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    pol = p.make_episode_policy(cfg, instance_id=0, deterministic=False)
    assert isinstance(pol, CFREpisodePolicy)
    pol_det = p.make_episode_policy(cfg, instance_id=1, deterministic=True)
    assert pol_det.deterministic is True


def test_cfr_paradigm_no_opponent_pool():
    """C5.3 — CFR uses symmetric selfplay; no opp_pool needed."""
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    p.make_network(cfg)
    assert p.make_opponent_pool(cfg, network=None) is None


# ---------- step_schedule ---------- #


def test_cfr_paradigm_step_schedule_iter_based():
    """CFR cadence is iter-based, not transition-based — every iter
    produces N traversals + advantage fit."""
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    state = PipelineState.fresh(seed=0)
    plan = p.step_schedule(state, cfg)
    assert plan.collect is True
    # n_episodes here means n_traversals (CFR semantics, per protocol comment).
    assert plan.n_episodes == 4
    assert plan.train is True
    assert plan.n_train_batches == 2  # advantage_fit_steps_per_iter
    assert plan.advance_step == 1


def test_cfr_paradigm_step_schedule_terminates():
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    state = PipelineState.fresh(seed=0)
    state.step = 10  # n_iterations = 10 → next call terminates
    plan = p.step_schedule(state, cfg)
    assert plan.collect is False
    assert plan.train is False
    assert plan.advance_step == 0


# ---------- CFRTraversalCollector (mocked traverser) ---------- #


class _FakeTraverser:
    """Stub CFRTraverser. Records traverse() calls; pushes one fake
    sample into the collector buffers so drain_single_traversal succeeds."""

    def __init__(self, adv_cols, strat_col, val_col, max_actions: int) -> None:
        self.adv_cols = adv_cols
        self.strat_col = strat_col
        self.val_col = val_col
        self.max_actions = max_actions
        self.traverse_calls: list = []

    def traverse(self, env, traverser_player: int, iteration: int) -> None:
        from training.core.buffer.static_dedup import GAME_STATIC_KEYS

        self.traverse_calls.append((traverser_player, iteration))
        static = {k: np.zeros(4, dtype=np.int64) for k in GAME_STATIC_KEYS}
        # Refine each key to a 1-D zero ndarray of plausible shape.
        for k in GAME_STATIC_KEYS:
            static[k] = np.zeros(4, dtype=np.int64)
        gid = self.adv_cols[traverser_player].register_game(static)
        gid_s = self.strat_col.register_game(static)
        gid_v = self.val_col.register_game(static)
        dyn = {
            'counter_values': np.zeros(2, dtype=np.float32),
            'buffs': np.zeros((128, 16), dtype=np.float32),
            'meta': np.zeros(4, dtype=np.float32),
            'card_buckets': np.zeros(2, dtype=np.float32),
            'enemy_sizes': np.zeros(2, dtype=np.float32),
            'action_refs': np.zeros((self.max_actions, 4), dtype=np.int64),
            'action_payments': np.zeros((self.max_actions, 8), dtype=np.float32),
            'legal_mask': np.zeros(self.max_actions, dtype=bool),
            'structural_values': np.zeros(2, dtype=np.float32),
        }
        regret = np.zeros(self.max_actions, dtype=np.float32)
        policy = np.zeros(self.max_actions, dtype=np.float32)
        outcome = 0.0
        self.adv_cols[traverser_player].add_sample(gid, dyn, regret, iteration)
        self.strat_col.add_sample(gid_s, dyn, policy, iteration)
        self.val_col.add_sample(gid_v, dyn, outcome, iteration)


def test_cfr_traversal_collector_mocked():
    """Run 2 traversals against a stubbed CFRTraverser; verify samples
    flow into runtime_metrics['cfr_batches'] and buffer.push routes them."""
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    net = p.make_network(cfg)

    def env_factory(seed: int):
        class _StubEnv:
            def close(self):
                pass

        return _StubEnv()

    collector = p.make_collector(cfg, env_factory=env_factory, network=net, opp_pool=None)
    # Hot-swap traverser with our stub (avoids Go engine + nets forward).
    collector.traverser = _FakeTraverser(
        collector._adv_cols,
        collector._strat_col,
        collector._val_col,
        max_actions=cfg.paradigm['agent']['max_actions'],
    )

    out = collector.collect(n_units=2, provider=None)
    assert isinstance(out, CollectorOutput)
    assert len(out.runtime_metrics['cfr_batches']) == 2
    assert len(out.episode_stats) == 2
    # n_units is the rollup sample-count (advantage + strategy + value
    # = 1+1+1 per traversal × 2 traversals = 6).
    assert out.n_units == 6
    # Alternation: 0 then 1.
    tps = [s['traverser_player'] for s in out.episode_stats]
    assert tps == [0, 1]

    # Buffer.push consumes the cfr_batches.
    buf = p.make_buffer(cfg)
    buf.push(out)
    # 2 traversals → advantage 1+1, strategy 2, value 2.
    assert len(buf.advantage_buffers[0]) == 1
    assert len(buf.advantage_buffers[1]) == 1
    assert len(buf.strategy_buffer) == 2
    assert len(buf.value_buffer) == 2


def test_cfr_buffer_bundle_sample_head():
    """sample_head routes correctly + raises on empty / unknown head."""
    bundle = _CFRBufferBundle(
        advantage_capacity=4,
        strategy_capacity=4,
        value_capacity=4,
        max_actions=4,
        seed=0,
    )
    # Empty reservoirs → raise on sample_head.
    with pytest.raises(RuntimeError, match='empty'):
        bundle.sample_head('advantage', batch_size=1, traverser_player=0)
    with pytest.raises(ValueError, match='advantage'):
        bundle.sample_head('bogus', batch_size=1)
    with pytest.raises(ValueError, match='traverser_player'):
        bundle.sample_head('advantage', batch_size=1, traverser_player=7)


def test_cfr_collector_state_dict_roundtrip():
    """State dict captures iteration + rng state — supports ckpt resume."""
    p = CFRParadigm()
    cfg = _MinimalCfg(paradigm=_paradigm_dict_small())
    net = p.make_network(cfg)
    collector = p.make_collector(cfg, env_factory=lambda s: None, network=net, opp_pool=None)
    collector._iteration = 5
    collector._traversal_seq = 17
    sd = collector.state_dict()
    assert sd['iteration'] == 5
    assert sd['traversal_seq'] == 17
    collector._iteration = 0
    collector._traversal_seq = 0
    collector.load_state_dict(sd)
    assert collector._iteration == 5
    assert collector._traversal_seq == 17


# ---------- CFRAsyncCollector (real async collector — class-level flag) ---------- #


def test_cfr_async_collector_requires_network_in_collect():
    """Class-level flag matches the serial CFRTraversalCollector (C5.2 —
    advantage net forward inside traversal). The async collector is now the
    real mp path (training.paradigms.cfr._async); spawn/drain behavior is
    covered by test_cfr_async_collector.py + test_cfr_async_mp_e2e.py."""
    assert CFRAsyncCollector.requires_network_in_collect is True
