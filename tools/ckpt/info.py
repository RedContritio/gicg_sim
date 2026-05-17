"""tools.ckpt.info — inspect ckpt metadata without loading nn.Module.

Usage:
    .venv/bin/python -m tools.ckpt.info <path>

Output (human-readable):
    paradigm:        az
    cfg_version:     1.0.0
    schema_version:  2
    net_kind:        ActorCritic
    git_commit:      abc123def
    created_at:      2026-05-17T14:23:11+08:00
    state_dict_keys: 87 keys (sample: hook_encoder.token_embed.weight ...)
    cfg:
        n_counter_slots: 256
        n_hooks: 32
        ...

Exit codes:
    0  - success
    1  - ckpt file missing or unreadable
    2  - ckpt uses pre-redesign schema (no schema_version key); needs retrain
        or git checkout pre-core-network-redesign-2026-05-17 for old loader
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch


def _format_cfg(cfg_dict: dict, indent: int = 4) -> str:
    """Pretty-print cfg dict with consistent indentation."""
    if not cfg_dict:
        return ' ' * indent + '(empty)'
    lines = []
    for k, v in sorted(cfg_dict.items()):
        lines.append(f'{" " * indent}{k}: {v!r}')
    return '\n'.join(lines)


def _format_state_dict_summary(state_dict, max_keys_shown: int = 5) -> str:
    """Summary line:'87 keys (sample: k1 ... k5)'."""
    keys = list(state_dict.keys())
    n = len(keys)
    sample = ' / '.join(keys[:max_keys_shown])
    if n > max_keys_shown:
        sample += f' ... ({n - max_keys_shown} more)'
    return f'{n} keys (sample: {sample})'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='tools.ckpt.info', description=__doc__.split('\n\n')[0])
    parser.add_argument('path', type=str, help='ckpt file path (.pt)')
    parser.add_argument(
        '--show-cfg',
        action='store_true',
        default=True,
        help='show cfg dict (default true)',
    )
    parser.add_argument(
        '--no-show-cfg',
        action='store_false',
        dest='show_cfg',
        help='suppress cfg dict (just metadata)',
    )
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f'error: {path} not found', file=sys.stderr)
        return 1

    try:
        blob = torch.load(str(path), weights_only=True, map_location='cpu')
    except Exception as e:
        print(f'error: failed to torch.load {path}: {e}', file=sys.stderr)
        return 1

    if not isinstance(blob, dict):
        print(f'error: {path} root is not dict (got {type(blob).__name__})', file=sys.stderr)
        return 2

    if 'schema_version' not in blob:
        print(
            f'error: {path} uses pre-redesign ckpt schema (no schema_version key).\n'
            f'  This ckpt was saved before core-network-generic-promotion Phase 0 (2026-05-17);\n'
            f'  Phase 0 archived/removed all pre-redesign ckpts.\n'
            f'  To inspect old ckpts: git checkout pre-core-network-redesign-2026-05-17',
            file=sys.stderr,
        )
        return 2

    print(f'path:            {path}')
    print(f'schema_version:  {blob.get("schema_version", "?")}')
    print(f'paradigm:        {blob.get("paradigm", "unknown")}')
    print(f'cfg_version:     {blob.get("cfg_version", "?")}')
    print(f'net_kind:        {blob.get("net_kind", "?")}')
    print(f'git_commit:      {blob.get("git_commit", "unknown")}')
    print(f'created_at:      {blob.get("created_at", "?")}')

    if 'net_state_dict' in blob:
        print(f'state_dict:      {_format_state_dict_summary(blob["net_state_dict"])}')

    if args.show_cfg and 'cfg' in blob:
        print('cfg:')
        print(_format_cfg(blob['cfg']))

    return 0


if __name__ == '__main__':
    sys.exit(main())
