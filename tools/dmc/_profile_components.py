"""Component construction + iteration body for the DMC full-train profiler.

Split out of :mod:`tools.dmc.profile_train` to keep both modules inside the
per-file line limit. The two functions here deliberately mirror
``training.core.pipeline.run_pipeline`` so the profiler measures the real
training loop rather than an approximation of it — keep them in sync when that
loop changes.
"""

from __future__ import annotations

from typing import Any

import torch


def build_full_components(cfg: Any) -> tuple[Any, Any, Any, Any, Any, Any, Any, Any]:
    """Mirror tools.runs._train.dispatch.run_paradigm_train +
    training.core.pipeline.run_pipeline construction shape — full
    training loop (collector + buffer + optimizer + loss + network).

    Returns (state, paradigm, collector, provider, buffer, optimizer,
    loss_fn, network).
    """
    from training.core.actor.network_provider import LocalNetworkProvider
    from training.core.env_factory import make_env_factory
    from training.core.protocols import PipelineState
    from training.paradigms import resolve as resolve_paradigm

    paradigm = resolve_paradigm(cfg.meta.paradigm)
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)

    network = paradigm.make_network(cfg)
    opp_pool = paradigm.make_opponent_pool(cfg, network) if hasattr(paradigm, 'make_opponent_pool') else None
    collector = paradigm.make_collector(cfg, env_factory, network, opp_pool)
    provider = LocalNetworkProvider(network, device=cfg.meta.device)

    optimizer = paradigm.make_optimizer(cfg, network)
    buffer = paradigm.make_buffer(cfg)
    loss_fn = paradigm.make_loss(cfg)

    state = PipelineState.fresh(cfg.meta.seed)
    return state, paradigm, collector, provider, buffer, optimizer, loss_fn, network


def run_one_iter(
    state: Any,
    cfg: Any,
    paradigm: Any,
    collector: Any,
    provider: Any,
    buffer: Any,
    optimizer: Any,
    loss_fn: Any,
    network: Any,
    counters: dict,
) -> None:
    """Mirror training.core.pipeline.run_pipeline main loop body MINUS
    ckpt / eval / log / nan_guard branches. Only collect + train_step +
    state.after_* are exercised.
    """
    plan = paradigm.step_schedule(state, cfg)

    if plan.collect:
        out = collector.collect(plan.n_episodes, provider)
        buffer.push(out)
        state.after_collect(out)
        counters['n_collect_calls'] += 1
        counters['n_transitions'] += int(out.n_units or out.n_transitions)

    if plan.train and plan.n_train_batches > 0:
        for _ in range(plan.n_train_batches):
            if len(buffer) < plan.batch_size:
                break
            batch = buffer.sample(plan.batch_size)
            optimizer.zero_grad()
            loss_result = loss_fn.compute(network, batch)
            loss_result.loss.backward()
            torch.nn.utils.clip_grad_norm_(
                network.parameters(),
                cfg.paradigm.get('max_grad_norm', 1.0),
            )
            optimizer.step()
            state.after_train(loss_result.breakdown)
            counters['n_train_steps'] += 1

    if plan.clear_buffer_after_train:
        buffer.clear()

    state.advance(plan)
