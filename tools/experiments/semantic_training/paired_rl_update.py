"""Weighted paired preference update for semantic policy checkpoints."""

import torch

from tools.experiments.semantic_training.agent import batch_observations
from tools.experiments.semantic_training.paired_counterfactual import paired_preference_loss


def update_paired(
    agent,
    anchor,
    optimizer,
    rows,
    *,
    batch_size=32,
    epochs=2,
    temperature=1.0,
    anchor_beta=0.02,
):
    if not rows:
        return {'updates': 0, 'rows': 0, 'reroll_rows': 0, 'ordinary_rows': 0}
    stats = []
    for _ in range(epochs):
        for offset in range(0, len(rows), batch_size):
            picked = rows[offset : offset + batch_size]
            batch = batch_observations([row['obs'] for row in picked], agent.cfg, agent.device)
            chosen = torch.tensor([row['chosen_action'] for row in picked], device=agent.device)
            alternative = torch.tensor([row['alternative_action'] for row in picked], device=agent.device)
            preference = torch.tensor([row['preference'] for row in picked], device=agent.device, dtype=torch.float32)
            weight = torch.tensor([row['sample_weight'] for row in picked], device=agent.device, dtype=torch.float32)
            logits = agent.net(batch)
            with torch.no_grad():
                anchor_logits = anchor.net(batch)
            loss, metrics = paired_preference_loss(
                logits,
                batch['legal_mask'],
                chosen,
                alternative,
                preference,
                anchor_logits,
                temperature=temperature,
                anchor_beta=anchor_beta,
                sample_weight=weight,
            )
            if not torch.isfinite(loss):
                raise ValueError('nonfinite paired preference loss')
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(agent.net.parameters(), 1.0)
            optimizer.step()
            stats.append({key: float(value.detach()) for key, value in metrics.items()})
    return {
        'updates': len(stats),
        'rows': len(rows),
        'reroll_rows': sum(row.get('decision_type') == 'reroll' for row in rows),
        'ordinary_rows': sum(row.get('decision_type') != 'reroll' for row in rows),
        'ties': sum(row.get('ties', 0) for row in rows),
        'discordance': sum(row.get('discordance', 0) for row in rows),
        **({key: sum(item[key] for item in stats) / len(stats) for key in stats[0]} if stats else {}),
    }
