"""Dice-value baseline for reroll choices, shared by all greedy depths."""

from gicg_env import ACTION_REROLL
from training.core.matchup.greedy_dice import build_color_values


def reroll_choice(env):
    refs = env.get_action_refs()
    if len(refs) == 0 or refs[0, 0] != ACTION_REROLL:
        return None
    color = int(refs[0, 2])
    if color == 8:
        return 0
    owner = env.acting_player
    pool = env.dice_counts(owner)
    values = build_color_values(env.export_view(), owner, pool)
    count = int(pool[color]) if int(values.sum()) > 8 * int(values[color]) else 0
    return next(i for i, row in enumerate(refs) if row[1] == count)
