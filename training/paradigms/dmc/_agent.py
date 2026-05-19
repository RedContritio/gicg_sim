"""DmcAgent — wraps ActorCritic for DMC training + Player-compatible inference.

DMC uses logits as Q values directly (no MCTS, no softmax sampling).
Inference: argmax over logits (with ε-greedy explore at actor time).
Training: MSE between selected-action logit and MC return G.

Reuses ``training.core.network.AgentBase`` for static caching, and
generic ``ActorCritic`` (via ``make_actor_critic`` with single Q head)
for the network architecture (decision #1: A1 logit-as-Q).

Relocated from ``legacy/agent.py`` (FU-W4-DMC-pt2) once ``tools/eval/``
adopted the adapter import path; no behavioural change.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import torch

from gicg_env import GicgEnv
from training.core.network import AgentBase, AgentConfig, make_actor_critic
from training.core.step_encoding import (
    build_legal_mask,
    pad_action_payments,
    pad_action_refs,
)
from training.core.structural import (
    compute_structural_obspos,
    compute_structural_values,
)


# DMC head subset: single Q head (decision A1, logit-as-Q per spec D2.1).
# QHead and PolicyHead share identical implementation (state_proj MLP +
# state_vec ⨯ action_emb dot product); naming reflects semantics
# (DMC treats output as Q-values not policy logits).
DMC_HEAD_KINDS = frozenset({'q'})


class DmcAgent(AgentBase):
    """ActorCritic-backed DMC agent (single Q head).

    Player interface: ``select_action(env) -> int``.
    Training interface: ``forward_batch_loss(batch, returns) -> loss``.
    Per-game caching: call ``game_start(env.static_obs)`` once at env reset.

    Core-network-generic-promotion Phase 2B: switched to generic ActorCritic
    backbone with single Q head (drop unused value + delta from prior
    'same as AZ for now' all-3-heads config). DI: hook_encoder injected.
    """

    def __init__(
        self,
        cfg: AgentConfig,
        device: str = 'cpu',
        lr: float = 1e-4,
        weight_decay: float = 0.0,
        epsilon: float = 0.0,
    ):
        net = make_actor_critic(
            cfg,
            head_kinds=DMC_HEAD_KINDS,
            use_typed_damage=True,
        ).to(torch.device(device))
        super().__init__(cfg, hook_encoder=net.hook_encoder, device=device)
        self.net = net
        self.optimizer = torch.optim.AdamW(
            self.net.parameters(),
            lr=lr,
            weight_decay=weight_decay,
        )
        self.epsilon = epsilon
        self.rng = random.Random()

    # --- Player interface ------------------------------------------- #

    def select_action(self, env: GicgEnv) -> int:
        """Argmax over logits with ε-greedy exploration. Player-compatible."""
        action_idx, _ = self.act_with_logit(env)
        return action_idx

    def act_with_logit(self, env: GicgEnv) -> tuple[int, float]:
        """Variant returning (action_idx, selected_logit). Selected logit
        is the *raw logit before softmax* — DMC treats it as Q estimate.
        Used by training actor to record (obs, action_idx, G) along with
        the predicted Q for diagnostic logging."""
        if self._hook_emb is None:
            raise RuntimeError(
                'DmcAgent.select_action called before game_start — call game_start(env.static_obs) at episode start.'
            )
        dyn_obs = env._get_obs()
        kinds, _ = env.get_legal_actions()
        n_legal = int(len(kinds))
        if n_legal == 0:
            return 0, 0.0
        refs_np = env.get_action_refs()
        pay_np = env.get_legal_action_payments()

        legal_logits = self._forward_logits(dyn_obs, refs_np, pay_np, n_legal)
        if self.epsilon > 0.0 and self.rng.random() < self.epsilon:
            idx = self.rng.randrange(n_legal)
        else:
            idx = int(legal_logits.argmax().item())
        return idx, float(legal_logits[idx].item())

    def _forward_logits(
        self,
        dyn_obs_np: np.ndarray,
        refs_np: np.ndarray,
        payments_np: np.ndarray,
        n_legal: int,
    ) -> torch.Tensor:
        """Forward pass, return raw legal logits (n_legal,)."""
        refs_padded = pad_action_refs(refs_np, self.cfg.max_actions)
        pay_padded = pad_action_payments(payments_np, self.cfg.max_actions)
        _ = build_legal_mask(self.cfg.max_actions, n_legal)  # consistency

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
            )
            # Generic ActorCritic returns dict; DMC uses 'q' head (logit-as-Q).
            return out['q'][0, :n_legal].clone()

    # --- Provider-backed inference --------------------------------- #

    def build_obs_dict(self, env: GicgEnv) -> dict:
        """Pack all 15 tensors needed by ActorCritic.forward.

        Combines cached static fields (from game_start) with dynamic
        fields parsed at this turn. Returns a dict ready for
        DMCInferenceNet.forward(obs). Caller must call game_start first
        and verify n_legal>0 before slicing the returned logits.
        """
        if self._hook_emb is None:
            raise RuntimeError(
                'DmcAgent.build_obs_dict called before game_start — call game_start(env.static_obs) at episode start.'
            )
        dyn_obs = env._get_obs()
        refs_np = env.get_action_refs()
        pay_np = env.get_legal_action_payments()

        refs_padded = pad_action_refs(refs_np, self.cfg.max_actions)
        pay_padded = pad_action_payments(pay_np, self.cfg.max_actions)

        (
            counter_values,
            meta,
            card_buckets,
            enemy_sizes,
            recent_damage,
            prepare_skill,
            modifier_log,
        ) = self._parse_dynamic_single(dyn_obs)

        refs_t = torch.tensor(refs_padded, dtype=torch.long, device=self.device).unsqueeze(0)
        pay_t = torch.tensor(pay_padded, dtype=torch.float32, device=self.device).unsqueeze(0)
        structural_values = compute_structural_values(counter_values, self._structural_obspos)

        return {
            'counter_values': counter_values,
            'counter_sids': self._counter_sids,
            'active_slot_mask': self._active_slot_mask,
            'hook_emb': self._hook_emb,
            'hook_mask': self._hook_mask,
            'card_buckets': card_buckets,
            'enemy_sizes': enemy_sizes,
            'meta': meta,
            'action_refs': refs_t,
            'action_payments': pay_t,
            'structural_values': structural_values,
            'char_skill_refs': self._char_skill_refs,
            'recent_damage': recent_damage,
            'prepare_skill': prepare_skill,
            'modifier_log': modifier_log,
        }

    def act_via_provider(self, env: GicgEnv, provider: Any) -> tuple[int, float]:
        """Provider-backed act_with_logit; same ε-greedy contract.

        Used by serial play_one_episode via DMCSerialCollector. Provider
        wrapping DMCInferenceNet in-proc is equivalent to act_with_logit;
        RemoteNetworkProvider routes forward to a GPU InferenceServer.
        """
        kinds, _ = env.get_legal_actions()
        n_legal = int(len(kinds))
        if n_legal == 0:
            return 0, 0.0

        obs_dict = self.build_obs_dict(env)
        with torch.no_grad():
            logits_full = provider.forward(obs_dict, mask=None)
        legal_logits = logits_full[0, :n_legal].clone()

        if self.epsilon > 0.0 and self.rng.random() < self.epsilon:
            idx = self.rng.randrange(n_legal)
        else:
            idx = int(legal_logits.argmax().item())
        return idx, float(legal_logits[idx].item())

    # --- Training interface ---------------------------------------- #

    def forward_batch(self, batch: dict):
        """Batched forward (same as AZ for now). Returns (logits, value, delta_pred)."""

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
        )
        # DMC uses single Q head; loss expects (logits, value, delta) 3-tuple
        # (DMCLogitAsQLoss only reads logits, the latter two are unused
        # placeholders for AZ-style protocol compatibility).
        return out['q'], None, None

    # --- Save / Load ---------------------------------------------- #

    def state_dict(self) -> dict:
        return {
            'net': self.net.state_dict(),
            'optimizer': self.optimizer.state_dict(),
        }

    def load_state_dict_full(self, sd: dict) -> None:
        self.net.load_state_dict(sd['net'])
        if 'optimizer' in sd:
            self.optimizer.load_state_dict(sd['optimizer'])

    def load_net_only(self, net_sd: dict) -> None:
        """Load only network weights (used by historical opponent loader)."""
        self.net.load_state_dict(net_sd)
