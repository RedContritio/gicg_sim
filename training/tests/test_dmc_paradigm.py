"""Unit tests for DMC paradigm adapter (P3-B).

Covers Paradigm protocol conformance + policy/loss/buffer adapters.
End-to-end smoke verify done out-of-band via `tools.runs.train` on
configs/dmc/smoke.toml (not run here; takes ~5 min).
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from training.core.protocols import Batch, Paradigm, PipelineState
from training.paradigms import resolve
from training.paradigms.dmc.collector import derive_seed
from training.paradigms.dmc.config import DMCParadigmConfig
from training.paradigms.dmc.loss import DMCLogitAsQLoss
from training.paradigms.dmc.policy import DMCEpisodePolicy


# ---------- Paradigm registry ---------- #


def test_paradigms_resolve_dmc():
    p = resolve('dmc')
    assert p.name == 'dmc'
    assert p.requires_network_in_collect is True


def test_paradigms_resolve_unknown_raises():
    with pytest.raises(ValueError, match='unknown paradigm'):
        resolve('does_not_exist')


# ---------- Config from_dict ---------- #


def test_dmc_paradigm_config_from_dict_minimal():
    cfg = DMCParadigmConfig.from_dict({})
    assert cfg.epsilon == 0.05
    assert cfg.gamma == 1.0


def test_dmc_paradigm_config_from_dict_full():
    cfg = DMCParadigmConfig.from_dict(
        {
            'epsilon': 0.1,
            'gamma': 0.99,
            'lr': 5e-4,
            'batch_size': 32,
            'buffer_cap': 10000,
            'agent': {'d_model': 64, 'n_cross_layers': 2},
            'opponent_mix': {
                'random': 0.5,
                'f1d2': 0.25,
                'f1d4': 0.0,
                'historical': 0.25,
                'ring_size': 10,
            },
        }
    )
    assert cfg.epsilon == 0.1
    assert cfg.agent.d_model == 64
    assert cfg.opponent_mix.f1d2 == 0.25


def test_dmc_paradigm_config_from_dict_unknown_key_raises():
    with pytest.raises(ValueError, match='unknown paradigm key'):
        DMCParadigmConfig.from_dict({'no_such_field': 1})


def test_opponent_mix_weights_must_sum_to_one():
    from training.paradigms.dmc.config import OpponentMixCfg

    with pytest.raises(ValueError, match='must sum to 1.0'):
        OpponentMixCfg(random=0.5, f1d2=0.5, f1d4=0.5, historical=0.5)


# ---------- DMCEpisodePolicy ---------- #


class _StubProvider:
    """Tiny provider returning fixed logits dict."""

    def __init__(self, logits: np.ndarray) -> None:
        self._logits = torch.from_numpy(logits.astype(np.float32))

    def forward(self, obs, mask):
        return {'logit_as_q': self._logits}

    def update_weights(self, **kwargs):
        return 0

    def current_version(self):
        return 0

    def close(self):
        pass


def test_dmc_episode_policy_argmax_when_deterministic():
    policy = DMCEpisodePolicy(epsilon=0.5, seed=0, deterministic=True)
    logits = np.array([0.1, 0.9, 0.2, 0.5])
    mask = np.array([True, True, True, True])
    provider = _StubProvider(logits)
    action, meta = policy.act(obs=None, mask=mask, provider=provider)
    assert action == 1
    assert meta['explore'] is False
    assert meta['q_value'] == pytest.approx(0.9, rel=1e-6)


def test_dmc_episode_policy_epsilon_explores():
    # epsilon = 1.0 forces explore every step.
    policy = DMCEpisodePolicy(epsilon=1.0, seed=42, deterministic=False)
    logits = np.array([0.1, 0.9, 0.2, 0.5])
    mask = np.array([True, True, True, True])
    provider = _StubProvider(logits)
    saw_explore = False
    for _ in range(10):
        _, meta = policy.act(obs=None, mask=mask, provider=provider)
        if meta['explore']:
            saw_explore = True
            break
    assert saw_explore, 'epsilon=1.0 should always explore'


def test_dmc_episode_policy_respects_mask():
    policy = DMCEpisodePolicy(epsilon=0.0, seed=0, deterministic=True)
    # Best raw logit at idx 1, but idx 1 is illegal.
    logits = np.array([0.1, 0.9, 0.2, 0.5])
    mask = np.array([True, False, True, True])
    provider = _StubProvider(logits)
    action, _ = policy.act(obs=None, mask=mask, provider=provider)
    assert action == 3  # next-best legal


def test_dmc_episode_policy_finalize_episode_win():
    policy = DMCEpisodePolicy(epsilon=0.0, seed=0)
    transitions = [({'a': 1}, 0, {'q_value': 0.5}), ({'a': 2}, 1, {'q_value': -0.1})]
    out = policy.finalize_episode(transitions, winner=0, acting_player=0)
    assert len(out) == 2
    assert all(r['return'] == 1.0 for r in out)


def test_dmc_episode_policy_finalize_episode_loss():
    policy = DMCEpisodePolicy(epsilon=0.0, seed=0)
    transitions = [({'a': 1}, 0, {}), ({'a': 2}, 1, {})]
    out = policy.finalize_episode(transitions, winner=1, acting_player=0)
    assert all(r['return'] == -1.0 for r in out)


def test_dmc_episode_policy_finalize_episode_draw():
    policy = DMCEpisodePolicy(epsilon=0.0, seed=0)
    transitions = [({'a': 1}, 0, {})]
    out = policy.finalize_episode(transitions, winner=2, acting_player=0)
    assert out[0]['return'] == 0.0


# ---------- DMCLogitAsQLoss ---------- #


class _StubNetwork:
    """Network exposing forward_batch with deterministic logits."""

    def __init__(self, logits: torch.Tensor) -> None:
        self._logits = logits

    def forward_batch(self, batch_dict):
        return self._logits, None, None


def test_dmc_loss_mse_numerical():
    # Logits[a]=1.0 for batch 0, =-1.0 for batch 1; returns=[1.0, -1.0]
    # → loss should be 0.
    logits = torch.tensor([[0.0, 1.0], [-1.0, 0.0]], dtype=torch.float32)
    action_idx = torch.tensor([1, 0], dtype=torch.long)
    returns = torch.tensor([1.0, -1.0], dtype=torch.float32)

    net = _StubNetwork(logits)
    batch = Batch(
        data={'collated': {}, 'action_idx': action_idx, 'returns': returns},
        size=2,
    )
    loss_fn = DMCLogitAsQLoss(paradigm_cfg=None)
    res = loss_fn.compute(net, batch)
    assert res.loss.item() == pytest.approx(0.0, abs=1e-6)


def test_dmc_loss_breakdown_keys():
    logits = torch.tensor([[0.2, 0.8]], dtype=torch.float32)
    action_idx = torch.tensor([0], dtype=torch.long)
    returns = torch.tensor([0.0], dtype=torch.float32)
    batch = Batch(data={'collated': {}, 'action_idx': action_idx, 'returns': returns}, size=1)
    loss_fn = DMCLogitAsQLoss(paradigm_cfg=None)
    res = loss_fn.compute(_StubNetwork(logits), batch)
    for k in ('loss', 'q_mean', 'target_mean', 'target_abs_mean'):
        assert k in res.breakdown


def test_dmc_loss_missing_keys_raises():
    batch = Batch(data={'collated': {}}, size=1)
    loss_fn = DMCLogitAsQLoss(paradigm_cfg=None)
    with pytest.raises(ValueError, match='missing required keys'):
        loss_fn.compute(_StubNetwork(torch.zeros(1, 1)), batch)


# ---------- derive_seed ---------- #


def test_derive_seed_deterministic():
    s1 = derive_seed(42, 'episode', 1)
    s2 = derive_seed(42, 'episode', 1)
    assert s1 == s2


def test_derive_seed_different_labels():
    s_a = derive_seed(42, 'episode', 1)
    s_b = derive_seed(42, 'episode', 2)
    assert s_a != s_b


def test_derive_seed_different_masters():
    s_a = derive_seed(42, 'x')
    s_b = derive_seed(43, 'x')
    assert s_a != s_b


# ---------- Paradigm protocol surface ---------- #


def _build_minimal_cfg():
    """Build a minimal TrainingConfig dict, schema-validated, for use
    in protocol smoke tests (no env_factory dispatched).

    cfg-toml-restructure-paradigm-scoped N6: archived legacy flat
    `configs/_archived/.../dmc_stage3_smoke_v2.toml` no longer loads
    (hard break per CC-301). Routed to current hybrid smoke cfg.
    """
    from training.core.config.loader import load_cfg

    return load_cfg('configs/dmc/smoke.toml')


def test_dmc_paradigm_make_network_returns_module():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    net = p.make_network(cfg)
    assert isinstance(net, torch.nn.Module)
    assert hasattr(net, 'forward_batch')
    assert hasattr(net, 'agent')


def test_dmc_paradigm_make_optimizer():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    net = p.make_network(cfg)
    opt = p.make_optimizer(cfg, net)
    assert isinstance(opt, torch.optim.AdamW)
    n_params = sum(1 for _ in opt.param_groups[0]['params'])
    assert n_params > 0


def test_dmc_paradigm_make_buffer():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    buf = p.make_buffer(cfg)
    # cfg-toml-restructure-paradigm-scoped: configs/dmc/smoke.toml uses buffer_cap=1000
    assert buf.capacity == 1000
    assert len(buf) == 0


def test_dmc_paradigm_make_loss_returns_loss_computer():
    from training.core.protocols import LossComputer

    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    loss = p.make_loss(cfg)
    assert isinstance(loss, LossComputer)


def test_dmc_paradigm_step_schedule_warmup():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    p.make_network(cfg)  # warm pcfg
    state = PipelineState.fresh(seed=cfg.meta.seed)
    plan = p.step_schedule(state, cfg)
    assert plan.collect is True
    assert plan.n_episodes == 1
    assert plan.train is False  # warmup


def test_dmc_paradigm_step_schedule_steady():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    p.make_network(cfg)
    state = PipelineState.fresh(seed=cfg.meta.seed)
    state.total_transitions = 100  # past warmup
    plan = p.step_schedule(state, cfg)
    assert plan.collect is True
    assert plan.train is True
    assert plan.n_train_batches == 4


def test_dmc_paradigm_step_schedule_terminates():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    p.make_network(cfg)
    state = PipelineState.fresh(seed=cfg.meta.seed)
    state.total_transitions = 10_000  # past total_frames=5000
    plan = p.step_schedule(state, cfg)
    assert plan.collect is False
    assert plan.train is False
    assert plan.eval is False


def test_dmc_paradigm_implements_protocol():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    # Force pcfg resolve via make_network so other protocol methods work.
    p.make_network(cfg)
    assert isinstance(p, Paradigm)


def test_dmc_paradigm_episode_policy_factory():
    cfg = _build_minimal_cfg()
    p = resolve('dmc')
    p.make_network(cfg)
    pol = p.make_episode_policy(cfg, instance_id=0, deterministic=False)
    assert isinstance(pol, DMCEpisodePolicy)
    pol_det = p.make_episode_policy(cfg, instance_id=1, deterministic=True)
    assert pol_det.deterministic is True
    assert pol_det.epsilon == 0.0
