"""TraverserBase — shared state + helper methods consumed by the
OS and ES mixins."""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
import torch

from training.paradigms.cfr.advantage_net import regret_to_policy
from training.paradigms.cfr.traversal.config import TraversalConfig
from training.paradigms.cfr.traversal.encoding import _StaticBundle, encode_static_for_traversal


class TraverserBase:
    """Base class for CFRTraverser. Holds the per-player AdvantageNets,
    the three reservoir buffers, config, rng, device.

    Concrete ``traverse()`` lives on the mixin subclasses; see
    ``training.paradigms.cfr.traversal.__init__.CFRTraverser`` for the final
    composition.
    """

    def __init__(
        self,
        advantage_nets,
        n_counter_slots: int,
        max_ops_per_hook: int,
        n_hooks_capacity: int,
        max_actions: int,
        advantage_buffers,
        strategy_buffer,
        value_buffer,
        config: Optional[TraversalConfig] = None,
        rng: Optional[random.Random] = None,
        device: Optional[torch.device] = None,
    ):
        if len(advantage_nets) != 2:
            raise ValueError(f'advantage_nets must be a list of 2 nets (one per player), got {len(advantage_nets)}')
        if len(advantage_buffers) != 2:
            raise ValueError(f'advantage_buffers must be a list of 2 buffers, got {len(advantage_buffers)}')
        for net in advantage_nets:
            net.eval()
        self.advantage_nets = list(advantage_nets)
        self.advantage_buffers = list(advantage_buffers)
        self.n_counter_slots = n_counter_slots
        self.max_ops_per_hook = max_ops_per_hook
        self.n_hooks_capacity = n_hooks_capacity
        self.max_actions = max_actions
        self.strategy_buffer = strategy_buffer
        self.value_buffer = value_buffer
        self.config = config if config is not None else TraversalConfig()
        self.rng = rng if rng is not None else random.Random()
        self.device = device if device is not None else torch.device('cpu')

    # --- Shared setup ------------------------------------------------ #

    def _prepare_traversal(self, env, traverser_player: int):
        """Encode static, register game in all three reservoirs."""
        static = encode_static_for_traversal(
            self.advantage_nets[0],
            env.static_obs,
            n_counter_slots=self.n_counter_slots,
            max_ops_per_hook=self.max_ops_per_hook,
            n_hooks_capacity=self.n_hooks_capacity,
            device=self.device,
        )
        adv_buffer = self.advantage_buffers[traverser_player]
        gid_adv = adv_buffer.register_game(static.static_np)
        gid_str = self.strategy_buffer.register_game(static.static_np)
        gid_val = self.value_buffer.register_game(static.static_np)
        return static, gid_adv, gid_str, gid_val, adv_buffer

    # --- Shared helpers --------------------------------------------- #

    def _current_policy(
        self,
        net,
        dynamic: dict,
        static: _StaticBundle,
        counter_values_t: torch.Tensor,
        structural_values_t: torch.Tensor,
        n_legal: int,
    ) -> np.ndarray:
        """Forward through the per-player AdvantageNet + regret_to_policy."""
        with torch.no_grad():
            meta_t = torch.tensor(
                dynamic['meta'],
                dtype=torch.float32,
                device=self.device,
            ).unsqueeze(0)
            card_buckets_t = torch.tensor(
                dynamic['card_buckets'],
                dtype=torch.float32,
                device=self.device,
            ).unsqueeze(0)
            enemy_sizes_t = torch.tensor(
                dynamic['enemy_sizes'],
                dtype=torch.float32,
                device=self.device,
            ).unsqueeze(0)
            action_refs_t = torch.tensor(
                dynamic['action_refs'],
                dtype=torch.long,
                device=self.device,
            ).unsqueeze(0)
            action_payments_t = torch.tensor(
                dynamic['action_payments'],
                dtype=torch.float32,
                device=self.device,
            ).unsqueeze(0)
            legal_mask_t = torch.tensor(
                dynamic['legal_mask'],
                dtype=torch.bool,
                device=self.device,
            ).unsqueeze(0)

            regret = net(
                counter_values=counter_values_t,
                counter_sids=static.counter_sids_t,
                active_slot_mask=static.active_slot_mask_t,
                hook_emb_cached=static.hook_emb,
                hook_mask=static.hook_mask_t,
                card_buckets=card_buckets_t,
                enemy_sizes=enemy_sizes_t,
                meta=meta_t,
                action_refs=action_refs_t,
                action_payments=action_payments_t,
                structural_values=structural_values_t,
                char_skill_refs=static.char_skill_refs_t,
            )
            policy_t = regret_to_policy(regret, legal_mask_t)
            policy = policy_t.squeeze(0).cpu().numpy().astype(np.float32)
        return policy

    def _sampling_dist(
        self,
        policy: np.ndarray,
        legal_mask: np.ndarray,
        n_legal: int,
    ) -> np.ndarray:
        """ε-exploration: q = ε*uniform_over_legal + (1-ε)*policy."""
        eps = self.config.epsilon
        if n_legal <= 0:
            raise ValueError(
                f'_sampling_dist: n_legal={n_legal}; caller should have stopped before reaching a no-legal-actions node'
            )
        legal_sum = float(policy[:n_legal].sum())
        if not (0.99 < legal_sum < 1.01):
            raise ValueError(
                f'_sampling_dist: policy[:{n_legal}].sum()={legal_sum:.4f} '
                'is not ~1; regret_to_policy invariant violated'
            )
        uniform_val = 1.0 / n_legal
        q = np.zeros_like(policy)
        q[:n_legal] = eps * uniform_val + (1.0 - eps) * policy[:n_legal]
        total = q[:n_legal].sum()
        q[:n_legal] = q[:n_legal] / total
        return q

    def _sample_action(self, q: np.ndarray, n_legal: int) -> int:
        """Sample an action index in [0, n_legal) from distribution q."""
        q_legal = q[:n_legal]
        if not np.all(np.isfinite(q_legal)):
            raise ValueError(f'_sample_action: q contains non-finite entries: {q_legal}')
        total = float(q_legal.sum())
        if not (0.99 < total < 1.01):
            raise ValueError(f'_sample_action: q[:{n_legal}].sum()={total:.4f} is not ~1')
        r = self.rng.random() * total
        cum = np.cumsum(q_legal)
        return int(np.searchsorted(cum, r, side='right'))

    def _regret_estimate(
        self,
        policy: np.ndarray,
        sampled_action: int,
        q_sampled: float,
        z: float,
        weight: float,
        legal_mask: np.ndarray,
    ) -> np.ndarray:
        """Outcome-sampling regret estimator (Lanctot 2013 Def.4)."""
        q_floor = max(float(q_sampled), 1e-6)
        sigma_sampled = float(policy[sampled_action])
        factor_nonsampled = -weight * z * sigma_sampled / q_floor
        regret = np.full_like(policy, factor_nonsampled, dtype=np.float32)
        regret[sampled_action] = weight * z * (1.0 - sigma_sampled) / q_floor
        regret[~legal_mask] = 0.0
        return regret
