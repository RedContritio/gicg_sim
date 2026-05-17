"""Structural-sid helper.

``compute_structural_obspos`` maps per-sample counter_sids + active mask
to the obs position where each canonical structural sid (0..K-1) appears.
``compute_structural_values`` gathers the counter values at those
positions — previously inlined at every call site as
``counter_values.gather(1, structural_obspos)``.

Public (underscore-prefix dropped per the new naming rules).
"""

from __future__ import annotations

import torch

from training.core.obs_constants import N_STRUCTURAL


def compute_structural_obspos(counter_sids: torch.Tensor, active_slot_mask: torch.Tensor) -> torch.Tensor:
    """Given (B, n_slots) counter_sids and active_slot_mask, return
    (B, N_STRUCTURAL) long — for each canonical structural sid s in
    0..K-1, the obs position where that sid appears.

    The engine pins structural counter IDs to sids 0..K-1 in a canonical
    order (BuildStructuralCounterIDs). Phantom counters fill unbound
    slots so every sid in 0..K-1 has exactly one obs position. Padding
    positions (bucket slack) default to sid=0 via zero-init; we exclude
    them via ``active | (sid > 0)`` so only the real sid=0 position
    (P0 c0 HP, always bound) survives the scatter.
    """
    B, n_slots = counter_sids.shape
    device = counter_sids.device
    valid = active_slot_mask | (counter_sids > 0)
    safe_sids = torch.where(
        valid,
        counter_sids,
        torch.full_like(counter_sids, n_slots - 1),
    )
    positions = torch.arange(n_slots, device=device).unsqueeze(0).expand(B, -1)
    pos_by_sid = torch.zeros(B, n_slots, dtype=torch.long, device=device)
    pos_by_sid.scatter_(1, safe_sids, positions)
    return pos_by_sid[:, :N_STRUCTURAL]


def compute_structural_values(
    counter_values: torch.Tensor,
    structural_obspos: torch.Tensor,
) -> torch.Tensor:
    """Gather the per-sample counter values at the canonical structural
    obspos positions. Formerly inlined at five call sites."""
    return counter_values.gather(1, structural_obspos)
