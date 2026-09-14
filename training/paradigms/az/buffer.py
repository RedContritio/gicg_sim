"""AZ buffer — self-contained ReplayBuffer + AZBuffer adapter.

P4 serial-mode uses the ring-buffer ReplayBuffer (with static dedup +
discovery priority — spec A3.1) directly inlined here (T2.5 Phase 2:
adapter no longer wraps ``legacy.buffer.ReplayBuffer``). The
``AZBuffer`` wrapper adapts ReplayBuffer to the core Buffer protocol.

The collector pushes a ``SelfPlayResult``-derived (game_static, steps)
pair per episode; ``AZBuffer.push`` forwards them into the inlined
``ReplayBuffer.add_trajectory``.

Spec A3.1-A3.3 (replay + static dedup + uniform/priority sample).
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
from training.core.step_encoding import pad_buffs_np
from training.core.obs_constants import OBS_BUFF_FIELDS

from training.core.buffer.static_dedup import (
    GAME_STATIC_KEYS,
    StaticDedupBufferBase,
)
from training.core.protocols import Batch, CollectorOutput


STEP_DYNAMIC_KEYS = (
    'counter_values',
    'meta',
    'card_buckets',
    'enemy_sizes',
    'recent_damage',
    'prepare_skill',
    'modifier_log',
    'action_refs',
    'action_payments',
    'legal_mask',
    'pi_target',
    'z_target',
    'is_discovery',
    'counter_target',
    'has_counter_target',
)


class ReplayBuffer(StaticDedupBufferBase):
    """Ring-buffer replay store with per-game static dedup and
    discovery-priority sampling."""

    def __init__(
        self,
        capacity: int,
        priority_weight: float = 3.0,
    ):
        if capacity <= 0:
            raise ValueError(f'capacity must be positive, got {capacity}')
        if priority_weight < 1.0:
            raise ValueError(f'priority_weight must be >= 1.0 (1.0 = uniform), got {priority_weight}')
        super().__init__()
        self.capacity = capacity
        self.priority_weight = priority_weight

        self._entries: list[dict] = []
        self._cursor: int = 0

    def add_trajectory(
        self,
        game_static: dict,
        steps: list[dict],
    ) -> int:
        """Add a completed game's trajectory. Returns the assigned game_id."""
        missing_static = set(GAME_STATIC_KEYS) - set(game_static.keys())
        if missing_static:
            raise KeyError(f'add_trajectory: game_static missing keys {sorted(missing_static)}')
        if not steps:
            raise ValueError('add_trajectory: empty steps list')
        for i, s in enumerate(steps):
            missing = set(STEP_DYNAMIC_KEYS) - set(s.keys())
            if missing:
                raise KeyError(f'add_trajectory: step[{i}] missing keys {sorted(missing)}')

        gid = self.register_game(game_static)
        for s in steps:
            self._add_step(gid, s)
        return gid

    def _add_step(self, game_id: int, step: dict) -> None:
        entry = {
            'game_id': game_id,
            'counter_values': np.asarray(step['counter_values'], dtype=np.float32),
            'counter_target': np.asarray(step['counter_target'], dtype=np.float32),
            'has_counter_target': bool(step['has_counter_target']),
            'meta': np.asarray(step['meta'], dtype=np.float32),
            'card_buckets': np.asarray(step['card_buckets'], dtype=np.float32),
            'enemy_sizes': np.asarray(step['enemy_sizes'], dtype=np.float32),
            # ADR-0019 §B.2/§B.3c typed obs segments
            'recent_damage': np.asarray(step['recent_damage'], dtype=np.float32),
            'prepare_skill': np.asarray(step['prepare_skill'], dtype=np.float32),
            'modifier_log': np.asarray(step['modifier_log'], dtype=np.float32),
            'buffs': np.asarray(step.get('buffs', np.zeros((1, OBS_BUFF_FIELDS))), dtype=np.float32),
            'action_refs': np.asarray(step['action_refs'], dtype=np.int64),
            'action_payments': np.asarray(step['action_payments'], dtype=np.float32),
            'legal_mask': np.asarray(step['legal_mask'], dtype=bool),
            'pi_target': np.asarray(step['pi_target'], dtype=np.float32),
            'z_target': float(step['z_target']),
            'is_discovery': bool(step['is_discovery']),
        }
        # Hold the incoming reference before releasing an evicted sample,
        # which may be the last sample from the very same game.
        self._incref(game_id)
        if len(self._entries) < self.capacity:
            self._entries.append(entry)
        else:
            old = self._entries[self._cursor]
            self._decref(old['game_id'])
            self._entries[self._cursor] = entry
            self._cursor = (self._cursor + 1) % self.capacity

    # --- Read path -------------------------------------------------- #

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> dict:
        n = len(self._entries)
        discovery_count = sum(1 for e in self._entries if e.get('is_discovery')) if n > 0 else 0
        return {
            'size': n,
            'capacity': self.capacity,
            'fill_pct': round(100.0 * n / self.capacity, 1) if self.capacity > 0 else 0,
            'n_games': len(self._game_static),
            'discovery_pct': round(100.0 * discovery_count / n, 1) if n > 0 else 0,
        }

    def sample(self, batch_size: int, rng: random.Random) -> dict:
        """Sample up to batch_size steps weighted by discovery priority."""
        n = len(self._entries)
        if n == 0:
            raise RuntimeError('ReplayBuffer.sample: buffer is empty')
        if batch_size <= 0:
            raise ValueError(f'batch_size must be positive, got {batch_size}')
        effective_batch = min(batch_size, n)

        weights = self._entry_weights()
        indices = rng.choices(range(n), weights=weights, k=effective_batch)
        picked = [self._entries[i] for i in indices]
        return self._build_batch(picked)

    def _entry_weights(self) -> list[float]:
        if self.priority_weight == 1.0:
            return [1.0] * len(self._entries)
        w_disc = self.priority_weight
        return [w_disc if e['is_discovery'] else 1.0 for e in self._entries]

    def _build_batch(self, entries: list[dict]) -> dict:
        counter_values = np.stack([e['counter_values'] for e in entries])
        counter_target = np.stack([e['counter_target'] for e in entries])
        has_counter_target = np.array(
            [e['has_counter_target'] for e in entries],
            dtype=bool,
        )
        card_buckets = np.stack([e['card_buckets'] for e in entries])
        enemy_sizes = np.stack([e['enemy_sizes'] for e in entries])
        recent_damage = np.stack([e['recent_damage'] for e in entries])
        prepare_skill = np.stack([e['prepare_skill'] for e in entries])
        modifier_log = np.stack([e['modifier_log'] for e in entries])
        meta = np.stack([e['meta'] for e in entries])
        action_refs = np.stack([e['action_refs'] for e in entries])
        action_payments = np.stack([e['action_payments'] for e in entries])
        legal_mask = np.stack([e['legal_mask'] for e in entries])
        pi_target = np.stack([e['pi_target'] for e in entries])
        z_target = np.array([e['z_target'] for e in entries], dtype=np.float32)

        game_ids = [e['game_id'] for e in entries]
        static_stacked = self._stack_game_static(game_ids)

        return {
            'counter_values': counter_values,
            'counter_target': counter_target,
            'has_counter_target': has_counter_target,
            'card_buckets': card_buckets,
            'enemy_sizes': enemy_sizes,
            'recent_damage': recent_damage,
            'prepare_skill': prepare_skill,
            'modifier_log': modifier_log,
            'buffs': pad_buffs_np([e['buffs'] for e in entries]),
            'meta': meta,
            'action_refs': action_refs,
            'action_payments': action_payments,
            'legal_mask': legal_mask,
            'pi_target': pi_target,
            'z_target': z_target,
            **static_stacked,
        }


class AZBuffer:
    """Wraps the inlined ``ReplayBuffer``; presents the core Buffer protocol.

    ``push(CollectorOutput)`` reads collector-produced trajectories from
    ``CollectorOutput.runtime_metrics['az_trajectories']`` — list of
    ``(game_static, steps)`` tuples. We do NOT use
    ``CollectorOutput.transitions`` (typed core Transition) because AZ
    obs is richer than the typed schema can carry until P5 redesign.
    """

    def __init__(self, capacity: int, priority_weight: float = 3.0, seed: int = 0) -> None:
        if capacity <= 0:
            raise ValueError(f'AZBuffer: capacity must be positive, got {capacity}')
        self.capacity = capacity
        self._buf = ReplayBuffer(capacity=capacity, priority_weight=priority_weight)
        self._rng = random.Random(seed)

    def __len__(self) -> int:
        return len(self._buf)

    def push(self, batch: CollectorOutput) -> None:
        """Push collector output. Reads list of ``(game_static, steps)``
        from ``runtime_metrics['az_trajectories']``."""
        trajs = batch.runtime_metrics.get('az_trajectories', [])
        for game_static, steps in trajs:
            if not steps:
                continue
            self._buf.add_trajectory(game_static, steps)

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        """Uniform-or-priority sample (priority via ``priority_weight``,
        spec A3.3). The inlined ReplayBuffer uses ``random.Random`` not
        numpy Generator; we tunnel rng state via the local Random instance."""
        if batch_size > len(self._buf):
            raise ValueError(f'AZBuffer.sample: have {len(self._buf)} < batch_size={batch_size}')
        data = self._buf.sample(batch_size, self._rng)
        return Batch(data=data, weights=None, size=batch_size)

    def clear(self) -> None:
        """Off-policy AZ rarely clears between iter; provided for protocol
        conformance + paradigm extensibility. Resets ring + static-dedup
        state to fresh."""
        self._buf._entries.clear()
        self._buf._cursor = 0
        self._buf._game_static.clear()

    def state_dict(self) -> dict:
        return {'capacity': self.capacity, 'size': len(self)}

    def load_state_dict(self, sd: dict) -> None:
        if sd.get('capacity') != self.capacity:
            raise ValueError(
                f'AZBuffer.load_state_dict: capacity mismatch sd={sd.get("capacity")} self={self.capacity}'
            )

    def stats(self) -> dict:
        return self._buf.stats()
