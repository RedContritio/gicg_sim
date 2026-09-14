"""Project canonical structural identities into the decision-maker's view.

Counter values/SIDs and rule references remain canonical throughout transport,
replay and attention. Only the positional structural readout is own-first.
"""

import torch

from training.core.obs_constants import N_STRUCTURAL, OBS_MAX_CHARS, OBS_META_SIZE


def relative_structural(values, meta):
    if meta.shape[-1] != OBS_META_SIZE:
        raise ValueError('unsupported observation meta layout')
    observer = meta[:, 18]
    if ((observer != 0) & (observer != 1)).any():
        raise ValueError('invalid observation perspective')
    chars = OBS_MAX_CHARS * 4
    dice = chars * 2
    # P0 chars, P1 chars, P0 dice, P1 dice, P0/P1 alive count.
    order = list(range(chars, dice)) + list(range(chars))
    order += list(range(dice + 8, dice + 16)) + list(range(dice, dice + 8))
    order += [dice + 17, dice + 16]
    if values.shape[-1] != N_STRUCTURAL or len(order) != N_STRUCTURAL:
        raise ValueError('unsupported structural layout')
    swapped = values[:, order]
    return torch.where(observer[:, None] == 1, swapped, values)
