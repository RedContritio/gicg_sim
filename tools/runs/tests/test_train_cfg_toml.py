"""Tests for tools.runs._train.cfg_toml — hand-rolled stdlib TOML emitter.

Standalone unit tests for the emitter, separate from the Phase B
end-to-end tests in test_train_cfg_metadata.py — emitter is pure
function with no Phase A / Phase B coupling, so isolated coverage
keeps the diagnostic radius small when an emit bug surfaces.

Real-cfg round-trip coverage (deck_padding inline table, bools,
floats, override, extends) lives in test_train_cfg_metadata.py
exercised via phase_b_write_cfg_metadata. This file focuses on the
emitter's edge cases (empty dict, bad key types, unsupported values).
"""

from __future__ import annotations

import sys

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from tools.runs._train import cfg_toml


def test_emitter_round_trips_empty_dict() -> None:
    text = cfg_toml.dict_to_toml({})
    assert tomllib.loads(text) == {}


def test_emitter_round_trips_nested_dict() -> None:
    src = {'a': {'b': {'c': 1, 'd': 'x'}, 'e': True}, 'f': 2.5}
    text = cfg_toml.dict_to_toml(src)
    assert tomllib.loads(text) == src


def test_emitter_rejects_non_string_key() -> None:
    with pytest.raises(TypeError, match='cfg key'):
        cfg_toml.dict_to_toml({1: 'x'})  # type: ignore[dict-item]


def test_emitter_rejects_empty_string_key() -> None:
    with pytest.raises(ValueError, match='cannot be empty'):
        cfg_toml.dict_to_toml({'': 'x'})


def test_emitter_rejects_unsupported_value_type() -> None:
    with pytest.raises(TypeError, match='not supported'):
        cfg_toml.dict_to_toml({'k': object()})


def test_emitter_rejects_list_of_dict_array_of_table() -> None:
    """Spec note in cfg_toml.py — array-of-table not in cfg shape;
    explicit raise rather than silent mis-emit."""
    with pytest.raises(TypeError, match='array-of-table'):
        cfg_toml.dict_to_toml({'tbls': [{'a': 1}, {'b': 2}]})


def test_emitter_handles_negative_and_zero_numbers() -> None:
    src = {'a': -42, 'b': 0, 'c': -3.14, 'd': 0.0}
    text = cfg_toml.dict_to_toml(src)
    assert tomllib.loads(text) == src


def test_emitter_handles_unicode_strings() -> None:
    src = {'meta': {'note': '赤蝶 vs 墨客'}}
    text = cfg_toml.dict_to_toml(src)
    assert tomllib.loads(text) == src


def test_emitter_handles_bools_int_distinction() -> None:
    """bool is subclass of int — emitter must check bool branch first."""
    src = {'flag': True, 'count': 1}
    text = cfg_toml.dict_to_toml(src)
    assert 'flag = true' in text
    assert 'count = 1' in text
    assert tomllib.loads(text) == src


def test_emitter_float_keeps_decimal_point() -> None:
    """``3.0`` must emit as ``3.0`` not ``3`` — else re-parse gives int."""
    src = {'x': 3.0}
    text = cfg_toml.dict_to_toml(src)
    reparsed = tomllib.loads(text)
    assert reparsed == src
    assert isinstance(reparsed['x'], float)


def test_emitter_string_escapes() -> None:
    src = {'k': 'has "quotes" and \\backslash and\nnewline\ttab'}
    text = cfg_toml.dict_to_toml(src)
    assert tomllib.loads(text) == src


def test_emitter_homogeneous_list_of_scalars() -> None:
    src = {'pool': ['v_legacy', 'test_basic'], 'nums': [1, 2, 3]}
    text = cfg_toml.dict_to_toml(src)
    assert tomllib.loads(text) == src


def test_emitter_deeply_nested_tables() -> None:
    """Multi-level nesting — paradigm.az.mcts.dirichlet_alpha pattern."""
    src = {'paradigm': {'az': {'mcts': {'n_rollouts': 200, 'c_puct': 1.4}}}}
    text = cfg_toml.dict_to_toml(src)
    assert tomllib.loads(text) == src
    # Verify header form.
    assert '[paradigm.az.mcts]' in text


def test_emitter_quoted_key_for_non_bare_chars() -> None:
    """Keys with chars outside [A-Za-z0-9_-] get quoted."""
    src = {'k.with.dots': 1}
    text = cfg_toml.dict_to_toml(src)
    assert tomllib.loads(text) == src
