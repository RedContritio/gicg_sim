"""Sanity check: structural sid pinning actually takes effect in a
real game's static_obs.

Verifies that for each canonical structural sid 0..K-1, exactly one obs
position carries that sid, with min/max matching the expected structural
counter semantics (e.g., HP max=declared max, phantom max=0).

Run:
    .venv/bin/python -m tools.sanity_sid_pin
"""

from __future__ import annotations

import sys

import numpy as np

from gicg_env import GicgEnv
from gicg_env.env import OBS_COUNTER_SLOTS


OBS_MAX_CHARS = 6
N_STRUCTURAL = 2 * OBS_MAX_CHARS * 4 + 2 * 8 + 2  # 66


FIELD_NAMES = ('HP', 'Energy', 'Alive', 'Active')


def canonical_label(sid: int) -> str:
    """Return the semantic label for a canonical structural sid.
    New layout: per-char block of 4 fields, iterated over (p, c).
    """
    if sid < 8 * OBS_MAX_CHARS:
        # Per-char block of 4 fields
        char_idx, field = divmod(sid, 4)
        p, c = divmod(char_idx, OBS_MAX_CHARS)
        return f'{FIELD_NAMES[field]} P{p} c{c}'
    if sid < 8 * OBS_MAX_CHARS + 16:
        s = sid - 8 * OBS_MAX_CHARS
        p, d = divmod(s, 8)
        dice_names = [
            'fire',
            'ice',
            'water',
            'electro',
            'geo',
            'anemo',
            'dendro',
            'omni',
        ]
        return f'P{p} dice_{dice_names[d]}'
    s = sid - (8 * OBS_MAX_CHARS + 16)
    return f'P{s} alive_count'


def main() -> int:
    env = GicgEnv(
        team_0=['赤蝶'],
        team_1=['墨客'],
        card_pool=None,
        seed=0,
        data_dir='data',
    )
    env.reset(seed=0)

    n_slots = OBS_COUNTER_SLOTS
    static = np.asarray(env.static_obs, dtype=np.int64)
    counter_meta = static[: n_slots * 3].reshape(n_slots, 3)

    # For each canonical structural sid, find obs positions carrying that sid.
    # Padding positions (bucket slack) default to sid=0 from zero-init, so we
    # have to filter them out for sid=0 by min|max != 0. For all other
    # structural sids in 1..K-1, exactly one position should carry that sid
    # (phantom counters are explicitly written, including their sid).
    sid_positions: dict[int, list[int]] = {}
    for pos in range(n_slots):
        sid = int(counter_meta[pos, 2])
        sid_positions.setdefault(sid, []).append(pos)

    # Bound chars: expected (min, max) — from DSL declare_counter
    bound_expected = {
        '赤蝶': {'hp': (0, 15), 'energy': (0, 3), 'alive': (0, 1), 'active': (0, 1)},
        '墨客': {'hp': (0, 15), 'energy': (0, 2), 'alive': (0, 1), 'active': (0, 1)},
    }

    # Which char slots are bound in this game
    bound_map = {(0, 0): '赤蝶', (1, 0): '墨客'}

    failures = []
    successes = 0
    total = 0

    print('=' * 75)
    print('Structural sid pinning sanity check')
    print('=' * 75)
    print('Team: 赤蝶 vs 墨客 (team_size=1)  n_slots=1832  N_STRUCTURAL=66')
    print()

    for sid in range(N_STRUCTURAL):
        total += 1
        label = canonical_label(sid)
        positions = sid_positions.get(sid, [])

        # Filter padding (sid=0 appears at zero-init positions with min=max=0)
        if sid == 0:
            # Real bound HP P0 c0 has max>0. Padding has min=max=0. Filter.
            positions = [p for p in positions if counter_meta[p, 0] != 0 or counter_meta[p, 1] != 0]

        if len(positions) != 1:
            failures.append(f'sid={sid:3d} {label}: expected 1 position, got {len(positions)}')
            continue

        pos = positions[0]
        mn = int(counter_meta[pos, 0])
        mx = int(counter_meta[pos, 1])

        # Expected min/max depends on whether the slot is bound/phantom and
        # which char is bound.
        if sid < 8 * OBS_MAX_CHARS:
            char_idx, field_idx = divmod(sid, 4)
            p, c = divmod(char_idx, OBS_MAX_CHARS)
            bound_char = bound_map.get((p, c))
            if bound_char is None:
                # Phantom
                expected_mm = (0, 0)
            else:
                field = FIELD_NAMES[field_idx].lower()
                expected_mm = bound_expected[bound_char][field]
        elif sid < 8 * OBS_MAX_CHARS + 16:
            expected_mm = (0, 16)  # dice range
        else:
            expected_mm = (0, 10)  # alive_count

        ok = (mn, mx) == expected_mm
        if ok:
            successes += 1
            print(f'  ✓ sid={sid:3d} {label:22s}  pos={pos:5d}  min={mn} max={mx}')
        else:
            failures.append(f'sid={sid:3d} {label}: pos={pos}  min={mn} max={mx}  expected={expected_mm}')

    if failures:
        print()
        print('FAILURES:')
        for f in failures:
            print(f'  ✗ {f}')

    print()
    print(f'RESULT: {successes}/{total} canonical sids verified')
    return 0 if successes == total else 1


if __name__ == '__main__':
    sys.exit(main())
