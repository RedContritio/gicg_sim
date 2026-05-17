"""Guard test for invariant A12.1 — deterministic head ordering in
`make_actor_critic` across subprocess.

Spec ref: ``openspec/specs/network-architecture/spec.md`` SHALL 12 sub-
invariant A12.1(`make_actor_critic` SHALL iterate `head_kinds` in
`HEAD_REGISTRY` insertion order,SHALL NOT iterate `head_kinds` directly
when typed as `set[str]` / `frozenset[str]`)。

Rationale: `head_kinds` is `frozenset[str]` whose iteration order varies
across subprocess(`PYTHONHASHSEED=random`) → `nn.ModuleDict heads`
插入顺序变化 → `model.parameters()` 顺序变化 → `optimizer.state_dict()`
positional state mapping 跨 save / resume 错位 → `optimizer.step()`
post-resume `addcdiv_` broadcast fail。Was actual symptom that motivated
`az-resume-shape-fix`(archived 2026-05-17)。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / 'gicg_engine').is_dir() and (p / 'tools').is_dir():
            return p
    raise RuntimeError(f'cannot locate repo root from {here}')


REPO_ROOT = _repo_root()

# Script: build ActorCritic with given head_kinds module path + name + dump
# `list(net.heads.keys())`. Uses minimum ObsShape to keep subprocess fast.
_DUMP_SCRIPT = """
import sys
from training.core.cfg.shape import ObsShape
from training.core.network.actor_critic import make_actor_critic

mod_path, kinds_name = sys.argv[1], sys.argv[2]
mod = __import__(mod_path, fromlist=[kinds_name])
head_kinds = getattr(mod, kinds_name)

cfg = ObsShape(
    n_counter_slots=10,
    n_hooks=10,
    max_tokens_per_hook=10,
    max_actions=10,
    d_model=8,
    n_cross_layers=1,
    dropout=0.0,
)
net = make_actor_critic(cfg, head_kinds, use_typed_damage=True)
print(','.join(net.heads.keys()))
"""


def _run_in_subprocess(mod_path: str, kinds_name: str) -> str:
    env = os.environ.copy()
    # Don't fix PYTHONHASHSEED — caller expects to test the
    # `PYTHONHASHSEED=random` default behavior。
    env.pop('PYTHONHASHSEED', None)
    out = subprocess.check_output(
        [sys.executable, '-c', _DUMP_SCRIPT, mod_path, kinds_name],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
    )
    return out.strip()


def _stress_head_order(mod_path: str, kinds_name: str, n: int = 3) -> None:
    """Subprocess-stress: `n` fresh subprocess `make_actor_critic` calls
    SHALL return identical `list(heads.keys())` (A12.1)."""
    orders = [_run_in_subprocess(mod_path, kinds_name) for _ in range(n)]
    unique = set(orders)
    assert len(unique) == 1, (
        f'A12.1 violation: non-deterministic head order across {n} subprocess for '
        f'{mod_path}.{kinds_name} — got {sorted(unique)}'
    )


def test_az_head_order_deterministic() -> None:
    """AZ heads = {policy, value, delta} — 3 heads, high non-determinism
    risk per `az-resume-shape-fix` diagnose(measured 4/5 distinct orders
    pre-fix)."""
    _stress_head_order('training.paradigms.az.network', 'AZ_HEAD_KINDS')


def test_bc_head_order_deterministic() -> None:
    """BC heads = {policy, value, delta} — same set as AZ。"""
    _stress_head_order('training.paradigms.bc.network', 'BC_HEAD_KINDS')


def test_ppo_head_order_deterministic() -> None:
    """PPO heads = {policy, value} — 2 heads,still order-sensitive。"""
    _stress_head_order('training.paradigms.ppo.agent', 'PPO_HEAD_KINDS')
