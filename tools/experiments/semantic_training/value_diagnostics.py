"""Heldout diagnostics for trained semantic value heads."""

import math

import torch


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = rank
        i = j + 1
    return ranks


def _pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0.0 or vy <= 0.0:
        return None
    return cov / math.sqrt(vx * vy)


def _calibration(preds, targets, bins=10):
    order = sorted(range(len(preds)), key=lambda i: preds[i])
    rows = []
    per_bin = max(1, math.ceil(len(order) / bins))
    for start in range(0, len(order), per_bin):
        idx = order[start : start + per_bin]
        rows.append(
            {
                'n': len(idx),
                'pred_mean': sum(preds[i] for i in idx) / len(idx),
                'actual_mean': sum(targets[i] for i in idx) / len(idx),
            }
        )
    return rows


def _metrics(preds, targets):
    n = len(preds)
    squared = sum((p - t) ** 2 for p, t in zip(preds, targets))
    mean = sum(targets) / n
    sst = sum((t - mean) ** 2 for t in targets)
    return {
        'n': n,
        'mse': squared / n,
        'r2': (1.0 - squared / sst) if sst > 0.0 else None,
        'pearson': _pearson(preds, targets),
        'spearman': _pearson(_ranks(preds), _ranks(targets)),
        'calibration_deciles': _calibration(preds, targets),
    }


def diagnose(agent, states, targets, old_values, device, chunk=512):
    """Compare a trained value head with rollout-recorded values on heldout rows."""
    states = states.to(device)
    target_list = [float(value) for value in targets.tolist()]
    with torch.no_grad():
        preds = torch.cat(
            [agent.value_head(states[start : start + chunk]) for start in range(0, states.shape[0], chunk)]
        )
    new_head = _metrics([float(v) for v in preds.cpu().tolist()], target_list)
    old_pairs = [(target, old) for target, old in zip(target_list, old_values) if old is not None]
    old_head = None
    if old_pairs:
        old_targets = [target for target, _old in old_pairs]
        old_preds = [min(1.0, max(0.0, (old + 1.0) / 2.0)) for _target, old in old_pairs]
        old_head = _metrics(old_preds, old_targets)
    ratio = None
    if old_head is not None and old_head['mse'] > 0.0:
        ratio = new_head['mse'] / old_head['mse']
    return {'new_head': new_head, 'old_head': old_head, 'mse_ratio_new_over_old': ratio}
