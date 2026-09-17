"""Offline mechanism diagnostics for the policy-retention arms."""

import argparse
import hashlib
import json
from pathlib import Path

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.paired_training import assess
from tools.experiments.semantic_training.policy_retention import initialize_rule_head, load_teacher_rows
from tools.experiments.semantic_training.retention_gradients import gradient_geometry
from tools.experiments.semantic_training.retention_metrics import (
    action_kind_name,
    masked_q,
    policy_probe,
    update_report,
)
from training.core.artifact_io import load_checkpoint
from training.core.network import AgentConfig


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_policy(path, device='cpu'):
    payload = load_checkpoint(path, map_location='cpu', weights_only=False)
    agent = SemanticAgent(AgentConfig(**payload['shape']), device)
    agent.net.load_state_dict(payload['net'], strict=True)
    if 'rule_head' in payload:
        initialize_rule_head(agent, 0).load_state_dict(payload['rule_head'], strict=True)
    return agent, payload


def _parse_checkpoint(value):
    if '=' not in value:
        raise argparse.ArgumentTypeError('checkpoint must be NAME=PATH')
    name, path = value.split('=', 1)
    if not name or not path:
        raise argparse.ArgumentTypeError('checkpoint must be NAME=PATH')
    return name, Path(path)


def run(args):
    torch.set_num_threads(args.threads)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    pairs = torch.load(args.pairs, weights_only=False)
    teacher = load_teacher_rows(args.teacher, args.teacher_rows, args.seed)
    if args.gradient_only:
        report = {
            'scope': 'offline gradient diagnostic; not a strength evaluation',
            'seed': args.seed,
            'teacher_rows': len(teacher),
            'arms': {},
        }
        selected = set(args.gradient_states.split(',')) if args.gradient_states else set()
        if 'warmup' in selected:
            reference, payload = load_policy(args.warmup)
            if 'rule_head' not in payload:
                initialize_rule_head(reference, args.seed)
            report['arms']['warmup'] = gradient_geometry(reference, pairs, teacher)
        for name, path in args.checkpoint:
            if name in selected:
                agent, payload = load_policy(path)
                if 'rule_head' not in payload:
                    raise ValueError(f'checkpoint {name!r} has no rule_head; gradient geometry is unavailable')
                report['arms'][name] = gradient_geometry(agent, pairs, teacher)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    pair_rows = [row for pair in pairs for row in pair['rows']]
    pair_observations = [row['obs'] for row in pair_rows]
    selected = [row['action'] for row in pair_rows]
    pair_groups = {
        'parameter': [pair['parameter'] for pair in pairs for _ in pair['rows']],
        'kind': [pair['kind'] for pair in pairs for _ in pair['rows']],
        'field': [pair['field'] for pair in pairs for _ in pair['rows']],
        'character': [pair['character'] for pair in pairs for _ in pair['rows']],
        'action_kind': [action_kind_name(row['obs'], row['action']) for row in pair_rows],
    }
    teacher_observations = [row['obs'] for row in teacher]
    tied = [row['tied'] for row in teacher]
    teacher_groups = {
        'executed_action': [action_kind_name(row['obs'], row['executed_action']) for row in teacher],
    }
    reference, reference_payload = load_policy(args.warmup)
    if 'rule_head' not in reference_payload:
        initialize_rule_head(reference, args.seed)
    reference_pair_q, reference_pair_mask = masked_q(reference, pair_observations, args.batch_size)
    reference_teacher_q, reference_teacher_mask = masked_q(reference, teacher_observations, args.batch_size)
    report = {
        'scope': 'offline mechanism diagnostic; not a strength evaluation',
        'seed': args.seed,
        'teacher_rows': len(teacher),
        'pair_rows': len(pair_rows),
        'temperature': args.temperature,
        'warmup': {'path': str(args.warmup), 'sha256': digest(args.warmup)},
        'arms': {},
    }
    states = {}
    for name, path in args.checkpoint:
        print(f'{name}: loading', flush=True)
        agent, payload = load_policy(path)
        states[name] = {
            'path': str(path),
            'sha256': digest(path),
            'format': payload.get('format'),
            'update': update_report(reference_payload['net'], payload['net']),
            'rule': assess(agent, pairs) if 'rule_head' in payload else None,
        }
        candidate_pair_q, candidate_pair_mask = masked_q(agent, pair_observations, args.batch_size)
        candidate_teacher_q, candidate_teacher_mask = masked_q(agent, teacher_observations, args.batch_size)
        states[name]['pairs'] = policy_probe(
            reference_pair_q,
            reference_pair_mask,
            candidate_pair_q,
            candidate_pair_mask,
            selected=selected,
            groups=pair_groups,
            temperature=args.temperature,
        )
        states[name]['teacher'] = policy_probe(
            reference_teacher_q,
            reference_teacher_mask,
            candidate_teacher_q,
            candidate_teacher_mask,
            tied=tied,
            groups=teacher_groups,
            temperature=args.temperature,
        )
        print(f'{name}: functional probe complete', flush=True)
    selected_gradient_states = set(args.gradient_states.split(',')) if args.gradient_states else set()
    if 'warmup' in selected_gradient_states:
        print('warmup: gradient geometry', flush=True)
        report['arms']['warmup'] = {
            'path': str(args.warmup),
            'sha256': digest(args.warmup),
            'gradients': gradient_geometry(reference, pairs, teacher),
        }
    for name, path in args.checkpoint:
        if name in selected_gradient_states:
            print(f'{name}: gradient geometry', flush=True)
            agent, payload = load_policy(path)
            if 'rule_head' not in payload:
                raise ValueError(f'checkpoint {name!r} has no rule_head; gradient geometry is unavailable')
            states[name]['gradients'] = gradient_geometry(agent, pairs, teacher)
    report['arms'].update(states)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(
        json.dumps(
            {
                name: {
                    'drift': row['update']['groups'],
                    'pairs': row['pairs'],
                    'teacher': row['teacher'],
                    **({'gradients': row['gradients']} if 'gradients' in row else {}),
                }
                for name, row in states.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('warmup', type=Path)
    parser.add_argument('pairs', type=Path)
    parser.add_argument('teacher', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--checkpoint', action='append', type=_parse_checkpoint, required=True)
    parser.add_argument('--gradient-states', default='warmup')
    parser.add_argument('--teacher-rows', type=int, default=512)
    parser.add_argument('--seed', type=int, default=95000)
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--temperature', type=float, default=0.5)
    parser.add_argument('--gradient-only', action='store_true')
    run(parser.parse_args())
