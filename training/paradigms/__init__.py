"""Paradigm registry — name → Paradigm class.

`tools.runs.train` (post 2026-05-18 clean-slate redesign; pre-redesign
`tools/run.py` deleted in T-23) dispatches by `cfg.meta.paradigm`. P3-B
ship DMC;P4 ship AZ / BC / PPO / CFR(并行 dispatch,registry
consolidation 由 controller 一次性 commit).
"""

from __future__ import annotations

from typing import Any


def _load_dmc():
    from training.paradigms.dmc.paradigm import DMCParadigm

    return DMCParadigm


def _load_az():
    from training.paradigms.az.paradigm import AZParadigm

    return AZParadigm


def _load_bc():
    from training.paradigms.bc.paradigm import BCParadigm

    return BCParadigm


def _load_ppo():
    from training.paradigms.ppo.paradigm import PPOParadigm

    return PPOParadigm


def _load_cfr():
    from training.paradigms.cfr.paradigm import CFRParadigm

    return CFRParadigm


PARADIGMS = {
    'dmc': _load_dmc,
    'az': _load_az,
    'bc': _load_bc,
    'ppo': _load_ppo,
    'cfr': _load_cfr,
}


def resolve(name: str) -> Any:
    """Instantiate the registered Paradigm for ``name``. Lazy import so
    importing this registry does not drag every paradigm's transitive
    deps into memory."""
    if name not in PARADIGMS:
        raise ValueError(f'paradigms.resolve: unknown paradigm {name!r} (registered: {sorted(PARADIGMS)})')
    cls = PARADIGMS[name]()
    return cls()
