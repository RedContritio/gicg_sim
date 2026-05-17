"""Unit tests for AZ paradigm adapter (P4-AZ).

Covers Paradigm protocol conformance + policy/loss/buffer/network
adapters. End-to-end smoke verify (selfplay → train loop) deferred to
P4.5+ container run on the existing s055_az_stage0_baseline.toml
scenario; this file only exercises the adapter surface.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from training.core.protocols import Batch, LossComputer, Paradigm, PipelineState
from training.paradigms.az import AZParadigm
from training.paradigms.az.buffer import AZBuffer
from training.paradigms.az.collector import derive_seed
from training.paradigms.az.config import AZParadigmConfig
from training.paradigms.az.loss import AZLoss
from training.paradigms.az.network import AZNetwork
from training.paradigms.az.policy import AZEpisodePolicy
from training.core.network import AgentConfig


# NOTE: Registry consolidation (paradigms/__init__.py 'az' entry) is
# owned by the controller P4 consolidate-step — this P4-AZ ship does not
# modify the registry. Tests instantiate AZParadigm() directly.


def _resolve_az() -> AZParadigm:
    return AZParadigm()


# ---------- Paradigm identity ---------- #


def test_az_paradigm_name():
    p = _resolve_az()
    assert p.name == 'az'
    assert p.requires_network_in_collect is True


# ---------- Config from_dict ---------- #


def test_az_paradigm_config_from_dict_minimal():
    cfg = AZParadigmConfig.from_dict({})
    assert cfg.lr == 1e-3
    assert cfg.priority_weight == 3.0
    assert cfg.train.l2_coef == 1e-4


def test_az_paradigm_config_from_dict_full():
    cfg = AZParadigmConfig.from_dict(
        {
            'lr': 5e-4,
            'batch_size': 128,
            'buffer_cap': 50_000,
            'priority_weight': 2.0,
            'agent': {'d_model': 64, 'n_cross_layers': 2},
            'mcts': {'n_rollouts': 50, 'c_puct': 2.0},
            'train': {'l2_coef': 1e-5, 'entropy_coef': 0.01},
        }
    )
    assert cfg.lr == 5e-4
    assert cfg.agent.d_model == 64
    assert cfg.mcts.n_rollouts == 50
    assert cfg.train.entropy_coef == 0.01


def test_az_paradigm_config_from_dict_unknown_key_raises():
    with pytest.raises(ValueError, match='unknown paradigm key'):
        AZParadigmConfig.from_dict({'no_such_field': 1})


def test_az_paradigm_config_init_from_ckpt_default_none():
    cfg = AZParadigmConfig.from_dict({})
    assert cfg.init_from_ckpt is None
    cfg2 = AZParadigmConfig.from_dict({'init_from_ckpt': '/tmp/x.pt'})
    assert cfg2.init_from_ckpt == '/tmp/x.pt'


# ---------- AZNetwork heads ---------- #


def _tiny_agent_cfg() -> AgentConfig:
    """Smallest viable AgentConfig for unit tests — keep d_model + max_actions
    tiny so torch ops are O(ms)."""
    return AgentConfig(
        n_counter_slots=8,
        n_hooks=4,
        max_tokens_per_hook=4,
        max_actions=8,
        d_model=8,
        n_cross_layers=1,
        dropout=0.0,
    )


def test_az_network_heads_policy_value():
    net = AZNetwork(_tiny_agent_cfg(), device='cpu', lr=1e-3)
    assert net.heads == ('policy', 'value')


def test_az_network_has_module_api():
    net = AZNetwork(_tiny_agent_cfg(), device='cpu', lr=1e-3)
    # Must be an nn.Module with non-empty parameters() for the driver
    # optimizer factory.
    assert isinstance(net, torch.nn.Module)
    params = list(net.parameters())
    assert len(params) > 0
    sd = net.state_dict()
    assert isinstance(sd, dict)
    assert len(sd) > 0


# ---------- AZLoss ---------- #


class _StubAZNetwork:
    """Network exposing forward_batch with fixed (logits, value, delta)."""

    def __init__(self, logits: torch.Tensor, value: torch.Tensor) -> None:
        self._logits = logits
        self._value = value
        self.net = torch.nn.Linear(1, 1)  # dummy so AZLoss can pass model= arg

    def forward_batch(self, batch_dict):
        # delta_pred shape doesn't matter when delta_aux not in batch.
        return self._logits, self._value, torch.zeros(1)


class _NoopTrainCfg:
    l2_coef = 0.0
    entropy_coef = 0.0
    delta_aux_coef = 0.0


class _NoopParadigmCfg:
    train = _NoopTrainCfg()


def test_az_loss_zero_when_policy_matches_target():
    """If pi_net = pi_target (one-hot at index 0) and value = z, loss → 0."""
    # 1 sample, 2 legal actions. logits very peaked at idx 0 →
    # softmax≈[1, 0]; pi_target = [1, 0] → policy loss ≈ 0.
    logits = torch.tensor([[10.0, 0.0]], dtype=torch.float32)
    value = torch.tensor([1.0], dtype=torch.float32)
    z_target = torch.tensor([1.0], dtype=torch.float32)
    pi_target = torch.tensor([[1.0, 0.0]], dtype=torch.float32)
    legal_mask = torch.tensor([[True, True]], dtype=torch.bool)

    batch = Batch(
        data={
            'pi_target': pi_target,
            'z_target': z_target,
            'legal_mask': legal_mask,
        },
        size=1,
    )
    loss_fn = AZLoss(_NoopParadigmCfg())
    res = loss_fn.compute(_StubAZNetwork(logits, value), batch)
    # Tolerance loose — softmax of [10,0] is ~[0.9999, 0.0001] so KL ~ 4e-5.
    assert res.loss.item() < 1e-3


def test_az_loss_value_mse_nonzero_when_v_mispredicted():
    logits = torch.tensor([[10.0, 0.0]], dtype=torch.float32)
    value = torch.tensor([0.0], dtype=torch.float32)
    z_target = torch.tensor([1.0], dtype=torch.float32)
    pi_target = torch.tensor([[1.0, 0.0]], dtype=torch.float32)
    legal_mask = torch.tensor([[True, True]], dtype=torch.bool)
    batch = Batch(
        data={'pi_target': pi_target, 'z_target': z_target, 'legal_mask': legal_mask},
        size=1,
    )
    loss_fn = AZLoss(_NoopParadigmCfg())
    res = loss_fn.compute(_StubAZNetwork(logits, value), batch)
    # MSE(0, 1) = 1; KL term ~0; total ≈ 1.
    assert res.loss.item() == pytest.approx(1.0, abs=1e-3)
    assert res.breakdown['value_loss'] == pytest.approx(1.0, abs=1e-3)
    assert res.breakdown['policy_loss'] < 1e-3


def test_az_loss_breakdown_keys():
    logits = torch.tensor([[0.2, 0.8]], dtype=torch.float32)
    value = torch.tensor([0.0], dtype=torch.float32)
    pi_target = torch.tensor([[0.5, 0.5]], dtype=torch.float32)
    z_target = torch.tensor([0.0], dtype=torch.float32)
    legal_mask = torch.tensor([[True, True]], dtype=torch.bool)
    batch = Batch(
        data={'pi_target': pi_target, 'z_target': z_target, 'legal_mask': legal_mask},
        size=1,
    )
    loss_fn = AZLoss(_NoopParadigmCfg())
    res = loss_fn.compute(_StubAZNetwork(logits, value), batch)
    for k in ('loss', 'policy_loss', 'value_loss', 'l2', 'entropy'):
        assert k in res.breakdown


def test_az_loss_missing_keys_raises():
    batch = Batch(data={'pi_target': torch.zeros(1, 2)}, size=1)
    loss_fn = AZLoss(_NoopParadigmCfg())
    with pytest.raises(ValueError, match='missing required keys'):
        loss_fn.compute(_StubAZNetwork(torch.zeros(1, 2), torch.zeros(1)), batch)


def test_az_loss_requires_forward_batch():
    class _NoForwardBatch:
        pass

    batch = Batch(
        data={
            'pi_target': torch.tensor([[1.0, 0.0]]),
            'z_target': torch.tensor([0.0]),
            'legal_mask': torch.tensor([[True, True]]),
        },
        size=1,
    )
    loss_fn = AZLoss(_NoopParadigmCfg())
    with pytest.raises(TypeError, match='forward_batch'):
        loss_fn.compute(_NoForwardBatch(), batch)


# ---------- AZEpisodePolicy ---------- #


def test_az_episode_policy_act_requires_env():
    pol = AZEpisodePolicy(mcts_cfg=None, card_pool_spec=None, seed=0)
    with pytest.raises(ValueError, match='env'):
        pol.act(obs={'no_env_key': True}, mask=None, provider=None)


def test_az_episode_policy_act_requires_mcts_cfg():
    pol = AZEpisodePolicy(mcts_cfg=None, card_pool_spec=None, seed=0)

    class _DummyEnv:
        pass

    with pytest.raises(ValueError, match='mcts_cfg'):
        pol.act(obs={'env': _DummyEnv()}, mask=None, provider=None)


def test_az_episode_policy_finalize_win_p0():
    pol = AZEpisodePolicy(seed=0)
    trans = [{'step': 0, '_acting_player': 0}, {'step': 1, '_acting_player': 0}]
    out = pol.finalize_episode(trans, winner=0)
    assert all(r['z_target'] == 1.0 for r in out)


def test_az_episode_policy_finalize_loss_p0():
    pol = AZEpisodePolicy(seed=0)
    trans = [{'step': 0, '_acting_player': 0}]
    out = pol.finalize_episode(trans, winner=1)
    assert out[0]['z_target'] == -1.0


def test_az_episode_policy_finalize_draw():
    pol = AZEpisodePolicy(seed=0)
    trans = [{'step': 0, '_acting_player': 0}, {'step': 1, '_acting_player': 1}]
    out = pol.finalize_episode(trans, winner=2)
    assert all(r['z_target'] == 0.0 for r in out)


def test_az_episode_policy_finalize_perspective_flip():
    """Acting player 1's perspective is flipped relative to winner=0."""
    pol = AZEpisodePolicy(seed=0)
    trans = [{'step': 0, '_acting_player': 0}, {'step': 1, '_acting_player': 1}]
    out = pol.finalize_episode(trans, winner=0)
    assert out[0]['z_target'] == 1.0
    assert out[1]['z_target'] == -1.0


def test_az_episode_policy_finalize_invalid_winner():
    pol = AZEpisodePolicy(seed=0)
    with pytest.raises(ValueError, match='unknown winner'):
        pol.finalize_episode([{'_acting_player': 0}], winner=99)


# ---------- AZBuffer ---------- #


def _fake_static() -> dict:
    """Minimal static dict satisfying GAME_STATIC_KEYS."""
    from training.core.buffer.static_dedup import GAME_STATIC_KEYS

    return {k: np.zeros(2, dtype=np.float32) for k in GAME_STATIC_KEYS}


def test_az_buffer_capacity_and_len():
    buf = AZBuffer(capacity=100, priority_weight=1.0, seed=0)
    assert buf.capacity == 100
    assert len(buf) == 0


def test_az_buffer_capacity_must_be_positive():
    with pytest.raises(ValueError, match='capacity'):
        AZBuffer(capacity=0)


def test_az_buffer_sample_empty_raises():
    buf = AZBuffer(capacity=10, seed=0)
    with pytest.raises(ValueError, match='have 0'):
        buf.sample(batch_size=1)


def test_az_buffer_state_dict_roundtrip():
    buf = AZBuffer(capacity=50, seed=0)
    sd = buf.state_dict()
    assert sd['capacity'] == 50
    # mismatch raises
    buf2 = AZBuffer(capacity=100, seed=0)
    with pytest.raises(ValueError, match='capacity mismatch'):
        buf2.load_state_dict(sd)


# ---------- derive_seed ---------- #


def test_derive_seed_deterministic():
    s1 = derive_seed(42, 'episode', 1)
    s2 = derive_seed(42, 'episode', 1)
    assert s1 == s2


def test_derive_seed_different_labels():
    s_a = derive_seed(42, 'episode', 1)
    s_b = derive_seed(42, 'episode', 2)
    assert s_a != s_b


# ---------- Paradigm protocol surface ---------- #


def _find_az_cfg() -> str:
    """Find a usable AZ cfg in configs/ for protocol tests. Prefer the
    smallest. AZ paradigm cfgs are not yet ported to the new schema —
    we synthesize a minimal one in tests below instead of loading TOML."""
    return ''  # unused — see _build_minimal_az_cfg


def _build_minimal_az_cfg():
    """Build a minimal frozen TrainingConfig for protocol smoke tests
    without depending on a written TOML preset (AZ adapter ships new
    cfgs in P4.5+)."""
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    return TrainingConfig(
        meta=MetaCfg(seed=42, paradigm='az', run_label='test_az', device='cpu'),
        pipeline=PipelineCfg(mode='serial', num_actors=1),
        scenario=ScenarioCfg(
            team_0=['赤蝶'],
            team_1=['赤蝶'],
            pool=['v_legacy', 'test_basic'],
            max_rounds=10,
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            data_dir='data',
        ),
        paradigm={
            'lr': 1e-3,
            'batch_size': 8,
            'buffer_cap': 500,
            'agent': {
                'n_counter_slots': 8,
                'n_hooks': 4,
                'max_tokens_per_hook': 4,
                'max_actions': 8,
                'd_model': 8,
                'n_cross_layers': 1,
            },
            'mcts': {'n_rollouts': 4, 'profile': False},
        },
        checkpoint=CheckpointCfg(save_every=1000, keep_last_n=3, artifacts_root='artifacts'),
    )


def test_az_paradigm_make_network_returns_module():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    net = p.make_network(cfg)
    assert isinstance(net, torch.nn.Module)
    assert hasattr(net, 'forward_batch')
    assert hasattr(net, 'eval_state')
    assert net.heads == ('policy', 'value')


def test_az_paradigm_make_optimizer():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    net = p.make_network(cfg)
    opt = p.make_optimizer(cfg, net)
    assert isinstance(opt, torch.optim.AdamW)
    n_params = sum(1 for _ in opt.param_groups[0]['params'])
    assert n_params > 0


def test_az_paradigm_make_buffer():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    buf = p.make_buffer(cfg)
    assert buf.capacity == 500
    assert len(buf) == 0


def test_az_paradigm_make_loss_returns_loss_computer():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    loss = p.make_loss(cfg)
    assert isinstance(loss, LossComputer)


def test_az_paradigm_step_schedule_warmup():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    p.make_network(cfg)
    state = PipelineState.fresh(seed=cfg.meta.seed)
    plan = p.step_schedule(state, cfg)
    # Default min_buffer_before_train=256, total_transitions=0 → warm-up.
    assert plan.collect is True
    assert plan.n_episodes == 1
    assert plan.train is False


def test_az_paradigm_step_schedule_steady():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    p.make_network(cfg)
    state = PipelineState.fresh(seed=cfg.meta.seed)
    state.total_transitions = 10_000  # past warm-up
    plan = p.step_schedule(state, cfg)
    assert plan.collect is True
    assert plan.train is True
    # Default train_steps_per_game=4
    assert plan.n_train_batches == 4


def test_az_paradigm_step_schedule_terminates():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    p.make_network(cfg)
    state = PipelineState.fresh(seed=cfg.meta.seed)
    state.total_episodes = 10_000  # past total_games default 2000
    plan = p.step_schedule(state, cfg)
    assert plan.collect is False
    assert plan.train is False
    assert plan.eval is False


def test_az_paradigm_implements_protocol():
    cfg = _build_minimal_az_cfg()
    p = _resolve_az()
    p.make_network(cfg)
    assert isinstance(p, Paradigm)


def test_az_paradigm_init_from_ckpt_loads(tmp_path: Path):
    """BC warm-start path (spec A6): ckpt loaded if init_from_ckpt set.

    Matches the legacy ``training.paradigms.bc.legacy.bc_train`` ckpt format:
    ``{'cfg': dict, 'net': ActorCritic.state_dict()}`` — inner net's
    state_dict (not the wrapper's), so ``load_net_only`` finds keys
    without the ``net.`` prefix that AZNetwork.state_dict() adds.
    """
    cfg = _build_minimal_az_cfg()
    p_src = _resolve_az()
    net_src = p_src.make_network(cfg)
    # Save the inner ActorCritic's state dict (BC train format).
    inner_sd = net_src.agent.net.state_dict()
    ckpt_path = tmp_path / 'bc_pretrain.pt'
    torch.save({'cfg': {}, 'net': inner_sd}, str(ckpt_path))

    # Now build a NEW paradigm with init_from_ckpt set.
    cfg_with_ckpt = _build_minimal_az_cfg()
    new_paradigm = cfg_with_ckpt.paradigm | {'init_from_ckpt': str(ckpt_path)}
    object.__setattr__(cfg_with_ckpt, 'paradigm', new_paradigm)

    p2 = _resolve_az()
    net2 = p2.make_network(cfg_with_ckpt)
    # Inner state dicts must match after load roundtrip.
    sd_dst_inner = net2.agent.net.state_dict()
    assert sorted(inner_sd.keys()) == sorted(sd_dst_inner.keys())
    for k in inner_sd:
        assert torch.equal(inner_sd[k], sd_dst_inner[k])
