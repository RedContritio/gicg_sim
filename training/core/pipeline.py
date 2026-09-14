"""Pipeline driver — paradigm-agnostic main loop.

Spec: ``openspec/specs/training-architecture/pipeline.md``.

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
from training.core.perf import trace
from training.core.protocols import Paradigm, PipelineState, StepPlan


def _maybe_sync_weights(plan: StepPlan, collector: Any, network: Any) -> None:
    """Republish trained weights when an async collector requests it."""
    if plan.sync_weights and hasattr(collector, 'sync_weights'):
        collector.sync_weights(network)


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
    artifacts_timestamp_utc: Optional[str] = None,
    prebuilt_artifacts_dir: Optional[Path] = None,
) -> PipelineState:
    """Main driver loop.

    Args:
        cfg: TrainingConfig (validated).
        paradigm: Paradigm impl.
        env_factory: callable from game index to a fresh environment.
        opp_pool: OpponentPool instance.
        eval_server: EvalServer for periodic eval (None to disable).
        resume_from: optional ckpt path to resume.
        train_provider: NetworkProvider used during train-time forward
            (collector's own provider may differ in async mode).
        max_steps: cap state.step for tests (None = unlimited).
        artifacts_timestamp_utc: optional `%Y%m%d%H%M` prefix for the
            fallback artifacts directory. ``tools.runs.train`` uses a
            prebuilt directory instead.
        prebuilt_artifacts_dir: optional existing dir created by the
            caller — Phase A of ``tools.runs.train`` already mkdir's the
            atomic per-run dir (``artifacts/<ts>_<NNN>_<label>/``).
            Mutually exclusive with both
            ``resume_from`` and ``artifacts_timestamp_utc``.
    Returns:
        final PipelineState (also persisted by CheckpointManager).
    """
    network = paradigm.make_network(cfg)
    optimizer = paradigm.make_optimizer(cfg, network)
    buffer = paradigm.make_buffer(cfg)
    loss_fn = paradigm.make_loss(cfg)
    collector = paradigm.make_collector(cfg, env_factory, network, opp_pool)

    ckpt_mgr = CheckpointManager(cfg, network, optimizer, buffer)
    if getattr(collector, 'checkpoint_complete', False):
        ckpt_mgr.runtime_components = {'buffer': buffer, 'collector': collector}
        if opp_pool is not None:
            ckpt_mgr.runtime_components['opponents'] = opp_pool
    artifacts_dir = ckpt_mgr.init_artifacts_dir(
        resume_from=resume_from,
        timestamp_utc=artifacts_timestamp_utc,
        prebuilt=prebuilt_artifacts_dir,
    )
    ckpt_mgr.save_cfg_snapshot()
    logger = MetricsLogger(artifacts_dir)
    # Give collectors with server-side metrics a logger sink.
    if hasattr(collector, 'attach_metrics_logger'):
        collector.attach_metrics_logger(logger)
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
                # `plan.collect` is the gate. Dataset collectors may use
                # `n_episodes=0`; episode collectors interpret it as units.
                provider = train_provider or _default_provider(network, cfg)
                with trace.span('pipeline.collect'):
                    out = collector.collect(plan.n_episodes, provider)
                with trace.span('pipeline.buffer_push'):
                    buffer.push(out)
                state.after_collect(out)

            if plan.train and plan.n_train_batches > 0:
                for _ in range(plan.n_train_batches):
                    if len(buffer) < plan.batch_size:
                        break
                    with trace.span('pipeline.buffer_sample'):
                        batch = buffer.sample(plan.batch_size)
                    optimizer.zero_grad()
                    with trace.span('pipeline.loss_compute'):
                        loss_result = loss_fn.compute(network, batch)
                    with trace.span('pipeline.backward'):
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
                    with trace.span('pipeline.optim_step'):
                        optimizer.step()
                    state.after_train(loss_result.breakdown)
                    logger.add_scalar('train/loss', float(loss_result.loss.item()), state.train_steps)

            # Republish weights before the next async collection round.
            _maybe_sync_weights(plan, collector, network)

            # On-policy paradigms clear consumed data before the next iteration.
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

            save_due = ckpt_mgr.should_save(state)
            if save_due:
                state.after_ckpt()
                # Snapshot tensors must be cloned: state_dict returns live
                # references that would otherwise change with the network.
                if opp_pool is not None and hasattr(opp_pool, 'add_snapshot'):
                    snapshot_sd = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
                    opp_pool.add_snapshot(snapshot_sd)

            logger.log_iter(state, breakdown={})
            state.advance(plan)
            if save_due:
                # Save the next decision boundary, including the just-added
                # historical opponent, rather than repeating this iteration.
                ckpt_mgr.save(state)

            if not plan.collect and not plan.train and not plan.eval:
                # Paradigm signaled completion via empty plan.
                break
        state.wall_seconds = time.perf_counter() - t_start
        ckpt_mgr.save(state)
    finally:
        # A partially failed iteration must not overwrite a resumable boundary.
        collector.close()
        logger.close()
        trace.close()

    return state


def _default_provider(network, cfg):
    """Wrap network in a LocalNetworkProvider for serial-mode train forward."""
    from training.core.actor.network_provider import LocalNetworkProvider

    return LocalNetworkProvider(network, device=cfg.meta.device)
