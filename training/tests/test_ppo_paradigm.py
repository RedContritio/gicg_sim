"""Unit tests for PPO paradigm adapter (P4-PPO).

Covers Paradigm protocol conformance + policy/loss/buffer/GAE adapters.
End-to-end smoke verify is not run here (PPO tier=frozen per ADR-0008
closure — no production cfg shipped with this change).

Updated per ``ppo-structural-backbone-migration``: PPO uses generic
structural ActorCritic backbone via PPOAgent (AgentBase). Tests build
PPONetwork via AgentConfig; loss tests build pre-collated structural
batch dicts via ``make_structural_batch_dict`` from smoke_template.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import torch

from training.core.buffer.rollout import RolloutBuffer
from training.core.network import AgentConfig
from training.core.protocols import Batch, LossComputer, Transition
from training.paradigms.ppo.collector import derive_seed
from training.paradigms.ppo.config import (
    PPOAgentShapeCfg,
    PPOParadigmConfig,
    PPORolloutCfg,
)
from training.paradigms.ppo.loss import PPOLoss
from training.paradigms.ppo.network import PPONetwork
from training.paradigms.ppo.paradigm import PPOParadigm
from training.paradigms.ppo.policy import PPOEpisodePolicy, compute_gae
from training.tests.smoke_template import make_structural_batch_dict


# ---------- Test helpers ---------- #


def _tiny_agent_cfg(max_actions: int = 6, d_model: int = 16) -> AgentConfig:
    """Tiny AgentConfig — match smoke_template defaults so structural
    batch fixtures align."""
    return AgentConfig(
        n_counter_slots=128,
        n_hooks=4,
        max_ops_per_hook=8,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=1,
        dropout=0.0,
    )


def _make_ppo_loss_batch(
    network: PPONetwork,
    batch_size: int,
    *,
    seed: int,
    chosen_actions: list[int],
    advantages: list[float],
    returns: list[float],
    old_log_probs: list[float] | None = None,
    legal_n: int | None = None,
) -> Batch:
    """Build a pre-collated batch for PPOLoss.compute (Path B)."""
    agent_cfg = network.agent.cfg
    collated = make_structural_batch_dict(agent_cfg, batch_size=batch_size, seed=seed)
    B = batch_size
    ma = agent_cfg.max_actions
    legal_n = ma if legal_n is None else legal_n
    legal_mask = np.zeros((B, ma), dtype=bool)
    legal_mask[:, :legal_n] = True
    collated['legal_mask'] = legal_mask
    action = torch.tensor(chosen_actions, dtype=torch.long)
    if old_log_probs is None:
        old_log_probs = [math.log(1.0 / legal_n)] * B
    old_lp = torch.tensor(old_log_probs, dtype=torch.float32)
    adv = torch.tensor(advantages, dtype=torch.float32)
    ret = torch.tensor(returns, dtype=torch.float32)
    return Batch(
        data={
            'collated': collated,
            'action': action,
            'old_log_prob': old_lp,
            'advantage': adv,
            'return': ret,
        },
        size=B,
    )


# ---------- Config from_dict ---------- #


def test_ppo_paradigm_config_from_dict_minimal():
    cfg = PPOParadigmConfig.from_dict({})
    assert cfg.gamma == 0.99
    assert cfg.gae_lambda == 0.95
    assert cfg.clip_epsilon == 0.2
    assert cfg.value_coef == 0.5
    assert cfg.entropy_coef == 0.01


def test_ppo_paradigm_config_from_dict_full():
    cfg = PPOParadigmConfig.from_dict(
        {
            'gamma': 0.95,
            'gae_lambda': 0.9,
            'clip_epsilon': 0.1,
            'lr': 1e-4,
            'agent': {'d_model': 128, 'max_actions': 64, 'n_counter_slots': 256, 'n_hooks': 16},
            'rollout': {'n_games_per_iter': 16, 'rollout_opponent': 'F1-D2'},
        }
    )
    assert cfg.gamma == 0.95
    assert cfg.agent.d_model == 128
    assert cfg.agent.max_actions == 64
    assert cfg.agent.n_counter_slots == 256
    assert cfg.rollout.n_games_per_iter == 16
    assert cfg.rollout.rollout_opponent == 'F1-D2'


def test_ppo_paradigm_config_from_dict_unknown_key_raises():
    with pytest.raises(ValueError, match='unknown paradigm key'):
        PPOParadigmConfig.from_dict({'no_such_field': 1})


def test_ppo_agent_shape_cfg_flat_mlp_field_removed():
    """R-PPO-CS-1: n_hidden_layers (flat MLP only) SHALL be removed."""
    with pytest.raises(TypeError, match='unexpected keyword'):
        PPOAgentShapeCfg(n_hidden_layers=2)


# ---------- PPONetwork ---------- #


def test_ppo_paradigm_make_network_has_two_heads():
    """P5.1: heads = (policy, value)."""
    agent_cfg = _tiny_agent_cfg(max_actions=8, d_model=16)
    net = PPONetwork(agent_cfg)
    assert net.heads == ('policy', 'value')
    # Verify structural forward path returns (policy_logits, value) shapes.
    collated = make_structural_batch_dict(agent_cfg, batch_size=2, seed=0)
    policy_logits, value = net.forward_batch(collated)
    assert policy_logits.shape == (2, 8)
    assert value.shape == (2,)


def test_ppo_paradigm_make_network_module_api():
    """nn.Module API: parameters() / state_dict() round-trip via net.* prefix."""
    agent_cfg = _tiny_agent_cfg(max_actions=4, d_model=8)
    net = PPONetwork(agent_cfg)
    assert isinstance(net, torch.nn.Module)
    params = list(net.parameters())
    assert len(params) > 0
    sd = net.state_dict()
    # Generic ActorCritic state_dict has keys 'net.*' from add_module('net', ...).
    assert any(k.startswith('net.') for k in sd)


def test_ppo_paradigm_make_network_structural_backbone_check():
    """A1 / M1: PPONetwork SHALL use generic ActorCritic backbone."""
    from training.core.network import ActorCritic

    agent_cfg = _tiny_agent_cfg(max_actions=4, d_model=8)
    net = PPONetwork(agent_cfg)
    assert isinstance(net.agent.net, ActorCritic)
    # typed_damage encoder SHALL be on (use_typed_damage=True).
    assert net.agent.net.typed_damage is not None
    assert net.agent.net._n_pools == 7  # 7-pool layout with typed_damage


# ---------- RolloutBuffer (P4.1 + P4.3) ---------- #


def test_ppo_paradigm_make_buffer_is_rollout_buffer():
    pcfg = PPOParadigmConfig.from_dict({'buffer_cap': 100})
    buf = RolloutBuffer(capacity=pcfg.buffer_cap)
    assert buf.capacity == 100
    assert len(buf) == 0


def test_ppo_rollout_buffer_clear_invariant():
    """P4.1: PPO buffer SHALL be cleared after each optimization iter."""
    buf = RolloutBuffer(capacity=10)
    from training.core.protocols import CollectorOutput

    t = Transition(obs=None, action=0, legal_mask=None, reward=0.0, done=False, payload={'log_prob': 0.0})
    out = CollectorOutput(transitions=[t, t, t], episode_stats=[], n_units=3)
    buf.push(out)
    assert len(buf) == 3
    buf.clear()
    assert len(buf) == 0


# ---------- PPOEpisodePolicy ---------- #


class _StubProvider:
    """Tiny provider returning dict {'logits','value'} for EpisodePolicy
    protocol. PPOEpisodePolicy still accepts the legacy (logits, value)
    tuple form for backwards compat — both paths tested below."""

    def __init__(self, logits: np.ndarray, value: float = 0.0) -> None:
        self._logits = torch.from_numpy(logits.astype(np.float32))
        self._value = float(value)

    def forward(self, obs, mask):
        return self._logits, torch.tensor(self._value)

    def update_weights(self, **kwargs):
        return 0

    def current_version(self):
        return 0

    def close(self):
        pass


def test_ppo_episode_policy_sample_records_log_prob():
    """P3.1 + P3.3: sample action + record log_prob for ratio computation."""
    policy = PPOEpisodePolicy(gamma=0.99, gae_lambda=0.95, seed=42)
    logits = np.array([0.0, 2.0, 0.0, 0.0])
    mask = np.array([True, True, True, True])
    provider = _StubProvider(logits, value=0.5)

    action, meta = policy.act(obs=None, mask=mask, provider=provider)
    assert action in (0, 1, 2, 3)
    assert 'log_prob' in meta
    assert 'value' in meta
    assert meta['value'] == pytest.approx(0.5)
    # log_prob is log of legal-softmax prob; bounded ≤ 0.
    assert meta['log_prob'] <= 0.0


def test_ppo_episode_policy_deterministic_argmax():
    """P3.2: eval = deterministic argmax."""
    policy = PPOEpisodePolicy(seed=0, deterministic=True)
    logits = np.array([0.1, 2.0, 0.5, 0.3])  # argmax = 1
    mask = np.array([True, True, True, True])
    provider = _StubProvider(logits)
    actions = set()
    for _ in range(5):
        a, _ = policy.act(obs=None, mask=mask, provider=provider)
        actions.add(a)
    assert actions == {1}


def test_ppo_episode_policy_respects_mask():
    """Mask: best raw logit at 1, but 1 illegal → next-best legal."""
    policy = PPOEpisodePolicy(seed=0, deterministic=True)
    logits = np.array([0.1, 2.0, 0.5, 0.3])
    mask = np.array([True, False, True, True])
    provider = _StubProvider(logits)
    a, _ = policy.act(obs=None, mask=mask, provider=provider)
    assert a == 2  # next-best legal


def test_ppo_episode_policy_finalize_gae_numeric():
    """GAE compute: simple sequence, verify formula matches spec."""
    policy = PPOEpisodePolicy(gamma=0.99, gae_lambda=0.95, seed=0)
    # 2 transitions, rewards=[1.0, -1.0], values=[0.5, 0.0], terminal at t=1.
    policy._buf = [
        {'obs': None, 'legal_mask': None, 'action': 0, 'log_prob': 0.0, 'value': 0.5, 'reward': 1.0, 'done': False},
        {'obs': None, 'legal_mask': None, 'action': 1, 'log_prob': 0.0, 'value': 0.0, 'reward': -1.0, 'done': False},
    ]
    out = policy.finalize_episode(winner=0)
    assert len(out) == 2
    assert out[1]['done'] is True
    # t=1 (done=True): next_value=0, nonterm=0
    #   delta = -1.0 + γ·0·0 - 0.0 = -1.0
    #   A_1 = -1.0
    #   R_1 = A_1 + V_1 = -1.0 + 0.0 = -1.0
    # t=0 (done=False): next_value=V_1=0.0, nonterm=1
    #   delta = 1.0 + 0.99·0·1 - 0.5 = 0.5
    #   A_0 = 0.5 + 0.99·0.95·1·A_1 = 0.5 + 0.9405·(-1.0) = -0.4405
    #   R_0 = A_0 + V_0 = -0.4405 + 0.5 = 0.0595
    assert out[1]['advantage'] == pytest.approx(-1.0, abs=1e-5)
    assert out[1]['return'] == pytest.approx(-1.0, abs=1e-5)
    assert out[0]['advantage'] == pytest.approx(-0.4405, abs=1e-4)
    assert out[0]['return'] == pytest.approx(0.0595, abs=1e-4)


def test_compute_gae_terminal_bootstrap_zero():
    """Single terminal step: A = r - V(s); R = r."""
    rewards = np.array([0.5], dtype=np.float32)
    values = np.array([0.2], dtype=np.float32)
    dones = np.array([True], dtype=bool)
    advs, rets = compute_gae(rewards, values, dones, gamma=0.99, lam=0.95)
    assert advs[0] == pytest.approx(0.3, abs=1e-6)  # 0.5 - 0.2
    assert rets[0] == pytest.approx(0.5, abs=1e-6)  # adv + V


# ---------- PPOLoss (P2) ---------- #


def test_ppo_loss_returns_loss_computer_protocol():
    pcfg = PPOParadigmConfig.from_dict({})
    loss = PPOLoss(pcfg)
    assert isinstance(loss, LossComputer)


def test_ppo_loss_clipped_surrogate_zero_advantage():
    """advantage=0 → policy_loss=0 (ratio·0 = 0); value_mse drives loss."""
    pcfg = PPOParadigmConfig.from_dict({})
    loss_fn = PPOLoss(pcfg)
    agent_cfg = _tiny_agent_cfg(max_actions=3, d_model=8)
    net = PPONetwork(agent_cfg)
    batch = _make_ppo_loss_batch(
        net,
        batch_size=2,
        seed=3,
        chosen_actions=[0, 1],
        advantages=[0.0, 0.0],
        returns=[0.0, 0.0],
        legal_n=3,
    )
    res = loss_fn.compute(net, batch)
    # policy_loss = -min(ratio·0, clip·0).mean() = 0
    assert res.breakdown['policy_loss'] == pytest.approx(0.0, abs=1e-6)
    # value_loss = MSE(value_pred, 0) >= 0
    assert res.breakdown['value_loss'] >= 0.0


def test_ppo_loss_value_mse_numerical():
    """Force network value pred via simple init; assert value_loss is MSE."""
    pcfg = PPOParadigmConfig.from_dict({'value_coef': 1.0, 'entropy_coef': 0.0})
    loss_fn = PPOLoss(pcfg)
    agent_cfg = _tiny_agent_cfg(max_actions=3, d_model=8)
    net = PPONetwork(agent_cfg)

    batch = _make_ppo_loss_batch(
        net,
        batch_size=2,
        seed=5,
        chosen_actions=[0, 1],
        advantages=[0.0, 0.0],  # zero policy loss
        returns=[1.0, -1.0],
        old_log_probs=[0.0, 0.0],
        legal_n=3,
    )
    with torch.no_grad():
        _, value_pred = net.forward_batch(batch.data['collated'])
        ret_t = batch.data['return']
        expected_mse = float(((value_pred - ret_t) ** 2).mean().item())

    res = loss_fn.compute(net, batch)
    assert res.breakdown['value_loss'] == pytest.approx(expected_mse, abs=1e-5)


def test_ppo_loss_entropy_bonus_signed_correctly():
    """entropy_coef > 0 → loss decreases as entropy increases.

    With advantage=0 + ret matching value → only entropy term remains;
    loss = -entropy_coef · entropy, so higher entropy → more negative."""
    pcfg = PPOParadigmConfig.from_dict({'value_coef': 0.0, 'entropy_coef': 0.1})
    loss_fn = PPOLoss(pcfg)
    agent_cfg = _tiny_agent_cfg(max_actions=4, d_model=8)
    net = PPONetwork(agent_cfg)
    batch = _make_ppo_loss_batch(
        net,
        batch_size=2,
        seed=7,
        chosen_actions=[0, 1],
        advantages=[0.0, 0.0],
        returns=[0.0, 0.0],
        old_log_probs=[0.0, 0.0],
        legal_n=4,
    )
    res = loss_fn.compute(net, batch)
    # entropy is positive; loss = -coef · entropy → negative.
    assert res.breakdown['entropy'] > 0.0
    # Loss should be approximately -entropy_coef · entropy (other terms zero).
    expected = -0.1 * res.breakdown['entropy']
    assert res.breakdown['loss'] == pytest.approx(expected, abs=1e-5)


def test_ppo_loss_missing_keys_raises():
    pcfg = PPOParadigmConfig.from_dict({})
    loss_fn = PPOLoss(pcfg)
    agent_cfg = _tiny_agent_cfg(max_actions=3, d_model=8)
    net = PPONetwork(agent_cfg)
    # Neither 'transitions' nor pre-collated keys present.
    batch = Batch(data={'foo': 'bar'}, size=1)
    with pytest.raises(ValueError, match='missing required keys'):
        loss_fn.compute(net, batch)


# ---------- Clipped surrogate explicit numerics ---------- #


def test_ppo_loss_clipped_surrogate_uses_clip_eps():
    """Build a controlled batch where ratio = exp(new_lp - old_lp) > 1+ε
    + advantage > 0 → surr1 = ratio·adv (larger), surr2 = clipped·adv (smaller),
    min picks surr2 → policy_loss = -surr2.mean()."""
    pcfg = PPOParadigmConfig.from_dict({'clip_epsilon': 0.2, 'value_coef': 0.0, 'entropy_coef': 0.0})
    loss_fn = PPOLoss(pcfg)
    agent_cfg = _tiny_agent_cfg(max_actions=2, d_model=8)
    net = PPONetwork(agent_cfg)

    # old_lp very negative → ratio = exp(new_lp - old_lp) very large → clipped.
    batch = _make_ppo_loss_batch(
        net,
        batch_size=4,
        seed=11,
        chosen_actions=[0, 0, 0, 0],
        advantages=[1.0, 1.0, 1.0, 1.0],
        returns=[0.0, 0.0, 0.0, 0.0],
        old_log_probs=[-10.0, -10.0, -10.0, -10.0],
        legal_n=2,
    )
    res = loss_fn.compute(net, batch)
    # Ratio ≫ 1+ε → clip_frac should be 1.0 (all clipped).
    assert res.breakdown['clip_frac'] == pytest.approx(1.0, abs=1e-6)


# ---------- PPOParadigm protocol surface ---------- #


def test_ppo_paradigm_name_and_requires_network():
    p = PPOParadigm()
    assert p.name == 'ppo'
    assert p.requires_network_in_collect is True


def test_ppo_paradigm_make_episode_policy():
    """make_episode_policy returns PPOEpisodePolicy; deterministic flag
    propagates."""
    p = PPOParadigm()
    p._pcfg = PPOParadigmConfig.from_dict({})

    class _StubCfg:
        class meta:
            seed = 7
            device = 'cpu'

    pol = p.make_episode_policy(_StubCfg(), instance_id=0, deterministic=False)
    assert isinstance(pol, PPOEpisodePolicy)
    assert pol.deterministic is False
    assert pol.gamma == 0.99
    assert pol.gae_lambda == 0.95

    pol_det = p.make_episode_policy(_StubCfg(), instance_id=1, deterministic=True)
    assert pol_det.deterministic is True


def test_ppo_paradigm_step_schedule_steady_then_stop():
    p = PPOParadigm()
    p._pcfg = PPOParadigmConfig.from_dict({'total_iterations': 2})

    from training.core.protocols import PipelineState

    class _StubCfg:
        class meta:
            seed = 0
            device = 'cpu'

        class pipeline:
            mode = 'serial'

    state = PipelineState.fresh(seed=0)
    # iter 0: steady (collect + train).
    plan = p.step_schedule(state, _StubCfg())
    assert plan.collect is True
    assert plan.train is True
    assert plan.eval is True

    # Past total_iterations → stop.
    state.step = 10
    plan_stop = p.step_schedule(state, _StubCfg())
    assert plan_stop.collect is False
    assert plan_stop.train is False
    assert plan_stop.eval is False


# ---------- derive_seed ---------- #


def test_derive_seed_deterministic():
    s1 = derive_seed(42, 'ppo-iter', 1)
    s2 = derive_seed(42, 'ppo-iter', 1)
    assert s1 == s2


def test_derive_seed_different_labels():
    s_a = derive_seed(42, 'ppo-iter', 1)
    s_b = derive_seed(42, 'ppo-iter', 2)
    assert s_a != s_b


# ---------- PPORolloutCfg sanity ---------- #


def test_ppo_rollout_cfg_defaults():
    rc = PPORolloutCfg()
    assert rc.n_games_per_iter == 32
    assert rc.max_steps_per_game == 200
    assert rc.rollout_opponent == 'self'
