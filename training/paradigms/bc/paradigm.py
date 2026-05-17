"""BCParadigm — implements training.core.protocols.Paradigm for BC.

Bridges the unified pipeline driver to BC static-dataset training. First-
class per D1 decision (paradigm-bc/spec.md BC6.1) — abstracted from
``training/paradigms/bc/legacy/bc_*.py``(physical dedupe shipped in
P5-E,az + ppo BC legacy 已统一落到 bc/legacy/)。

Key deltas from RL paradigms(AZ / DMC / PPO):
 - ``requires_network_in_collect = False``(BC3.3) — driver SHALL NOT
   build NetworkProvider on BC collect path
 - No EpisodeRunner — DatasetCollector 一次性 push 全 dataset(BC3.1)
 - 1 head only(policy);value head 可在 ckpt 但 not trained when
   ``value_coef = 0.0``(BC4.1)
 - step_schedule:每 outer iter = 1 epoch over dataset(
   epoch_steps = dataset_size // batch_size);state.iter < n_epochs

Spec ref: paradigm-bc/spec.md BC1-BC6 + training-architecture SHALL #2.
"""

from __future__ import annotations

from typing import Any, Optional

import torch

from training.core.buffer.dataset import DatasetBuffer
from training.core.protocols import PipelineState, StepPlan
from training.paradigms.bc.collector import DatasetCollector
from training.paradigms.bc.config import BCParadigmConfig
from training.paradigms.bc.loss import BCLoss
from training.paradigms.bc.network import BCNetwork


class BCParadigm:
    """Top-level BC paradigm. driver instantiates one per run.

    Holds per-run BCNetwork + DatasetCollector(so make_buffer can size
    itself from dataset size,make_loss can read fields from collector)。
    """

    name = 'bc'
    requires_network_in_collect = False  # BC3.3 — no env episode loop

    def __init__(self) -> None:
        self._pcfg: Optional[BCParadigmConfig] = None
        self._network: Optional[BCNetwork] = None
        self._collector: Optional[DatasetCollector] = None

    # --- internal --------------------------------------------------- #

    def _resolve_pcfg(self, cfg: Any) -> BCParadigmConfig:
        if self._pcfg is None:
            self._pcfg = BCParadigmConfig.from_dict(cfg.paradigm)
        return self._pcfg

    def _resolve_collector(self, cfg: Any) -> DatasetCollector:
        """Lazy-build collector — BCDataset NPZ load is expensive (~GB)
        so we defer until first make_collector / make_buffer call."""
        if self._collector is None:
            pcfg = self._resolve_pcfg(cfg)
            self._collector = DatasetCollector(
                dataset_path=pcfg.dataset_path,
                n_counter_slots=pcfg.agent.n_counter_slots,
                n_hooks=pcfg.agent.n_hooks,
                max_tokens_per_hook=pcfg.agent.max_tokens_per_hook,
            )
        return self._collector

    # --- 7 Protocol make_* + step_schedule ------------------------- #

    def make_network(self, cfg: Any) -> Any:
        """Build BCNetwork (ActorCritic wrapper)。BC4.2: encoder paradigm-
        agnostic,policy head dims match other paradigms."""
        pcfg = self._resolve_pcfg(cfg)
        self._network = BCNetwork(pcfg.agent, device=cfg.meta.device)
        return self._network

    def make_optimizer(self, cfg: Any, network: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return torch.optim.Adam(
            network.parameters(),
            lr=pcfg.lr,
            weight_decay=pcfg.weight_decay,
        )

    def make_buffer(self, cfg: Any) -> Any:
        """DatasetBuffer sized to dataset。capacity = max(buffer_cap,
        dataset_size) so push 不溢出。

        Pass ``collector.build_batch`` as ``batch_builder`` so
        ``buffer.sample`` returns ``Batch(data={'fields': ...})``
        compatible with ``BCLoss.compute`` (which reads
        ``batch.data['fields']`` — see paradigm-bc/spec.md BC2)。
        """
        pcfg = self._resolve_pcfg(cfg)
        collector = self._resolve_collector(cfg)
        n = len(collector.dataset)
        capacity = max(pcfg.buffer_cap, n)
        return DatasetBuffer(capacity=capacity, batch_builder=collector.build_batch)

    def make_loss(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return BCLoss(pcfg)

    def make_collector(self, cfg: Any, env_factory: Any, network: Any, opp_pool: Any) -> Any:
        """BC collector ignores env_factory / network / opp_pool —
        static dataset only。BC1.1 / BC1.3."""
        del env_factory, network, opp_pool
        return self._resolve_collector(cfg)

    def make_episode_policy(self, cfg: Any, instance_id: int = 0, deterministic: bool = False) -> Any:
        """BC5.1 — argmax-logits policy。BC paradigm SHALL NOT 调
        EpisodeRunner 在训练 path(BC5.2);此 factory 仅供 eval 路径用。
        """
        # Lazy import to keep module light
        from training.paradigms.bc.policy import BCArgmaxPolicy

        del instance_id
        return BCArgmaxPolicy(deterministic=deterministic)

    def make_opponent_pool(self, cfg: Any, network: Any) -> Any:
        """BC has no opponent — static dataset training。tools/run.py
        SHALL NOT call this for BC paradigm,but expose stub for
        protocol uniformity。"""
        del cfg, network
        return None

    def step_schedule(self, state: PipelineState, cfg: Any) -> StepPlan:
        """Cadence: 每 outer iter = 1 epoch over dataset。

        - iter 0: collect(one-shot push 全 dataset)+ train epoch
        - iter 1..n_epochs-1: train epoch only(collect 是 no-op,n_units=0)
        - iter ≥ n_epochs: stop

        epoch_steps = dataset_size // batch_size。
        """
        pcfg = self._resolve_pcfg(cfg)
        collector = self._resolve_collector(cfg)
        dataset_size = len(collector.dataset)
        epoch_steps = max(1, dataset_size // pcfg.batch_size)

        if state.step >= pcfg.n_epochs:
            return StepPlan(
                collect=False,
                n_episodes=0,
                train=False,
                n_train_batches=0,
                batch_size=pcfg.batch_size,
                eval=False,
                advance_step=0,
            )

        # iter 0:must collect(one-shot push);subsequent iters skip
        # collect because dataset 已 exhausted。
        need_collect = state.step == 0
        return StepPlan(
            collect=need_collect,
            n_episodes=0,  # BC has no env episodes
            train=True,
            n_train_batches=epoch_steps,
            batch_size=pcfg.batch_size,
            eval=True,
            advance_step=1,
        )
