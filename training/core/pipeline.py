"""Pipeline driver — paradigm-agnostic main loop.

Spec: design/pipeline-driver.md.

``run_pipeline(cfg, paradigm)`` orchestrates collect → train → eval →
ckpt by calling the 6 Protocol methods. Paradigm-specific cadence
lives in ``paradigm.step_schedule()``.

Driver knows nothing about MCTS / Q-learning / CFR / PPO — every
deviation goes through StepPlan flags + breakdown dicts.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import torch

from training.core.checkpoint import CheckpointManager
from training.core.config.base import TrainingConfig
from training.core.eval.periodic import PeriodicEvalScheduler
from training.core.logging import MetricsLogger
from training.core.nan_guard import NaNGuard
from training.core.protocols import Paradigm, PipelineState


def run_pipeline(
    cfg: TrainingConfig,
    paradigm: Paradigm,
    *,
    env_factory: Any = None,
    opp_pool: Any = None,
    eval_server: Any = None,
    resume_from: Optional[Path] = None,
    train_provider: Any = None,
    max_steps: Optional[int] = None,
) -> PipelineState:
    """Main driver loop.

    Args:
        cfg: TrainingConfig (validated).
        paradigm: Paradigm impl.
        env_factory: callable game_idx → env (P3-A: caller builds, P3-B
            wires from cfg automatically).
        opp_pool: OpponentPool instance.
        eval_server: EvalServer for periodic eval (None to disable).
        resume_from: optional ckpt path to resume.
        train_provider: NetworkProvider used during train-time forward
            (collector's own provider may differ in async mode).
        max_steps: cap state.step for tests (None = unlimited).
    Returns:
        final PipelineState (also persisted by CheckpointManager).
    """
    network = paradigm.make_network(cfg)
    optimizer = paradigm.make_optimizer(cfg, network)
    buffer = paradigm.make_buffer(cfg)
    loss_fn = paradigm.make_loss(cfg)
    collector = paradigm.make_collector(cfg, env_factory, network, opp_pool)

    ckpt_mgr = CheckpointManager(cfg, network, optimizer, buffer)
    artifacts_dir = ckpt_mgr.init_artifacts_dir(resume_from=resume_from)
    ckpt_mgr.save_cfg_snapshot()
    logger = MetricsLogger(artifacts_dir)
    nan_guard = NaNGuard(artifacts_dir)

    eval_scheduler = None
    if eval_server is not None and cfg.eval is not None:
        eval_scheduler = PeriodicEvalScheduler(cfg.eval.schedule)

    state = (
        ckpt_mgr.try_resume(resume_from, device=cfg.meta.device)
        if resume_from is not None
        else PipelineState.fresh(cfg.meta.seed)
    )

    t_start = time.perf_counter()
    try:
        while max_steps is None or state.step < max_steps:
            plan = paradigm.step_schedule(state, cfg)

            if plan.collect:
                # Gate by `plan.collect` only — `plan.n_episodes` is a
                # collector-internal contract (paradigm-aware metadata),
                # NOT a driver-side gate. Dataset-driven paradigm (BC)
                # legitimately emit `n_episodes=0` since they have no
                # episode concept; their DatasetCollector.collect ignores
                # n_units and one-shot pushes the full static dataset.
                # Episode-driven paradigm (AZ/DMC/PPO/CFR) always emit
                # `n_episodes > 0` when collect=True → bit-identical
                # behavior. See specs/training-architecture/pipeline.md §3 #7.
                provider = train_provider or _default_provider(network, cfg)
                out = collector.collect(plan.n_episodes, provider)
                buffer.push(out)
                state.after_collect(out)

            if plan.train and plan.n_train_batches > 0:
                for _ in range(plan.n_train_batches):
                    if len(buffer) < plan.batch_size:
                        break
                    batch = buffer.sample(plan.batch_size)
                    optimizer.zero_grad()
                    loss_result = loss_fn.compute(network, batch)
                    loss_result.loss.backward()
                    grad_norm = torch.nn.utils.clip_grad_norm_(
                        network.parameters(),
                        cfg.paradigm.get('max_grad_norm', 1.0),
                    )
                    nan_guard.check(
                        loss_result.loss,
                        grad_norm,
                        batch=batch.data if isinstance(batch.data, dict) else None,
                        network=network,
                        optimizer=optimizer,
                        state_snapshot=state.snapshot(),
                        train_step=state.train_steps,
                    )
                    optimizer.step()
                    state.after_train(loss_result.breakdown)
                    logger.add_scalar('train/loss', float(loss_result.loss.item()), state.train_steps)

            # On-policy paradigm(PPO)epilogue per protocols.md § 4 / paradigm-
            # ppo § P4.1:per-iter buffer.clear after train(before eval/ckpt
            # so next iter's collect 写入空 buffer)。Off-policy/dataset-driven
            # paradigm 默认 False,此分支 no-op。
            if plan.clear_buffer_after_train:
                buffer.clear()

            if plan.eval and eval_scheduler is not None and eval_scheduler.due(state):
                jobs = eval_scheduler.jobs
                if eval_server is not None and jobs:
                    reports = eval_server.run_jobs(jobs)
                    for opp_id, report in reports.items():
                        logger.log_eval(state, report)
                    state.after_eval()
                    eval_scheduler.mark_done(state)

            if ckpt_mgr.should_save(state):
                ckpt_mgr.save(state)
                state.after_ckpt()

            logger.log_iter(state, breakdown={})
            state.advance(plan)

            if not plan.collect and not plan.train and not plan.eval:
                # Paradigm signaled completion via empty plan.
                break
    finally:
        state.wall_seconds = time.perf_counter() - t_start
        ckpt_mgr.save(state)
        collector.close()
        logger.close()

    return state


def _default_provider(network, cfg):
    """Wrap network in a LocalNetworkProvider for serial-mode train forward."""
    from training.core.actor.network_provider import LocalNetworkProvider

    return LocalNetworkProvider(network, device=cfg.meta.device)
