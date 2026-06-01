"""Worker-side collection abstraction for parallel CFR.

CollectorBuffer implements the same ``register_game`` + ``add_sample``
interface as the reservoir buffers (duck-typed) — but stores every
sample (no eviction) and flushes into per-game batches for Queue
transport. Kept independent of StaticDedupBufferBase because the
semantics differ (no refcount, no eviction) and forcing inheritance
would be more plumbing than win.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from training.paradigms.cfr.reservoir.base import SAMPLE_DYNAMIC_KEYS
from training.core.buffer.static_dedup import GAME_STATIC_KEYS


@dataclass
class CFRGameBatch:
    """All samples harvested from one completed traversal."""

    static: dict
    advantage_samples_per_player: list = field(default_factory=lambda: [[], []])
    strategy_samples: list = field(default_factory=list)
    value_samples: list = field(default_factory=list)

    def n_samples(self) -> tuple[int, int, int, int]:
        return (
            len(self.advantage_samples_per_player[0]),
            len(self.advantage_samples_per_player[1]),
            len(self.strategy_samples),
            len(self.value_samples),
        )


class CollectorBuffer:
    """Flat sample collector with the reservoir buffer's interface."""

    def __init__(self) -> None:
        self._next_game_id: int = 0
        self._statics: dict[int, dict] = {}
        self._samples_by_gid: dict[int, list[tuple[dict, Any, int]]] = {}

    def register_game(self, static: dict) -> int:
        missing = set(GAME_STATIC_KEYS) - set(static.keys())
        if missing:
            raise KeyError(f'CollectorBuffer.register_game: missing {sorted(missing)}')
        gid = self._next_game_id
        self._next_game_id += 1
        self._statics[gid] = {k: np.asarray(static[k]) for k in GAME_STATIC_KEYS}
        self._samples_by_gid[gid] = []
        return gid

    def add_sample(
        self,
        game_id: int,
        dynamic: dict,
        target: Any,
        iteration: int,
        rng: Any = None,
    ) -> bool:
        if game_id not in self._samples_by_gid:
            raise KeyError(f'CollectorBuffer.add_sample: unknown gid {game_id}')
        missing = set(SAMPLE_DYNAMIC_KEYS) - set(dynamic.keys())
        if missing:
            raise KeyError(f'CollectorBuffer.add_sample: dynamic missing {sorted(missing)}')
        stored_dyn = {k: np.asarray(dynamic[k]).copy() for k in SAMPLE_DYNAMIC_KEYS}
        if isinstance(target, np.ndarray):
            stored_target = target.copy()
        else:
            stored_target = target
        self._samples_by_gid[game_id].append(
            (stored_dyn, stored_target, int(iteration)),
        )
        return True

    def __len__(self) -> int:
        return sum(len(v) for v in self._samples_by_gid.values())

    def prune_empty_registrations(self) -> int:
        """No-op (collector doesn't evict)."""
        return 0

    def clear(self) -> None:
        self._next_game_id = 0
        self._statics.clear()
        self._samples_by_gid.clear()

    def drain_batches(self) -> list[tuple[dict, list]]:
        out = []
        for gid in sorted(self._statics.keys()):
            out.append((self._statics[gid], self._samples_by_gid[gid]))
        self.clear()
        return out


def pick_traverser_player(mode: str, seq: int, rng) -> int:
    """Choose which player traverses for traversal ``seq``, per the cfg field
    ``traversal.traverser_alternation``. Single source of truth shared by the
    serial ``CFRTraversalCollector._pick_traverser`` and the async
    ``mp_factories.cfr_spec_sampler`` so both honor the same contract (an
    unknown mode raises rather than silently degrading to alternate)."""
    if mode == 'alternate':
        return seq % 2
    if mode == 'random':
        return rng.randint(0, 1)
    raise ValueError(f'pick_traverser_player: unknown traverser_alternation {mode!r}')


def drain_single_traversal(
    advantage_collectors,
    strategy_collector: CollectorBuffer,
    value_collector: CollectorBuffer,
    traverser_player: int,
) -> CFRGameBatch:
    """Drain collectors after a single CFRTraverser.traverse() call."""
    if len(advantage_collectors) != 2:
        raise ValueError('advantage_collectors must be length 2')
    if traverser_player not in (0, 1):
        raise ValueError(f'traverser_player must be 0 or 1, got {traverser_player}')

    adv_drained = advantage_collectors[traverser_player].drain_batches()
    other = advantage_collectors[1 - traverser_player].drain_batches()
    if other:
        raise RuntimeError(
            f'advantage_collectors[{1 - traverser_player}] has samples '
            f'from a non-traverser side — traversal invariant broken'
        )
    strat = strategy_collector.drain_batches()
    val = value_collector.drain_batches()
    if len(adv_drained) != 1 or len(strat) != 1 or len(val) != 1:
        raise RuntimeError(
            f'drain_single_traversal: expected exactly one game per '
            f'collector; got adv={len(adv_drained)} strat={len(strat)} '
            f'val={len(val)}'
        )
    static, adv_samples = adv_drained[0]
    _, strat_samples = strat[0]
    _, val_samples = val[0]

    adv_per_player: list = [[], []]
    adv_per_player[traverser_player] = adv_samples
    return CFRGameBatch(
        static=static,
        advantage_samples_per_player=adv_per_player,
        strategy_samples=strat_samples,
        value_samples=val_samples,
    )


def ingest_batches(
    batches: list[CFRGameBatch],
    advantage_buffers,
    strategy_buffer,
    value_buffer,
    rng,
) -> tuple[int, int, int, int]:
    """Replay the contents of a batch list into central reservoir buffers."""
    if len(advantage_buffers) != 2:
        raise ValueError('advantage_buffers must be length 2')
    n_adv = [0, 0]
    n_str = 0
    n_val = 0
    for batch in batches:
        for p in range(2):
            samples = batch.advantage_samples_per_player[p]
            if samples:
                gid_adv = advantage_buffers[p].register_game(batch.static)
                for dyn, regret, iteration in samples:
                    advantage_buffers[p].add_sample(
                        gid_adv,
                        dyn,
                        regret,
                        iteration,
                        rng,
                    )
                    n_adv[p] += 1
        if batch.strategy_samples:
            gid_str = strategy_buffer.register_game(batch.static)
            for dyn, policy, iteration in batch.strategy_samples:
                strategy_buffer.add_sample(gid_str, dyn, policy, iteration, rng)
                n_str += 1
        if batch.value_samples:
            gid_val = value_buffer.register_game(batch.static)
            for dyn, outcome, iteration in batch.value_samples:
                value_buffer.add_sample(gid_val, dyn, outcome, iteration, rng)
                n_val += 1
    for buf in advantage_buffers:
        buf.prune_empty_registrations()
    strategy_buffer.prune_empty_registrations()
    value_buffer.prune_empty_registrations()
    return n_adv[0], n_adv[1], n_str, n_val
