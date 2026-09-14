"""Paradigm registry for tools/eval/. Keeps ckpt.py / daemon.py /
metrics_view.py paradigm-agnostic. Only 'dmc' is populated in this rev;
'az' / 'cfr' entries reserved for future paradigms."""

from __future__ import annotations

from importlib import import_module
from typing import Any

PARADIGMS: dict[str, dict[str, str]] = {
    'dmc': {
        'load_config': 'training.paradigms.dmc._run_config:load_config',
        'build_agent': 'training.paradigms.dmc._eval_adapter:build_eval_agent',
        'build_evaluator': 'tools.eval.paired:build_evaluator',
        'build_baseline': 'training.paradigms.dmc._eval_adapter:build_baseline',
        'ckpt_frame': 'training.paradigms.dmc._eval_adapter:ckpt_frame',
        'build_random_agent': 'training.paradigms.dmc._eval_adapter:build_random_agent',
    },
    # 'az': {...},   # reserved — not implemented this rev
    # 'cfr': {...},  # reserved — not implemented this rev
}


def resolve(paradigm: str, key: str) -> Any:
    """Dynamic-import the function bound to (paradigm, key)."""
    if paradigm not in PARADIGMS:
        raise KeyError(f'unknown paradigm {paradigm!r}; known: {sorted(PARADIGMS)}')
    spec = PARADIGMS[paradigm].get(key)
    if spec is None:
        raise NotImplementedError(f'paradigm {paradigm!r} has no {key!r} adapter')
    mod_name, fn_name = spec.split(':')
    return getattr(import_module(mod_name), fn_name)
