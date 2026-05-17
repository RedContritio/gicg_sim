"""Cfg inheritance + R1-R7 placement schema tests.

Covers CS2 (device fallback + seed derive) + CS3 (R1-R7 placement) +
CS4 (loader strictness). Each ``pytest.raises`` matches a SHALL invariant.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from training.core.config.inheritance import (
    INHERITED_FIELDS,
    derive_seed,
    resolve_inheritance,
)
from training.core.config.loader import load_cfg
from training.core.config.schema import validate_schema


# ---------- derive_seed ---------- #


def test_derive_seed_deterministic():
    a = derive_seed(42, 'actor', 0)
    b = derive_seed(42, 'actor', 0)
    assert a == b
    assert a >= 0


def test_derive_seed_different_roles():
    a = derive_seed(42, 'actor', 0)
    b = derive_seed(42, 'learner', 0)
    assert a != b


def test_derive_seed_different_instances():
    a = derive_seed(42, 'actor', 0)
    b = derive_seed(42, 'actor', 1)
    assert a != b


def test_derive_seed_master_none_raises():
    with pytest.raises(ValueError, match='master seed'):
        derive_seed(None, 'actor', 0)


# ---------- resolve_inheritance: device fallback ---------- #


def test_device_fallback_from_meta():
    cfg = {
        'meta': {'seed': 1, 'paradigm': 'dmc', 'run_label': 'r', 'device': 'cuda'},
        'pipeline': {'inference': {'placement': 'local'}},
    }
    out = resolve_inheritance(cfg)
    assert out['pipeline']['inference']['device'] == 'cuda'


def test_device_hard_default_cpu():
    cfg = {
        'meta': {'seed': 1, 'paradigm': 'dmc', 'run_label': 'r'},
        'pipeline': {'inference': {'placement': 'local'}},
    }
    out = resolve_inheritance(cfg)
    # meta.device fell through to hard_default cpu
    # then inference.device fell back to meta.device = cpu
    assert out['pipeline']['inference']['device'] == 'cpu'


def test_device_remote_chain():
    cfg = {
        'meta': {'seed': 1, 'paradigm': 'dmc', 'run_label': 'r', 'device': 'cuda'},
        'pipeline': {
            'inference': {
                'placement': 'remote',
                'device': 'cuda:1',
                'remote': {'pool_size': 2, 'max_batch': 64, 'batch_timeout_ms': 2},
            }
        },
    }
    out = resolve_inheritance(cfg)
    # remote.device fallback chain: remote.device → inference.device → meta.device
    assert out['pipeline']['inference']['remote']['device'] == 'cuda:1'


# ---------- INHERITED_FIELDS registry sanity ---------- #


def test_inherited_fields_registry_has_device_and_seed():
    assert 'device' in INHERITED_FIELDS
    assert 'seed' in INHERITED_FIELDS
    assert INHERITED_FIELDS['device']['mode'] == 'fallback'
    assert INHERITED_FIELDS['seed']['mode'] == 'fallback+derive'


# ---------- R1: placement enum ---------- #


def test_r1_placement_missing_raises():
    cfg = _minimal_cfg(extra_pipeline_inference={'version_tag': 'latest'})
    with pytest.raises(ValueError, match='R1'):
        validate_schema(cfg)


def test_r1_placement_bad_enum_raises():
    cfg = _minimal_cfg(extra_pipeline_inference={'placement': 'gpu'})
    with pytest.raises(ValueError, match='R1'):
        validate_schema(cfg)


# ---------- R2: local + remote section coexist ---------- #


def test_r2_local_with_remote_raises():
    cfg = _minimal_cfg(
        extra_pipeline_inference={
            'placement': 'local',
            'remote': {'pool_size': 1, 'max_batch': 1, 'batch_timeout_ms': 1},
        }
    )
    with pytest.raises(ValueError, match='R2'):
        validate_schema(cfg)


# ---------- R3: remote requires remote section + fields ---------- #


def test_r3_remote_missing_section_raises():
    cfg = _minimal_cfg(extra_pipeline_inference={'placement': 'remote'})
    with pytest.raises(ValueError, match='R3'):
        validate_schema(cfg)


def test_r3_remote_missing_field_raises():
    cfg = _minimal_cfg(
        extra_pipeline_inference={
            'placement': 'remote',
            'remote': {'pool_size': 1, 'max_batch': 1},  # missing batch_timeout_ms
        }
    )
    with pytest.raises(ValueError, match='R3'):
        validate_schema(cfg)


# ---------- R4: closed field set ---------- #


def test_r4_unknown_inference_field_raises():
    cfg = _minimal_cfg(
        extra_pipeline_inference={
            'placement': 'local',
            'pool_size': 4,  # typo'd into top-level
        }
    )
    with pytest.raises(ValueError, match='R4'):
        validate_schema(cfg)


# ---------- R5: device unresolved ---------- #


def test_r5_device_explicitly_blank_raises():
    cfg = {
        'meta': {'seed': 1, 'paradigm': 'dmc', 'run_label': 'r', 'device': ''},
        'pipeline': {'inference': {'placement': 'local', 'device': ''}},
        'scenario': {'team_0': ['x'], 'team_1': ['y']},
        'paradigm': {},
    }
    with pytest.raises(ValueError, match='R5'):
        resolve_inheritance(cfg)


# ---------- CS1.2: meta.seed required ---------- #


def test_meta_seed_missing_raises():
    cfg = {
        'meta': {'paradigm': 'dmc', 'run_label': 'r'},
        'pipeline': {},
        'scenario': {'team_0': ['x'], 'team_1': ['y']},
        'paradigm': {},
    }
    with pytest.raises(ValueError, match='seed'):
        validate_schema(cfg)


# ---------- CS1.3: paradigm enum ---------- #


def test_paradigm_unknown_raises():
    cfg = _minimal_cfg(paradigm='deep_q')
    with pytest.raises(ValueError, match='paradigm'):
        validate_schema(cfg)


# ---------- CS4.1: unknown top-level key ---------- #


def test_unknown_top_level_raises():
    cfg = _minimal_cfg(extra={'unknown_segment': {}})
    with pytest.raises(ValueError, match='unknown top-level'):
        validate_schema(cfg)


# ---------- load_cfg end-to-end ---------- #


def test_load_cfg_smoke(tmp_path):
    # cfg-toml-restructure-paradigm-scoped N6: hybrid [paradigm.<name>.X] structure.
    p = tmp_path / 'cfg.toml'
    p.write_text(
        """
[meta]
seed = 42
paradigm = "dmc"
run_label = "smoke"

[pipeline]
mode = "serial"
[pipeline.inference]
placement = "local"

[scenario]
team_0 = ["凯亚"]
team_1 = ["凯亚"]

[paradigm.dmc]
lr = 0.0001
""",
        encoding='utf-8',
    )
    cfg = load_cfg(p)
    assert cfg.meta.seed == 42
    assert cfg.meta.paradigm == 'dmc'
    assert cfg.pipeline.inference.placement == 'local'
    assert cfg.pipeline.inference.device == 'cpu'  # fallback from meta hard_default


def test_load_cfg_extends_chain(tmp_path):
    # cfg-toml-restructure-paradigm-scoped N6: hybrid [paradigm.<name>.X] structure.
    base = tmp_path / 'base.toml'
    base.write_text(
        """
[meta]
seed = 7
paradigm = "dmc"
run_label = "base"

[pipeline]
mode = "serial"
[pipeline.inference]
placement = "local"

[scenario]
team_0 = ["a"]
team_1 = ["b"]

[paradigm.dmc]
lr = 0.001
""",
        encoding='utf-8',
    )
    child = tmp_path / 'child.toml'
    child.write_text(
        """
[meta]
extends = "base.toml"
seed = 100
paradigm = "dmc"
run_label = "child"

[paradigm.dmc]
lr = 0.0001
""",
        encoding='utf-8',
    )
    cfg = load_cfg(child)
    assert cfg.meta.seed == 100  # child overrides
    assert cfg.paradigm['lr'] == 0.0001  # child overrides
    assert cfg.scenario.team_0 == ['a']  # inherited from base


# ---------- helpers ---------- #


def _minimal_cfg(
    *,
    paradigm: str = 'dmc',
    extra_pipeline_inference: dict | None = None,
    extra: dict | None = None,
) -> dict:
    cfg = {
        'meta': {'seed': 1, 'paradigm': paradigm, 'run_label': 'r', 'device': 'cpu'},
        'pipeline': {'mode': 'serial'},
        'scenario': {'team_0': ['x'], 'team_1': ['y']},
        'paradigm': {},
    }
    if extra_pipeline_inference is not None:
        cfg['pipeline']['inference'] = extra_pipeline_inference
    if extra:
        cfg.update(extra)
    return cfg
