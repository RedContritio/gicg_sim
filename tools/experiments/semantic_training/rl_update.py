"""Clipped terminal policy gradient with lagged side baseline and frozen-policy KL."""

import torch
from tools.experiments.semantic_training.agent import batch_observations


def policy_loss(logits, mask, actions, old_logp, advantages, anchor_logits, clip=0.2, beta=0.02):
    logp = logits.masked_fill(~mask, -1e9).log_softmax(-1)
    anchor = anchor_logits.masked_fill(~mask, -1e9).log_softmax(-1)
    selected = logp.gather(1, actions[:, None]).squeeze(1)
    logratio = selected - old_logp
    ratio = logratio.exp()
    surrogate = torch.minimum(ratio * advantages, ratio.clamp(1 - clip, 1 + clip) * advantages)
    kl = (logp.exp() * (logp - anchor)).sum(-1).mean()
    entropy = -(logp.exp() * logp).sum(-1).mean()
    loss = -surrogate.mean() + beta * kl - 0.001 * entropy
    approx_kl = ((ratio - 1) - logratio).mean()
    return loss, {'anchor_kl': kl, 'sample_kl': approx_kl, 'entropy': entropy}


def update(
    agent,
    anchor,
    optimizer,
    rows,
    baseline,
    rng,
    epochs=2,
    batch_size=32,
    value_optimizer=None,
    temperature=1.0,
    rule_optimizer=None,
    rule_beta=0.0,
    auxiliary_loss=None,
    anchor_beta=0.02,
):
    stats = []
    stopped = False
    # Baseline is estimated only from previous collection rounds, independent of current actions.
    for _ in range(epochs):
        order = list(range(len(rows)))
        rng.shuffle(order)
        for offset in range(0, len(order), batch_size):
            picked = [rows[i] for i in order[offset : offset + batch_size]]
            batch = batch_observations([r['obs'] for r in picked], agent.cfg, agent.device)
            actions = torch.tensor([r['action'] for r in picked], device=agent.device)
            old = torch.tensor([r['old_logp'] for r in picked], device=agent.device)
            value_loss = None
            representation = agent.net(batch, return_actions=True) if rule_optimizer is not None else None
            if value_optimizer is not None:
                from tools.experiments.semantic_training.value_baseline import advantages as state_advantages

                rewards = torch.tensor([r['reward'] for r in picked], device=agent.device, dtype=torch.float32)
                old_values = torch.tensor([r['old_value'] for r in picked], device=agent.device, dtype=torch.float32)
                advantages = state_advantages(rewards, old_values)
                logits, state = (
                    representation[:2] if representation is not None else agent.net(batch, return_state=True)
                )
                value_loss = torch.nn.functional.mse_loss(agent.value_head(state), rewards)
            else:
                advantages = torch.tensor([r['reward'] - baseline[r['side']] for r in picked], device=agent.device)
                logits = representation[0] if representation is not None else agent.net(batch)
            with torch.no_grad():
                reference = anchor.net(batch)
            loss, metrics = policy_loss(
                logits / temperature,
                batch['legal_mask'],
                actions,
                old,
                advantages,
                reference / temperature,
                beta=anchor_beta,
            )
            if value_loss is not None:
                metrics['value_loss'] = value_loss
            if rule_optimizer is not None:
                from tools.experiments.semantic_training.rule_auxiliary import loss as rule_loss

                auxiliary = (
                    auxiliary_loss(agent)
                    if auxiliary_loss is not None
                    else rule_loss(agent.rule_head, representation[1], representation[2], picked)
                )
                metrics['rule_loss'] = auxiliary
                loss = loss + rule_beta * auxiliary
            if not torch.isfinite(loss) or not all(torch.isfinite(v) for v in metrics.values()):
                raise ValueError('nonfinite RL update')
            if metrics['sample_kl'].detach().item() > 0.02:
                stopped = True
                break
            optimizer.zero_grad()
            if rule_optimizer is not None:
                rule_optimizer.zero_grad()
            if value_optimizer is not None:
                value_optimizer.zero_grad()
            (loss if value_loss is None else loss + value_loss).backward()
            torch.nn.utils.clip_grad_norm_(agent.net.parameters(), 1.0)
            optimizer.step()
            if rule_optimizer is not None:
                torch.nn.utils.clip_grad_norm_(agent.rule_head.parameters(), 1.0)
                rule_optimizer.step()
            if value_optimizer is not None:
                torch.nn.utils.clip_grad_norm_(agent.value_head.parameters(), 1.0)
                value_optimizer.step()
            stats.append({'loss': float(loss.detach()), **{k: float(v.detach()) for k, v in metrics.items()}})
        if stopped:
            break
    return {
        'updates': len(stats),
        'early_stop_kl': stopped,
        **({key: sum(s[key] for s in stats) / len(stats) for key in stats[0]} if stats else {}),
    }
