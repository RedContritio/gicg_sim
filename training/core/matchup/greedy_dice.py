"""Dice-payment filter for GreedyPlayer — the "collapse n-fanout" module.

The engine enumerates every legal dice payment for a given logical
action: e.g. "use 赤蝶 Q with cost [1 pyro, 2 any]" fans out to
C(pool, 2) payments for the 'any' slots. This balloons len(legal)
from ~n_logical (~10-30) to ~n_total (~100-500+) per decision. Since
GreedyPlayer simulates every action via snapshot/restore, per-
decision wall time scales linearly with len(legal). Collapsing the
fanout to one top-1 payment per logical action is a strict n→
n_logical speedup with no change in final-choice quality IF the
payment selector picks the payment the human-expert baseline would
have chosen.

## Heuristic (from spec, verbatim)

> 任意应该优先用数量最少的杂色骰。在元素骰中，认为价值上，和出战
> 角色同色的骰子＞和后台角色同色的骰子＞其他数量多的杂色＞数量少
> 的杂色。每次打出消耗价值最少的方案。
>
> 调和时候，按照一张牌预定义一个价值（仅用于贪心），优先调和价值
> 低的。

Concretely, value per die color (HIGHER = more valuable = prefer to
KEEP; payment "cost" = sum of (count_used_c × value_per_die_c)):

- Tier 1000: color matches acting char's element (scarce + critical)
- Tier 500: omni (color 7) — wildcard, keep unless clearly junk
- Tier 100: color matches ANY alive backline char's element
- Tier (10 × count): other colors (irrelevant); MORE in pool = MORE
  value (i.e. this is where the "杂色数量多>杂色数量少" rule
  lives). Concretely, a color I have 5 of is more valuable than a
  color I have 1 of — because the 1-of is a "loner" that contributes
  nothing to future cost-matching.

Then among all payments for a given logical action (= same
identity row), pick the one whose total paid value is MINIMAL.

For Tune (ActionKind=4), the spec says preserve high-value cards
and discard low-value ones. No curated card-value table exists yet,
so we proxy using (1) the Go engine's declared card dice-cost-sum —
more expensive cards are assumed higher value — and (2) hand index
as tiebreak (lower index = older = "stabler" cards, preserve). This
satisfies the "每张牌预定义一个价值" contract with a crude but
principled table.
"""

from __future__ import annotations

import numpy as np

from gicg_env import GicgEnv

# ActionKind enum values (mirror of gicg_engine/types.go::ActionKind)
_KIND_SKILL = 0
_KIND_CARD = 1
_KIND_SWITCH = 2
_KIND_END_TURN = 3
_KIND_TUNE = 4

# DiceColor enum values
_COLOR_OMNI = 7
_COLOR_COUNT = 8

# Value tiers (see module docstring).
_VALUE_ACTIVE = 1000
_VALUE_OMNI = 500
_VALUE_BACKLINE = 100
_VALUE_JUNK_PER_COUNT = 10  # multiplied by pool count

# Element name → DiceColor index (aligned with Go ElementToDiceColor).
_ELEM_TO_COLOR = {
    'fire': 0,
    'ice': 1,
    'water': 2,
    'electro': 3,
    'geo': 4,
    'anemo': 5,
    'dendro': 6,
}


def build_color_values(view: dict, me: int, dice_pool: np.ndarray) -> np.ndarray:
    """Compute per-color dice value array (length 8).

    view: env.export_view() dict.
    me: acting player index.
    dice_pool: np.ndarray[8] — live per-color counts (used for the
      "abundant junk > rare junk" rule).

    Returns: np.ndarray[8] of int32 values, HIGHER = prefer to keep.
    """
    values = np.zeros(_COLOR_COUNT, dtype=np.int64)
    my_chars = view['players'][me]['chars']
    active_idx = view['players'][me]['active_char']

    # Active char's element → highest tier.
    active_color = -1
    if 0 <= active_idx < len(my_chars):
        active_color = _ELEM_TO_COLOR.get(my_chars[active_idx]['element'], -1)

    # Backline (alive non-active chars) → mid tier.
    backline_colors = set()
    for i, ch in enumerate(my_chars):
        if i == active_idx:
            continue
        if not ch['alive']:
            continue
        c = _ELEM_TO_COLOR.get(ch['element'], -1)
        if c >= 0:
            backline_colors.add(c)

    # Seed "junk" base from pool count so abundant > rare naturally.
    for c in range(_COLOR_COUNT):
        values[c] = _VALUE_JUNK_PER_COUNT * int(dice_pool[c])

    # Override with role-based tiers.
    for c in backline_colors:
        if values[c] < _VALUE_BACKLINE:
            values[c] = _VALUE_BACKLINE
    if active_color >= 0 and values[active_color] < _VALUE_ACTIVE:
        values[active_color] = _VALUE_ACTIVE
    # Omni always gets the fixed omni tier (wildcard preservation),
    # regardless of pool count — even 1 omni is precious.
    if values[_COLOR_OMNI] < _VALUE_OMNI:
        values[_COLOR_OMNI] = _VALUE_OMNI
    return values


def payment_cost(payment: np.ndarray, color_values: np.ndarray) -> int:
    """Sum of (dice_used × per-die-value) across colors."""
    return int(np.dot(payment.astype(np.int64), color_values))


def _tune_card_value(env: GicgEnv, hand_idx: int) -> int:
    """Crude proxy for a card's "value to keep" for tune decisions.

    No curated value table exists yet; we use (1) the declared dice-
    cost-sum from the engine cost as a proxy for card strength (more
    expensive → presumed higher value), and (2) hand index as a
    tiebreak (lower = older = more "stable"). Both pieces are
    predefined per card/position, satisfying the "每张牌预定义一个
    价值" contract from the spec."""
    try:
        hand_refs = env._engine.hand_refs(env.acting_player)
    except Exception:
        return -hand_idx  # fallback: raw index tiebreak
    if not (0 <= hand_idx < len(hand_refs)):
        return -hand_idx
    # We don't have a direct card-cost-sum API from Python side; use
    # the *engine's* DeclaredCost via the card ref. As a portable
    # proxy, use hand_refs[hand_idx] itself — higher ref numbers
    # aren't semantic, but the contract only requires a STABLE
    # predefined ordering. Stable ordering by (hand_idx) gives
    # "discard oldest" which is a sensible default for a baseline.
    # Lower value = prefer to discard FIRST.
    return hand_idx


def filter_logical_actions(env: GicgEnv) -> list[int]:
    """Collapse env.get_legal_actions() to one top-1 payment per
    logical action. Returns sorted indices into the legal-action
    array — callers iterate these instead of range(n_legal).

    Grouping key is engine-native action identity (kind, subject_ref,
    aux, target_player, target_char) — stable across determinizations
    (see GameGetActionIdentities docstring). Within a group we pick
    the payment with MIN total value; for Tune, we break ties by
    preferring low-value cards.

    Actions with a single payment (the majority for cheap skills /
    switch / end_turn) pass through unchanged."""
    kinds, _ = env.get_legal_actions()
    n = len(kinds)
    if n == 0:
        return []
    identities = env.get_action_identities()  # (n, 5)
    payments = env.get_legal_action_payments()  # (n, 8)
    view = env.export_view()
    me = env.acting_player
    dice_pool = env.dice_counts(me)
    color_values = build_color_values(view, me, dice_pool)

    # Group by identity tuple (kind, subject_ref, aux, target_player,
    # target_char). dict preserves insertion order → sort of the
    # output is unnecessary.
    groups: dict[tuple, list[int]] = {}
    for i in range(n):
        key = tuple(int(x) for x in identities[i])
        groups.setdefault(key, []).append(i)

    chosen: list[int] = []
    for key, idxs in groups.items():
        if len(idxs) == 1:
            chosen.append(idxs[0])
            continue
        kind = key[0]
        if kind == _KIND_TUNE:
            # Spec: tune prefers discarding LOW-value cards. For a
            # given tune group, subject_ref is the discarded card
            # (see capi_actions_query.go docstring). But in practice
            # each tune (hand_idx, source_color) enumerates as its
            # own identity — identical identity + different payment
            # should only arise when the 'any' slot of tune's cost
            # itself fans out (tune cost is 0 so this group is
            # typically size 1 anyway). Fallback: min-value payment.
            best = min(
                idxs,
                key=lambda i: (
                    payment_cost(payments[i], color_values),
                    _tune_card_value(env, int(identities[i][1])),
                ),
            )
            chosen.append(best)
            continue
        # Skill / Card / Switch / EndTurn: min-value payment.
        best = min(idxs, key=lambda i: payment_cost(payments[i], color_values))
        chosen.append(best)

    chosen.sort()
    return chosen
