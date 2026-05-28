"""Verify DMCInferenceNet.batched_forward matches per-request forward.

``batched_forward`` stacks N single-request obs_dicts and runs one
ActorCritic.forward; the result must be numerically equivalent to
running ``forward(obs_i)`` N times. Variable-length hook fields
(``hook_emb`` / ``hook_mask``) are zero-padded to batch-max ``n_active``
with ``False`` mask — masked positions must NOT contaminate valid rows
(test 2 verifies via heterogeneous n_active).

Real env + DmcAgent.build_obs_dict is used to construct obs (instead of
hand-rolling all 15 tensors) so the test stays aligned with the actual
inference contract rather than a synthetic fixture.
"""

from __future__ import annotations

import os

import pytest
import torch

from gicg_env import GicgEnv
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.inference_net import DMCInferenceNet

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def _tiny_agent_cfg() -> AgentConfig:
    """Match the bundled 赤蝶 smoke scenario shapes (mirrors
    test_inference_server._cfg) at minimal d_model."""
    return AgentConfig(
        n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
        n_hooks=900,
        max_ops_per_hook=64,
        max_actions=256,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )


def _build_env(seed: int = 0) -> GicgEnv:
    env = GicgEnv(['赤蝶'], ['赤蝶'], seed=seed, data_dir=DATA_DIR)
    env.reset(seed=seed)
    while env.phase == 1:
        env.step(0)
        if env.done:
            break
    return env


def _agent_and_obs(seed: int) -> tuple[DmcAgent, dict]:
    """Build a DmcAgent (with fixed weights via global manual_seed) +
    pull a real build_obs_dict from a freshly-started env. Caller owns
    env.close() — we keep env alive in the returned obs_dict via
    references on cached tensors.

    Note: we deliberately share network weights across calls (caller is
    responsible for torch.manual_seed before constructing the agent).
    """
    env = _build_env(seed=seed)
    cfg = _tiny_agent_cfg()
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    agent.net.eval()
    agent.game_start(env.static_obs)
    obs = agent.build_obs_dict(env)
    env.close()
    return agent, obs


# --- Tests ----------------------------------------------------------- #


def test_batched_forward_empty_raises():
    """``batched_forward([])`` must surface a ValueError, not return an
    empty tensor that downstream callers would silently misinterpret."""
    torch.manual_seed(0)
    cfg = _tiny_agent_cfg()
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    inf_net = DMCInferenceNet(agent.net).eval()
    with pytest.raises(ValueError, match='empty'):
        inf_net.batched_forward([])


def test_batched_forward_n1_matches_single():
    """N=1 is a degenerate batched call; output must equal ``forward(obs)``
    exactly (no padding, no concat overhead)."""
    torch.manual_seed(0)
    _agent, obs = _agent_and_obs(seed=0)
    # Re-seed + rebuild agent so weights are reproducible.
    torch.manual_seed(0)
    cfg = _tiny_agent_cfg()
    agent2 = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    agent2.net.eval()
    inf_net = DMCInferenceNet(agent2.net).eval()

    # build_obs_dict caches static fields from agent (different
    # instance) — rebuild via agent2 + a fresh env to keep weights +
    # caches consistent.
    env = _build_env(seed=0)
    agent2.game_start(env.static_obs)
    obs2 = agent2.build_obs_dict(env)
    env.close()

    with torch.inference_mode():
        single = inf_net.forward(obs2)
        batched = inf_net.batched_forward([obs2])
    assert single.shape == batched.shape
    assert torch.allclose(single, batched, atol=1e-6), 'N=1 batched diverged from forward'


def test_batched_forward_matches_single_equal_n_active():
    """Two requests with identical static obs → identical n_active →
    no padding needed. Each batched row must equal the per-request
    forward output for the same obs."""
    torch.manual_seed(0)
    cfg = _tiny_agent_cfg()
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    agent.net.eval()
    inf_net = DMCInferenceNet(agent.net).eval()

    # Two envs with same seed → same static obs → same n_active.
    env_a = _build_env(seed=0)
    env_b = _build_env(seed=0)
    agent.game_start(env_a.static_obs)
    obs_a = agent.build_obs_dict(env_a)
    obs_b = agent.build_obs_dict(env_b)
    # n_active must match for this test's premise to hold.
    assert obs_a['hook_emb'].shape == obs_b['hook_emb'].shape
    env_a.close()
    env_b.close()

    with torch.inference_mode():
        single_a = inf_net.forward(obs_a)
        single_b = inf_net.forward(obs_b)
        batched = inf_net.batched_forward([obs_a, obs_b])

    assert batched.shape[0] == 2
    assert torch.allclose(batched[0:1], single_a, atol=1e-5), (
        f'batched row 0 diverged from single forward, max diff {(batched[0:1] - single_a).abs().max()}'
    )
    assert torch.allclose(batched[1:2], single_b, atol=1e-5), (
        f'batched row 1 diverged from single forward, max diff {(batched[1:2] - single_b).abs().max()}'
    )


def test_batched_forward_padding_does_not_affect_valid_rows():
    """When ``n_active`` differs across requests, the smaller-``n_active``
    row must still match its single forward. Padding zeros + False mask
    on the cross-attention path must be masked out so they cannot bleed
    into the valid positions of the smaller row.

    Construction: build obs_a normally (full n_active from a real env),
    then make obs_b by truncating the hook_emb / hook_mask to half the
    n_active. Both go through forward() singly (each sees its own
    n_active) and through batched_forward() together (padded to max).
    The batched row for obs_b must equal forward(obs_b).
    """
    torch.manual_seed(0)
    cfg = _tiny_agent_cfg()
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    agent.net.eval()
    inf_net = DMCInferenceNet(agent.net).eval()

    env = _build_env(seed=0)
    agent.game_start(env.static_obs)
    obs_a = agent.build_obs_dict(env)
    env.close()

    n_active_a = obs_a['hook_emb'].shape[1]
    if n_active_a < 2:
        pytest.skip(f'env has only {n_active_a} active hooks; cannot construct asymmetric batch')

    n_active_b = max(1, n_active_a // 2)
    obs_b = {k: v for k, v in obs_a.items()}
    # Slice hook fields to shorter n_active. Clone so we don't alias obs_a.
    obs_b['hook_emb'] = obs_a['hook_emb'][:, :n_active_b, :].clone()
    obs_b['hook_mask'] = obs_a['hook_mask'][:, :n_active_b].clone()

    # In real inference each agent's action_refs + char_skill_refs only
    # reference hooks in its own n_active range (caches built at
    # game_start). Here we synthesised obs_b by truncating obs_a, so any
    # ref >= n_active_b must be remapped to the -1 sentinel ("no hook
    # bound") — otherwise the single forward clamps to n_active_b-1
    # (wrapping silently) while the batched forward gathers from the
    # padded position, producing artificial divergence unrelated to the
    # padding-mask contract this test is verifying.
    def _clip_refs_to_valid_or_unbound(refs: torch.Tensor, max_valid: int) -> torch.Tensor:
        out = refs.clone()
        out[out >= max_valid] = -1
        return out

    action_refs_b = obs_a['action_refs'].clone()
    action_refs_b[..., 1] = _clip_refs_to_valid_or_unbound(action_refs_b[..., 1], n_active_b)
    obs_b['action_refs'] = action_refs_b
    obs_b['char_skill_refs'] = _clip_refs_to_valid_or_unbound(obs_a['char_skill_refs'], n_active_b)
    # Re-run single forward for obs_a with the same _clip applied to its
    # refs is NOT needed — obs_a uses full n_active_a and its refs are
    # naturally in range.

    with torch.inference_mode():
        single_a = inf_net.forward(obs_a)
        single_b = inf_net.forward(obs_b)
        batched = inf_net.batched_forward([obs_a, obs_b])

    assert batched.shape[0] == 2
    # obs_a was the longer one → its row should be exact (no padding).
    assert torch.allclose(batched[0:1], single_a, atol=1e-5), (
        f'longer-n_active row diverged, max diff {(batched[0:1] - single_a).abs().max()}'
    )
    # obs_b was padded; if cross-attention or pooling leaks the padded
    # positions into valid rows, this assert fails — that is the bug
    # this test catches.
    assert torch.allclose(batched[1:2], single_b, atol=1e-5), (
        f'padded-row contaminated by padded hooks, max diff {(batched[1:2] - single_b).abs().max()}'
    )
