"""AZ training step — one (agent, batch, config) call does forward +
loss + backward + optimizer step.

Phase 2-ζ (FU-W4-AZ-rewrite, T2.ζ) — inlined from
``training.paradigms.az.legacy.train_step`` so the adapter
``train_loop`` (mv'd here at T2.ζ) no longer touches ``legacy.*``.
``legacy/train_step.py`` stays alive (Phase 5 git rm); ``test_train`` +
the legacy buffer ingest path still reference it directly.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from training.paradigms.az._az_losses import az_losses


@dataclass
class TrainStepConfig:
    l2_coef: float = 1e-4
    max_grad_norm: float = 1.0
    value_target_source: str = 'z'  # "z" | "mcts_value" | "mixed"
    value_mix_lambda: float = 0.5
    entropy_coef: float = 0.0
    delta_aux_coef: float = 0.1


def train_step(
    agent,
    batch: dict,
    config: TrainStepConfig,
) -> dict[str, float]:
    """One gradient step. Expects batch in the ReplayBuffer shape."""
    device = agent.device

    logits, value, delta_pred = agent.forward_batch(batch)

    legal_mask = torch.as_tensor(batch['legal_mask'], dtype=torch.bool, device=device)
    pi_target = torch.as_tensor(batch['pi_target'], dtype=torch.float32, device=device)
    z_target = torch.as_tensor(batch['z_target'], dtype=torch.float32, device=device)

    v_target = _select_value_target(batch, z_target, config, device)

    losses = az_losses(
        logits=logits,
        value=value,
        legal_mask=legal_mask,
        pi_target=pi_target,
        z_target=v_target,
        model=agent.net,
        l2_coef=config.l2_coef,
        entropy_coef=config.entropy_coef,
    )

    if config.delta_aux_coef > 0.0 and 'counter_target' in batch:
        counter_target = torch.as_tensor(
            batch['counter_target'],
            dtype=torch.float32,
            device=device,
        )
        has_target = torch.as_tensor(
            batch['has_counter_target'],
            dtype=torch.bool,
            device=device,
        )
        active_mask = torch.as_tensor(
            batch['active_slot_mask'],
            dtype=torch.bool,
            device=device,
        )
        row_mask = has_target.unsqueeze(-1) & active_mask
        diff2 = (delta_pred - counter_target) ** 2
        denom = row_mask.float().sum().clamp_min(1.0)
        delta_loss = (diff2 * row_mask.float()).sum() / denom
        losses['delta_aux'] = delta_loss
        losses['total'] = losses['total'] + config.delta_aux_coef * delta_loss

    for name in ('total', 'value', 'policy', 'l2'):
        if name not in losses:
            continue
        t = losses[name]
        if not torch.isfinite(t).all().item():
            raise RuntimeError(
                f'train_step: loss[{name}] is non-finite ({float(t.detach().item())}). '
                f'Aborting before the bad gradient hits the optimizer.'
            )

    agent.optimizer.zero_grad()
    losses['total'].backward()
    if config.max_grad_norm > 0:
        torch.nn.utils.clip_grad_norm_(
            agent.net.parameters(),
            max_norm=config.max_grad_norm,
        )
    agent.optimizer.step()

    return {k: float(v.detach().item()) for k, v in losses.items()}


def _select_value_target(
    batch: dict,
    z_target: torch.Tensor,
    config: TrainStepConfig,
    device: torch.device,
) -> torch.Tensor:
    src = config.value_target_source
    if src == 'z':
        return z_target
    if src == 'mcts_value':
        if 'mcts_value' not in batch:
            raise KeyError(
                "train_step: value_target_source='mcts_value' but batch "
                "has no 'mcts_value' field. Either switch the source to "
                "'z' or have the self-play worker record MCTS root "
                'values per step.'
            )
        return torch.as_tensor(
            batch['mcts_value'],
            dtype=torch.float32,
            device=device,
        )
    if src == 'mixed':
        if 'mcts_value' not in batch:
            raise KeyError("train_step: value_target_source='mixed' but batch has no 'mcts_value' field.")
        mv = torch.as_tensor(
            batch['mcts_value'],
            dtype=torch.float32,
            device=device,
        )
        lam = config.value_mix_lambda
        return lam * z_target + (1.0 - lam) * mv
    raise ValueError(f"train_step: unknown value_target_source={src!r}; expected one of 'z', 'mcts_value', 'mixed'")
