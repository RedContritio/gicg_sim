"""Tests for training.core.cfg — ObsShape + ParadigmConfigBase contract.

Post cfg-schema-unification:
- ParadigmConfigBase no longer has `shape` field (CC-203);subclass provides
  shape via paradigm-local `agent: ObsShape` field.
- Base only carries `version` + `paradigm` metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from training.core.cfg import ObsShape, ParadigmConfigBase


def test_obs_shape_required_fields():
    s = ObsShape(n_counter_slots=10, n_hooks=4, max_tokens_per_hook=8, max_actions=16)
    assert s.n_counter_slots == 10
    assert s.n_hooks == 4
    assert s.max_tokens_per_hook == 8
    assert s.max_actions == 16
    assert s.d_model == 128
    assert s.dropout == 0.0
    assert s.n_cross_layers == 2


def test_obs_shape_frozen():
    s = ObsShape(n_counter_slots=10, n_hooks=4, max_tokens_per_hook=8, max_actions=16)
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        s.n_counter_slots = 99  # type: ignore


def test_obs_shape_d_model_override():
    s = ObsShape(
        n_counter_slots=10,
        n_hooks=4,
        max_tokens_per_hook=8,
        max_actions=16,
        d_model=64,
        n_cross_layers=3,
        dropout=0.2,
    )
    assert s.d_model == 64
    assert s.n_cross_layers == 3
    assert s.dropout == 0.2


def test_paradigm_config_base_defaults():
    """Base only carries version + paradigm (CC-203 no shape field)."""
    cfg = ParadigmConfigBase()
    assert cfg.version == '1.0.0'
    assert cfg.paradigm == ''
    # No `shape` field on base — subclass provides via `agent`.
    assert not hasattr(cfg, 'shape')


def test_paradigm_config_base_compose_via_subclass():
    """Subclass overrides paradigm + adds own shape field (e.g. agent)."""

    @dataclass(frozen=True)
    class MyParadigmConfig(ParadigmConfigBase):
        paradigm: str = 'my_paradigm'
        agent: ObsShape = field(
            default_factory=lambda: ObsShape(
                n_counter_slots=16,
                n_hooks=4,
                max_tokens_per_hook=8,
                max_actions=10,
            )
        )

    cfg = MyParadigmConfig()
    assert cfg.paradigm == 'my_paradigm'
    assert cfg.version == '1.0.0'
    assert cfg.agent.n_counter_slots == 16


def test_paradigm_config_version_override():
    @dataclass(frozen=True)
    class V2Config(ParadigmConfigBase):
        version: str = '2.0.0'
        paradigm: str = 'v2_paradigm'

    cfg = V2Config()
    assert cfg.version == '2.0.0'
