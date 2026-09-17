"""Gradient geometry for retention diagnostics."""

import torch

from tools.experiments.semantic_training.agent import batch_observations
from tools.experiments.semantic_training.imitation_loss import imitation_loss
from tools.experiments.semantic_training.paired_training import objective, predict
from tools.experiments.semantic_training.retention_metrics import parameter_group


def _gradient_vector(parameters):
    return [torch.zeros_like(parameter) for parameter in parameters]


def _add_gradients(total, gradients):
    for destination, gradient in zip(total, gradients, strict=True):
        if gradient is not None:
            destination.add_(gradient)


def paired_gradients(agent, pairs, batch_pairs=8):
    pairs = [pair for pair in pairs if pair['split'] == 'train']
    if not pairs:
        raise ValueError('paired gradients require training pairs')
    names = [name for name, parameter in agent.net.named_parameters() if parameter.requires_grad]
    parameters = [agent.net.get_parameter(name) for name in names]
    head_parameters = list(agent.rule_head.parameters())
    totals = _gradient_vector(parameters)
    head_totals = _gradient_vector(head_parameters)
    losses = []
    total_pairs = 0
    for start in range(0, len(pairs), batch_pairs):
        part = pairs[start : start + batch_pairs]
        prediction, truth = predict(agent, part)
        loss = objective(prediction, truth, part, beta=1.0)
        parameter_gradients = torch.autograd.grad(
            loss, parameters + head_parameters, allow_unused=True, retain_graph=False
        )
        _add_gradients(totals, parameter_gradients[: len(parameters)])
        _add_gradients(head_totals, parameter_gradients[len(parameters) :])
        losses.append(float(loss.detach()) * len(part))
        total_pairs += len(part)
    return (
        dict(zip(names, (gradient / total_pairs for gradient in totals), strict=True)),
        [gradient / total_pairs for gradient in head_totals],
        sum(losses) / total_pairs,
    )


def imitation_gradients(agent, rows, batch_size=128):
    names = [name for name, parameter in agent.net.named_parameters() if parameter.requires_grad]
    parameters = [agent.net.get_parameter(name) for name in names]
    totals = _gradient_vector(parameters)
    losses = []
    total_rows = 0
    for start in range(0, len(rows), batch_size):
        part = rows[start : start + batch_size]
        batch = batch_observations([row['obs'] for row in part], agent.cfg, agent.device)
        logits = agent.net(batch).masked_fill(~batch['legal_mask'], -1e9)
        loss, fit, _ = imitation_loss(logits, [row['tied'] for row in part], 'uniform', None, 0.0)
        gradients = torch.autograd.grad(loss, parameters, allow_unused=True)
        _add_gradients(totals, gradients)
        losses.append(float(fit) * len(part))
        total_rows += len(part)
    return dict(zip(names, (gradient / total_rows for gradient in totals), strict=True)), sum(losses) / total_rows


def gradient_geometry(agent, pairs, teacher_rows):
    paired, paired_head, paired_loss = paired_gradients(agent, pairs)
    imitation, imitation_loss_value = imitation_gradients(agent, teacher_rows)
    if paired.keys() != imitation.keys():
        raise ValueError('gradient parameter names differ')

    def geometry(names):
        left = [paired[name].to(torch.float64).reshape(-1) for name in names]
        right = [imitation[name].to(torch.float64).reshape(-1) for name in names]
        left = torch.cat(left) if left else torch.zeros(1, dtype=torch.float64)
        right = torch.cat(right) if right else torch.zeros(1, dtype=torch.float64)
        paired_norm = float(left.norm())
        imitation_norm = float(right.norm())
        denominator = paired_norm * imitation_norm
        return {
            'paired_norm': paired_norm,
            'imitation_norm': imitation_norm,
            'imitation_to_paired': imitation_norm / paired_norm if paired_norm else None,
            'cosine': float(left @ right / denominator) if denominator else None,
            'tensors': len(names),
            'paired_connected': sum(bool(paired[name].any()) for name in names),
            'imitation_connected': sum(bool(imitation[name].any()) for name in names),
        }

    groups = {}
    for group in sorted({parameter_group(name) for name in paired}):
        names = [name for name in paired if parameter_group(name) == group]
        groups[group] = geometry(names)
    head_norm = sum(float(gradient.double().norm()) ** 2 for gradient in paired_head) ** 0.5
    return {
        'paired_loss': paired_loss,
        'imitation_loss': imitation_loss_value,
        'paired_head_norm': head_norm,
        'all': geometry(list(paired)),
        'groups': groups,
    }
