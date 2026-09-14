"""Select ordered live effect semantics without embedding raw lifecycle IDs."""

import torch
from training.core.obs_constants import OBS_BUFF_ROWS


def selected_buff_embeddings(refs, rows, tokens):
    selected = refs <= -2
    if rows is None or tokens is None:
        if selected.any():
            raise ValueError('buff-target action requires live effect observations')
        return None
    batch, count, width = tokens.shape
    positions = rows[..., 6].long()
    effects = (rows[..., 0] > 0) & (rows[..., 12] == 0)
    supports = (rows[..., 0] > 0) & (rows[..., 12] == 1) & (rows[..., 1] == 0)
    if (((positions < 0) | (positions >= count)) & effects).any():
        raise ValueError('invalid live buff position')
    if (((positions < 0) | (positions >= 4)) & supports).any():
        raise ValueError('invalid support replacement slot')
    valid = effects | supports
    positions = torch.where(supports, count + positions, positions).clamp(0, count + 3)
    sums = tokens.new_zeros((batch, count + 4, width)).scatter_add(
        1, positions.unsqueeze(-1).expand(-1, -1, width), tokens * valid.unsqueeze(-1)
    )
    weights = tokens.new_zeros((batch, count + 4)).scatter_add(1, positions, valid.to(tokens.dtype))
    target = -2 - refs.long()
    support_target = target >= OBS_BUFF_ROWS
    address = torch.where(support_target, target - OBS_BUFF_ROWS + count, target)
    safe = address.clamp(0, count + 3)
    invalid = torch.where(support_target, target >= OBS_BUFF_ROWS + 4, target >= count)
    if (selected & (invalid | (weights.gather(1, safe) == 0))).any():
        raise ValueError('selected buff is absent from live effect observations')
    pooled = sums / weights.clamp_min(1).unsqueeze(-1)
    return pooled.gather(1, safe.unsqueeze(-1).expand(-1, -1, width)) * selected.unsqueeze(-1)
