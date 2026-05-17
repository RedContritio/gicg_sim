"""CFR training loop: ties together traversal + buffers + networks.

Fit steps live in ``training.paradigms.cfr.fit_steps`` so this file stays below
the line-limit.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import torch

from gicg_env import GicgEnv
from training.paradigms.cfr.fit_steps import fit_advantage, fit_strategy_joint
from training.paradigms.cfr.advantage_net import AdvantageNet
from training.paradigms.cfr.strategy_net import CFRNetConfig, CFRStrategyNet
from training.paradigms.cfr.reservoir import (
    AdvantageBuffer,
    StrategyBuffer,
    ValueBuffer,
)
from training.paradigms.cfr.traversal import CFRTraverser, TraversalConfig


@dataclass
class CFRTrainConfig:
    n_iterations: int = 100
    traversals_per_iteration: int = 64
    traverser_alternation: str = 'alternate'

    advantage_fit_steps_per_iter: int = 32
    advantage_lr: float = 1e-3
    advantage_reset_each_iter: bool = False

    strategy_fit_every: int = 4
    strategy_fit_steps: int = 64
    strategy_lr: float = 1e-3
    value_loss_alpha: float = 1.0

    grad_clip_max_norm: float = 1.0

    advantage_buffer_capacity: int = 100_000
    strategy_buffer_capacity: int = 200_000
    value_buffer_capacity: int = 100_000

    fit_batch_size: int = 128

    checkpoint_every: int = 10
    checkpoint_dir: Optional[str] = None

    traversal: TraversalConfig = field(default_factory=TraversalConfig)

    seed: int = 0


@dataclass
class IterationMetrics:
    iteration: int
    wall_s: float
    n_traversals: int
    advantage_loss: float
    strategy_loss: Optional[float]
    value_loss: Optional[float]
    buffer_sizes: dict

    def to_dict(self) -> dict:
        return {
            'iteration': self.iteration,
            'wall_s': round(self.wall_s, 2),
            'n_traversals': self.n_traversals,
            'advantage_loss': round(float(self.advantage_loss), 5),
            'strategy_loss': (round(float(self.strategy_loss), 5) if self.strategy_loss is not None else None),
            'value_loss': (round(float(self.value_loss), 5) if self.value_loss is not None else None),
            'buffer_sizes': self.buffer_sizes,
        }


class CFRTrainer:
    """Sequential CFR training controller."""

    def __init__(
        self,
        net_cfg: CFRNetConfig,
        train_cfg: CFRTrainConfig,
        env_factory: Callable[[int], GicgEnv],
        device: Optional[torch.device] = None,
    ):
        self.net_cfg = net_cfg
        self.train_cfg = train_cfg
        self.env_factory = env_factory
        self.device = device if device is not None else torch.device('cpu')

        torch.manual_seed(train_cfg.seed)
        self.advantage_nets = [
            AdvantageNet(net_cfg).to(self.device),
            AdvantageNet(net_cfg).to(self.device),
        ]
        self.strategy_net = CFRStrategyNet(net_cfg).to(self.device)

        self.adv_optimizers = [torch.optim.Adam(n.parameters(), lr=train_cfg.advantage_lr) for n in self.advantage_nets]
        self.strat_optimizer = torch.optim.Adam(
            self.strategy_net.parameters(),
            lr=train_cfg.strategy_lr,
        )

        self.advantage_buffers = [
            AdvantageBuffer(
                capacity=train_cfg.advantage_buffer_capacity,
                max_actions=net_cfg.max_actions,
            )
            for _ in range(2)
        ]
        self.strategy_buffer = StrategyBuffer(
            capacity=train_cfg.strategy_buffer_capacity,
            max_actions=net_cfg.max_actions,
        )
        self.value_buffer = ValueBuffer(
            capacity=train_cfg.value_buffer_capacity,
        )

        self.rng = random.Random(train_cfg.seed)

        self.traverser = CFRTraverser(
            advantage_nets=self.advantage_nets,
            n_counter_slots=net_cfg.n_counter_slots,
            max_tokens_per_hook=net_cfg.max_tokens_per_hook,
            n_hooks_capacity=net_cfg.n_hooks,
            max_actions=net_cfg.max_actions,
            advantage_buffers=self.advantage_buffers,
            strategy_buffer=self.strategy_buffer,
            value_buffer=self.value_buffer,
            config=train_cfg.traversal,
            rng=self.rng,
            device=self.device,
        )

        self.metrics_log: list[IterationMetrics] = []

    def run_iteration(self, iteration: int) -> IterationMetrics:
        t0 = time.perf_counter()

        self._run_traversals(iteration)
        adv_loss = fit_advantage(self, iteration)

        strat_loss: Optional[float] = None
        value_loss: Optional[float] = None
        if iteration > 0 and iteration % self.train_cfg.strategy_fit_every == 0:
            strat_loss, value_loss = fit_strategy_joint(self)
            if strat_loss is None and value_loss is None:
                strat_loss = float('nan')
                value_loss = float('nan')

        m = IterationMetrics(
            iteration=iteration,
            wall_s=time.perf_counter() - t0,
            n_traversals=self.train_cfg.traversals_per_iteration,
            advantage_loss=adv_loss,
            strategy_loss=strat_loss,
            value_loss=value_loss,
            buffer_sizes={
                'advantage_p0': len(self.advantage_buffers[0]),
                'advantage_p1': len(self.advantage_buffers[1]),
                'strategy': len(self.strategy_buffer),
                'value': len(self.value_buffer),
            },
        )
        self.metrics_log.append(m)
        return m

    def _run_traversals(self, iteration: int) -> None:
        for net in self.advantage_nets:
            net.eval()
        for k in range(self.train_cfg.traversals_per_iteration):
            seed = 1_000_000 * iteration + k
            env = self.env_factory(seed)
            try:
                traverser_player = self._pick_traverser(iteration, k)
                self.traverser.traverse(
                    env,
                    traverser_player=traverser_player,
                    iteration=iteration,
                )
            finally:
                env.close()

    def _pick_traverser(self, iteration: int, k: int) -> int:
        mode = self.train_cfg.traverser_alternation
        if mode == 'alternate':
            return k % 2
        if mode == 'random':
            return self.rng.randint(0, 1)
        raise ValueError(f'unknown traverser_alternation: {mode!r}')

    def save_checkpoint(self, iteration: int) -> Optional[str]:
        """Save CFRStrategyNet — the deliverable."""
        if self.train_cfg.checkpoint_dir is None:
            return None
        if iteration == 0:
            return None
        root = Path(self.train_cfg.checkpoint_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f'cfr_strategy_iter{iteration:06d}.pt'
        self.strategy_net.save(str(path))
        return str(path)

    def train(self) -> list[IterationMetrics]:
        """Run all iterations."""
        try:
            for i in range(self.train_cfg.n_iterations):
                m = self.run_iteration(i)
                if self.train_cfg.checkpoint_every > 0 and (
                    i % self.train_cfg.checkpoint_every == 0 or i == self.train_cfg.n_iterations - 1
                ):
                    self.save_checkpoint(i)
            return self.metrics_log
        except KeyboardInterrupt:
            if self.metrics_log:
                self.save_checkpoint(self.metrics_log[-1].iteration)
            raise
