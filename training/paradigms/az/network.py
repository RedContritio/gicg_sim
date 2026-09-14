"""AZNetwork — thin nn.Module wrapper around AZ Agent for driver compat.

The unified pipeline driver expects ``make_network`` to return an
``nn.Module``-like object that supports ``parameters()`` /
``state_dict()`` / ``load_state_dict()``. AZ's loss path however needs
the ``Agent.forward_batch(batch_dict)`` because obs is captured by the
agent's private static cache (game_start / game_end lifecycle).

The ``Agent`` class is canonically defined in this adapter module
(az-paradigm-rewrite Phase 2-δ inlined from the former
``training.paradigms.az.legacy.network.agent``; Phase 5 git-rm'd the
legacy subdir on 2026-05-16). Old r009 checkpoint names do not imply
compatibility with the current observation and state-dict schema.

Phase 1 — `paradigms/az/network.py` references ``core/network/heads``
(PolicyHead / ValueHead) as the canonical basic-head classes via
``BASIC_HEAD_CLASSES``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn

from training.core.network import AgentBase, AgentConfig, make_actor_critic
from training.core.network.heads import PolicyHead, ValueHead
from training.core.step_encoding import (
    pad_action_payments,
    pad_action_refs,
)
from training.core.structural import (
    compute_structural_obspos,
    compute_structural_values,
)

__all__ = ['AZNetwork', 'Agent', 'AgentConfig', 'BASIC_HEAD_CLASSES']


# AZ canonical head set per paradigm-az/spec.md A4.1 (policy + value) +
# delta (counter-delta aux per ADR-0019 §B.3). Kept at module level for
# introspection (tests + downstream tooling can inspect without
# instantiating a network).
BASIC_HEAD_CLASSES: dict[str, type[nn.Module]] = {
    'policy': PolicyHead,
    'value': ValueHead,
}

# Head subset passed to make_actor_critic for AZ paradigm:
# policy + value + delta (typed_damage on per ADR-0019 §B.3a).
AZ_HEAD_KINDS = frozenset({'policy', 'value', 'delta'})


class Agent(AgentBase):
    """MCTS-facing network wrapper.

    Holds an ActorCritic (generic, built via make_actor_critic) + an
    AdamW optimizer + per-game static cache. See ``AgentBase`` for the
    shared caching + static-parse scaffolding.

    Core-network-generic-promotion Phase 2A: switched from legacy 207-line
    god class ActorCritic to generic thin composition via
    ``make_actor_critic(cfg, head_kinds=AZ_HEAD_KINDS, use_typed_damage=True)``.
    Backbone is identical (encoders + 7-pool + struct_readout) — only the
    class topology differs (composition vs hardcoded). DI: ``hook_encoder`` is
    injected into ``AgentBase`` from the constructed network.
    """

    def __init__(
        self,
        cfg: AgentConfig,
        device: str = 'cpu',
        lr: float = 1e-3,
        weight_decay: float = 0.0,
    ):
        # Construct net first so we can inject its hook_encoder into AgentBase.
        # AgentConfig and ObsShape have structurally compatible fields
        # (n_counter_slots / n_hooks / max_ops_per_hook / max_actions /
        #  d_model / n_cross_layers / dropout) — duck-typed pass.
        net = make_actor_critic(
            cfg,
            head_kinds=AZ_HEAD_KINDS,
            use_typed_damage=True,
        ).to(torch.device(device))
        super().__init__(cfg, hook_encoder=net.hook_encoder, device=device)
        self.net = net
        self.optimizer = torch.optim.AdamW(
            self.net.parameters(),
            lr=lr,
            weight_decay=weight_decay,
        )

    def _pad_action_refs(self, refs_np: np.ndarray) -> np.ndarray:
        """Return padded action refs with the int32 dtype expected by callers."""
        return pad_action_refs(refs_np, self.cfg.max_actions).astype(np.int32)

    def _pad_action_payments(self, payments_np: np.ndarray) -> np.ndarray:
        return pad_action_payments(payments_np, self.cfg.max_actions)

    def eval_state(
        self,
        dyn_obs_np: np.ndarray,
        refs_np: np.ndarray,
        payments_np: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        """Run one forward pass and return (prior, value) for MCTS."""
        if self._hook_emb is None:
            raise RuntimeError(
                'Agent.eval_state called before game_start — call '
                "game_start(env.static_obs) once at the game's root "
                'before any MCTS rollouts.'
            )
        n_legal = int(len(refs_np))
        if n_legal == 0:
            raise ValueError('eval_state called with 0 legal actions')
        if n_legal > self.cfg.max_actions:
            raise ValueError(
                f'eval_state: n_legal={n_legal} exceeds agent '
                f'max_actions={self.cfg.max_actions}; raise '
                'AgentConfig.max_actions to accommodate the largest '
                'legal list this ruleset produces'
            )

        refs_padded = pad_action_refs(refs_np, self.cfg.max_actions)
        pay_padded = pad_action_payments(payments_np, self.cfg.max_actions)
        # NB: eval_state does NOT need a legal_mask — the truncate to
        # ``logits[0, :n_legal]`` below is the mask. The legacy file
        # had a dead ``mask = build_legal_mask(...)`` assignment here
        # (ruff F841); dropped during T2.6 inline per "Dead defensive
        # code 必须删" rule (CLAUDE.md §2). Legacy file remains as-is
        # since it's slated for git-rm in Phase 5.

        with torch.no_grad():
            (
                counter_values,
                meta,
                card_buckets,
                enemy_sizes,
                recent_damage,
                prepare_skill,
                modifier_log,
            ) = self._parse_dynamic_single(dyn_obs_np)
            refs_t = torch.tensor(refs_padded, dtype=torch.long, device=self.device).unsqueeze(0)
            pay_t = torch.tensor(pay_padded, dtype=torch.float32, device=self.device).unsqueeze(0)

            structural_values = compute_structural_values(counter_values, self._structural_obspos)
            out = self.net(
                counter_values,
                self._counter_sids,
                self._active_slot_mask,
                self._hook_emb,
                self._hook_mask,
                card_buckets,
                enemy_sizes,
                meta,
                refs_t,
                pay_t,
                structural_values,
                self._char_skill_refs,
                recent_damage,
                prepare_skill,
                modifier_log,
                buffs=self._parse_buff_single(dyn_obs_np),
                definition_links=self._definition_links,
            )
            # Generic ActorCritic returns dict {head_name: tensor, '_state_vec', ...}
            logits = out['policy']
            value = out['value']
            legal_logits = logits[0, :n_legal]
            prior = torch.softmax(legal_logits, dim=-1).cpu().numpy()
            v_scalar = float(value[0].item())
        return prior, v_scalar

    def forward_batch(self, batch: dict):
        """Batched forward for a training minibatch. Returns
        ``(logits, value, delta_pred)``."""

        def _t(key, dtype):
            x = batch[key]
            if isinstance(x, torch.Tensor):
                return x.to(self.device).to(dtype)
            return torch.as_tensor(x, dtype=dtype, device=self.device)

        counter_values = _t('counter_values', torch.float32)
        counter_sids = _t('counter_sids', torch.long)
        active_slot_mask = _t('active_slot_mask', torch.bool)
        hook_ir = _t('hook_ir', torch.long)
        hook_mask = _t('hook_mask', torch.bool)
        card_buckets = _t('card_buckets', torch.float32)
        enemy_sizes = _t('enemy_sizes', torch.float32)
        meta = _t('meta', torch.float32)
        action_refs = _t('action_refs', torch.long)
        action_payments = _t('action_payments', torch.float32)
        char_skill_refs = _t('char_skill_refs', torch.long)
        definition_links = _t('definition_links', torch.long)
        recent_damage = _t('recent_damage', torch.float32)
        prepare_skill = _t('prepare_skill', torch.float32)
        modifier_log = _t('modifier_log', torch.float32)

        hook_emb = self.net.hook_encoder(hook_ir, hook_mask)

        structural_obspos = compute_structural_obspos(counter_sids, active_slot_mask)
        structural_values = compute_structural_values(counter_values, structural_obspos)

        out = self.net(
            counter_values,
            counter_sids,
            active_slot_mask,
            hook_emb,
            hook_mask,
            card_buckets,
            enemy_sizes,
            meta,
            action_refs,
            action_payments,
            structural_values,
            char_skill_refs,
            recent_damage,
            prepare_skill,
            modifier_log,
            buffs=_t('buffs', torch.float32) if 'buffs' in batch else None,
            definition_links=definition_links,
        )
        # Generic ActorCritic returns dict; destructure for AZLoss 3-tuple compat.
        return out['policy'], out['value'], out['delta']


class AZNetwork(nn.Module):
    """nn.Module wrapper exposing AZ Agent surface + standard module API.

    Construction owns its own Agent, which builds an ActorCritic with
    policy, value, and auxiliary delta heads. Driver
    passes the underlying ``net`` parameters to its optimizer via
    ``parameters()`` so ``optimizer.step()`` updates the same tensors
    ``forward_batch`` reads.

    ``BASIC_HEAD_CLASSES`` exposes the two primary decision heads for
    compatibility; ``AZ_HEAD_KINDS`` also includes the trained delta head.
    """

    HEAD_CLASSES = BASIC_HEAD_CLASSES  # class-level handle for introspection

    def __init__(self, agent_cfg: AgentConfig, device: str = 'cpu', lr: float = 1e-3) -> None:
        super().__init__()
        self._agent = Agent(agent_cfg, device=device, lr=lr)
        # Register ActorCritic as child module so module-level
        # parameters() / state_dict() naturally see all its tensors.
        self.add_module('net', self._agent.net)

    @property
    def agent(self) -> Agent:
        return self._agent

    @property
    def heads(self) -> tuple:
        """Return the primary policy/value head names used by callers.

        The underlying ActorCritic also carries the auxiliary ``delta`` head;
        ``forward_batch`` returns all three outputs.
        """
        return tuple(BASIC_HEAD_CLASSES.keys())

    def forward_batch(self, batch: dict):
        """Run batched forward (returns logits, value, delta_pred)."""
        return self._agent.forward_batch(batch)

    def eval_state(self, dyn_obs_np, refs_np, payments_np):
        """MCTS leaf eval — spec A1.2 (`provider.forward` at every leaf)."""
        return self._agent.eval_state(dyn_obs_np, refs_np, payments_np)

    def game_start(self, static_obs: Any) -> dict:
        """Initialize the inner agent and return its per-game static fields."""
        return self._agent.game_start(static_obs)

    def game_end(self) -> None:
        if hasattr(self._agent, 'game_end'):
            self._agent.game_end()

    def load_net_only(self, sd: dict) -> None:
        """Load just the ActorCritic weights (used by BC warm-start —
        spec A6 reproducibility tier)."""
        self._agent.net.load_state_dict(sd)

    def forward(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError('AZNetwork.forward not used — call forward_batch(batch) or eval_state(...) instead.')
