"""Policy and parameter metrics for retention diagnostics."""

from collections import defaultdict

import torch

from gicg_env import ACTION_CARD, ACTION_END_TURN, ACTION_REROLL, ACTION_SKILL, ACTION_SWITCH, ACTION_TUNE
from tools.experiments.semantic_training.agent import batch_observations


ACTION_KIND_NAMES = {
    ACTION_SKILL: 'Skill',
    ACTION_CARD: 'Card',
    ACTION_SWITCH: 'Switch',
    ACTION_END_TURN: 'EndTurn',
    ACTION_TUNE: 'Tune',
    ACTION_REROLL: 'Reroll',
}


def parameter_group(name):
    if name.startswith('base.hook_encoder.'):
        return 'hook_encoder'
    if name.startswith('base.cross_layers.'):
        return 'cross_layers'
    if name.startswith('base.state_proj.'):
        return 'state_proj'
    if name.startswith('base.heads.q.'):
        return 'q_head'
    if name.startswith('base.buff_encoder.'):
        return 'buff_encoder'
    if name.startswith('base.typed_damage.'):
        return 'typed_damage'
    if name.startswith(('base.dice_combo_proj.', 'base.action_emb_norm.')) or name in {
        'base.tune_action_emb',
        'base.end_turn_emb',
        'base.tune_source_emb',
    }:
        return 'action_encoding'
    if name.startswith('base.'):
        return 'base_other'
    return 'semantic_encoders'


def update_report(reference, candidate):
    if reference.keys() != candidate.keys():
        missing = sorted(set(reference) ^ set(candidate))
        raise ValueError(f'state dict keys differ: {missing}')
    tensors = {}
    grouped = {}
    for name in sorted(reference):
        left = reference[name].detach().to(device='cpu', dtype=torch.float64)
        right = candidate[name].detach().to(device='cpu', dtype=torch.float64)
        if left.shape != right.shape:
            raise ValueError(f'tensor shape differs for {name}')
        delta = right - left
        delta_norm = float(delta.norm())
        reference_norm = float(left.norm())
        row = {
            'reference_norm': reference_norm,
            'delta_norm': delta_norm,
            'relative_norm': delta_norm / reference_norm if reference_norm else None,
            'delta_max': float(delta.abs().max()) if delta.numel() else 0.0,
        }
        tensors[name] = row
        group = grouped.setdefault(parameter_group(name), {'tensors': 0, 'squared_norm': 0.0, 'reference_squared': 0.0})
        group['tensors'] += 1
        group['squared_norm'] += delta_norm**2
        group['reference_squared'] += reference_norm**2
    groups = {
        name: {
            'tensors': row['tensors'],
            'delta_norm': row['squared_norm'] ** 0.5,
            'reference_norm': row['reference_squared'] ** 0.5,
            'relative_norm': row['squared_norm'] ** 0.5 / row['reference_squared'] ** 0.5
            if row['reference_squared']
            else None,
        }
        for name, row in sorted(grouped.items())
    }
    return {
        'tensors': tensors,
        'groups': groups,
        'top_delta_norm': sorted(tensors, key=lambda name: tensors[name]['delta_norm'], reverse=True)[:25],
    }


def masked_q(agent, observations, batch_size):
    rows = []
    masks = []
    agent.net.eval()
    with torch.no_grad():
        for start in range(0, len(observations), batch_size):
            batch = batch_observations(observations[start : start + batch_size], agent.cfg, agent.device)
            q = agent.net(batch).masked_fill(~batch['legal_mask'], -1e9)
            rows.append(q.cpu())
            masks.append(batch['legal_mask'].cpu())
    return torch.cat(rows), torch.cat(masks)


def average_rank_at(values, selected):
    score = values[selected]
    lower = int((values > score).sum())
    equal = int((values == score).sum())
    return 1.0 + lower + (equal - 1) / 2


def _spearman(left, right):
    if left.numel() < 2:
        return None
    left_rank = torch.argsort(torch.argsort(left)).to(torch.float64)
    right_rank = torch.argsort(torch.argsort(right)).to(torch.float64)
    left_rank -= left_rank.mean()
    right_rank -= right_rank.mean()
    denominator = left_rank.norm() * right_rank.norm()
    return float(left_rank @ right_rank / denominator) if denominator else None


def _mean(rows, key):
    values = [row[key] for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def action_kind_name(observation, index):
    refs = observation.get('action_refs')
    if refs is None or index < 0 or index >= len(refs):
        return 'unknown'
    kind = int(refs[index][0])
    return ACTION_KIND_NAMES.get(kind, f'unknown:{kind}')


def summarize_policy_rows(rows):
    keys = rows[0].keys()
    return {
        'rows': len(rows),
        **{
            key: _mean(rows, key)
            for key in keys
            if key not in {'top1_agreement', 'top5_overlap', 'candidate_tied_top1'}
        },
        'top1_agreement': _mean(rows, 'top1_agreement'),
        'top5_overlap': _mean(rows, 'top5_overlap'),
        'candidate_tied_top1': _mean(rows, 'candidate_tied_top1'),
    }


def group_policy_rows(rows, groups):
    report = {}
    for name, labels in groups.items():
        labels = list(labels)
        if len(labels) != len(rows):
            raise ValueError(f'group {name!r} has {len(labels)} labels for {len(rows)} rows')
        buckets = defaultdict(list)
        for row, label in zip(rows, labels, strict=True):
            buckets[str(label)].append(row)
        report[name] = {label: summarize_policy_rows(bucket) for label, bucket in sorted(buckets.items())}
    return report


def policy_probe(
    reference_q,
    reference_mask,
    candidate_q,
    candidate_mask,
    *,
    selected=None,
    tied=None,
    groups=None,
    temperature=0.5,
):
    if not torch.equal(reference_mask, candidate_mask):
        raise ValueError('policy probes use different legal masks')
    if temperature <= 0:
        raise ValueError('temperature must be positive')
    rows = []
    for index in range(reference_q.shape[0]):
        mask = reference_mask[index]
        legal = mask.nonzero(as_tuple=False).squeeze(1)
        reference = reference_q[index].index_select(0, legal)
        candidate = candidate_q[index].index_select(0, legal)
        reference_logp = (reference / temperature).log_softmax(0)
        candidate_logp = (candidate / temperature).log_softmax(0)
        reference_top = int(reference.argmax())
        candidate_top = int(candidate.argmax())
        top_k = min(5, legal.numel())
        reference_topk = set(reference.topk(top_k).indices.tolist())
        candidate_topk = set(candidate.topk(top_k).indices.tolist())
        row = {
            'kl': float((reference_logp.exp() * (reference_logp - candidate_logp)).sum()),
            'top1_agreement': float(reference_top == candidate_top),
            'top5_overlap': len(reference_topk & candidate_topk) / top_k,
            'spearman': _spearman(reference, candidate),
            'reference_q_rms': float(reference.square().mean().sqrt()),
            'candidate_q_rms': float(candidate.square().mean().sqrt()),
        }
        if selected is not None and selected[index] >= 0:
            position = int((legal == selected[index]).nonzero(as_tuple=False)[0])
            other = torch.cat((reference[:position], reference[position + 1 :]))
            other_candidate = torch.cat((candidate[:position], candidate[position + 1 :]))
            row['reference_selected_rank'] = average_rank_at(reference, position)
            row['candidate_selected_rank'] = average_rank_at(candidate, position)
            row['reference_selected_margin'] = float(reference[position] - other.max()) if other.numel() else None
            row['candidate_selected_margin'] = (
                float(candidate[position] - other_candidate.max()) if other.numel() else None
            )
        if tied is not None and tied[index]:
            expert = torch.tensor(sorted(set(tied[index])), dtype=legal.dtype)
            positions = torch.nonzero((legal[:, None] == expert[None, :]).any(1), as_tuple=False).squeeze(1)
            outside = torch.ones_like(legal, dtype=torch.bool)
            outside[positions] = False
            best_position = positions[int(candidate[positions].argmax())]
            row['candidate_tied_mass'] = float(candidate_logp[positions].exp().sum())
            row['candidate_tied_best_rank'] = average_rank_at(candidate, best_position)
            row['candidate_tied_top1'] = float(candidate_top in set(positions.tolist()))
            if outside.any() and positions.any():
                row['candidate_tied_margin'] = float(candidate[positions].max() - candidate[outside].max())
            else:
                row['candidate_tied_margin'] = None
        rows.append(row)
    return {
        **summarize_policy_rows(rows),
        'groups': group_policy_rows(rows, groups or {}),
    }
