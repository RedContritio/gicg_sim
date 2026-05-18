"""TOML config loader for AZ training runs.

External config pattern: a TOML file declares ``base = "<preset>"`` plus
a nested dict of overrides. The loader picks the preset builder from
``BASE_PRESETS`` and applies the overrides onto the resulting
``AZConfig`` dataclass.

Phase 3c (FU-W4-AZ-rewrite, T3c) — inline from
``training.paradigms.az.legacy.config_loader``. Imports switched to
adapter ``paradigms.az.config`` (consistent with Phase 2 ζ inline of
AZConfig + presets). ``legacy/config_loader.py`` remains alive for the
transitional period (Phase 5 git rm); the only external reference was
``test_config_loader.py`` which is being migrated to this path as part
of T3c batch.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Union

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore

from training.paradigms.az.config import (
    AZConfig,
    fixed_1v1_config,
    random_1v1_config,
    smoke_config,
)


BASE_PRESETS = {
    'smoke': smoke_config,
    'fixed_1v1': fixed_1v1_config,
    'random_1v1': random_1v1_config,
}

# Top-level fields consumed by tools._meta.multi_seed_launch
# (not AZConfig). The post-FU-W2A wrapper passes them through to
# tools.runs.train as overrides instead of stripping, but direct legacy
# loaders (test_config_loader / one-off scripts) hand the raw TOML to
# load_config — drop the fields here so those callers don't have to
# special-case them.
#
# `meta` is the unified-pipeline section (FU-W1B): every cfg now carries
# `[meta] paradigm = "az"`. The legacy AZ loader doesn't consume meta
# (it predates the unified schema), so we strip it here. The unified
# loader at `training.core.config.loader.load_cfg` is the consumer.
_LAUNCHER_ONLY_FIELDS = frozenset({'seeds', 'seed_labels', 'meta'})


def load_config(path: Union[str, Path], data_dir: str = 'data') -> AZConfig:
    """Load a TOML config file into a fully-populated AZConfig."""
    text = Path(path).read_text(encoding='utf-8')
    data: dict[str, Any] = tomllib.loads(text)

    base_name = data.pop('base', 'random_1v1')
    if base_name not in BASE_PRESETS:
        raise ValueError(f'config {path}: unknown base preset {base_name!r}; valid = {sorted(BASE_PRESETS)}')
    for k in _LAUNCHER_ONLY_FIELDS:
        data.pop(k, None)
    cfg = BASE_PRESETS[base_name](data_dir=data_dir)
    _apply_overrides(cfg, data, path=str(path), trail='')
    return cfg


def _apply_overrides(target: Any, overrides: dict, *, path: str, trail: str) -> None:
    """Recursively apply a nested dict of overrides onto a dataclass."""
    if not is_dataclass(target):
        raise TypeError(
            f'config {path}: cannot apply overrides to non-dataclass {type(target).__name__} at {trail or "<root>"}'
        )

    known_fields = {f.name for f in fields(target)}
    for key, val in overrides.items():
        dotted = f'{trail}.{key}' if trail else key
        if key not in known_fields:
            raise ValueError(
                f'config {path}: unknown field {dotted!r}; '
                f'valid fields on {type(target).__name__} = {sorted(known_fields)}'
            )
        if isinstance(val, dict):
            sub = getattr(target, key)
            if is_dataclass(sub):
                _apply_overrides(sub, val, path=path, trail=dotted)
            else:
                # Leaf dict field (e.g. Optional[dict] like deck_padding):
                # the override replaces wholesale instead of merging.
                setattr(target, key, val)
        else:
            setattr(target, key, val)
