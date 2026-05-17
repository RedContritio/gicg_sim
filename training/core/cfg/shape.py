"""ObsShape — observation shape parameters shared across 5 paradigms.

Replaces paradigm-local ``AgentShapeCfg`` (AZ/BC/DMC) + ``CFRAgentShapeCfg``
+ ``PPOAgentShapeCfg`` which were 同语义不同表面 (per
core-network-generic-promotion proposal).

Single source-of-truth for fields that determine network input/output
shapes; cfg loaders + ckpt schema validators reference this contract.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObsShape:
    """Observation shape — paradigm-agnostic, env-derived.

    All 5 paradigm cfgs compose this as ``shape: ObsShape`` field
    (per ParadigmConfigBase).
    """

    n_counter_slots: int
    n_hooks: int
    max_tokens_per_hook: int
    max_actions: int

    d_model: int = 128
    dropout: float = 0.0
    n_cross_layers: int = 2
