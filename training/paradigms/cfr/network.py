"""CFRNetwork — nn.Module wrapper exposing 2 heads (avg_policy + advantage).

Spec ref: paradigm-cfr/spec.md C4. CFR uses a shared encoder trunk fed
into two heads:

  - ``avg_policy_head``: action logits (eval / production inference path)
  - ``advantage_head``: per-action regret scalar (training-only)

The legacy CFR implementation realizes the two heads as **two separate
modules** sharing trunk *architecture* (not weights — see docstring on
``training.paradigms.cfr.strategy_net._CFRTrunk``). This wrapper preserves
that 1:1 — it composes a ``CFRStrategyNet`` (avg_policy + value) and a
pair of ``AdvantageNet`` (one per traverser_player, per C1.2).

P5 consolidation may unify the trunks; for now the wrapper is a thin
forwarding layer so r008 reproducibility (C6.2) holds exactly.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from training.paradigms.cfr.advantage_net import AdvantageNet
from training.paradigms.cfr.strategy_net import CFRNetConfig, CFRStrategyNet


class CFRNetwork(nn.Module):
    """nn.Module wrapper composing CFRStrategyNet + two AdvantageNets.

    Exposes the heads named per C4.1: ``avg_policy`` (forwards strategy_net)
    and ``advantage`` (list of 2, one per traverser_player). The driver's
    `make_optimizer` walks `self.parameters()` to cover all three modules
    — collector / loss path can read individual head modules via the
    accessors below.
    """

    HEAD_NAMES = ('avg_policy', 'advantage')

    def __init__(self, cfg: CFRNetConfig, device: str = 'cpu') -> None:
        super().__init__()
        self.cfg = cfg
        self.device = torch.device(device)
        self.strategy_net = CFRStrategyNet(cfg).to(self.device)
        # C1.2 — per-traverser advantage nets (regret is player-specific).
        self.advantage_nets = nn.ModuleList(
            [
                AdvantageNet(cfg).to(self.device),
                AdvantageNet(cfg).to(self.device),
            ]
        )

    @property
    def avg_policy_head(self) -> CFRStrategyNet:
        """C4.2 — production inference uses this head only."""
        return self.strategy_net

    def advantage_head(self, traverser_player: int) -> AdvantageNet:
        if traverser_player not in (0, 1):
            raise ValueError(f'CFRNetwork.advantage_head: traverser_player must be 0/1, got {traverser_player}')
        return self.advantage_nets[traverser_player]

    def forward(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(
            'CFRNetwork.forward not used — call strategy_net(...) or advantage_nets[p](...) directly.'
        )
