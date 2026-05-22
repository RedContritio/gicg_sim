"""PPOParadigm — implements training.core.protocols.Paradigm for PPO.

Bridges the unified pipeline driver to the PPO components (rollout
+ clipped surrogate + GAE). Six make_* factories + step_schedule cadence.
PPO legacy stack retired in FU-W4-PPO — all logic now lives in this
adapter package.

Per ``ppo-structural-backbone-migration``: PPO now uses generic
structural ActorCritic backbone (via ``make_actor_critic`` inside
``PPOAgent``). ``_probe_obs_size`` removed (M4) — structural shape is
derived from ``pcfg.agent`` directly.

Spec ref: paradigm-ppo/spec.md P1-P6 + training-architecture SHALL #2
(Paradigm protocol).

Tier: ``frozen`` per P6.1 — closed by archived ``0008-rl-paradigm-pivot``.
Adapter exists for s021-s054 ablation reproducibility (P6.2 + D2). Not
expected to support new PPO production runs (P6.3).

PPO-specific cadence (vs DMC):
- On-policy: buffer SHALL be cleared every iter (P4.1)
- Each outer iter: 1 collect (rollout of n_games games) + n_epochs ×
  ⌈n_trans / minibatch_size⌉ minibatch trains
- No warm-up phase — collect-train interleave from iter 0
"""

from __future__ import annotations

from typing import Any

import torch

from training.core.buffer.rollout import RolloutBuffer
from training.core.network import AgentConfig
from training.core.protocols import PipelineState, StepPlan
from training.paradigms.ppo.collector import PPOAsyncCollector, PPORolloutCollector
from training.paradigms.ppo.config import PPOParadigmConfig
from training.paradigms.ppo.loss import PPOLoss
from training.paradigms.ppo.network import PPONetwork
from training.paradigms.ppo.policy import PPOEpisodePolicy


class PPOParadigm:
    """Top-level PPO paradigm. driver instantiates one per run.

    Holds the per-run PPONetwork (so make_collector + make_loss share
    the same network without rebuilding it)."""

    name = 'ppo'
    requires_network_in_collect = True

    def __init__(self) -> None:
        self._pcfg: PPOParadigmConfig | None = None
        self._network: PPONetwork | None = None

    # --- internal --------------------------------------------------- #

    def _resolve_pcfg(self, cfg: Any) -> PPOParadigmConfig:
        if self._pcfg is None:
            self._pcfg = PPOParadigmConfig.from_dict(cfg.paradigm)
        return self._pcfg

    # --- 7 Protocol make_* + step_schedule ------------------------- #

    def make_network(self, cfg: Any) -> Any:
        """Build PPONetwork (structural ActorCritic backbone via PPOAgent).

        Per M4: shape derived from pcfg.agent directly — no env probe."""
        pcfg = self._resolve_pcfg(cfg)
        agent_cfg = AgentConfig(
            n_counter_slots=pcfg.agent.n_counter_slots,
            n_hooks=pcfg.agent.n_hooks,
            max_ops_per_hook=pcfg.agent.max_ops_per_hook,
            max_actions=pcfg.agent.max_actions,
            d_model=pcfg.agent.d_model,
            dropout=pcfg.agent.dropout,
            n_cross_layers=pcfg.agent.n_cross_layers,
        )
        self._network = PPONetwork(agent_cfg, device=cfg.meta.device)
        return self._network

    def make_optimizer(self, cfg: Any, network: Any) -> Any:
        """PPO uses Adam (not AdamW — legacy ppo/train.py uses Adam)."""
        pcfg = self._resolve_pcfg(cfg)
        return torch.optim.Adam(network.parameters(), lr=pcfg.lr)

    def make_buffer(self, cfg: Any) -> Any:
        """PPO buffer = RolloutBuffer (on-policy, clear每 iter per P4.1)."""
        pcfg = self._resolve_pcfg(cfg)
        return RolloutBuffer(capacity=pcfg.buffer_cap)

    def make_loss(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return PPOLoss(pcfg)

    def make_collector(self, cfg: Any, env_factory: Any, network: Any, opp_pool: Any) -> Any:
        """Build collector by cfg.pipeline.mode。opp_pool ignored — PPO 用
        cfg.paradigm.rollout.rollout_opponent (string spec)。

        - mode='serial':PPORolloutCollector(legacy collect_rollout)。
        - mode='async':PPOAsyncCollector(FU-W3b-PPO — W3a core/actor 真 mp,
          frozen tier 简单接通,不投入 batched server)。
        """
        if getattr(cfg.pipeline, 'actor_backend', 'python') == 'go':
            raise ValueError(
                "PPOParadigm 不支持 actor_backend='go'(I29 Phase 2 pending);PPO 当前仅 Python actor backend。"
            )
        del opp_pool  # PPO uses string rollout_opponent, not OpponentPool
        pcfg = self._resolve_pcfg(cfg)
        mode = cfg.pipeline.mode
        if mode == 'serial':
            return PPORolloutCollector(cfg, pcfg, network, env_factory)
        if mode == 'async':
            return PPOAsyncCollector(cfg, pcfg, network, env_factory)
        raise ValueError(f'PPOParadigm.make_collector: unknown pipeline.mode={mode!r}')

    def make_episode_policy(self, cfg: Any, instance_id: int = 0, deterministic: bool = False) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return PPOEpisodePolicy(
            gamma=pcfg.gamma,
            gae_lambda=pcfg.gae_lambda,
            seed=cfg.meta.seed + 13 + instance_id,
            deterministic=deterministic,
        )

    def step_schedule(self, state: PipelineState, cfg: Any) -> StepPlan:
        """PPO cadence: per outer iter, collect full rollout + train
        n_epochs × minibatches. No warm-up (on-policy: data freshness
        is the contract).

        Per P4.1 on-policy invariant:每 steady iter set
        ``clear_buffer_after_train=True``,driver epilogue 调用
        ``buffer.clear()``(详 protocols.md § 4 on-policy buffer 契约 +
        ``ppo-buffer-clear-orchestration`` archive 2026-05-17)。终止
        empty-plan 分支不 set(无 train,无意义)。"""
        pcfg = self._resolve_pcfg(cfg)
        # Stop when total_iterations reached.
        if state.step >= pcfg.total_iterations:
            return StepPlan(
                collect=False,
                n_episodes=0,
                train=False,
                n_train_batches=0,
                batch_size=pcfg.batch_size,
                eval=False,
                advance_step=0,
            )
        # Steady: 1 rollout (n_games_per_iter games) + n_epochs minibatch
        # trains. n_train_batches here is the TOTAL minibatch count for
        # one PPO iter (driver loops train_steps over this number).
        return StepPlan(
            collect=True,
            n_episodes=pcfg.rollout.n_games_per_iter,
            train=True,
            n_train_batches=pcfg.n_epochs,  # actual #updates = n_epochs × ⌈N/mb⌉, driver handles inner mb loop
            batch_size=pcfg.minibatch_size,
            eval=True,
            advance_step=1,
            clear_buffer_after_train=True,  # P4.1 on-policy buffer clear epilogue
        )
