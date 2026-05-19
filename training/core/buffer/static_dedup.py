"""StaticDedupBufferBase — game-static refcount + dedup table.

Copied + adapted from training/framework/buffer/base.py. Shared by
AZ replay + CFR reservoir to avoid re-storing 50KB of hook IR ops
per step (per-game static fields shared across all transitions of
that game, refcounted).

IR-4 cutover: per-hook representation changed from (token_type,
token_value) pairs to (opcode, dst, op1, op2, op3) IR ops. The
`hook_ir` field has shape (n_active_hooks, max_ops, 5) int64.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


GAME_STATIC_KEYS = (
    'hook_ir',
    'hook_mask',
    'counter_sids',
    'active_slot_mask',
    'char_skill_refs',
)


@dataclass
class _GameStatic:
    hook_ir: np.ndarray
    hook_mask: np.ndarray
    counter_sids: np.ndarray
    active_slot_mask: np.ndarray
    char_skill_refs: np.ndarray
    refcount: int = 0


class StaticDedupBufferBase:
    """Refcount-owned per-game static table. Subclasses add their own
    entries list + dynamic-key handling + eviction policy + sample()."""

    def __init__(self) -> None:
        self._game_static: dict = {}
        self._next_game_id: int = 0

    def register_game(self, static: dict) -> int:
        missing = set(GAME_STATIC_KEYS) - set(static.keys())
        if missing:
            raise KeyError(f'register_game: static missing {sorted(missing)}')
        gid = self._next_game_id
        self._next_game_id += 1
        self._game_static[gid] = _GameStatic(
            hook_ir=np.asarray(static['hook_ir'], dtype=np.int64),
            hook_mask=np.asarray(static['hook_mask'], dtype=bool),
            counter_sids=np.asarray(static['counter_sids'], dtype=np.int64),
            active_slot_mask=np.asarray(static['active_slot_mask'], dtype=bool),
            char_skill_refs=np.asarray(static['char_skill_refs'], dtype=np.int64),
            refcount=0,
        )
        return gid

    def _incref(self, game_id: int) -> None:
        self._game_static[game_id].refcount += 1

    def _decref(self, game_id: int) -> None:
        s = self._game_static[game_id]
        s.refcount -= 1
        if s.refcount <= 0:
            if s.refcount < 0:
                raise RuntimeError(f'StaticDedup game {game_id} refcount negative ({s.refcount})')
            del self._game_static[game_id]

    def prune_empty_registrations(self) -> int:
        dead = [gid for gid, s in self._game_static.items() if s.refcount == 0]
        for gid in dead:
            del self._game_static[gid]
        return len(dead)

    def n_games(self) -> int:
        return len(self._game_static)

    def _stack_game_static(self, game_ids: list) -> dict:
        B = len(game_ids)
        statics = [self._game_static[gid] for gid in game_ids]
        max_hooks = max(s.hook_ir.shape[0] for s in statics)
        max_ops = statics[0].hook_ir.shape[1]
        fields_per_op = statics[0].hook_ir.shape[2]
        n_slots = statics[0].counter_sids.shape[0]
        hook_ir = np.zeros((B, max_hooks, max_ops, fields_per_op), dtype=np.int64)
        hook_mask = np.zeros((B, max_hooks), dtype=bool)
        counter_sids = np.zeros((B, n_slots), dtype=np.int64)
        active_slot_mask = np.zeros((B, n_slots), dtype=bool)
        csr_shape = statics[0].char_skill_refs.shape
        char_skill_refs = np.zeros((B,) + csr_shape, dtype=np.int64)
        for i, s in enumerate(statics):
            n_active = s.hook_ir.shape[0]
            hook_ir[i, :n_active] = s.hook_ir
            hook_mask[i, :n_active] = s.hook_mask
            counter_sids[i] = s.counter_sids
            active_slot_mask[i] = s.active_slot_mask
            char_skill_refs[i] = s.char_skill_refs
        return {
            'hook_ir': hook_ir,
            'hook_mask': hook_mask,
            'counter_sids': counter_sids,
            'active_slot_mask': active_slot_mask,
            'char_skill_refs': char_skill_refs,
        }
