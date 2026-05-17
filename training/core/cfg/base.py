"""ParadigmConfigBase — base dataclass for paradigm-agnostic metadata.

Spec ref: config-schema/spec.md § 7 N2 (cfg-schema-unification delta).

Each paradigm's root config (``AZParadigmConfig`` / ``BCParadigmConfig`` / ...)
SHALL compose this base via dataclass inheritance, providing:

- ``version``: cfg schema version (bump on any field change to detect
  ckpt-cfg mismatch at load time, per spec N3)
- ``paradigm``: identifier string ('az' | 'bc' | 'cfr' | 'dmc' | 'ppo')
  matching the dispatch key (per spec N3.3)

Note: base **does NOT** declare a ``shape`` field. Subclass provides
the shape via an ``agent: ObsShape = field(default_factory=make_<x>_default_shape)``
field of its own (see CC-201 / CC-203 in change DECISIONS.md). This keeps
caller pattern ``pcfg.agent.X`` (20+ runtime sites) unchanged while still
unifying the shape *type* to ``ObsShape`` across 4 paradigm (AZ/BC/CFR/DMC).
PPO does not compose (CC-206) until structural backbone migration ships.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParadigmConfigBase:
    """Base for paradigm-specific configs.

    Subclass usage:

        @dataclass(frozen=True)
        class AZParadigmConfig(ParadigmConfigBase):
            paradigm: str = 'az'
            agent: ObsShape = field(default_factory=make_az_default_shape)
            mcts: MCTSCfg = field(default_factory=MCTSCfg)
            train: TrainStepCfg = field(default_factory=TrainStepCfg)
            # ... other paradigm-specific fields ...
    """

    version: str = '1.0.0'
    paradigm: str = ''
