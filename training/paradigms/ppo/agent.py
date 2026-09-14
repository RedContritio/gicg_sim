"""PPOAgent — wraps ActorCritic for PPO + AgentBase per-game cache.

Mirror of ``training.paradigms.dmc._agent.DmcAgent`` shape (single
``select_action`` is replaced here with ``act`` because PPO needs the
log_prob + value alongside the chosen action for the clipped-surrogate
loss).

Uses generic structural ActorCritic backbone via
``make_actor_critic(head_kinds={'policy','value'}, use_typed_damage=True)``
per `ppo-structural-backbone-migration` invariant A1 (P1.new). DI:
hook_encoder injected to AgentBase.

Player interface (single ``select_action(env)`` deterministic argmax) is
provided as well for arena / matchup compatibility (the rollout path
goes through ``act(env, rng)`` which returns log_prob + value).
"""

from __future__ import annotations

import math
import random

import numpy as np
import torch
import torch.nn.functional as F

from gicg_env import GicgEnv
from training.core.network import AgentBase, AgentConfig, make_actor_critic
from training.core.step_encoding import (
    pad_action_payments,
    pad_action_refs,
)
from training.core.structural import (
    compute_structural_obspos,
    compute_structural_values,
)


# PPO head subset: policy + value (P5.1).
PPO_HEAD_KINDS = frozenset({'policy', 'value'})


class PPOAgent(AgentBase):
    """ActorCritic-backed PPO agent (policy + value heads).

    Per-game caching: call ``game_start(env.static_obs)`` once at env
    reset (typically inside the rollout loop). Then per step::

        a, meta = agent.act(env, rng, deterministic=False)
        # meta = {'log_prob': float, 'value': float, 'n_legal': int}

    Training interface: ``forward_batch(collated_dict)`` returns
    ``(policy_logits, value)`` over a batched collated dict (same
    shape as DMC / BC / AZ paradigms expect).

    A1 (P1.new) — generic backbone via make_actor_critic; A3 (P3.new) —
    AgentBase per-game cache.
    """

    def __init__(self, cfg: AgentConfig, device: str = 'cpu') -> None:
        net = make_actor_critic(
            cfg,
            head_kinds=PPO_HEAD_KINDS,
            use_typed_damage=True,
        ).to(torch.device(device))
        super().__init__(cfg, hook_encoder=net.hook_encoder, device=device)
        self.net = net
        self.rng = random.Random()

    # --- Player interface (matchup/arena compat) -------------------- #

    def select_action(self, env: GicgEnv) -> int:
        """Argmax over legal logits. Player-compatible (no log_prob)."""
        action_idx, _ = self.act(env, self.rng, deterministic=True)
        return action_idx

    # --- Rollout actor interface ------------------------------------ #

    def act(
        self,
        env: GicgEnv,
        rng: random.Random | np.random.Generator,
        *,
        deterministic: bool = False,
    ) -> tuple[int, dict]:
        """Sample (or argmax) one action; return (action_idx, meta).

        meta carries the diagnostic fields the rollout buffer needs:
            log_prob: legal-softmax log-prob of chosen action (≤ 0)
            value: V(s) prediction (scalar)
            n_legal: number of legal actions at this state
        """
        if self._hook_emb is None:
            raise RuntimeError(
                'PPOAgent.act called before game_start — call game_start(env.static_obs) at episode start.'
            )
        kinds, _ = env.get_legal_actions()
        n_legal = int(len(kinds))
        if n_legal == 0:
            # End-of-episode safe path; loss never sees this transition
            # because rollout breaks on no-legal-action before push.
            return 0, {'log_prob': 0.0, 'value': 0.0, 'n_legal': 0}

        dyn_obs = env._get_obs()
        refs_np = env.get_action_refs()
        pay_np = env.get_legal_action_payments()

        legal_logits, value = self._forward_logits_value(dyn_obs, refs_np, pay_np, n_legal)
        # Legal-softmax (no -inf needed — we already slice to n_legal).
        log_probs = F.log_softmax(legal_logits, dim=-1)
        probs = log_probs.exp().detach().cpu().numpy()

        if deterministic:
            idx = int(np.argmax(probs))
        else:
            # Use numpy choice for either RNG type.
            if isinstance(rng, np.random.Generator):
                idx = int(rng.choice(n_legal, p=probs))
            else:
                # random.Random: emulate weighted choice over n_legal.
                r = rng.random()
                acc = 0.0
                idx = n_legal - 1
                for i in range(n_legal):
                    acc += float(probs[i])
                    if r < acc:
                        idx = i
                        break

        log_prob = float(log_probs[idx].item())
        return idx, {
            'log_prob': log_prob,
            'value': float(value.item()),
            'n_legal': n_legal,
        }

    def _forward_logits_value(
        self,
        dyn_obs_np: np.ndarray,
        refs_np: np.ndarray,
        payments_np: np.ndarray,
        n_legal: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Single forward returning (legal_logits, value).

        legal_logits shape (n_legal,); value shape (scalar,)."""
        if n_legal > self.cfg.max_actions:
            raise ValueError(f'PPO legal actions {n_legal} exceed max_actions={self.cfg.max_actions}')
        if n_legal != len(refs_np) or n_legal != len(payments_np):
            raise ValueError('PPO action refs/payments must align with legal actions')
        refs_padded = pad_action_refs(refs_np, self.cfg.max_actions)
        pay_padded = pad_action_payments(payments_np, self.cfg.max_actions)

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
            legal_logits = out['policy'][0, :n_legal].clone()
            value = out['value'][0]
        return legal_logits, value

    # --- Training (batched forward) -------------------------------- #

    def forward_batch(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
        """Batched forward — returns (policy_logits, value).

        policy_logits shape (B, max_actions);value shape (B,).

        Mirrors DmcAgent.forward_batch / Agent.forward_batch shape (AZ).
        Loss reads policy_logits, slices to legal via batch['legal_mask']
        (which is also in the collated dict from collect/collate).
        """

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
        return out['policy'], out['value']

    # --- Convenience: masked Categorical for loss path -------------- #

    @staticmethod
    def masked_log_prob(
        policy_logits: torch.Tensor,
        legal_mask: torch.Tensor,
        action: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Compute (new_log_prob, entropy) under legal-softmax.

        Args:
            policy_logits: (B, max_actions)
            legal_mask: (B, max_actions) bool
            action: (B,) long index into legal action space.
        """
        neg_inf = torch.finfo(policy_logits.dtype).min
        masked = torch.where(legal_mask, policy_logits, torch.full_like(policy_logits, neg_inf))
        log_probs = F.log_softmax(masked, dim=-1)
        new_lp = log_probs.gather(1, action.unsqueeze(-1)).squeeze(-1)
        probs = log_probs.exp()
        entropy = -(probs * log_probs.masked_fill(~legal_mask, 0.0)).sum(dim=-1)
        return new_lp, entropy


# Backwards-compat helper: tests reach for this name through agent.act paths.
__all__ = ['PPOAgent', 'PPO_HEAD_KINDS']


# Avoid unused-import linter warning while keeping math available for downstream callers.
_ = math
