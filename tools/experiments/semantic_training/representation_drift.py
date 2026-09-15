"""Representation- and gradient-drift diagnostics for policy-retention experiments.

Mechanism evidence only. CKA and parameter drift describe *how* a network moved;
they do not measure whether the policy got better or worse. Never report them as
strength evidence, and never substitute them for the paired evaluation panel.

Why linear CKA is weak evidence: it is invariant to orthogonal reparametrisation
and to isotropic rescaling, so two networks descended from a shared initialisation
score high even when their behaviour has changed. It systematically over-reports
"preserved" — read it next to functional drift (KL between policies, action
agreement) rather than instead of it.
"""

import torch


def linear_cka(features, other):
    """Linear CKA between two ``(n_samples, n_features)`` matrices.

    Centres both matrices, then returns ``||YᵗX||_F² / (||XᵗX||_F · ||YᵗY||_F)``
    (Kornblith et al. 2019). ``1.0`` for identical inputs; requires the same
    samples in the same order, since it compares sample-to-sample structure.
    """
    if features.ndim != 2 or other.ndim != 2:
        raise ValueError('CKA requires two 2-D feature matrices')
    if features.shape[0] != other.shape[0]:
        raise ValueError('CKA requires the same number of samples')
    if features.shape[0] < 2:
        raise ValueError('CKA requires at least two samples')
    x = features.to(torch.float64)
    y = other.to(torch.float64)
    x = x - x.mean(0, keepdim=True)
    y = y - y.mean(0, keepdim=True)
    cross = (y.t() @ x).norm().pow(2)
    denominator = (x.t() @ x).norm() * (y.t() @ y).norm()
    if denominator == 0:
        raise ValueError('CKA is undefined for constant features')
    return float(cross / denominator)


def tensor_drift(reference, candidate):
    """Per-tensor mean/max absolute drift between two state dictionaries.

    Returns ``{'tensors': {key: {'mean', 'max'}}, 'mean', 'max'}``. Keys and
    shapes must match exactly; a mismatched key is a real incompatibility, not
    a drift signal, so it raises.
    """
    if reference.keys() != candidate.keys():
        missing = sorted(set(reference) ^ set(candidate))
        raise ValueError(f'state dict keys differ: {missing}')
    rows = {}
    for key, value in reference.items():
        other = candidate[key]
        if value.shape != other.shape:
            raise ValueError(f'tensor shape differs for {key}: {tuple(value.shape)} vs {tuple(other.shape)}')
        delta = (other.to(torch.float64) - value.to(torch.float64)).abs()
        rows[key] = {'mean': float(delta.mean()), 'max': float(delta.max())}
    if not rows:
        raise ValueError('state dict is empty')
    return {
        'tensors': rows,
        'mean': sum(row['mean'] for row in rows.values()) / len(rows),
        'max': max(row['max'] for row in rows.values()),
    }


def cosine_similarity(left, right):
    """Flattened cosine between two gradient collections (iterables of tensors).

    Returns ``None`` when either side has zero norm: the cosine is genuinely
    undefined there, and returning ``0.0`` would silently read as "orthogonal" —
    a claim the data does not support. Callers must count and report such steps
    instead of folding them into an average.
    """
    left = list(left)
    right = list(right)
    if len(left) != len(right):
        raise ValueError('gradient collections differ in length')
    if not left:
        raise ValueError('gradient collections are empty')
    a = torch.cat([tensor.detach().reshape(-1).to(torch.float64) for tensor in left])
    b = torch.cat([tensor.detach().reshape(-1).to(torch.float64) for tensor in right])
    if a.numel() == 0:
        raise ValueError('gradient tensors are empty')
    norm_a, norm_b = a.norm(), b.norm()
    if norm_a == 0 or norm_b == 0:
        return None
    return float((a @ b) / (norm_a * norm_b))
