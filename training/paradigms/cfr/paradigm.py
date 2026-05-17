"""CFRParadigm — implements training.core.protocols.Paradigm for CFR.

Spec ref: paradigm-cfr/spec.md C1-C6. Bridges the unified pipeline
driver to the legacy `training.paradigms.cfr` OS-MCCFR implementation. Six
``make_*`` factories + ``step_schedule`` iter-based cadence.

Frozen-research tier (C6.1) — adapter exists for r008 reproducibility
(C6.2). New CFR training runs SHALL NOT launch without an OpenSpec
change unfreezing the tier (C6.3). The adapter does not block at the
code level (paradigm cannot know "is this a new run"); the contract is
enforced at the change-spec layer.

NOTE: CFR's buffer is paradigm-specific (two reservoirs — advantage[0/1]
+ strategy; spec C3.1). The unified driver's Buffer protocol returns
exactly one Buffer per paradigm, so this adapter returns a tiny
``_CFRBufferBundle`` that wraps the three reservoirs behind the Buffer
protocol — ``push`` routes by sample type, ``sample`` requires a
head-tagged ``Batch`` request (raises if called without the discriminator).
"""

from __future__ import annotations

import os
from typing import Any, Optional

import numpy as np
import torch

from training.paradigms.cfr._collect_helpers import ingest_batches
from training.paradigms.cfr.strategy_net import CFRNetConfig
from training.paradigms.cfr.reservoir import AdvantageBuffer, StrategyBuffer, ValueBuffer
from training.core.protocols import Batch, CollectorOutput, PipelineState, StepPlan
from training.paradigms.cfr.collector import CFRTraversalCollector
from training.paradigms.cfr.config import CFRParadigmConfig
from training.paradigms.cfr.loss import CFRLoss
from training.paradigms.cfr.network import CFRNetwork
from training.paradigms.cfr.policy import CFREpisodePolicy


class _CFRBufferBundle:
    """Wraps the three CFR reservoirs behind the Buffer protocol.

    push: dispatches CollectorOutput's ``cfr_batches`` runtime metric into
        advantage[0/1] + strategy + value reservoirs (via legacy
        ``ingest_batches``).
    sample: head-tagged. Caller passes ``batch_size`` only; head dispatch
        happens via ``sample_head(head, batch_size, ...)`` — direct
        protocol-level ``sample(batch_size)`` raises (would be ambiguous).
    """

    def __init__(
        self,
        advantage_capacity: int,
        strategy_capacity: int,
        value_capacity: int,
        max_actions: int,
        seed: int = 0,
    ) -> None:
        self.advantage_buffers = [
            AdvantageBuffer(capacity=advantage_capacity, max_actions=max_actions),
            AdvantageBuffer(capacity=advantage_capacity, max_actions=max_actions),
        ]
        self.strategy_buffer = StrategyBuffer(capacity=strategy_capacity, max_actions=max_actions)
        self.value_buffer = ValueBuffer(capacity=value_capacity)
        self.capacity = advantage_capacity + strategy_capacity + value_capacity
        import random

        self._rng = random.Random(seed)

    def __len__(self) -> int:
        return len(self.advantage_buffers[0]) + len(self.advantage_buffers[1]) + len(self.strategy_buffer)

    def push(self, batch: CollectorOutput) -> None:
        cfr_batches = batch.runtime_metrics.get('cfr_batches', [])
        if not cfr_batches:
            return
        ingest_batches(
            cfr_batches,
            advantage_buffers=self.advantage_buffers,
            strategy_buffer=self.strategy_buffer,
            value_buffer=self.value_buffer,
            rng=self._rng,
        )

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        """Protocol-level sample is ambiguous for CFR (3 reservoirs).
        Driver should call ``sample_head`` instead."""
        raise RuntimeError(
            '_CFRBufferBundle.sample: CFR buffer is 3-headed (advantage[0/1] + strategy); '
            'driver SHALL call sample_head(head, traverser_player?, batch_size) instead.'
        )

    def sample_head(self, head: str, batch_size: int, traverser_player: int = 0) -> Batch:
        """Head-tagged sample. Returns Batch.data with the raw reservoir
        dict (caller side runs network forward against it). Mirrors
        ``fit_advantage`` / ``fit_strategy_joint`` reservoir.sample shape."""
        if head == 'advantage':
            if traverser_player not in (0, 1):
                raise ValueError(f'sample_head: traverser_player must be 0/1 for advantage, got {traverser_player}')
            buf = self.advantage_buffers[traverser_player]
        elif head == 'strategy':
            buf = self.strategy_buffer
        elif head == 'value':
            buf = self.value_buffer
        else:
            raise ValueError(f"sample_head: head must be 'advantage'/'strategy'/'value', got {head!r}")
        if len(buf) == 0:
            raise RuntimeError(f"sample_head: '{head}' reservoir empty")
        raw = buf.sample(batch_size, self._rng)
        return Batch(data={'head': head, 'reservoir_batch': raw}, weights=None, size=batch_size)

    def clear(self) -> None:
        # CFR is not on-policy; clear only on explicit reset.
        for b in self.advantage_buffers:
            b.__init__(capacity=b.capacity, max_actions=b.max_actions)
        self.strategy_buffer.__init__(
            capacity=self.strategy_buffer.capacity, max_actions=self.strategy_buffer.max_actions
        )
        self.value_buffer.__init__(capacity=self.value_buffer.capacity)

    def state_dict(self) -> dict:
        return {
            'advantage_sizes': [len(b) for b in self.advantage_buffers],
            'strategy_size': len(self.strategy_buffer),
            'value_size': len(self.value_buffer),
        }

    def load_state_dict(self, sd: dict) -> None:
        # Reservoir persistence is via legacy save/load on each reservoir
        # individually — pipeline ckpt path will route through there.
        del sd


class CFRParadigm:
    """Top-level CFR paradigm adapter — frozen-research tier."""

    name = 'cfr'
    # C5.2 — traverser needs advantage net forward during traversal.
    requires_network_in_collect = True

    def __init__(self) -> None:
        self._pcfg: CFRParadigmConfig | None = None
        self._network: CFRNetwork | None = None

    def _resolve_pcfg(self, cfg: Any) -> CFRParadigmConfig:
        if self._pcfg is None:
            self._pcfg = CFRParadigmConfig.from_dict(cfg.paradigm)
        return self._pcfg

    def make_network(self, cfg: Any) -> CFRNetwork:
        """Build CFRNetwork with heads=(avg_policy, advantage). Spec C4."""
        pcfg = self._resolve_pcfg(cfg)
        net_cfg = CFRNetConfig(
            n_counter_slots=pcfg.agent.n_counter_slots,
            n_hooks=pcfg.agent.n_hooks,
            max_tokens_per_hook=pcfg.agent.max_tokens_per_hook,
            max_actions=pcfg.agent.max_actions,
            d_model=pcfg.agent.d_model,
            dropout=pcfg.agent.dropout,
            n_cross_layers=pcfg.agent.n_cross_layers,
        )
        torch.manual_seed(cfg.meta.seed)
        self._network = CFRNetwork(net_cfg, device=cfg.meta.device)
        return self._network

    def make_optimizer(self, cfg: Any, network: Any) -> Any:
        """One AdamW over all params (strategy_net + 2 advantage_nets).

        Note: legacy CFRTrainer used 3 separate Adam optimizers (1 per
        head). The driver's single-optimizer contract forces a join here;
        per-head lr can be recovered via param-group split if needed —
        the wrapper exposes the 3 submodules so a future enhancement
        could swap to ``torch.optim.AdamW([{params=..., lr=...}, ...])``.
        """
        pcfg = self._resolve_pcfg(cfg)
        return torch.optim.AdamW(
            network.parameters(),
            lr=pcfg.strategy_lr,
            weight_decay=0.0,
        )

    def make_buffer(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        # Smoke test infra dispatch — env-flag gated, production NEVER
        # sets this. Spec ref: paradigm-cfr/spec.md C6.4 (ADD by
        # cfr-driver-buffer-multihead-fix). Lazy import so production
        # CFR runs do not touch training/tests/* import chain.
        if os.environ.get('GICG_CFR_SMOKE_STUB_BUFFER') == '1':
            from training.tests._cfr_smoke_stub import _SmokeStubBuffer

            return _SmokeStubBuffer(
                max_actions=pcfg.agent.max_actions,
                capacity=max(pcfg.fit_batch_size * 10, 100),
            )
        return _CFRBufferBundle(
            advantage_capacity=pcfg.advantage_buffer_capacity,
            strategy_capacity=pcfg.strategy_buffer_capacity,
            value_capacity=pcfg.value_buffer_capacity,
            max_actions=pcfg.agent.max_actions,
            seed=cfg.meta.seed + 3,
        )

    def make_loss(self, cfg: Any) -> CFRLoss:
        pcfg = self._resolve_pcfg(cfg)
        return CFRLoss(pcfg)

    def make_collector(
        self,
        cfg: Any,
        env_factory: Any,
        network: Any,
        opp_pool: Any,
    ) -> CFRTraversalCollector:
        """Build serial traversal collector. ``opp_pool`` is unused — CFR
        traversal is symmetric selfplay (C5.3), no historical opponent."""
        del opp_pool  # spec C5.3 — both players share the network
        if env_factory is None:
            raise ValueError('CFRParadigm.make_collector: env_factory required (None passed)')
        pcfg = self._resolve_pcfg(cfg)
        return CFRTraversalCollector(cfg, pcfg, network, env_factory)

    def make_episode_policy(
        self,
        cfg: Any,
        instance_id: int = 0,
        deterministic: bool = False,
    ) -> CFREpisodePolicy:
        """Protocol stub — CFR does not rollout episodes (see policy.py)."""
        return CFREpisodePolicy(seed=cfg.meta.seed + 11 + instance_id, deterministic=deterministic)

    def make_opponent_pool(self, cfg: Any, network: Any) -> None:
        """C5.3 — CFR shares the network across both players, no opp_pool."""
        del cfg, network
        return None

    def step_schedule(self, state: PipelineState, cfg: Any) -> StepPlan:
        """Iter-based cadence: per outer iter, collect ``traversals_per_iteration``
        traversals, then fit advantage every iter + strategy every
        ``strategy_fit_every`` iters."""
        pcfg = self._resolve_pcfg(cfg)
        if state.step >= pcfg.n_iterations:
            return StepPlan(
                collect=False,
                n_episodes=0,
                train=False,
                n_train_batches=0,
                batch_size=pcfg.fit_batch_size,
                eval=False,
                advance_step=0,
            )
        # CFR has no buffer warm-up — first traversal seeds the reservoir
        # and the same iter runs fit_advantage on whatever landed (matches
        # legacy CFRTrainer.run_iteration shape).
        return StepPlan(
            collect=True,
            n_episodes=pcfg.traversals_per_iteration,
            train=True,
            n_train_batches=pcfg.advantage_fit_steps_per_iter,
            batch_size=pcfg.fit_batch_size,
            eval=True,
            advance_step=1,
        )
