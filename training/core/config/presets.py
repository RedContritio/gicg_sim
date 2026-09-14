"""Optional name-to-path registry for configuration presets.

The main ``tools.runs.train`` command takes a configuration path and uses
``meta.extends`` for inheritance. This registry remains available to
out-of-band callers and is empty until they register entries.
"""

from __future__ import annotations

# Map a caller-defined name to a repository-relative configuration path.
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
