"""Dense reward shaping — per-step reward from RewardEvents delta.

Applied on top of the engine's per-player RewardEvents accumulator
(see ``gicg_engine/reward_events.go`` and ``gicg_env._constants.REWARD_EVENTS_FIELDS``).
Each ``env.step()`` snapshots the acting player's events before and
after, diffs them, and scores the delta via ``RewardShaping`` coefs.

Orthogonal to the pure-terminal signal — callers leave
``reward_shaping=None`` and read ``info['z']`` at game over for terminal
outcome only; dense-shaping callers pass explicit ``RewardShaping``
coefs。 See ``docs/3_plans/curriculum/plan.md`` for the canonical
shaping schedule。
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np

from gicg_env._constants import REWARD_EVENTS_FIELDS

# Slot indices into the int32 RewardEvents vector. Derived from the
# canonical field tuple so reordering the Go struct propagates here.
_IDX = {name: i for i, name in enumerate(REWARD_EVENTS_FIELDS)}
_EV_DAMAGE_DEALT = _IDX['damage_dealt']
_EV_DAMAGE_RECEIVED = _IDX['damage_received']
_EV_KILLS = _IDX['kills']
_EV_DEATHS = _IDX['deaths']


@dataclass(frozen=True)
class RewardShaping:
    """Per-step reward coefficients for dense-shaping mode.

    Applied to (events_after_me − events_before_me) per call to
    ``env.step()``; all signals are already from ``me``'s perspective
    (damage_dealt = damage *me* dealt to enemies, damage_received =
    damage *me* took, etc.).

    Formula::

        r = hp_delta * dmg_dealt
          - hp_taken_penalty * dmg_received
          + kill_bonus * kills
          - death_penalty * deaths
          + (terminal_win if me won else -terminal_loss if me lost else 0)

    All coefficients default to 0.0 — pass only the terms you want
    active. Asymmetric ``hp_delta`` vs ``hp_taken_penalty`` (e.g.
    1.0 vs 1.1) creates the same mild defensive pressure the historical
    `30df35e^` reward did, without hard-coding the bias here.
    """

    hp_delta: float = 0.0
    hp_taken_penalty: float = 0.0
    kill_bonus: float = 0.0
    death_penalty: float = 0.0
    terminal_win: float = 0.0
    terminal_loss: float = 0.0

    @classmethod
    def from_arg(cls, arg):
        """Normalize a user-supplied arg to ``RewardShaping | None``.

        Accepts ``None`` (returns ``None`` — shaping disabled), an
        existing ``RewardShaping`` (pass-through), or a plain ``dict``
        whose keys must all be valid field names. Unknown keys raise
        ``ValueError`` rather than being silently dropped — misspelled
        coef names would otherwise train on zero weight undetected.
        """
        if arg is None:
            return None
        if isinstance(arg, cls):
            return arg
        known = {f.name for f in fields(cls)}
        unknown = set(arg) - known
        if unknown:
            raise ValueError(f'RewardShaping: unknown keys {sorted(unknown)}; allowed: {sorted(known)}')
        return cls(**arg)


def compute_shaped_reward(
    shaping: RewardShaping,
    events_before: np.ndarray,
    events_after: np.ndarray,
    done: bool,
    winner: int,
    me: int,
) -> float:
    """Δ RewardEvents × coefs + optional terminal bonus for player ``me``.

    ``winner`` is the engine code: 0/1 = player index, 2 = draw, −1 =
    not terminal. Draw at done=True intentionally gives zero terminal
    bonus either way — symmetric on a symmetric outcome.

    Callers must only invoke this when ``shaping is not None``; ``None``
    is the wire-disabled signal and should short-circuit at the call site.
    """
    d = events_after.astype(np.float64) - events_before.astype(np.float64)
    r = (
        shaping.hp_delta * float(d[_EV_DAMAGE_DEALT])
        - shaping.hp_taken_penalty * float(d[_EV_DAMAGE_RECEIVED])
        + shaping.kill_bonus * float(d[_EV_KILLS])
        - shaping.death_penalty * float(d[_EV_DEATHS])
    )
    if done:
        if winner == me:
            r += shaping.terminal_win
        elif winner == 1 - me:
            r -= shaping.terminal_loss
    return r
