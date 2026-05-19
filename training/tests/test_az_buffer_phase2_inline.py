"""Phase-2 T2.5 inline-copy verification for paradigms/az/buffer.py.

This test guards the AZ Phase 2 (az-paradigm-rewrite) invariant: the
adapter ``training.paradigms.az.buffer`` must self-contain
``ReplayBuffer`` rather than re-exporting from
``training.paradigms.az.legacy.buffer``. Three checks:

1. Static: ``ReplayBuffer`` resolves from the adapter symbol path.
2. AST: the adapter source does NOT contain an
   ``import ... legacy.buffer`` line.
3. Smoke: instantiate ReplayBuffer, add a trajectory, sample back —
   round-trip works without going through legacy.

T2.11 verify scope: ``adapter has zero ``from training.paradigms.az.legacy``
imports``. We assert it inline so a regression flips this test red.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import random

import numpy as np
import pytest

from training.paradigms.az import buffer as adapter_buffer_mod
from training.paradigms.az.buffer import ReplayBuffer
from training.tests._typed_obs_fixtures import (
    make_modifier_log_padding_np as _make_modifier_log_padding,
    make_recent_damage_padding_np as _make_recent_damage_padding,
)


def _fake_static(n_slots=64, n_hooks=4, max_ops=8, fields_per_op=5):
    return {
        'hook_ir': np.random.randint(1, 14, (n_hooks, max_ops, fields_per_op), dtype=np.int64),
        'hook_mask': np.ones(n_hooks, dtype=bool),
        'counter_sids': np.arange(n_slots, dtype=np.int64),
        'active_slot_mask': np.ones(n_slots, dtype=bool),
        'char_skill_refs': -np.ones((2, 6, 10), dtype=np.int64),
    }


def _fake_step(*, n_slots=64, max_actions=4, n_legal=2, z=0.0, is_discovery=False):
    pi = np.zeros(max_actions, dtype=np.float32)
    pi[:n_legal] = 1.0 / n_legal
    legal = np.zeros(max_actions, dtype=bool)
    legal[:n_legal] = True
    return {
        'counter_values': np.random.randn(n_slots).astype(np.float32),
        'counter_target': np.random.randn(n_slots).astype(np.float32),
        'has_counter_target': True,
        'meta': np.array([3.0, 1.0, 1.0], dtype=np.float32),
        'card_buckets': np.zeros((4, 80), dtype=np.float32),
        'enemy_sizes': np.zeros(2, dtype=np.float32),
        'recent_damage': _make_recent_damage_padding(),
        'prepare_skill': np.full((2, 2), -1.0, dtype=np.float32),
        'modifier_log': _make_modifier_log_padding(),
        'action_refs': np.full((max_actions, 3), -1, dtype=np.int64),
        'action_payments': np.zeros((max_actions, 8), dtype=np.float32),
        'legal_mask': legal,
        'pi_target': pi,
        'z_target': float(z),
        'is_discovery': is_discovery,
    }


class TestStaticResolution:
    """Check 1: ReplayBuffer resolves to a class defined IN the adapter,
    not re-exported from legacy.buffer."""

    def test_replay_buffer_module_is_adapter(self):
        # __module__ must point at the adapter, not the legacy module.
        assert ReplayBuffer.__module__ == 'training.paradigms.az.buffer', (
            f'ReplayBuffer.__module__ = {ReplayBuffer.__module__!r}; expected adapter, not a legacy re-export.'
        )

    def test_replay_buffer_defined_in_adapter_file(self):
        # The class source file must be the adapter, not legacy/buffer.py.
        src_file = inspect.getsourcefile(ReplayBuffer)
        assert src_file is not None
        assert src_file.endswith('training/paradigms/az/buffer.py'), (
            f'ReplayBuffer source = {src_file!r}; expected adapter path.'
        )


class TestImportTopology:
    """Check 2: adapter source AST has ZERO ``legacy.buffer`` imports
    (T2.11 verify scope)."""

    def test_adapter_has_no_legacy_buffer_import(self):
        adapter_path = pathlib.Path(adapter_buffer_mod.__file__)
        tree = ast.parse(adapter_path.read_text())
        offending = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ''
                if mod.startswith('training.paradigms.az.legacy'):
                    offending.append(f'from {mod} import ...')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('training.paradigms.az.legacy'):
                        offending.append(f'import {alias.name}')
        assert not offending, (
            f'Adapter paradigms/az/buffer.py must have zero legacy.* imports (T2.11). Found: {offending}'
        )


class TestRoundtripSmoke:
    """Check 3: behavioral smoke — ReplayBuffer add/sample roundtrip works
    via the adapter symbol (not via legacy)."""

    def test_add_then_sample_basic_roundtrip(self):
        rb = ReplayBuffer(capacity=20)
        static = _fake_static()
        steps = [_fake_step(z=1.0) for _ in range(4)]
        gid = rb.add_trajectory(static, steps)
        assert isinstance(gid, int)
        assert len(rb) == 4
        assert rb.n_games() == 1

        rng = random.Random(0)
        batch = rb.sample(batch_size=3, rng=rng)
        assert batch['counter_values'].shape == (3, 64)
        assert batch['pi_target'].shape == (3, 4)
        assert batch['z_target'].shape == (3,)
        assert (batch['z_target'] == 1.0).all()
        # Static deduped — all sampled rows share game 0's static.
        assert batch['hook_ir'].shape == (3, 4, 8, 5)

    def test_capacity_bound_raises_on_zero(self):
        with pytest.raises(ValueError, match='capacity'):
            ReplayBuffer(capacity=0)

    def test_sample_on_empty_raises(self):
        rb = ReplayBuffer(capacity=5)
        with pytest.raises(RuntimeError, match='empty'):
            rb.sample(batch_size=1, rng=random.Random(0))
