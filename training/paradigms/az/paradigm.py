"""AZParadigm — implements training.core.protocols.Paradigm for AlphaZero.

Seven make_* factories + step_schedule cadence. Drives the unified
pipeline collectors: serial ``AZSelfPlayCollector`` or async
``AZAsyncCollector`` (N actors + shared InferenceServer) per
``cfg.pipeline.mode`` — see collector.AZAsyncCollector docstring.

Spec ref: paradigm-az/spec.md A1-A6 + training-architecture/spec.md
SHALL #2 (Paradigm protocol).
"""

from __future__ import annotations

from training.core.artifact_io import load_checkpoint

from typing import Any

import torch

from training.core.protocols import PipelineState, StepPlan, async_sync_weights_due
from training.core.network import AgentConfig
from training.paradigms.az.buffer import AZBuffer
from training.paradigms.az.collector import AZAsyncCollector, AZSelfPlayCollector
from training.paradigms.az.config import AZParadigmConfig
from training.paradigms.az.loss import AZLoss
from training.paradigms.az.network import AZNetwork
from training.paradigms.az.policy import AZEpisodePolicy


class AZParadigm:
    """Top-level AZ paradigm. driver instantiates one per run.

    Holds the per-run AZNetwork (so make_collector + make_loss share
    the same agent without rebuilding). Same stateful retention pattern
    as DMCParadigm — protocol allows it (``make_network`` is called
    once by driver, then the same instance flows to make_optimizer +
    make_loss + make_collector).
    """

    name = 'az'
    requires_network_in_collect = True

    def __init__(self) -> None:
        self._pcfg: AZParadigmConfig | None = None
        self._network: AZNetwork | None = None

    # --- internal --------------------------------------------------- #

    def _resolve_pcfg(self, cfg: Any) -> AZParadigmConfig:
        if self._pcfg is None:
            self._pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        return self._pcfg

    # --- 7 Protocol make_* + step_schedule -------------------------- #

    def make_network(self, cfg: Any) -> Any:
        """Build AZNetwork around the policy, value, and delta ActorCritic heads."""
        pcfg = self._resolve_pcfg(cfg)
        agent_cfg = AgentConfig.from_obs_shape(pcfg.agent)
        self._network = AZNetwork(agent_cfg, device=cfg.meta.device, lr=pcfg.lr)
        # BC warm-start (spec A6 reproducibility) — load if cfg asks.
        if pcfg.init_from_ckpt:
            self._load_init_ckpt(self._network, pcfg.init_from_ckpt)
        return self._network

    @staticmethod
    def _load_init_ckpt(network: AZNetwork, ckpt_path: str) -> None:
        """Load BC warm-start ckpt into the network's ActorCritic.

        Accepts a CheckpointManager payload with a ``net`` entry or a plain
        state dict."""
        blob = load_checkpoint(ckpt_path, map_location='cpu', weights_only=True)
        state = blob['net'] if isinstance(blob, dict) and 'net' in blob else blob
        network.load_net_only(state)
        print(f'[az_paradigm] init_from_ckpt: loaded BC pretrain from {ckpt_path}')

    def make_optimizer(self, cfg: Any, network: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return torch.optim.AdamW(
            network.parameters(),
            lr=pcfg.lr,
            weight_decay=pcfg.weight_decay,
        )

    def make_buffer(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return AZBuffer(
            capacity=pcfg.buffer_cap,
            priority_weight=pcfg.priority_weight,
            seed=cfg.meta.seed + 7,
        )

    def make_loss(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return AZLoss(pcfg)

    def make_collector(self, cfg: Any, env_factory: Any, network: Any, opp_pool: Any) -> Any:
        """Serial selfplay collector (spec A5).

        env_factory: callable(game_idx) → GicgEnv, built by tools.runs.train.
        opp_pool: AZ paradigm does NOT use an opponent pool in selfplay
            (A5.2 — both sides share the same network). The kwarg is
            accepted for protocol uniformity + ignored.
        """
        if getattr(cfg.pipeline, 'actor_backend', 'python') == 'go':
            raise ValueError(
                "AZParadigm 不支持 actor_backend='go'(I29 Phase 2 pending);AZ 当前仅 Python actor backend。"
            )
        del opp_pool  # AZ selfplay shares network across both sides
        pcfg = self._resolve_pcfg(cfg)
        if cfg.pipeline.mode == 'async':
            return AZAsyncCollector(cfg, pcfg, network, env_factory)
        # Serial default
        if env_factory is None:
            raise ValueError('AZParadigm.make_collector: env_factory required (None passed)')
        env = env_factory(0)
        return AZSelfPlayCollector(cfg, pcfg, network, env)

    def make_episode_policy(self, cfg: Any, instance_id: int = 0, deterministic: bool = False) -> Any:
        """Protocol-conformant MCTS-driven actor (spec A1).

        Note: serial AZ collector calls ``play_self_game`` directly so
        this factory is mostly for tests + async P4.5+ wiring."""
        pcfg = self._resolve_pcfg(cfg)
        from training.paradigms.az.mcts import MCTSConfig
        from training.paradigms.az.pool_spec import make_pool_spec, resolve_pool_refs

        # Build the legacy MCTSConfig from our paradigm sub-cfg.
        m = pcfg.mcts
        mcts_cfg = MCTSConfig(
            n_rollouts=m.n_rollouts,
            c_puct=m.c_puct,
            dirichlet_alpha=m.dirichlet_alpha,
            dirichlet_eps=m.dirichlet_eps,
            temperature=m.temperature,
            temperature_switch_step=m.temperature_switch_step,
            max_rollout_depth=m.max_rollout_depth,
            parallel_rollouts=m.parallel_rollouts,
            value_mix_lambda=m.value_mix_lambda,
            prior_mix_lambda=m.prior_mix_lambda,
            lambda_anneal_games=m.lambda_anneal_games,
            lambda_start=m.lambda_start,
            lambda_end=m.lambda_end,
            profile=m.profile,
            backend=m.backend,
        )
        # A5.4: dict from resolve_pool_refs SHALL be wrapped via make_pool_spec
        card_pool_spec = make_pool_spec(cfg.scenario, resolve_pool_refs(cfg.scenario))
        return AZEpisodePolicy(
            mcts_cfg=mcts_cfg,
            card_pool_spec=card_pool_spec,
            seed=cfg.meta.seed + 17 + instance_id,
            deterministic=deterministic,
            n_counter_slots=pcfg.agent.n_counter_slots,
            max_actions=pcfg.agent.max_actions,
        )

    def step_schedule(self, state: PipelineState, cfg: Any) -> StepPlan:
        """Cadence: per outer iter, collect 1 selfplay game + (warm-up
        gated) train_steps_per_game batches.

        AZ is off-policy with replay buffer; we never clear between
        iters. Termination: ``total_episodes >= pcfg.total_games``
        (driver writes total_episodes via PipelineState.after_collect).
        """
        pcfg = self._resolve_pcfg(cfg)
        if state.total_episodes >= pcfg.total_games:
            return StepPlan(
                collect=False,
                n_episodes=0,
                train=False,
                n_train_batches=0,
                batch_size=pcfg.batch_size,
                eval=False,
                advance_step=0,
            )
        # Warm-up: collect-only until buffer ≥ min_buffer_before_train.
        if state.total_transitions < pcfg.min_buffer_before_train:
            return StepPlan(
                collect=True,
                n_episodes=1,
                train=False,
                n_train_batches=0,
                batch_size=pcfg.batch_size,
                eval=False,
                advance_step=1,
            )
        # Steady: 1 selfplay + train_steps_per_game batches. PeriodicEval
        # gating still owned by driver scheduler (we flip the bit).
        return StepPlan(
            collect=True,
            n_episodes=1,
            train=True,
            n_train_batches=pcfg.train_steps_per_game,
            batch_size=pcfg.batch_size,
            eval=True,
            advance_step=1,
            sync_weights=async_sync_weights_due(cfg, state, pcfg.sync_weights_every_train_steps),
        )
