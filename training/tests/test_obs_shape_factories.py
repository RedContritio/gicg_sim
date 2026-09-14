"""Tests for training.core.cfg.factories — 4 paradigm-specific ObsShape factories.

Verifies each factory returns an ObsShape with paradigm 历史 d_model +
n_cross_layers defaults, plus shared base shape fields (n_counter_slots
/ n_hooks / max_ops_per_hook / max_actions / dropout).

Spec ref: config-schema/spec.md § 7 N1.2.
"""

from __future__ import annotations

from training.core.cfg import (
    ObsShape,
    make_az_default_shape,
    make_bc_default_shape,
    make_cfr_default_shape,
    make_dmc_default_shape,
)


# Shared base shape fields (per factories.py _BASE_SHAPE_FIELDS).
_BASE_N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16  # 1832
_BASE_N_HOOKS = 900
_BASE_MAX_TOKENS_PER_HOOK = 128
_BASE_MAX_ACTIONS = 2048
_BASE_DROPOUT = 0.0


def _assert_base_shape(shape: ObsShape) -> None:
    """Assert paradigm-shared base fields."""
    assert shape.n_counter_slots == _BASE_N_COUNTER_SLOTS
    assert shape.n_hooks == _BASE_N_HOOKS
    assert shape.max_ops_per_hook == _BASE_MAX_TOKENS_PER_HOOK
    assert shape.max_actions == _BASE_MAX_ACTIONS
    assert shape.dropout == _BASE_DROPOUT


def test_make_az_default_shape_returns_az_defaults():
    """AZ historical default: d_model=128 / n_cross_layers=2."""
    shape = make_az_default_shape()
    assert isinstance(shape, ObsShape)
    _assert_base_shape(shape)
    assert shape.d_model == 128
    assert shape.n_cross_layers == 2


def test_make_bc_default_shape_returns_bc_defaults():
    """BC historical default: d_model=32 / n_cross_layers=1."""
    shape = make_bc_default_shape()
    assert isinstance(shape, ObsShape)
    _assert_base_shape(shape)
    assert shape.d_model == 32
    assert shape.n_cross_layers == 1


def test_make_cfr_default_shape_returns_cfr_defaults():
    """CFR historical default: d_model=64 / n_cross_layers=2."""
    shape = make_cfr_default_shape()
    assert isinstance(shape, ObsShape)
    _assert_base_shape(shape)
    assert shape.d_model == 64
    assert shape.n_cross_layers == 2


def test_make_dmc_default_shape_returns_dmc_defaults():
    """DMC historical default: d_model=32 / n_cross_layers=1."""
    shape = make_dmc_default_shape()
    assert isinstance(shape, ObsShape)
    _assert_base_shape(shape)
    assert shape.d_model == 32
    assert shape.n_cross_layers == 1


def test_factories_return_independent_instances():
    """Each call returns a new instance (ObsShape is frozen but mutability
    not at issue; this guards against accidental shared singleton)."""
    a = make_az_default_shape()
    b = make_az_default_shape()
    assert a is not b


def test_factories_all_return_obs_shape_type():
    """All 4 factories return same dataclass type — unified per N1.1."""
    factories = [
        make_az_default_shape,
        make_bc_default_shape,
        make_cfr_default_shape,
        make_dmc_default_shape,
    ]
    for f in factories:
        assert type(f()) is ObsShape, f'{f.__name__} returned {type(f()).__name__}, expected ObsShape'


def test_factory_d_models_diverge_by_paradigm():
    """d_model defaults are paradigm-specific (preserved from pre-unification)."""
    assert make_az_default_shape().d_model == 128
    assert make_bc_default_shape().d_model == 32
    assert make_cfr_default_shape().d_model == 64
    assert make_dmc_default_shape().d_model == 32
