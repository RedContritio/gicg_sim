"""Tests for new AgentBase DI contract.

Covers:
- DI: hook_encoder injected at construction, no `self.net.hook_encoder` requirement
- Subclass without `self.net` cannot save/load (clear error)
- Static obs cache populated by encode_static, accessible after
- game_start/game_end protocol
"""

from __future__ import annotations

import numpy as np
import pytest
import torch
import torch.nn as nn

from training.core.network.agent_base import AgentBase, AgentConfig
from training.core.network.encoder import HookEncoder


def _make_cfg() -> AgentConfig:
    return AgentConfig(
        n_counter_slots=8,
        n_hooks=4,
        max_ops_per_hook=4,
        max_actions=6,
        d_model=16,
    )


def _make_hook_encoder(d_model: int = 16) -> HookEncoder:
    return HookEncoder(
        opcode_vocab=16,
        operand_vocab=2048,
        token_dim=d_model,
        n_heads=4,
        n_layers=1,
        max_ops=4,
    )


def test_di_constructor_signature():
    """AgentBase requires hook_encoder at construction (no self.net lookup)."""
    cfg = _make_cfg()
    he = _make_hook_encoder(d_model=cfg.d_model)
    agent = AgentBase(cfg, hook_encoder=he, device='cpu')
    assert agent.cfg is cfg
    assert agent._hook_encoder is he
    assert agent.device == torch.device('cpu')


def test_no_self_net_required_at_init():
    """Subclass doesn't need self.net to construct AgentBase (DI解耦)."""
    cfg = _make_cfg()
    he = _make_hook_encoder(d_model=cfg.d_model)

    class BareAgent(AgentBase):
        pass

    agent = BareAgent(cfg, hook_encoder=he)
    assert not hasattr(agent, 'net')
    # encode_static works without self.net (uses self._hook_encoder)
    from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE

    meta_size = cfg.n_counter_slots * 3
    hook_size = cfg.n_hooks * cfg.max_ops_per_hook * cfg.fields_per_op
    static = np.zeros(meta_size + OBS_CHAR_SKILL_REFS_SIZE + hook_size, dtype=np.float32)
    # mark one slot active by setting min/max non-zero
    static[0] = 1.0  # slot 0 min
    static[1] = 10.0  # slot 0 max
    agent.encode_static(static)
    assert agent._hook_emb is not None
    assert agent._counter_sids is not None
    assert agent._active_slot_mask is not None


def test_save_load_require_self_net():
    """save/load raise clear error if subclass forgot self.net."""
    cfg = _make_cfg()
    he = _make_hook_encoder(d_model=cfg.d_model)
    agent = AgentBase(cfg, hook_encoder=he)
    with pytest.raises(RuntimeError, match='subclass must set self.net'):
        agent.save('/tmp/no_net.pt')


def test_game_start_returns_cache_dict():
    cfg = _make_cfg()
    he = _make_hook_encoder(d_model=cfg.d_model)
    agent = AgentBase(cfg, hook_encoder=he)
    from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE

    meta_size = cfg.n_counter_slots * 3
    hook_size = cfg.n_hooks * cfg.max_ops_per_hook * cfg.fields_per_op
    static = np.zeros(meta_size + OBS_CHAR_SKILL_REFS_SIZE + hook_size, dtype=np.float32)
    static[0] = 1.0
    static[1] = 10.0
    cache = agent.game_start(static)
    assert set(cache.keys()) == {
        'hook_ir',
        'hook_mask',
        'counter_sids',
        'active_slot_mask',
        'char_skill_refs',
    }


def test_game_end_noop():
    """game_end is no-op (cache overwritten on next game_start)."""
    cfg = _make_cfg()
    he = _make_hook_encoder(d_model=cfg.d_model)
    agent = AgentBase(cfg, hook_encoder=he)
    agent.game_end()  # no error


def test_mock_hook_encoder_injection():
    """DI allows mock hook_encoder for testing without real HookEncoder."""
    cfg = _make_cfg()

    class IdentityHookEncoder(nn.Module):
        def forward(self, hook_ir, mask):
            # Return (B, N, d_model) with random init for shape only
            B, N = hook_ir.shape[0], hook_ir.shape[1]
            return torch.zeros(B, N, cfg.d_model)

    he = IdentityHookEncoder()
    agent = AgentBase(cfg, hook_encoder=he)
    # encode_static still works with mock encoder
    from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE

    meta_size = cfg.n_counter_slots * 3
    hook_size = cfg.n_hooks * cfg.max_ops_per_hook * cfg.fields_per_op
    static = np.zeros(meta_size + OBS_CHAR_SKILL_REFS_SIZE + hook_size, dtype=np.float32)
    # active hook token to force forward path
    static[meta_size + OBS_CHAR_SKILL_REFS_SIZE] = 5.0  # hook[0][0] type=5
    agent.encode_static(static)
    assert agent._hook_emb is not None
