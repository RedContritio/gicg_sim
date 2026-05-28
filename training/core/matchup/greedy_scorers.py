"""Feature-based scorers F1..F5 for GreedyPlayer.

Split out of greedy_player.py to keep the player module under the 300-
line Python cap (hook-filter + scorers + GreedyPlayer class together
exceed it). See greedy_player.py module docstring for the F1..F5
rationale and the scorer signature contract.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from gicg_env import REWARD_EVENTS_FIELDS

# Slot indices into the RewardEvents int32 vector. Derived from the
# canonical field order so reordering the Go struct + Python tuple
# automatically propagates here.
_IDX = {name: i for i, name in enumerate(REWARD_EVENTS_FIELDS)}
EV_HEAL_DONE = _IDX['heal_done']
EV_ENEMY_HEAL_DONE = _IDX['enemy_heal_done']
EV_SHIELD_ABSORBED = _IDX['shield_absorbed']
EV_DAMAGE_BLOCKED = _IDX['damage_blocked']
EV_REACTIONS_TRIGGERED = _IDX['reactions_triggered']
EV_REACTIONS_RECEIVED = _IDX['reactions_received']
EV_ENERGY_OVERFLOW = _IDX['energy_overflow']
EV_AP_WASTED = _IDX['ap_wasted']
EV_KILLS = _IDX['kills']
EV_TOTAL_KILLS = _IDX['total_kills']


def _own_hp_alive(view: dict, me: int) -> tuple[int, int]:
    """Return (total HP, alive count) for ``me`` from export_view."""
    chars = view['players'][me]['chars']
    return sum(c['hp'] for c in chars), sum(1 for c in chars if c['alive'])


def _ap_waste_piecewise(n: int) -> float:
    """Piecewise-escalating penalty for unused AP at round end. First
    3 AP are cheap (0.2 each), next 3 middling (0.5), next 2 heavy
    (0.8), past 8 very heavy (1.0). Models the real convexity: the
    marginal value of a single unused AP grows with how bad the round
    was overall."""
    n = max(0, int(n))
    return 0.2 * min(n, 3) + 0.5 * max(0, min(n - 3, 3)) + 0.8 * max(0, min(n - 6, 2)) + 1.0 * max(0, n - 8)


def _kill_slope_escalating(k: int, total_before: int) -> float:
    """Escalating bonus for each kill in the step, on top of F2's flat
    10·k. The i-th kill in a game is worth ``10 + 5*(total_before+i)``
    total, of which F2 already gives 10 — this returns only the
    *additional* 5·(total_before+i) term, so stacking F5 on F4 doesn't
    double-count the base."""
    return sum(5.0 * (total_before + i) for i in range(int(k)))


def _score_f1(
    view_before: dict,
    view_after: dict,
    events_before: np.ndarray,
    events_after: np.ndarray,
    me: int,
) -> float:
    """dmg_dealt - 1.1 * dmg_received. Ignores events args."""
    del events_before, events_after
    opp = 1 - me
    own_before, _ = _own_hp_alive(view_before, me)
    own_after, _ = _own_hp_alive(view_after, me)
    enemy_before, _ = _own_hp_alive(view_before, opp)
    enemy_after, _ = _own_hp_alive(view_after, opp)
    dmg_dealt = enemy_before - enemy_after
    dmg_taken = own_before - own_after
    return float(dmg_dealt) - 1.1 * float(dmg_taken)


def _score_f2(
    view_before: dict,
    view_after: dict,
    events_before: np.ndarray,
    events_after: np.ndarray,
    me: int,
) -> float:
    """F1 + 10 * own_kill - 8 * own_death (flat kill_base)."""
    opp = 1 - me
    _, own_alive_before = _own_hp_alive(view_before, me)
    _, own_alive_after = _own_hp_alive(view_after, me)
    _, enemy_alive_before = _own_hp_alive(view_before, opp)
    _, enemy_alive_after = _own_hp_alive(view_after, opp)
    kill_delta = max(0, enemy_alive_before - enemy_alive_after)
    death_delta = max(0, own_alive_before - own_alive_after)
    return _score_f1(view_before, view_after, events_before, events_after, me) + 10.0 * kill_delta - 8.0 * death_delta


def _score_f3(
    view_before: dict,
    view_after: dict,
    events_before: np.ndarray,
    events_after: np.ndarray,
    me: int,
) -> float:
    """F2 + (heal_done - 0.8 * enemy_heal_done). Uses RewardEvents
    deltas so interleaved heals (e.g. shrine-of-depths auto-heal)
    get counted even when export_view's HP snapshot doesn't reflect
    them cleanly."""
    d = events_after - events_before
    heal = float(d[EV_HEAL_DONE]) - 0.8 * float(d[EV_ENEMY_HEAL_DONE])
    return _score_f2(view_before, view_after, events_before, events_after, me) + heal


def _score_f4(
    view_before: dict,
    view_after: dict,
    events_before: np.ndarray,
    events_after: np.ndarray,
    me: int,
) -> float:
    """F3 + (shield_absorbed - 0.8 * damage_blocked) +
    (reactions_triggered - 0.8 * reactions_received). Asymmetric
    weights (<1 on the enemy side) mean both-sides-symmetric events
    still net-out nonzero in my favor when I'm the one triggering."""
    d = events_after - events_before
    shield = float(d[EV_SHIELD_ABSORBED]) - 0.8 * float(d[EV_DAMAGE_BLOCKED])
    react = float(d[EV_REACTIONS_TRIGGERED]) - 0.8 * float(d[EV_REACTIONS_RECEIVED])
    return _score_f3(view_before, view_after, events_before, events_after, me) + shield + react


def _score_f5(
    view_before: dict,
    view_after: dict,
    events_before: np.ndarray,
    events_after: np.ndarray,
    me: int,
) -> float:
    """F4 + energy/AP waste penalties + escalating kill bonus on top
    of F2's flat kill. See _ap_waste_piecewise + _kill_slope_escalating
    for the shape rationale."""
    d = events_after - events_before
    energy_pen = -0.4 * float(d[EV_ENERGY_OVERFLOW])
    ap_pen = -_ap_waste_piecewise(int(d[EV_AP_WASTED]))
    kill_bonus = _kill_slope_escalating(int(d[EV_KILLS]), int(events_before[EV_TOTAL_KILLS]))
    return _score_f4(view_before, view_after, events_before, events_after, me) + energy_pen + ap_pen + kill_bonus


ScorerFn = Callable[[dict, dict, np.ndarray, np.ndarray, int], float]
SCORERS: dict[str, ScorerFn] = {
    'F1': _score_f1,
    'F2': _score_f2,
    'F3': _score_f3,
    'F4': _score_f4,
    'F5': _score_f5,
}
