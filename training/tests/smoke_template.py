"""Paradigm-symmetric smoke template (Phase 4 of core-network-generic-promotion).

User decision (D-303, 2026-05-17): "测试实际上也应该是基本对称的". The 5
paradigm smoke tests SHALL NOT each re-implement the from-zero → train
→ eval flow; they SHALL share one paradigm-agnostic template + plug in
paradigm-specific builders (network / batch / invariant). Adding a new
paradigm = registering one ``SmokeBuilder`` subclass, NOT writing a
new end-to-end test from scratch.

OpenSpec ref: ``openspec/changes/core-network-generic-promotion/specs/
training-architecture/spec.md`` invariant A1 — every paradigm SHALL
provide a smoke that:

1. From-zero start (no ckpt dependency).
2. Mini-train: collector → buffer → forward → backward → optimizer.step
   really runs (not stubbed).
3. Eval probe: ≥ 1 e2e probe of the network producing a usable signal
   (action selection, value estimate, or policy distribution depending
   on paradigm).
4. Paradigm-specific invariant — listed in spec A1.4 per paradigm.
5. Wall ≤ 60s per paradigm.

This module owns the "what every smoke does" template. Each paradigm's
smoke test (``test_<paradigm>_smoke.py`` OR the parametrized
``test_paradigm_smoke.py``) supplies a ``SmokeBuilder`` and the
template runs the 5 symmetric phases.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import torch


# F4: explicit 15-card deck for the 赤蝶-mirror v_legacy+test_basic
# union-pool smoke scenario. The union eligibility exceeds the 15-slot
# padding target and the engine no longer truncates silently — this
# pins the historical truncation-era composition (probe 2026-06-12,
# byte order). Shared by the AZ fixtures (_az_fixtures /
# test_az_paradigm / test_az_mp_factories) which use the same scenario.
SMOKE_MIRROR_DECK = [
    '乘胜追击',
    '以攻代守',
    '以牙还牙',
    '伏兵之术',
    '佛跳墙',
    '占星',
    '反制',
    '测试卡_增幅',
    '测试卡_碎片',
    '测试卡_神秘水流',
    '清洁时间',
    '玄冰',
    '瞬身之术',
    '美味烧鸡',
    '荷花酥',
]

# Smoke wall-time budget (per paradigm). Spec A1.5: ≤ 60s. We assert at
# 60s with a generous + 5s buffer for CI variance — tests should normally
# finish < 30s on a developer Mac.
SMOKE_WALL_BUDGET_S = 60.0
SMOKE_WALL_HARD_LIMIT_S = 75.0  # CI variance buffer


@dataclass
class TrainStepReport:
    """One mini-train step's observable signals — passed to invariant check."""

    loss_value_before: float
    loss_value_after: float
    grad_norm: float
    breakdown_before: dict
    breakdown_after: dict
    network: Any  # paradigm network (post-step weights)


@dataclass
class EvalProbeReport:
    """One e2e eval probe's observable signals — passed to invariant check.

    Different paradigms emit different probes (AZ: MCTS visit_counts +
    value; BC: argmax action + logit; PPO: action + log_prob + value;
    DMC: action + q_value; CFR: avg_policy distribution). Caller stuffs
    the relevant fields into ``payload`` for invariant inspection.
    """

    action: int
    payload: dict


class SmokeBuilder(Protocol):
    """Per-paradigm contract — implementations live next to each paradigm's
    smoke test (or as inline classes in the parametrized file).

    The template invokes these in order: build_paradigm → build_network →
    build_batch (×2 for before/after comparison) → eval_probe →
    paradigm_invariant.
    """

    name: str  # paradigm name (matches Paradigm.name; for test ids)

    def build_paradigm(self) -> Any:
        """Instantiate the Paradigm (e.g. ``AZParadigm()``)."""
        ...

    def build_cfg(self) -> Any:
        """Build a minimal TrainingConfig-shaped object (tiny d_model /
        max_actions / batch_size) for from-zero start."""
        ...

    def build_network(self, paradigm: Any, cfg: Any) -> Any:
        """Build the network via ``paradigm.make_network(cfg)`` — exposes
        the call site for tests that want to also assert head shape."""
        ...

    def build_optimizer(self, paradigm: Any, cfg: Any, network: Any) -> torch.optim.Optimizer:
        """Wrap ``paradigm.make_optimizer``."""
        ...

    def build_loss(self, paradigm: Any, cfg: Any) -> Any:
        """Wrap ``paradigm.make_loss``."""
        ...

    def build_batch(self, network: Any, cfg: Any) -> Any:
        """Synthesize a single training Batch matching the paradigm's
        ``LossComputer.compute(network, batch)`` contract.

        Returns a ``training.core.protocols.Batch``. The template will
        call this twice (before + after train step) so paradigm-specific
        invariants can compare loss/breakdown drift. Synthesis SHALL be
        deterministic (seeded) so the before/after delta is meaningful.
        """
        ...

    def eval_probe(self, paradigm: Any, cfg: Any, network: Any) -> EvalProbeReport:
        """Run one e2e eval probe — the network forwards through one
        episode-step-shaped input + emits an action selection. Returns
        the action + paradigm-specific payload dict for invariant check.

        SHALL be lightweight (single forward pass; not a full env
        episode) since smoke wall budget is 60s.
        """
        ...

    def paradigm_invariant(self, report: TrainStepReport, probe: EvalProbeReport) -> None:
        """Assert paradigm-specific invariant from spec A1.4. Raises
        AssertionError on violation. Examples:

        - AZ: probe.payload['value'] in [-1, 1]; MCTS visit_counts > 0
        - BC: report.loss_value_after < report.loss_value_before
        - DMC: probe.payload['q_value'] finite; ε=1 → all random
        - CFR: probe.payload['strategy_dist'].sum() ≈ 1; regret finite
        - PPO: probe.payload['log_prob'] ≤ 0; clip_frac in [0, 1]
        """
        ...


def run_symmetric_smoke(builder: SmokeBuilder) -> None:
    """Run the 5-phase symmetric smoke contract against one paradigm.

    Phase 1: build paradigm + cfg (from-zero, no ckpt).
    Phase 2: build network + optimizer + loss + batch.
    Phase 3: forward → backward → optimizer.step (real, not stub).
    Phase 4: eval probe (single forward pass via paradigm's eval path).
    Phase 5: assert paradigm-specific invariant + wall budget.
    """
    t_start = time.perf_counter()

    # Phase 1: from-zero paradigm + cfg.
    paradigm = builder.build_paradigm()
    cfg = builder.build_cfg()
    assert paradigm.name == builder.name, f'SmokeBuilder.name={builder.name!r} but paradigm.name={paradigm.name!r}'

    # Phase 2: build trainable components.
    network = builder.build_network(paradigm, cfg)
    assert isinstance(network, torch.nn.Module), f'build_network must return nn.Module, got {type(network).__name__}'
    # Parameter count > 0 is the "trainable from zero" gate.
    params = list(network.parameters())
    assert len(params) > 0, 'network has zero parameters — backward will be a no-op'
    optimizer = builder.build_optimizer(paradigm, cfg, network)
    loss_fn = builder.build_loss(paradigm, cfg)

    # Phase 3: real forward → backward → optimizer.step.
    network.train()
    batch_before = builder.build_batch(network, cfg)
    loss_result_before = loss_fn.compute(network, batch_before)
    loss_before = float(loss_result_before.loss.item())
    breakdown_before = dict(loss_result_before.breakdown)

    optimizer.zero_grad()
    loss_result_before.loss.backward()
    grad_norm = float(torch.nn.utils.clip_grad_norm_(network.parameters(), max_norm=10.0))
    # Backward must produce real grad on at least one param (else the
    # forward path detached somewhere and we're not really training).
    has_grad = any(p.grad is not None and p.grad.abs().sum().item() > 0 for p in params)
    assert has_grad, 'backward produced zero grad on all params — train loop is broken'
    optimizer.step()

    # Re-compute loss on a fresh batch after step (paradigm-specific
    # invariant may compare or just sanity-check non-NaN).
    network.eval()
    batch_after = builder.build_batch(network, cfg)
    with torch.no_grad():
        loss_result_after = loss_fn.compute(network, batch_after)
    loss_after = float(loss_result_after.loss.item())
    breakdown_after = dict(loss_result_after.breakdown)

    # Common sanity: loss is finite after step (NaN guard).
    assert loss_after == loss_after, f'loss became NaN after step (before={loss_before})'
    assert abs(loss_after) < 1e9, f'loss diverged after step: {loss_after}'

    report = TrainStepReport(
        loss_value_before=loss_before,
        loss_value_after=loss_after,
        grad_norm=grad_norm,
        breakdown_before=breakdown_before,
        breakdown_after=breakdown_after,
        network=network,
    )

    # Phase 4: eval probe (paradigm picks the right surface).
    probe = builder.eval_probe(paradigm, cfg, network)
    assert isinstance(probe, EvalProbeReport), f'eval_probe must return EvalProbeReport, got {type(probe).__name__}'

    # Phase 5: paradigm-specific invariant + wall budget.
    builder.paradigm_invariant(report, probe)

    wall = time.perf_counter() - t_start
    assert wall < SMOKE_WALL_HARD_LIMIT_S, (
        f'paradigm {builder.name!r} smoke exceeded wall budget: {wall:.1f}s > '
        f'{SMOKE_WALL_HARD_LIMIT_S}s (target ≤ {SMOKE_WALL_BUDGET_S}s per spec A1.5)'
    )
    # Stash wall time for parent assertion / reporting.
    setattr(builder, 'wall_seconds', wall)


# ----- Shared helpers for synthetic batch construction ----- #


def make_tiny_agent_cfg(
    *,
    n_counter_slots: int = 128,  # SHALL be >= N_STRUCTURAL (66) — struct_readout slices [:, :N_STRUCTURAL]
    n_hooks: int = 4,
    max_ops_per_hook: int = 8,
    max_actions: int = 6,
    d_model: int = 16,
    n_cross_layers: int = 1,
):
    """Tiny AgentConfig for all paradigms that consume the generic
    structural backbone (AZ / BC / DMC / CFR). PPO has its own flat
    MLP cfg path — see PPO builder for that.

    n_counter_slots SHALL be >= N_STRUCTURAL (66): the struct_readout
    block slices ``pos_by_sid[:, :N_STRUCTURAL]`` and feeds the
    gathered values into ``Linear(N_STRUCTURAL, d_model)`` — a smaller
    n_counter_slots produces shape (B, n_counter_slots) and the linear
    fails with a matmul mismatch.
    """
    from training.core.network import AgentConfig

    return AgentConfig(
        n_counter_slots=n_counter_slots,
        n_hooks=n_hooks,
        max_ops_per_hook=max_ops_per_hook,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=n_cross_layers,
        dropout=0.0,
    )


def make_structural_batch_dict(agent_cfg: Any, *, batch_size: int = 2, seed: int = 0) -> dict:
    """Build a single forward_batch dict matching the structural backbone
    contract (counter_values / hook_ir / typed_damage / ...). Used by
    AZ / BC / DMC builders. CFR pre-forwards so it doesn't need this.
    """
    import numpy as np

    from training.core.obs_constants import (
        DICE_COLOR_COUNT,
        OBS_ENEMY_SIZES,
        OBS_HAND_BUCKETS,
        OBS_MAX_CARD_TYPES,
        OBS_MAX_CHARS,
        OBS_MAX_SKILLS_PER_CHAR,
        OBS_META_SIZE,
        OBS_MODIFIER_LOG_FIELD_COUNT,
        OBS_MODIFIER_LOG_K_MOD,
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_RECENT_DAMAGE_FIELD_COUNT,
    )
    from training.tests._typed_obs_fixtures import (
        make_modifier_log_padding_np,
        make_recent_damage_padding_np,
    )

    rng = np.random.default_rng(seed)
    B = batch_size
    ncs = agent_cfg.n_counter_slots
    nh = agent_cfg.n_hooks
    mt = agent_cfg.max_ops_per_hook
    ma = agent_cfg.max_actions

    # IR-4: hook obs is now (B, nh, max_ops, fields_per_op=5) IR-op tensor.
    # Opcodes in [1, 14] (1-14 are real opcodes, 0 is OpNop pad).
    fpo = agent_cfg.fields_per_op
    hook_ir = rng.integers(1, 14, size=(B, nh, mt, fpo)).astype(np.int64)
    hook_mask = np.ones((B, nh), dtype=bool)

    # Padded recent_damage / modifier_log per typed_obs convention.
    rd_pad = make_recent_damage_padding_np(K=OBS_RECENT_DAMAGE_EVENTS)
    ml_pad = make_modifier_log_padding_np(K=OBS_RECENT_DAMAGE_EVENTS, K_mod=OBS_MODIFIER_LOG_K_MOD)
    recent_damage = np.broadcast_to(rd_pad, (B, OBS_RECENT_DAMAGE_EVENTS, OBS_RECENT_DAMAGE_FIELD_COUNT)).copy()
    modifier_log = np.broadcast_to(
        ml_pad, (B, OBS_RECENT_DAMAGE_EVENTS, OBS_MODIFIER_LOG_K_MOD, OBS_MODIFIER_LOG_FIELD_COUNT)
    ).copy()
    prepare_skill = np.full((B, 2, 2), -1.0, dtype=np.float32)

    # Counter sids in [0, n_counter_slots) (HookEmb uses 0 as canonical
    # null sid in the encoder; values aren't looked up against any
    # external dict here — see CounterEncoder for the actual contract).
    counter_sids = np.tile(np.arange(ncs, dtype=np.int64), (B, 1))
    counter_values = rng.standard_normal((B, ncs)).astype(np.float32)
    active_slot_mask = np.ones((B, ncs), dtype=bool)

    return {
        'counter_values': counter_values,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'hook_ir': hook_ir,
        'hook_mask': hook_mask,
        'card_buckets': rng.standard_normal((B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)).astype(np.float32),
        'enemy_sizes': rng.standard_normal((B, OBS_ENEMY_SIZES)).astype(np.float32),
        'meta': np.concatenate(
            (rng.standard_normal((B, OBS_META_SIZE - 1)), rng.integers(0, 2, (B, 1))), axis=1
        ).astype(np.float32),
        'action_refs': np.full((B, ma, 3), -1, dtype=np.int64),
        'action_payments': rng.standard_normal((B, ma, DICE_COLOR_COUNT)).astype(np.float32),
        'char_skill_refs': np.full((B, 2, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR), -1, dtype=np.int64),
        'definition_links': np.full((B, 1, 2), -1, dtype=np.int64),
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
    }


def make_dummy_cfg(paradigm_name: str, paradigm_dict: dict, *, seed: int = 42, device: str = 'cpu') -> Any:
    """Build a TrainingConfig-stub for protocol surface tests, matching
    the pattern from test_az_paradigm._build_minimal_az_cfg.

    Caller passes ``paradigm_dict`` (paradigm-specific cfg keys). For
    PPO that needs an env probe at make_network time, callers should
    build a real TrainingConfig instead (see PPO smoke builder).
    """
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    return TrainingConfig(
        meta=MetaCfg(seed=seed, paradigm=paradigm_name, run_label=f'smoke_{paradigm_name}', device=device),
        pipeline=PipelineCfg(mode='serial', num_actors=1),
        scenario=ScenarioCfg(
            team_0=['赤蝶'],
            team_1=['赤蝶'],
            pool=['v_legacy', 'test_basic'],
            max_rounds=10,
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            data_dir='data',
            deck_0=SMOKE_MIRROR_DECK,
            deck_1=SMOKE_MIRROR_DECK,
        ),
        paradigm=paradigm_dict,
        checkpoint=CheckpointCfg(save_every=1000, keep_last_n=3, artifacts_root='artifacts'),
    )
