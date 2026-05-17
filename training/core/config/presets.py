"""Cfg preset registry — names → preset cfg path.

Used by ``tools/run.py --preset <name>``. Presets are normal TOML
files under ``configs/presets/`` (path resolved via this registry).
Spec ref: config-schema/spec.md §2 'Cfg presets out of scope for the
spec; path-anchored here'.
"""

from __future__ import annotations

# Map preset name → relative path under repo root. P3-A registers an
# empty set; P3-B+ paradigms add their own (e.g. 'dmc-smoke',
# 'dmc-prod-async'). User cfgs typically use ``extends`` to chain in.
PRESETS: dict = {}


def register_preset(name: str, path: str) -> None:
    """Add a preset. Raises if duplicated to surface naming collisions."""
    if name in PRESETS:
        raise ValueError(f'preset: {name!r} already registered to {PRESETS[name]!r}')
    PRESETS[name] = path


def resolve_preset(name: str) -> str:
    """Return cfg path for a preset name. Raises if unknown."""
    if name not in PRESETS:
        raise ValueError(f'preset: unknown name {name!r} (known: {sorted(PRESETS)})')
    return PRESETS[name]
