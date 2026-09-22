"""Average structurally compatible semantic checkpoints for inference."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

import torch

from training.core.artifact_io import load_checkpoint, save_checkpoint
from tools.experiments.semantic_training.player_loader import (
    CONSEQUENCE_FORMAT,
    FORMAT,
)


_FORMATS = {FORMAT, CONSEQUENCE_FORMAT}
_TRAINING_KEYS = {
    'optimizer',
    'value_optimizer',
    'rule_optimizer',
    'rng',
    'torch_rng',
    'cuda_rng',
    'baseline',
    'iteration',
}


def _same_structure(left: Mapping, right: Mapping, label: str) -> None:
    if left.keys() != right.keys():
        raise ValueError(f'{label} keys differ')
    for key in left:
        first, second = left[key], right[key]
        if not isinstance(first, torch.Tensor) or not isinstance(second, torch.Tensor):
            raise ValueError(f'{label}[{key!r}] must be a tensor')
        if first.shape != second.shape or first.dtype != second.dtype:
            raise ValueError(f'{label}[{key!r}] shape or dtype differs')


def _average_states(states: list[Mapping], label: str) -> dict:
    result = {}
    for key in states[0]:
        values = [state[key] for state in states]
        if values[0].is_floating_point() or values[0].is_complex():
            total = torch.zeros_like(values[0], dtype=torch.float64)
            for value in values:
                total.add_(value.to(dtype=torch.float64))
            result[key] = (total / len(values)).to(dtype=values[0].dtype)
        elif all(torch.equal(value, values[0]) for value in values[1:]):
            result[key] = values[0].clone()
        else:
            raise ValueError(f'{label}[{key!r}] is non-floating and differs')
    return result


def average_payloads(payloads: list[Mapping]) -> dict:
    if len(payloads) < 2:
        raise ValueError('at least two checkpoints are required')
    for index, payload in enumerate(payloads):
        if not isinstance(payload, Mapping) or not all(key in payload for key in ('format', 'shape', 'net')):
            raise ValueError(f'checkpoint {index} is missing semantic envelope fields')
    first = payloads[0]
    if first.get('format') not in _FORMATS:
        raise ValueError(f'unsupported semantic checkpoint format: {first.get("format")!r}')
    for index, payload in enumerate(payloads[1:], 1):
        if payload.get('format') != first['format']:
            raise ValueError(f'checkpoint {index} format differs')
        if payload.get('shape') != first.get('shape'):
            raise ValueError(f'checkpoint {index} shape differs')
        _same_structure(first['net'], payload['net'], 'net')
        if ('value_head' in first) != ('value_head' in payload):
            raise ValueError('value_head must be present in every checkpoint or none')
        if 'value_head' in first:
            _same_structure(first['value_head'], payload['value_head'], 'value_head')
        if payload.get('value_encoding', 'signed_outcome') != first.get('value_encoding', 'signed_outcome'):
            raise ValueError(f'checkpoint {index} value encoding differs')
    averaged = {
        key: value
        for key, value in first.items()
        if key not in {'net', 'value_head', *_TRAINING_KEYS, '_training_provenance'}
    }
    averaged['net'] = _average_states([payload['net'] for payload in payloads], 'net')
    if 'value_head' in first:
        averaged['value_head'] = _average_states([payload['value_head'] for payload in payloads], 'value_head')
        averaged['value_encoding'] = first.get('value_encoding', 'signed_outcome')
    return averaged


def average_checkpoints(inputs: list[Path], output: Path, *, verify_provenance: bool = True) -> dict:
    if len(inputs) != 4:
        raise ValueError('exactly four checkpoints are required')
    payloads = [
        load_checkpoint(path, map_location='cpu', weights_only=False, verify_provenance=verify_provenance)
        for path in inputs
    ]
    result = average_payloads(payloads)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint(result, output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs=4, type=Path, metavar='CHECKPOINT')
    parser.add_argument('-o', '--output', required=True, type=Path)
    parser.add_argument('--allow-unverified', action='store_true')
    args = parser.parse_args()
    average_checkpoints(args.inputs, args.output, verify_provenance=not args.allow_unverified)
    print(args.output)


if __name__ == '__main__':
    main()
