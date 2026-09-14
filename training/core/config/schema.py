"""Placement and top-level configuration validation.

Spec: config-schema/spec.md §3 CS3 (R1-R7) + CS4 (loader strictness).

Each rule raises ValueError with field path + expected vs actual.
Validator runs AFTER ``resolve_inheritance``; the device-resolve raise
is owned by ``inheritance.resolve_inheritance`` itself (R5).
"""

from __future__ import annotations

from typing import Any

from training.core.config.base import (
    DEVICE_VALUES_PREFIX,
    PARADIGM_VALUES,
    PLACEMENT_VALUES,
)


# Allowed top-level segments of the TOML cfg.
# ``shape`` is the shared ObsShape section merged into paradigm.agent by
# ``load_paradigm_cfg``. ``remote`` is validated by
# ``tools.runs._host.load_remote_from_cfg``.
ALLOWED_TOP_LEVEL = {
    'meta',
    'pipeline',
    'eval',
    'scenario',
    'paradigm',
    'checkpoint',
    'shape',
    'remote',
    'debug',
    'runtime',
}

# Closed field set per InferenceCfg (R4).
INFERENCE_FIELDS = {'placement', 'device', 'version_tag', 'remote'}
REMOTE_REQUIRED_FIELDS = {'pool_size', 'max_batch', 'batch_timeout_ms'}
REMOTE_ALLOWED_FIELDS = REMOTE_REQUIRED_FIELDS | {'device', 'socket_path'}


def _is_valid_device(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if value in ('cpu', 'mps'):
        return True
    if value.startswith('cuda'):
        # 'cuda' or 'cuda:0' / 'cuda:1' / ...
        rest = value[4:]
        return rest == '' or (rest.startswith(':') and rest[1:].isdigit())
    return False


def _check_inference_cfg(inf_dict: dict, path: str) -> None:
    """R1-R4 + R7 placement section validation."""
    if not isinstance(inf_dict, dict):
        raise ValueError(f'config R7: {path} must be a section,got {type(inf_dict).__name__}')

    # R4 closed field set
    extra = set(inf_dict.keys()) - INFERENCE_FIELDS
    if extra:
        raise ValueError(f'config R4: unknown field in {path}: {sorted(extra)} (allowed: {sorted(INFERENCE_FIELDS)})')

    # R1 placement required + enum
    if 'placement' not in inf_dict:
        raise ValueError(f'config R1: {path}.placement required (enum {PLACEMENT_VALUES})')
    placement = inf_dict['placement']
    if placement not in PLACEMENT_VALUES:
        raise ValueError(f'config R1: {path}.placement = {placement!r} not in {PLACEMENT_VALUES}')

    # R2/R3 placement ⟺ remote section presence + content
    remote = inf_dict.get('remote')
    if placement == 'local':
        if remote is not None:
            raise ValueError(
                f"config R2: {path}.placement='local' but [{path}.remote] section present — remove the section或改 placement='remote'"
            )
    else:  # 'remote'
        if remote is None:
            raise ValueError(f"config R3: {path}.placement='remote' but [{path}.remote] section missing")
        if not isinstance(remote, dict):
            raise ValueError(f'config R3: {path}.remote must be a section')
        extra_r = set(remote.keys()) - REMOTE_ALLOWED_FIELDS
        if extra_r:
            raise ValueError(
                f'config R3: unknown field in {path}.remote: {sorted(extra_r)} '
                f'(allowed: {sorted(REMOTE_ALLOWED_FIELDS)})'
            )
        missing = REMOTE_REQUIRED_FIELDS - set(remote.keys())
        if missing:
            raise ValueError(f'config R3: {path}.remote missing required: {sorted(missing)}')

    # device value sanity (after resolve_inheritance fills it)
    if 'device' in inf_dict and inf_dict['device'] is not None:
        if not _is_valid_device(inf_dict['device']):
            raise ValueError(f'config: {path}.device = {inf_dict["device"]!r} invalid (cpu/cuda[:N]/mps)')


def _check_meta(cfg: dict) -> None:
    if 'meta' not in cfg:
        raise ValueError('config CS1.1: [meta] section required')
    meta = cfg['meta']
    if not isinstance(meta, dict):
        raise ValueError('config: [meta] must be a section')

    if 'seed' not in meta or meta['seed'] is None:
        raise ValueError('config CS1.2: meta.seed required (no hard default)')
    if not isinstance(meta['seed'], int):
        raise ValueError(f'config: meta.seed must be int,got {type(meta["seed"]).__name__}')

    if 'paradigm' not in meta:
        raise ValueError('config CS1.3: meta.paradigm required')
    if meta['paradigm'] not in PARADIGM_VALUES:
        raise ValueError(f'config CS1.3: meta.paradigm = {meta["paradigm"]!r} not in {PARADIGM_VALUES}')

    if 'run_label' not in meta:
        raise ValueError('config: meta.run_label required')

    if 'device' in meta and not _is_valid_device(meta['device']):
        raise ValueError(f'config CS1.4: meta.device = {meta["device"]!r} invalid (cpu/cuda[:N]/mps)')


def _check_pipeline(cfg: dict) -> None:
    if 'pipeline' not in cfg:
        raise ValueError('config CS1.1: [pipeline] section required')
    pipe = cfg['pipeline']
    if 'mode' in pipe and pipe['mode'] not in ('serial', 'async'):
        raise ValueError(f"config: pipeline.mode = {pipe['mode']!r} not in ('serial','async')")

    if 'inference' in pipe:
        _check_inference_cfg(pipe['inference'], 'pipeline.inference')


def _check_eval(cfg: dict) -> None:
    pipe_mode = cfg.get('pipeline', {}).get('mode', 'serial')
    if 'eval' in cfg:
        if 'inference' in cfg['eval']:
            _check_inference_cfg(cfg['eval']['inference'], 'eval.inference')
    elif pipe_mode == 'async':
        raise ValueError("config CS1.1: pipeline.mode='async' requires [eval] section")


def _check_scenario(cfg: dict) -> None:
    if 'scenario' not in cfg:
        raise ValueError('config CS1.1: [scenario] section required')
    sc = cfg['scenario']
    if 'team_0' not in sc or 'team_1' not in sc:
        raise ValueError('config: scenario.team_0 + scenario.team_1 required')
    if not isinstance(sc['team_0'], list) or not isinstance(sc['team_1'], list):
        raise ValueError('config: scenario.team_{0,1} must be list[str]')


def _check_paradigm(cfg: dict) -> None:
    if 'paradigm' not in cfg:
        raise ValueError('config CS1.1: [paradigm] section required (paradigm-specific schema)')
    if not isinstance(cfg['paradigm'], dict):
        raise ValueError('config: [paradigm] must be a section')


def _check_top_level_keys(cfg: dict) -> None:
    extra = set(cfg.keys()) - ALLOWED_TOP_LEVEL
    if extra:
        raise ValueError(
            f'config CS4.1: unknown top-level segment(s): {sorted(extra)} (allowed: {sorted(ALLOWED_TOP_LEVEL)})'
        )


def validate_schema(cfg: dict) -> None:
    """Validate top-level, required, and placement fields.

    The caller should first run ``resolve_inheritance`` (R5). Extends
    placement synchronization (R6) is checked while loading parents.
    """
    _check_top_level_keys(cfg)
    _check_meta(cfg)
    _check_pipeline(cfg)
    _check_eval(cfg)
    _check_scenario(cfg)
    _check_paradigm(cfg)


def check_extends_placement_sync(parent_inf: Any, child_inf: Any, path: str) -> None:
    """Require an extends placement override to update its remote block.

    ``parent_inf`` and ``child_inf`` are the unmerged inference mappings.
    The loader calls this before merging to catch a child that sets
    placement='remote' but did not provide [remote] block."""
    if not isinstance(child_inf, dict) or 'placement' not in child_inf:
        return  # child didn't override placement
    parent_placement = parent_inf.get('placement') if isinstance(parent_inf, dict) else None
    if child_inf['placement'] == parent_placement:
        return  # no override
    # placement changed — child MUST supply the matching remote block (or
    # explicitly remove it for placement='local').
    if child_inf['placement'] == 'remote' and 'remote' not in child_inf:
        raise ValueError(f"config R6: {path}.placement changed to 'remote' in child cfg but no [remote] block provided")
    if child_inf['placement'] == 'local' and 'remote' in child_inf:
        raise ValueError(f"config R6: {path}.placement changed to 'local' in child but [remote] block still present")
