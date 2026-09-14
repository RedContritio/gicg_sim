"""Unit tests for BC paradigm adapter (P4-BC).

Covers Paradigm protocol conformance + config / loss / policy / network。
DatasetCollector real NPZ load is heavy(BCDataset 解码全 game_static_obs
≈ ~GB);here we patch out BCDataset to a tiny stub for collector tests。
End-to-end smoke verify(r009 ckpt reload + valid acc ± 0.005)happens
out-of-band per P4-T2.8。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
import torch

from training.core.protocols import Batch, LossComputer, PipelineState
from training.paradigms.bc.config import BCParadigmConfig
from training.paradigms.bc.loss import BCLoss
from training.paradigms.bc.network import BCNetwork
from training.paradigms.bc.paradigm import BCParadigm
from training.paradigms.bc.policy import BCArgmaxPolicy


# ---------- BCParadigmConfig ---------- #


def test_bc_paradigm_config_from_dict_minimal():
    cfg = BCParadigmConfig.from_dict({'dataset_path': '/tmp/d.npz'})
    assert cfg.dataset_path == '/tmp/d.npz'
    assert cfg.loss_kind == 'ce'
    assert cfg.value_coef == 0.0


def test_bc_paradigm_config_from_dict_kl():
    cfg = BCParadigmConfig.from_dict({'dataset_path': '/tmp/d.npz', 'loss_kind': 'kl'})
    assert cfg.loss_kind == 'kl'


def test_bc_paradigm_config_unknown_key_raises():
    with pytest.raises(ValueError, match='unknown paradigm key'):
        BCParadigmConfig.from_dict({'no_such_field': 1})


def test_bc_paradigm_config_invalid_loss_kind_raises():
    with pytest.raises(ValueError, match='loss_kind must be'):
        BCParadigmConfig.from_dict({'loss_kind': 'bad_loss'})


# ---------- BCParadigm static attributes(spec BC1.3 / BC3.3) ---------- #


def test_bc_paradigm_name_and_collect_flag():
    p = BCParadigm()
    assert p.name == 'bc'
    assert p.requires_network_in_collect is False


# ---------- Loss(numerical) ---------- #


def test_bc_loss_hard_target_ce_numerical():
    """Hard CE — perfect prediction → loss ≈ 0(after softmax 上的 -log 1)。
    Reference:logits = [+100, 0] picks idx 0 with prob ≈ 1。"""
    big = 1e3
    logits = torch.tensor([[big, 0.0]], dtype=torch.float32, requires_grad=True)
    chosen = torch.tensor([0], dtype=torch.long)
    legal = torch.tensor([[True, True]], dtype=torch.bool)

    class _StubNet:
        def forward_batch(self, batch):
            return logits, torch.zeros(1)

    cfg = BCParadigmConfig.from_dict({'dataset_path': '/x', 'loss_kind': 'ce'})
    loss_fn = BCLoss(cfg)
    batch = Batch(
        data={'fields': {'chosen_action': chosen, 'legal_mask': legal, 'terminal_z': torch.zeros(1)}},
        size=1,
    )
    res = loss_fn.compute(_StubNet(), batch)
    assert res.loss.item() == pytest.approx(0.0, abs=1e-3)
    assert res.breakdown['loss_kind'] == 0.0


def test_bc_loss_hard_target_uniform_log_n():
    """Uniform logits over 2 legal → CE = log 2 ≈ 0.693。"""
    logits = torch.zeros(1, 2)

    class _StubNet:
        def forward_batch(self, batch):
            return logits, torch.zeros(1)

    cfg = BCParadigmConfig.from_dict({'dataset_path': '/x', 'loss_kind': 'ce'})
    loss_fn = BCLoss(cfg)
    batch = Batch(
        data={
            'fields': {
                'chosen_action': torch.tensor([0]),
                'legal_mask': torch.tensor([[True, True]]),
                'terminal_z': torch.zeros(1),
            }
        },
        size=1,
    )
    res = loss_fn.compute(_StubNet(), batch)
    assert res.loss.item() == pytest.approx(np.log(2.0), abs=1e-4)


def test_bc_loss_soft_target_kl_numerical():
    """Soft target = uniform over 2 tied legals → log 2(matches the retained BC loss
    soft_target_ce_loss when target == uniform legal)。"""
    logits = torch.zeros(1, 2)

    class _StubNet:
        def forward_batch(self, batch):
            return logits, torch.zeros(1)

    cfg = BCParadigmConfig.from_dict({'dataset_path': '/x', 'loss_kind': 'kl'})
    loss_fn = BCLoss(cfg)
    batch = Batch(
        data={
            'fields': {
                'tied_mask': torch.tensor([[True, True]]),
                'legal_mask': torch.tensor([[True, True]]),
                'terminal_z': torch.zeros(1),
            }
        },
        size=1,
    )
    res = loss_fn.compute(_StubNet(), batch)
    # Soft target uniform 2-way, logits uniform → CE = log 2
    assert res.loss.item() == pytest.approx(np.log(2.0), abs=1e-4)
    assert res.breakdown['loss_kind'] == 1.0


def test_bc_loss_missing_fields_raises():
    cfg = BCParadigmConfig.from_dict({'dataset_path': '/x'})
    loss_fn = BCLoss(cfg)

    class _StubNet:
        def forward_batch(self, b):
            return torch.zeros(1, 2), torch.zeros(1)

    batch = Batch(data={'no_fields_key': {}}, size=1)
    with pytest.raises(ValueError, match="missing 'fields' key"):
        loss_fn.compute(_StubNet(), batch)


def test_bc_loss_value_coef_adds_mse():
    """value_coef > 0 → loss = policy_loss + value_coef * MSE(value, z)。
    Verify breakdown.value_loss > 0 when value mismatch from z。"""
    logits = torch.zeros(1, 2)
    value = torch.tensor([0.5])

    class _StubNet:
        def forward_batch(self, batch):
            return logits, value

    cfg = BCParadigmConfig.from_dict({'dataset_path': '/x', 'loss_kind': 'ce', 'value_coef': 1.0})
    loss_fn = BCLoss(cfg)
    batch = Batch(
        data={
            'fields': {
                'chosen_action': torch.tensor([0]),
                'legal_mask': torch.tensor([[True, True]]),
                'terminal_z': torch.tensor([-0.5]),  # gap = 1.0,MSE = 1.0
            }
        },
        size=1,
    )
    res = loss_fn.compute(_StubNet(), batch)
    assert res.breakdown['value_loss'] == pytest.approx(1.0, abs=1e-4)


# ---------- BCArgmaxPolicy(BC5.1) ---------- #


class _StubProvider:
    def __init__(self, logits: np.ndarray) -> None:
        self._logits = torch.from_numpy(logits.astype(np.float32))

    def forward(self, obs, mask):
        return {'policy_logits': self._logits}

    def update_weights(self, **kwargs):
        return 0

    def current_version(self):
        return 0

    def close(self):
        pass


def test_bc_policy_argmax_over_legal():
    policy = BCArgmaxPolicy(deterministic=True)
    logits = np.array([0.1, 0.9, 0.2, 0.5])
    mask = np.array([True, True, True, True])
    action, meta = policy.act(obs=None, mask=mask, provider=_StubProvider(logits))
    assert action == 1
    assert meta['logit_value'] == pytest.approx(0.9, rel=1e-6)


def test_bc_policy_respects_mask():
    policy = BCArgmaxPolicy(deterministic=True)
    # Best raw logit at idx 1 but masked illegal — fallback to next best
    logits = np.array([0.1, 0.9, 0.2, 0.5])
    mask = np.array([True, False, True, True])
    action, _ = policy.act(obs=None, mask=mask, provider=_StubProvider(logits))
    assert action == 3


def test_bc_policy_no_legal_returns_zero():
    policy = BCArgmaxPolicy(deterministic=True)
    logits = np.array([0.1, 0.9])
    mask = np.array([False, False])
    action, meta = policy.act(obs=None, mask=mask, provider=_StubProvider(logits))
    assert action == 0
    assert meta['n_legal'] == 0


def test_bc_policy_dict_missing_keys_raises():
    """Provider returning unexpected dict keys → KeyError。Guards against
    silent fallback when provider schema drifts。"""

    class _BadProvider:
        def forward(self, obs, mask):
            return {'unexpected_key': torch.zeros(2)}

    policy = BCArgmaxPolicy(deterministic=True)
    with pytest.raises(KeyError, match='policy_logits'):
        policy.act(obs=None, mask=np.array([True, True]), provider=_BadProvider())


# ---------- BCNetwork(BC4.1 / BC4.2)---------- #


def test_bc_paradigm_make_network_has_policy_head():
    """BCNetwork wraps ActorCritic — exposes policy logits via
    forward_batch。Value head 存在(BC4.1 — ckpt 可携带)but is_trained
    decided by value_coef = 0.0 default。"""
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    net = p.make_network(cfg)
    assert isinstance(net, BCNetwork)
    assert isinstance(net, torch.nn.Module)
    assert hasattr(net, 'forward_batch')
    # Generic ActorCritic has state_proj (combined → state_vec MLP) +
    # heads ModuleDict containing policy + value + delta (BC4.2 ckpt
    # warm-start spec preserves all 3 heads for AZ/PPO/DMC init_from_ckpt)。
    assert hasattr(net.actor_critic, 'state_proj')
    assert 'policy' in net.actor_critic.heads
    assert 'value' in net.actor_critic.heads
    assert 'delta' in net.actor_critic.heads


# ---------- BCParadigm protocol surface(no NPZ needed)---------- #


class _StubBCDataset:
    """Tiny stub replacing BCDataset so paradigm-level tests do not
    incur NPZ obs decoding overhead。"""

    def __init__(self, *args, **kwargs):
        self.chosen_action = np.array([0, 1, 0])
        self.legal_mask = np.array([[True, True], [True, True], [True, True]])
        self.tied_mask = np.array([[True, False], [False, True], [True, False]])
        self.terminal_z = np.array([1.0, -1.0, 0.0])

    def __len__(self):
        return 3

    def build_batch(self, indices):
        return {'indices': indices}


class _DummyCfg:
    """Minimal cfg.meta + cfg.paradigm + cfg.scenario object — avoids
    needing a real configs/*.toml file for protocol surface tests。"""

    class _Meta:
        seed = 0
        device = 'cpu'
        paradigm = 'bc'
        run_label = 'test_bc'

    def __init__(self, paradigm: dict) -> None:
        self.meta = self._Meta()
        self.paradigm = paradigm


def _build_minimal_cfg() -> Any:
    return _DummyCfg(
        paradigm={
            'dataset_path': '/synthetic/path.npz',
            'loss_kind': 'ce',
            'n_epochs': 3,
            'batch_size': 2,
        }
    )


def test_bc_paradigm_step_schedule_iter0_collects():
    """Spec: iter 0 collect=True(one-shot push);后续 iter collect=False。"""
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    with (
        patch('training.paradigms.bc.dataset.BCDataset', _StubBCDataset),
        patch('pathlib.Path.exists', return_value=True),
    ):
        plan = p.step_schedule(PipelineState.fresh(seed=0), cfg)
    assert plan.collect is True
    assert plan.train is True
    assert plan.n_train_batches >= 1


def test_bc_paradigm_step_schedule_iter1_skips_collect():
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    state = PipelineState.fresh(seed=0)
    state.step = 1
    with (
        patch('training.paradigms.bc.dataset.BCDataset', _StubBCDataset),
        patch('pathlib.Path.exists', return_value=True),
    ):
        plan = p.step_schedule(state, cfg)
    assert plan.collect is False
    assert plan.train is True


def test_bc_paradigm_step_schedule_terminates_after_n_epochs():
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    state = PipelineState.fresh(seed=0)
    state.step = 10  # > n_epochs=3
    with (
        patch('training.paradigms.bc.dataset.BCDataset', _StubBCDataset),
        patch('pathlib.Path.exists', return_value=True),
    ):
        plan = p.step_schedule(state, cfg)
    assert plan.collect is False
    assert plan.train is False


def test_bc_paradigm_make_buffer_sizes_to_dataset():
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    with (
        patch('training.paradigms.bc.dataset.BCDataset', _StubBCDataset),
        patch('pathlib.Path.exists', return_value=True),
    ):
        buf = p.make_buffer(cfg)
    assert buf.capacity >= 3  # at least dataset_size = 3


def test_bc_paradigm_make_collector_one_shot_push():
    """DatasetCollector.collect emits 全 dataset transitions on iter 0,
    后续 calls no-op (n_units=0)。"""
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    with (
        patch('training.paradigms.bc.dataset.BCDataset', _StubBCDataset),
        patch('pathlib.Path.exists', return_value=True),
    ):
        col = p.make_collector(cfg, env_factory=None, network=None, opp_pool=None)
        assert col.requires_network_in_collect is False
        out1 = col.collect(n_units=0, provider=None)
        assert out1.n_units == 3  # full dataset on first call
        assert len(out1.transitions) == 3
        # Subsequent collect:no-op
        out2 = col.collect(n_units=0, provider=None)
        assert out2.n_units == 0


def test_bc_paradigm_make_loss_returns_loss_computer():
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    loss = p.make_loss(cfg)
    assert isinstance(loss, LossComputer)


def test_bc_paradigm_make_episode_policy_deterministic_default():
    """BC5.1:eval-path policy is argmax,deterministic=True default。"""
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    pol = p.make_episode_policy(cfg, deterministic=True)
    assert isinstance(pol, BCArgmaxPolicy)
    assert pol.deterministic is True


def test_bc_paradigm_make_opponent_pool_none():
    """BC has no opponent — static dataset。tools.runs.train SHALL skip
    opponent for BC paradigm。"""
    p = BCParadigm()
    cfg = _build_minimal_cfg()
    assert p.make_opponent_pool(cfg, network=None) is None
