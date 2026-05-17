"""CFRLoss — advantage MSE + strategy MSE.

Spec ref: paradigm-cfr/spec.md C2. Two-head loss:

  - Advantage head: MSE between predicted per-action regret and target
    regret, masked & averaged over legal actions only (mirrors
    ``training.paradigms.cfr.fit_steps.fit_advantage`` per-sample reduction).
  - Strategy head: MSE between predicted action probability and target
    cumulative-strategy distribution (also masked by legal actions).

C2.3 — reduction = mean over batch, no policy/strategy reweighting at
the loss level (avoids the loss/quality decoupling observed in r008
per memory `project_r008_postmortem`).

Driver contract: ``loss_fn.compute(network, batch)`` returns a
``LossResult``. ``batch.data`` must carry either:

  - ``head='advantage'`` + ``pred`` (B, max_actions) + ``target`` (same) +
    ``legal_mask`` (B, max_actions), OR
  - ``head='strategy'`` + ``pred`` + ``target`` + ``legal_mask``

Pre-computed forward (collector or fit driver) is expected — wrapping
the legacy ``forward_cfr_batch`` is out of scope for this adapter
(would require copying the encoder forward path; P5 will consolidate).
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

from training.core.protocols import Batch, LossResult


class CFRLoss:
    """Two-head MSE loss, dispatched by ``batch.data['head']``."""

    REQUIRED_KEYS = ('head', 'pred', 'target', 'legal_mask')

    def __init__(self, paradigm_cfg: Any = None) -> None:
        self.cfg = paradigm_cfg

    def compute(self, network: Any, batch: Batch) -> LossResult:
        """Compute per-action-masked MSE on either head.

        ``network`` is accepted for protocol conformance but unused —
        forward must be done upstream by the fit driver (matches legacy
        ``fit_advantage`` / ``fit_strategy_joint``). This keeps the loss
        layer head-agnostic and avoids dragging the encoder path here.
        """
        del network  # forward owned by fit driver, not this loss
        d = batch.data
        missing = [k for k in self.REQUIRED_KEYS if k not in d]
        if missing:
            raise ValueError(
                f'CFRLoss.compute: batch.data missing required keys '
                f'{missing} (got {sorted(d.keys())}; need {list(self.REQUIRED_KEYS)})'
            )
        head = d['head']
        if head not in ('advantage', 'strategy'):
            raise ValueError(f"CFRLoss.compute: head must be 'advantage' or 'strategy', got {head!r}")

        pred = d['pred']
        target = d['target']
        legal_mask = d['legal_mask']
        if not torch.is_tensor(pred):
            pred = torch.as_tensor(pred, dtype=torch.float32)
        if not torch.is_tensor(target):
            target = torch.as_tensor(target, dtype=torch.float32)
        if not torch.is_tensor(legal_mask):
            legal_mask = torch.as_tensor(legal_mask, dtype=torch.bool)
        if pred.shape != target.shape:
            raise ValueError(f'CFRLoss.compute: pred shape {tuple(pred.shape)} != target shape {tuple(target.shape)}')
        if pred.shape != legal_mask.shape:
            raise ValueError(
                f'CFRLoss.compute: pred shape {tuple(pred.shape)} != legal_mask shape {tuple(legal_mask.shape)}'
            )

        legal_f = legal_mask.float()
        # Per-sample mean over legal actions, then batch mean (matches
        # `fit_advantage`'s `(pred-target)^2 * legal / n_legal` form).
        sq = (pred - target).pow(2) * legal_f
        per_sample_n = legal_f.sum(dim=-1).clamp(min=1.0)
        per_sample_loss = sq.sum(dim=-1) / per_sample_n
        loss = per_sample_loss.mean()

        breakdown = {
            f'{head}_loss': float(loss.detach().item()),
            f'{head}_pred_mean': float(pred.detach().mean().item()),
            f'{head}_target_mean': float(target.detach().mean().item()),
            f'{head}_n_legal_mean': float(per_sample_n.mean().item()),
        }
        return LossResult(loss=loss, breakdown=breakdown)


def cfr_advantage_mse(pred: torch.Tensor, target: torch.Tensor, legal_mask: torch.Tensor) -> torch.Tensor:
    """Convenience functional form mirroring `fit_advantage` exactly."""
    legal_f = legal_mask.float()
    sq = (pred - target).pow(2) * legal_f
    n = legal_f.sum(dim=-1).clamp(min=1.0)
    return (sq.sum(dim=-1) / n).mean()


def cfr_strategy_mse(pred: torch.Tensor, target: torch.Tensor, legal_mask: torch.Tensor) -> torch.Tensor:
    """Strategy head — same masked MSE; semantically pred & target are
    probabilities over legal actions (softmax / regret-matching normalize).
    """
    return cfr_advantage_mse(pred, target, legal_mask)
