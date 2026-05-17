"""Core probe helpers for tools.probe_numeric_sensitivity. Split out
of the CLI script to stay under the 300-line cap. Holds the obs
builder, perturbation sampling, and response-measurement primitives;
the CLI orchestrator + summary printing stays in the sibling
script."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from gicg_env import GicgEnv
from training.paradigms.az.network import Agent

TOK_LIT_NUMBER = 240

CONFIG_BUILDERS = {
    'c1_random': 'training.paradigms.az.config.random_1v1_config',
    'c1': 'training.paradigms.az.config.fixed_1v1_config',
    'smoke': 'training.paradigms.az.config.smoke_config',
}


def load_cfg(name: str):
    """Dynamically import cfg builder."""
    mod_path, fn = CONFIG_BUILDERS[name].rsplit('.', 1)
    mod = __import__(mod_path, fromlist=[fn])
    return getattr(mod, fn)(data_dir='data')


# --------------------------------------------------------------------------- #
# Obs construction


def _advance_steps(env: GicgEnv, n_steps: int, seed: int):
    rng = np.random.default_rng(seed)
    env.reset(seed=seed)
    for _ in range(n_steps):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            break
        env.step(int(rng.integers(0, len(kinds))))


def build_obs(env: GicgEnv, step: int, seed: int):
    """Run env to `step` steps, return (static, dyn, refs, payments).

    If env terminates early, back off half-way."""
    _advance_steps(env, step, seed)
    if env.done:
        _advance_steps(env, max(1, step // 2), seed)
    if env.done:
        return None
    try:
        refs = env.get_action_refs()
        if len(refs) == 0:
            return None
        return (
            env.static_obs.copy(),
            env._get_obs().copy(),
            refs,
            env.get_legal_action_payments(),
        )
    except Exception as e:
        print(f'  [skip step={step} seed={seed}] {type(e).__name__}: {e}')
        return None


def parse_hook_data(static_obs: np.ndarray, cfg) -> np.ndarray:
    meta_size = cfg.agent.n_counter_slots * 3
    return static_obs[meta_size:].reshape(
        cfg.agent.n_hooks,
        cfg.agent.max_tokens_per_hook,
        2,
    )


def flat_token_idx(cfg, hook_idx: int, tok_idx: int, field: int) -> int:
    """field=0: type, 1: value."""
    meta_size = cfg.agent.n_counter_slots * 3
    return meta_size + (hook_idx * cfg.agent.max_tokens_per_hook + tok_idx) * 2 + field


# --------------------------------------------------------------------------- #
# Perturbation experiments


@dataclass
class ResponseStats:
    n_samples: int
    value_abs_delta_mean: float
    value_abs_delta_max: float
    top1_change_rate: float  # fraction of samples where argmax(prior) changed

    def __str__(self):
        return (
            f'n={self.n_samples} '
            f'|Δv|_mean={self.value_abs_delta_mean:.4f} '
            f'|Δv|_max={self.value_abs_delta_max:.4f} '
            f'top1_change={100 * self.top1_change_rate:.1f}%'
        )


def measure_response(
    agent: Agent,
    static: np.ndarray,
    dyn: np.ndarray,
    refs: np.ndarray,
    payments: np.ndarray,
    perturbations: list[tuple[int, float]],
) -> ResponseStats:
    """Apply each perturbation in turn, measure value delta and top1 delta."""
    # Baseline
    agent.encode_static(static)
    prior_base, v_base = agent.eval_state(dyn, refs, payments)
    top1_base = int(np.argmax(prior_base))

    dv, dt = [], []
    for flat_idx, new_val in perturbations:
        s = static.copy()
        s[flat_idx] = float(new_val)
        agent.encode_static(s)
        prior, v = agent.eval_state(dyn, refs, payments)
        dv.append(abs(v - v_base))
        dt.append(1 if int(np.argmax(prior)) != top1_base else 0)

    return ResponseStats(
        n_samples=len(perturbations),
        value_abs_delta_mean=float(np.mean(dv)) if dv else 0.0,
        value_abs_delta_max=float(np.max(dv)) if dv else 0.0,
        top1_change_rate=float(np.mean(dt)) if dt else 0.0,
    )


def measure_counter_response(
    agent: Agent,
    static: np.ndarray,
    dyn: np.ndarray,
    refs: np.ndarray,
    payments: np.ndarray,
    n_trials: int = 20,
    seed: int = 0,
) -> ResponseStats:
    """Baseline: perturb dyn counter_values with random ±N offsets, same metric."""
    agent.encode_static(static)
    prior_base, v_base = agent.eval_state(dyn, refs, payments)
    top1_base = int(np.argmax(prior_base))

    rng = np.random.default_rng(seed)
    n_slots = len(dyn) - 3  # minus meta
    dv, dt = [], []
    for _ in range(n_trials):
        d = dyn.copy()
        c_start = 3
        # perturb 5 random slots
        offsets = rng.choice(min(200, n_slots), size=5, replace=False)
        deltas = rng.integers(-3, 4, size=5).astype(np.float32)
        for o, delta in zip(offsets, deltas):
            d[c_start + int(o)] = d[c_start + int(o)] + delta
        prior, v = agent.eval_state(d, refs, payments)
        dv.append(abs(v - v_base))
        dt.append(1 if int(np.argmax(prior)) != top1_base else 0)

    return ResponseStats(
        n_samples=n_trials,
        value_abs_delta_mean=float(np.mean(dv)),
        value_abs_delta_max=float(np.max(dv)),
        top1_change_rate=float(np.mean(dt)),
    )


def sample_perturbations(
    hook_data: np.ndarray,
    cfg,
    n_samples: int,
    rng: np.random.Generator,
    mode: str,  # "lit_number" | "type_swap"
) -> list[tuple[int, float]]:
    """Randomly sample N perturbation points. Each returns (flat_idx, new_value)."""
    active_hook_mask = hook_data[:, :, 0].sum(axis=1) != 0
    active_hooks = np.where(active_hook_mask)[0]
    if len(active_hooks) == 0:
        return []

    out = []
    attempts = 0
    while len(out) < n_samples and attempts < 10 * n_samples:
        attempts += 1
        h = int(rng.choice(active_hooks))
        if mode == 'lit_number':
            lit_toks = np.where(hook_data[h, :, 0] == TOK_LIT_NUMBER)[0]
            if len(lit_toks) == 0:
                continue
            t = int(rng.choice(lit_toks))
            orig = int(hook_data[h, t, 1])
            new_val = int(rng.integers(1, 9))
            if new_val == orig:
                new_val = (new_val % 8) + 1
            out.append((flat_token_idx(cfg, h, t, 1), float(new_val)))
        elif mode == 'type_swap':
            non_pad = np.where(hook_data[h, :, 0] != 0)[0]
            if len(non_pad) == 0:
                continue
            t = int(rng.choice(non_pad))
            orig = int(hook_data[h, t, 0])
            candidates = [x for x in (80, 88, 89, 110, 111, 112, 150, 240) if x != orig]
            new_type = int(rng.choice(candidates))
            out.append((flat_token_idx(cfg, h, t, 0), float(new_type)))
    return out


def aggregate(lst: list[ResponseStats]) -> 'ResponseStats | None':
    """Aggregate per-obs stats into a single cross-obs summary."""
    if not lst:
        return None
    return ResponseStats(
        n_samples=sum(s.n_samples for s in lst),
        value_abs_delta_mean=float(np.mean([s.value_abs_delta_mean for s in lst])),
        value_abs_delta_max=float(np.max([s.value_abs_delta_max for s in lst])),
        top1_change_rate=float(np.mean([s.top1_change_rate for s in lst])),
    )
