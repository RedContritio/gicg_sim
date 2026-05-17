"""Multiprocess CFR traversal worker."""

from __future__ import annotations

import multiprocessing as mp
import random
import time
import traceback
from dataclasses import dataclass
from typing import Optional

import torch

from gicg_env import GicgEnv
from gicg_env.engine import preload_dsl
from training.paradigms.cfr._collect_helpers import (
    CFRGameBatch,
    CollectorBuffer,
    drain_single_traversal,
)
from training.paradigms.cfr.advantage_net import AdvantageNet
from training.paradigms.cfr.strategy_net import CFRNetConfig
from training.paradigms.cfr.traversal import CFRTraverser, TraversalConfig


@dataclass
class WorkItem:
    weights_per_player: list  # list[dict] of length 2
    n_traversals: int
    iteration: int
    seed_base: int
    traverser_seq: list


@dataclass
class WorkResult:
    worker_id: int
    batches: list  # list[CFRGameBatch]
    wall_s: float


@dataclass
class WorkError:
    worker_id: int
    traceback: str


@dataclass
class WorkerConfig:
    net_cfg: CFRNetConfig
    team_0: list
    team_1: list
    card_pool: Optional[list]
    data_dir: str
    traversal: TraversalConfig


def _make_env(
    cfg: WorkerConfig,
    seed: int,
) -> GicgEnv:
    env = GicgEnv(
        cfg.team_0,
        cfg.team_1,
        card_pool=cfg.card_pool,
        seed=seed,
        data_dir=cfg.data_dir,
    )
    env.reset(seed=seed)
    return env


def cfr_worker_main(
    worker_id: int,
    cfg: WorkerConfig,
    in_q: mp.Queue,
    out_q: mp.Queue,
) -> None:
    """Worker entrypoint. Runs until a None WorkItem is received."""
    try:
        preload_dsl(cfg.data_dir)
    except Exception:
        out_q.put(
            WorkError(
                worker_id=worker_id,
                traceback=traceback.format_exc(),
            )
        )
        return

    device = torch.device('cpu')
    nets = [
        AdvantageNet(cfg.net_cfg).to(device),
        AdvantageNet(cfg.net_cfg).to(device),
    ]
    for n in nets:
        n.eval()

    adv_cols = [CollectorBuffer(), CollectorBuffer()]
    strat_col = CollectorBuffer()
    val_col = CollectorBuffer()

    rng = random.Random(abs(hash(('cfr-worker-init', worker_id))))

    traverser = CFRTraverser(
        advantage_nets=nets,
        n_counter_slots=cfg.net_cfg.n_counter_slots,
        max_tokens_per_hook=cfg.net_cfg.max_tokens_per_hook,
        n_hooks_capacity=cfg.net_cfg.n_hooks,
        max_actions=cfg.net_cfg.max_actions,
        advantage_buffers=adv_cols,  # type: ignore[arg-type]
        strategy_buffer=strat_col,  # type: ignore[arg-type]
        value_buffer=val_col,  # type: ignore[arg-type]
        config=cfg.traversal,
        rng=rng,
        device=device,
    )

    while True:
        try:
            item = in_q.get()
        except (EOFError, KeyboardInterrupt):
            break
        if item is None:
            break

        t0 = time.perf_counter()
        try:
            if not isinstance(item, WorkItem):
                raise TypeError(f'worker {worker_id}: expected WorkItem, got {type(item)!r}')
            if len(item.traverser_seq) != item.n_traversals:
                raise ValueError(
                    f'worker {worker_id}: traverser_seq length '
                    f'{len(item.traverser_seq)} != n_traversals '
                    f'{item.n_traversals}'
                )

            if len(item.weights_per_player) != 2:
                raise ValueError(f'WorkItem.weights_per_player length must be 2, got {len(item.weights_per_player)}')
            for p in range(2):
                nets[p].load_state_dict(item.weights_per_player[p])
                nets[p].eval()

            rng.seed(abs(hash(('cfr-worker-iter', worker_id, item.iteration, item.seed_base))))

            for c in adv_cols:
                c.clear()
            strat_col.clear()
            val_col.clear()

            batches: list[CFRGameBatch] = []
            for k in range(item.n_traversals):
                seed = item.seed_base + k
                traverser_p = int(item.traverser_seq[k])
                env = _make_env(cfg, seed)
                try:
                    traverser.traverse(
                        env,
                        traverser_player=traverser_p,
                        iteration=item.iteration,
                    )
                finally:
                    env.close()
                batches.append(
                    drain_single_traversal(
                        adv_cols,
                        strat_col,
                        val_col,
                        traverser_p,
                    )
                )

            out_q.put(
                WorkResult(
                    worker_id=worker_id,
                    batches=batches,
                    wall_s=time.perf_counter() - t0,
                )
            )
        except Exception:
            out_q.put(
                WorkError(
                    worker_id=worker_id,
                    traceback=traceback.format_exc(),
                )
            )


def spawn_worker(
    worker_id: int,
    cfg: WorkerConfig,
    in_q: mp.Queue,
    out_q: mp.Queue,
) -> mp.Process:
    """Start a worker process and return the handle."""
    p = mp.Process(
        target=cfr_worker_main,
        args=(worker_id, cfg, in_q, out_q),
        name=f'cfr-worker-{worker_id}',
        daemon=True,
    )
    p.start()
    return p
