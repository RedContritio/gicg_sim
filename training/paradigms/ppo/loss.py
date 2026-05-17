"""PPOLoss — clipped surrogate + value MSE + entropy bonus (P2.1-P2.3).

LossComputer impl exposing the PPO update formula as a single
``LossComputer.compute`` step. Formula preserved from the retired PPO
legacy stack (FU-W4-PPO) — clip + value MSE + entropy math unchanged.

Per ``ppo-structural-backbone-migration`` invariant M5: forward path
switched from flat ``network.forward(obs) → (logits, value)`` to
structural ``network.forward_batch(collated) → (policy_logits, value)``.
The masked Categorical now uses ``legal_mask`` from the collated dict
(padded to ``max_actions``) instead of an ad-hoc per-batch mask tensor.

Loss formula (P2.1):

    L = clipped_surrogate + value_coef * value_mse - entropy_coef * H

where:
    ratio  = exp(new_log_prob - old_log_prob)
    surr1  = ratio * advantage
    surr2  = clip(ratio, 1-ε, 1+ε) * advantage
    clipped_surrogate = -min(surr1, surr2).mean()
    value_mse = MSE(value_pred, return)
    H = Categorical(legal-softmax logits).entropy().mean()

Spec ref: paradigm-ppo/spec.md §3 P2 (loss三项 sum)。

The compute method accepts two batch shapes (for both production +
unit-test paths):

A. Real pipeline (RolloutBuffer.sample) path —
   ``batch.data = {'transitions': list[Transition]}`` with structured
   payload per transition. Loss collates internally via
   ``transitions_to_collated`` (requires agent's static cache).

B. Unit-test path —
   ``batch.data = {'collated': dict, 'action': Tensor, 'old_log_prob':
   Tensor, 'advantage': Tensor, 'return': Tensor}``. Caller pre-collates
   structural inputs (e.g. via ``make_structural_batch_dict``).
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

from training.core.protocols import Batch, LossResult


class PPOLoss:
    """LossComputer protocol implementation for PPO."""

    def __init__(self, paradigm_cfg: Any) -> None:
        self.cfg = paradigm_cfg
        # Default hyperparams used when paradigm_cfg is None (e.g. unit
        # tests passing raw tensors directly).
        self._clip_eps = getattr(paradigm_cfg, 'clip_epsilon', 0.2) if paradigm_cfg is not None else 0.2
        self._value_coef = getattr(paradigm_cfg, 'value_coef', 0.5) if paradigm_cfg is not None else 0.5
        self._entropy_coef = getattr(paradigm_cfg, 'entropy_coef', 0.01) if paradigm_cfg is not None else 0.01

    def compute(self, network: Any, batch: Batch) -> LossResult:
        """Forward + clipped surrogate + value MSE + entropy.

        Args:
            network: PPONetwork (or any module exposing
                ``forward_batch(collated_dict) → (policy_logits, value)``).
            batch: Batch with data dict. See module docstring for the two
                accepted shapes (A: 'transitions' list, B: pre-collated dict).
        """
        d = batch.data

        if not hasattr(network, 'forward_batch'):
            raise TypeError(
                f'PPOLoss.compute: network must expose forward_batch(collated_dict); got {type(network).__name__}'
            )

        # Path A: pipeline serial / async — list of Transitions.
        if 'transitions' in d:
            from training.paradigms.ppo._collate import transitions_to_collated

            agent = network.agent if hasattr(network, 'agent') else network
            transitions = d['transitions']
            collated = transitions_to_collated(transitions, agent)
            action = torch.tensor(
                [int(t.action) for t in transitions],
                dtype=torch.long,
                device=agent.device,
            )
            old_lp = torch.tensor(
                [float(t.payload['log_prob']) for t in transitions],
                dtype=torch.float32,
                device=agent.device,
            )
            adv_raw = torch.tensor(
                [float(t.payload['advantage']) for t in transitions],
                dtype=torch.float32,
                device=agent.device,
            )
            # Normalize advantages per-minibatch (standard PPO practice).
            adv = (adv_raw - adv_raw.mean()) / (adv_raw.std(unbiased=False) + 1e-8)
            ret = torch.tensor(
                [float(t.payload['return']) for t in transitions],
                dtype=torch.float32,
                device=agent.device,
            )
        else:
            # Path B: pre-collated.
            required = ('collated', 'action', 'old_log_prob', 'advantage', 'return')
            missing = [k for k in required if k not in d]
            if missing:
                raise ValueError(
                    f'PPOLoss.compute: batch.data missing required keys {missing} '
                    f'(got {sorted(d.keys())}; need either "transitions" or {list(required)})'
                )
            collated = d['collated']
            action = d['action']
            old_lp = d['old_log_prob']
            adv = d['advantage']
            ret = d['return']

        # Forward via structural backbone.
        policy_logits, value = network.forward_batch(collated)
        legal_mask = torch.as_tensor(collated['legal_mask'], dtype=torch.bool, device=policy_logits.device)

        # Legal-softmax log_prob + entropy.
        neg_inf = torch.finfo(policy_logits.dtype).min
        masked = torch.where(legal_mask, policy_logits, torch.full_like(policy_logits, neg_inf))
        log_probs = F.log_softmax(masked, dim=-1)
        new_lp = log_probs.gather(1, action.unsqueeze(-1)).squeeze(-1)
        probs = log_probs.exp()
        # Mask -inf log_probs to 0 before multiplication (avoid 0 * -inf = NaN).
        entropy = -(probs * log_probs.masked_fill(~legal_mask, 0.0)).sum(dim=-1).mean()

        ratio = torch.exp(new_lp - old_lp)
        surr1 = ratio * adv
        surr2 = torch.clamp(ratio, 1.0 - self._clip_eps, 1.0 + self._clip_eps) * adv
        policy_loss = -torch.min(surr1, surr2).mean()
        value_loss = F.mse_loss(value, ret)
        loss = policy_loss + self._value_coef * value_loss - self._entropy_coef * entropy

        with torch.no_grad():
            clip_frac = ((ratio - 1.0).abs() > self._clip_eps).float().mean()

        breakdown = {
            'loss': float(loss.detach().item()),
            'policy_loss': float(policy_loss.detach().item()),
            'value_loss': float(value_loss.detach().item()),
            'entropy': float(entropy.detach().item()),
            'clip_frac': float(clip_frac.item()),
        }
        return LossResult(loss=loss, breakdown=breakdown)
