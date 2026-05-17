"""CFRReservoirBase: Vitter-R reservoir layered over the framework's
StaticDedupBufferBase. Subclasses specialize the target key."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict

import numpy as np

from training.core.buffer.static_dedup import (
    GAME_STATIC_KEYS,
    StaticDedupBufferBase,
    _GameStatic,
)


# Per-sample dynamic fields shared across all CFR target types.
SAMPLE_DYNAMIC_KEYS = (
    'counter_values',
    'meta',
    'card_buckets',
    'enemy_sizes',
    'action_refs',
    'action_payments',
    'legal_mask',
    'structural_values',
)


class CFRReservoirBase(StaticDedupBufferBase):
    """Reservoir buffer for Deep-CFR samples.

    Subclasses must override:
      - ``TARGET_KEY``: name of the target field (e.g. ``"regret"``)
      - ``_validate_target(target)``
      - ``_stack_targets(entries)``

    Not thread-safe.
    """

    TARGET_KEY: str = 'target'

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError(f'capacity must be positive, got {capacity}')
        super().__init__()
        self.capacity = capacity
        self._entries: list[dict] = []
        self._n_added: int = 0

    def add_sample(
        self,
        game_id: int,
        dynamic: dict,
        target: Any,
        iteration: int,
        rng: random.Random,
    ) -> bool:
        """Reservoir-sample this (dynamic, target) pair. Returns True
        if the sample landed in the buffer."""
        if game_id not in self._game_static:
            raise KeyError(f'add_sample: unknown game_id {game_id}')
        missing = set(SAMPLE_DYNAMIC_KEYS) - set(dynamic.keys())
        if missing:
            raise KeyError(f'add_sample: dynamic missing {sorted(missing)}')
        self._validate_target(target)

        entry = {
            'game_id': game_id,
            'iteration': int(iteration),
            'counter_values': np.asarray(dynamic['counter_values'], dtype=np.float32),
            'meta': np.asarray(dynamic['meta'], dtype=np.float32),
            'card_buckets': np.asarray(dynamic['card_buckets'], dtype=np.float32),
            'enemy_sizes': np.asarray(dynamic['enemy_sizes'], dtype=np.float32),
            'action_refs': np.asarray(dynamic['action_refs'], dtype=np.int64),
            'action_payments': np.asarray(dynamic['action_payments'], dtype=np.float32),
            'legal_mask': np.asarray(dynamic['legal_mask'], dtype=bool),
            'structural_values': np.asarray(dynamic['structural_values'], dtype=np.float32),
            self.TARGET_KEY: self._coerce_target(target),
        }

        # Vitter's Algorithm R
        landed = False
        if len(self._entries) < self.capacity:
            self._entries.append(entry)
            self._incref(game_id)
            landed = True
        else:
            j = rng.randrange(0, self._n_added + 1)
            if j < self.capacity:
                old = self._entries[j]
                self._decref(old['game_id'])
                self._entries[j] = entry
                self._incref(game_id)
                landed = True
        self._n_added += 1
        return landed

    # --- Read path -------------------------------------------------- #

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> dict:
        n = len(self._entries)
        return {
            'size': n,
            'capacity': self.capacity,
            'fill_pct': round(100.0 * n / self.capacity, 1) if self.capacity > 0 else 0,
            'n_games': len(self._game_static),
            'n_added_total': self._n_added,
        }

    def sample(self, batch_size: int, rng: random.Random) -> dict:
        """Sample ``batch_size`` entries uniformly at random, with
        replacement. Returns a batch dict ready for forward_batch."""
        n = len(self._entries)
        if n == 0:
            raise RuntimeError(f'{type(self).__name__}.sample: buffer empty')
        if batch_size <= 0:
            raise ValueError(f'batch_size must be positive, got {batch_size}')
        effective = min(batch_size, n)
        idx = rng.choices(range(n), k=effective)
        picked = [self._entries[i] for i in idx]
        return self._build_batch(picked)

    def _build_batch(self, entries: list[dict]) -> dict:
        counter_values = np.stack([e['counter_values'] for e in entries])
        meta = np.stack([e['meta'] for e in entries])
        card_buckets = np.stack([e['card_buckets'] for e in entries])
        enemy_sizes = np.stack([e['enemy_sizes'] for e in entries])
        action_refs = np.stack([e['action_refs'] for e in entries])
        action_payments = np.stack([e['action_payments'] for e in entries])
        legal_mask = np.stack([e['legal_mask'] for e in entries])
        structural_values = np.stack([e['structural_values'] for e in entries])

        game_ids = [e['game_id'] for e in entries]
        static_stacked = self._stack_game_static(game_ids)

        iterations = np.array([e['iteration'] for e in entries], dtype=np.int64)
        target_stack = self._stack_targets(entries)

        return {
            'counter_values': counter_values,
            'meta': meta,
            'card_buckets': card_buckets,
            'enemy_sizes': enemy_sizes,
            'action_refs': action_refs,
            'action_payments': action_payments,
            'legal_mask': legal_mask,
            'structural_values': structural_values,
            **static_stacked,
            'iteration': iterations,
            self.TARGET_KEY: target_stack,
        }

    # --- Persistence ------------------------------------------------ #

    def save(self, path: str | Path) -> None:
        """Dump the buffer to an npz file."""
        path = Path(path)
        arrays: Dict[str, np.ndarray] = {
            'capacity': np.int64(self.capacity),
            'n_added': np.int64(self._n_added),
            'next_game_id': np.int64(self._next_game_id),
            'size': np.int64(len(self._entries)),
        }
        for i, e in enumerate(self._entries):
            arrays[f'entry_{i}_game_id'] = np.int64(e['game_id'])
            arrays[f'entry_{i}_iteration'] = np.int64(e['iteration'])
            for key in SAMPLE_DYNAMIC_KEYS:
                arrays[f'entry_{i}_{key}'] = e[key]
            arrays[f'entry_{i}_{self.TARGET_KEY}'] = e[self.TARGET_KEY]
        for gid, s in self._game_static.items():
            for key in GAME_STATIC_KEYS:
                arrays[f'game_{gid}_{key}'] = getattr(s, key)
            arrays[f'game_{gid}_refcount'] = np.int64(s.refcount)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(str(path), **arrays)

    def load(self, path: str | Path) -> None:
        """Restore buffer state from an npz file."""
        data = np.load(str(path), allow_pickle=False)
        self.capacity = int(data['capacity'].item())
        self._n_added = int(data['n_added'].item())
        self._next_game_id = int(data['next_game_id'].item())
        size = int(data['size'].item())

        self._game_static = {}
        for key in data.files:
            if key.startswith('game_') and key.endswith('_hook_types'):
                gid = int(key.split('_')[1])
                self._game_static[gid] = _GameStatic(
                    hook_types=data[f'game_{gid}_hook_types'],
                    hook_values=data[f'game_{gid}_hook_values'],
                    hook_mask=data[f'game_{gid}_hook_mask'].astype(bool),
                    counter_sids=data[f'game_{gid}_counter_sids'],
                    active_slot_mask=data[f'game_{gid}_active_slot_mask'].astype(bool),
                    char_skill_refs=data[f'game_{gid}_char_skill_refs'],
                    refcount=int(data[f'game_{gid}_refcount'].item()),
                )

        self._entries = []
        for i in range(size):
            entry = {
                'game_id': int(data[f'entry_{i}_game_id'].item()),
                'iteration': int(data[f'entry_{i}_iteration'].item()),
            }
            for key in SAMPLE_DYNAMIC_KEYS:
                entry[key] = data[f'entry_{i}_{key}']
            entry[self.TARGET_KEY] = data[f'entry_{i}_{self.TARGET_KEY}']
            self._entries.append(entry)

    # --- Subclass hooks --------------------------------------------- #

    def _validate_target(self, target: Any) -> None:
        raise NotImplementedError

    def _coerce_target(self, target: Any) -> np.ndarray:
        raise NotImplementedError

    def _stack_targets(self, entries: list[dict]) -> np.ndarray:
        raise NotImplementedError
