"""Read-only policy/auxiliary gradient diagnostics on recorded training minibatches."""

import torch

from tools.experiments.semantic_training.agent import batch_observations
from tools.experiments.semantic_training.rl_update import policy_loss


def compare_gradients(named_parameters, policy, auxiliary, auxiliary_beta):
    """Report Euclidean geometry before clipping or Adam; not optimizer displacement."""
    result = {}
    groups = {
        'all': lambda name: True,
        'hook_encoder': lambda name: name.startswith('base.hook_encoder.'),
        'policy_head': lambda name: name.startswith('base.heads.q.'),
        'other_shared': lambda name: not name.startswith(('base.hook_encoder.', 'base.heads.q.')),
    }
    for group, includes in groups.items():
        pp = aa = dot = 0.0
        connected_policy = connected_auxiliary = 0
        for (name, _), p, a in zip(named_parameters, policy, auxiliary, strict=True):
            if not includes(name):
                continue
            if p is not None:
                connected_policy += 1
                pp += float(p.double().square().sum())
            if a is not None:
                connected_auxiliary += 1
                aa += float(a.double().square().sum())
            if p is not None and a is not None:
                dot += float((p.double() * a.double()).sum())
        result[group] = dict(
            policy_norm=pp**0.5,
            auxiliary_norm=aa**0.5,
            scaled_auxiliary_norm=auxiliary_beta * aa**0.5,
            cosine=dot / (pp * aa) ** 0.5 if pp > 0 and aa > 0 else None,
            policy_connected_tensors=connected_policy,
            auxiliary_connected_tensors=connected_auxiliary,
        )
    return result


def measure(agent, rows, auxiliary_loss, temperature=0.5, auxiliary_beta=0.5):
    """Use recorded advantages; report behavior mismatch, with current policy as KL anchor.

    This isolates the clipped reward/entropy gradient. It is not a reconstruction
    of later updates' frozen-anchor penalty, minibatch order, or Adam state.
    """
    batch = batch_observations([r['obs'] for r in rows], agent.cfg, agent.device)
    logits = agent.net(batch) / temperature
    actions = torch.tensor([r['action'] for r in rows], device=agent.device)
    old = logits.new_tensor([r['old_logp'] for r in rows])
    advantages = logits.new_tensor([r['reward'] - r['old_value'] for r in rows])
    loss, metrics = policy_loss(logits, batch['legal_mask'], actions, old, advantages, logits.detach(), beta=0)
    names = [(n, p) for n, p in agent.net.named_parameters() if p.requires_grad]
    params = [p for _, p in names]
    policy = torch.autograd.grad(loss, params, allow_unused=True)
    auxiliary_value = auxiliary_loss(agent)
    auxiliary = torch.autograd.grad(auxiliary_value, params, allow_unused=True)
    selected = logits.detach().masked_fill(~batch['legal_mask'], -1e9).log_softmax(-1)
    discrepancy = selected.gather(1, actions[:, None]).squeeze(1) - old
    return dict(
        rows=len(rows),
        policy_loss=float(loss.detach()),
        auxiliary_loss=float(auxiliary_value.detach()),
        sample_kl=float(metrics['sample_kl'].detach()),
        behavior_logp_max_error=float(discrepancy.abs().max()),
        advantage_min=float(advantages.min()),
        advantage_max=float(advantages.max()),
        groups=compare_gradients(names, policy, auxiliary, auxiliary_beta),
    )
