"""INHERITED_FIELDS registry + resolver + ``derive_seed``.

Spec: config-schema/spec.md §3 CS2.

Single source of truth for cfg fallback chains. New inherited fields
SHALL be added here via OpenSpec change (spec + impl 同步). Only
'device' (fallback) + 'seed' (fallback+derive) currently registered.
"""

from __future__ import annotations

import hashlib
from typing import Any


# Registry of cross-section inheritance. Key paths use dot-notation.
# 'mode' = 'fallback' (simple chain) or 'fallback+derive' (after
# fallback, derive_seed runs to produce per-instance reproducibility).
INHERITED_FIELDS: dict = {
    'device': {
        'mode': 'fallback',
        'hard_default': 'cpu',
        'chains': {
            'pipeline.learner.device': ['meta.device'],
            'pipeline.inference.device': ['meta.device'],
            'pipeline.inference.remote.device': [
                'pipeline.inference.device',
                'meta.device',
            ],
            'eval.inference.device': ['meta.device'],
            'eval.inference.remote.device': [
                'eval.inference.device',
                'meta.device',
            ],
        },
    },
    'seed': {
        'mode': 'fallback+derive',
        'hard_default': None,  # meta.seed required
        'chains': {
            'pipeline.learner.seed': ['__derive(learner)'],
            'pipeline.actor_seed': ['__derive(actor, instance_id)'],
            'eval.scenario_seed': ['__derive(eval_scenario)'],
            'eval.worker_seed': ['__derive(eval_worker, instance_id)'],
        },
    },
}


def derive_seed(master: int, role: str, instance_id: int = 0) -> int:
    """blake2s-based derivation for per-role / per-instance seeding.

    Same (master, role, instance_id) triple → same derived seed →
    reproducibility invariant. Returns positive int32-fitting value."""
    if master is None:
        raise ValueError('derive_seed: master seed is None (meta.seed required)')
    h = hashlib.blake2s(f'{role}/{instance_id}'.encode(), digest_size=4).digest()
    return (int(master) ^ int.from_bytes(h, 'big')) & 0x7FFFFFFF


def _get_nested(d: dict, path: str) -> Any:
    """Return ``d.<a>.<b>.<c>`` or None if any segment missing.
    Distinguish 'segment missing' (returns None) from 'segment present
    but value None' (returns None) — both treated as fallback trigger."""
    cur: Any = d
    for seg in path.split('.'):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _set_nested(d: dict, path: str, value: Any, *, create_intermediate: bool = True) -> bool:
    """Set ``d.<a>.<b>.<c> = value``. When create_intermediate=False,
    returns False (no-op) if any intermediate segment missing. Returns
    True on successful set."""
    segments = path.split('.')
    cur = d
    for seg in segments[:-1]:
        if seg not in cur or not isinstance(cur[seg], dict):
            if not create_intermediate:
                return False
            cur[seg] = {}
        cur = cur[seg]
    cur[segments[-1]] = value
    return True


def _parent_exists(d: dict, path: str) -> bool:
    """Check whether all segments leading up to the leaf exist as dicts."""
    segments = path.split('.')
    cur = d
    for seg in segments[:-1]:
        if not isinstance(cur, dict) or seg not in cur or not isinstance(cur[seg], dict):
            return False
        cur = cur[seg]
    return True


def _resolve_one(cfg: dict, target_path: str, chain: list, hard_default: Any) -> Any:
    """Walk chain until a non-None value found. ``__derive(...)``
    entries trigger ``derive_seed`` with the master seed from
    ``meta.seed``."""
    for step in chain:
        if step.startswith('__derive('):
            args = step[len('__derive(') : -1]
            parts = [p.strip() for p in args.split(',')]
            role = parts[0]
            instance_id = 0
            if len(parts) > 1 and parts[1] == 'instance_id':
                # Caller must inject instance_id at runtime; default 0
                instance_id = 0
            master = _get_nested(cfg, 'meta.seed')
            if master is None:
                raise ValueError(f'inheritance: cannot derive {target_path!r} — meta.seed is None')
            return derive_seed(master, role, instance_id)
        v = _get_nested(cfg, step)
        if v is not None and v != '':
            return v
    return hard_default


def resolve_inheritance(cfg: dict, *, fail_on_unresolved: bool = True) -> dict:
    """Walk INHERITED_FIELDS and fill missing leaf values.

    Mutates a deep-copied cfg dict and returns it. ``fail_on_unresolved``
    raises if a 'device' chain ends with hard_default but every node
    in the chain was explicitly cleared to ''(empty string) — i.e. R5
    'device unresolved' rule."""
    import copy

    out = copy.deepcopy(cfg)

    # R5 early-check: meta.device explicitly cleared (empty string) is
    # an explicit "no fallback" signal; raises rather than silently
    # using the hard_default. Same for any *.device set to '' at the
    # chain root.
    if fail_on_unresolved:
        meta_dev = _get_nested(out, 'meta.device')
        if meta_dev == '':
            raise ValueError(
                "config R5: meta.device='' (empty string) explicit clear — provide a device or remove the field"
            )

    for field_name, registry in INHERITED_FIELDS.items():
        chains = registry['chains']
        hard_default = registry['hard_default']
        for target_path, chain in chains.items():
            # Skip target whose parent path doesn't exist — don't auto-
            # create empty [remote] sections etc. The presence of the
            # parent section IS the toggle for whether the leaf applies.
            if not _parent_exists(out, target_path):
                continue
            existing = _get_nested(out, target_path)
            if existing is not None and existing != '':
                continue  # explicit value wins
            value = _resolve_one(out, target_path, chain, hard_default)
            # R5: explicit empty-string anywhere in chain + no fallback →
            # raise (signal cfg bug rather than silently fall back to 'cpu').
            if field_name == 'device' and value is None and fail_on_unresolved:
                raise ValueError(f'config R5: device unresolved at {target_path!r} (meta.device + chain都被显式置空)')
            _set_nested(out, target_path, value, create_intermediate=False)

    return out
