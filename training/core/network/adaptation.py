"""Explicit warm-start helpers; resume remains strict and restores no new optimizer state."""

from collections.abc import Mapping

import torch


def load_for_adaptation(module, state: Mapping[str, torch.Tensor]) -> list[str]:
    """Permit appended primitive token rows only; legacy observations are rejected.

    Validate everything before mutation. Existing rows are copied exactly; new
    rows retain the module's initialization. Returns names requiring adaptation.
    This is intentionally separate from exact checkpoint resume.
    """
    current = module.state_dict()
    unexpected = set(state) - set(current)
    missing = set(current) - set(state)
    allowed_missing = set()
    if unexpected or missing != allowed_missing:
        raise ValueError(
            f'incompatible warm-start: missing={sorted(missing - allowed_missing)}, extra={sorted(unexpected)}'
        )
    merged = dict(current)
    expanded = []
    for name, old in state.items():
        new = current[name]
        if old.shape == new.shape:
            merged[name] = old
        elif (
            name.endswith(('operand_embed.weight', 'opcode_embed.weight'))
            and old.ndim == new.ndim == 2
            and old.shape[1] == new.shape[1]
            and old.shape[0] < new.shape[0]
        ):
            value = new.clone()
            value[: old.shape[0]] = old.to(value)
            merged[name] = value
            expanded.append(name)
        else:
            raise ValueError(f'incompatible warm-start shape: {name}: {old.shape} -> {new.shape}')
    module.load_state_dict(merged, strict=True)
    return sorted(allowed_missing | set(expanded))
