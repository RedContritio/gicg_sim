"""DMCLogitAsQLoss — DMC MSE loss on logit-as-Q vs MC return.

Spec ref: paradigm-dmc/spec.md D2.1-D2.3. Treats raw policy logits as Q
values; MSE between logit[a_i] and Monte Carlo return G_i. γ=1, no
bootstrap, no policy gradient. DouZero (Zha et al., ICML 2021) showed
this suffices for imperfect-info large-action games.

FU-W4-DMC: ``dmc_mse_loss`` inlined directly here (previously imported
from ``legacy/loss.py``); the adapter loss path is now self-contained.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

from training.core.protocols import Batch, LossResult


def dmc_mse_loss(
    logits: torch.Tensor,
    action_idx: torch.Tensor,
    returns: torch.Tensor,
) -> torch.Tensor:
    """MSE on selected-action logit vs MC return.

    Loss formula::

        L = mean_i ( logit_i[a_i] - G_i )^2

    Args:
        logits: ``(B, N_act)`` raw model logits (no softmax).
        action_idx: ``(B,)`` int64 — index of the action taken at this step.
        returns: ``(B,)`` float32 — MC return G from acting player's view.

    Returns:
        Scalar tensor — MSE loss on selected-action logit vs G.
    """
    if logits.dim() != 2:
        raise ValueError(f'logits must be (B, N_act), got shape {tuple(logits.shape)}')
    if action_idx.dim() != 1:
        raise ValueError(f'action_idx must be (B,), got shape {tuple(action_idx.shape)}')
    if returns.dim() != 1:
        raise ValueError(f'returns must be (B,), got shape {tuple(returns.shape)}')

    selected_logit = logits.gather(1, action_idx.long().unsqueeze(1)).squeeze(1)
    return F.mse_loss(selected_logit, returns.float())


class DMCLogitAsQLoss:
    """LossComputer protocol implementation. Reads ``batch.data`` keys
    ``collated`` / ``action_idx`` / ``returns``.

    The adapter accepts a ``Batch`` whose ``data`` dict carries
    ``collated`` (dict of stacked numpy arrays) + ``action_idx`` +
    ``returns``; the loss runs the network forward pass internally
    because GICG obs capture is owned by ``DmcAgent``'s static cache.
    """

    def __init__(self, paradigm_cfg: Any) -> None:
        self.cfg = paradigm_cfg

    def compute(self, network: Any, batch: Batch) -> LossResult:
        """Forward + MSE on selected-action logit vs MC return.

        Args:
            network: must expose ``forward_batch(collated_dict)`` →
                ``(logits, value, delta)``. For DMC that's a
                ``DmcAgent`` (held by the collector / scheduler).
            batch: Batch with ``data['collated']`` (dict) +
                ``data['action_idx']`` (LongTensor) +
                ``data['returns']`` (FloatTensor).
        """
        d = batch.data
        if 'collated' not in d or 'action_idx' not in d or 'returns' not in d:
            raise ValueError(
                f'DMCLogitAsQLoss.compute: batch.data missing required keys '
                f'(got {sorted(d.keys())}; need collated/action_idx/returns)'
            )
        collated = d['collated']
        action_idx = d['action_idx']
        returns = d['returns']

        if not hasattr(network, 'forward_batch'):
            raise TypeError(
                f'DMCLogitAsQLoss.compute: network must expose forward_batch(dict); got {type(network).__name__}'
            )
        logits, _value, _delta = network.forward_batch(collated)
        loss = dmc_mse_loss(logits, action_idx, returns)

        breakdown = {
            'loss': float(loss.detach().item()),
            'q_mean': float(logits.detach().gather(1, action_idx.long().unsqueeze(1)).squeeze(1).mean().item()),
            'target_mean': float(returns.float().mean().item()),
            'target_abs_mean': float(returns.float().abs().mean().item()),
        }
        return LossResult(loss=loss, breakdown=breakdown)
