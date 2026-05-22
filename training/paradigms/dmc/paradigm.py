"""DMCParadigm — implements training.core.protocols.Paradigm for DMC.

Bridges the unified pipeline driver to legacy DMC components. Six
make_* factories + step_schedule cadence. Serial mode in P3-B (real mp
deferred to P4 — see collector.DMCMultiProcessCollector docstring).

Spec ref: paradigm-dmc/spec.md D1-D7 + training-architecture SHALL #2
(Paradigm protocol).
"""

from __future__ import annotations

from typing import Any

import torch

from training.core.protocols import PipelineState, StepPlan
from training.paradigms.dmc._opponent import OpponentPool, OpponentPoolConfig
from training.core.network import AgentConfig
from training.paradigms.dmc.buffer import DMCBuffer
from training.paradigms.dmc.collector import DMCSerialCollector, DMCMultiProcessCollector
from training.paradigms.dmc.config import DMCParadigmConfig
from training.paradigms.dmc.loss import DMCLogitAsQLoss
from training.paradigms.dmc.network import DMCNetwork
from training.paradigms.dmc.policy import DMCEpisodePolicy


class DMCParadigm:
    """Top-level DMC paradigm. driver instantiates one per run.

    Holds the per-run DMCNetwork (so make_collector + make_loss share
    the same agent without rebuilding it). Note: this stateful retention
    is intentional — protocol allows it (`make_network` is called once
    by driver, then the same instance is passed to make_optimizer +
    make_loss compute).
    """

    name = 'dmc'
    requires_network_in_collect = True

    def __init__(self) -> None:
        self._pcfg: DMCParadigmConfig | None = None
        self._network: DMCNetwork | None = None

    # --- internal --------------------------------------------------- #

    def _resolve_pcfg(self, cfg: Any) -> DMCParadigmConfig:
        if self._pcfg is None:
            self._pcfg = DMCParadigmConfig.from_dict(cfg.paradigm)
        return self._pcfg

    # --- 7 Protocol make_* + step_schedule ------------------------- #

    def make_network(self, cfg: Any) -> Any:
        """Build DMCNetwork (nn.Module wrapper around DmcAgent)."""
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
        self._network = DMCNetwork(agent_cfg, device=cfg.meta.device, epsilon=pcfg.epsilon)
        return self._network

    def make_optimizer(self, cfg: Any, network: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return torch.optim.AdamW(
            network.parameters(),
            lr=pcfg.lr,
            weight_decay=pcfg.weight_decay,
        )

    def make_buffer(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return DMCBuffer(capacity=pcfg.buffer_cap, seed=cfg.meta.seed + 2, device=cfg.meta.device)

    def make_loss(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return DMCLogitAsQLoss(pcfg)

    def make_collector(self, cfg: Any, env_factory: Any, network: Any, opp_pool: Any) -> Any:
        """Serial / Python mp / Go-native collector based on cfg.pipeline.{mode,actor_backend}.

        env_factory: callable(game_idx) → GicgEnv, built by tools.runs.train.
        opp_pool: paradigm-built OpponentPool from ``make_opponent_pool``。

        Dispatch matrix:
        - mode='serial':DMCSerialCollector(Python in-proc,no actor pool)
        - mode='async' + actor_backend='python'(默认):DMCMultiProcessCollector
          (现 Python mp.Process pool)
        - mode='async' + actor_backend='go'(I29):DMCGoActorCollector
          (Go-native goroutine pool via libgicg_actor)
        """
        pcfg = self._resolve_pcfg(cfg)
        if cfg.pipeline.mode == 'async':
            actor_backend = getattr(cfg.pipeline, 'actor_backend', 'python')
            if actor_backend == 'go':
                return self._make_go_collector(cfg, pcfg, network)
            return DMCMultiProcessCollector(cfg, pcfg, network, opp_pool, env_factory)
        # Serial default
        if env_factory is None:
            raise ValueError('DMCParadigm.make_collector: env_factory required (None passed)')
        env = env_factory(0)
        agent = network.agent if hasattr(network, 'agent') else network
        return DMCSerialCollector(cfg, pcfg, agent, opp_pool, env)

    def _make_go_collector(self, cfg: Any, pcfg: Any, network: Any) -> Any:
        """Build DMCGoActorCollector with paradigm_cfg_dict assembled from cfg + pcfg。

        Scenario / opp 配置 walk cfg.scenario + pcfg(epsilon / opp_features /
        opp_depth from opponent_mix 简化:取 F1-D2 默认)。
        """
        from training.paradigms.dmc.go_collector import DMCGoActorCollector

        sc = cfg.scenario
        game_spec = {
            'pools': [sc.pool] if isinstance(sc.pool, str) else sc.pool or ['v_legacy'],
            'seed': cfg.meta.seed,
            'players': [
                {'chars': [{'name': n} for n in sc.team_0]},
                {'chars': [{'name': n} for n in sc.team_1]},
            ],
        }
        if sc.card_pool is not None:
            game_spec['card_pool'] = sc.card_pool
        if sc.deck_padding is not None:
            game_spec['deck_padding'] = sc.deck_padding
        if sc.max_rounds:
            game_spec['max_rounds'] = sc.max_rounds

        paradigm_cfg = {
            'game_spec': game_spec,
            'opp_features': 'F1',
            'opp_depth': 2,
            # Go actor obs / assembler / logits 宽度 — 必须 == 网络 action 容量
            # (AgentConfig.max_actions),否则 n_legal > max_actions 时 chosen_action
            # 越出 logits 宽 → 训练 gather OOB。 与 Python mp 路径(mp_factories.py)
            # 同取 pcfg.agent.max_actions。
            'max_actions': int(pcfg.agent.max_actions),
            'max_episode_steps': int(getattr(pcfg, 'max_game_steps', 360)),
            'my_player_strategy': 'alternate',
            'base_seed': int(cfg.meta.seed),
            'epsilon': float(getattr(pcfg, 'epsilon', 0.05)),
        }
        n_actors = int(getattr(cfg.pipeline, 'num_actors', 1))
        return DMCGoActorCollector(
            cfg=cfg,
            network=network,
            paradigm_cfg_dict=paradigm_cfg,
            n_actors=n_actors,
        )

    def make_episode_policy(self, cfg: Any, instance_id: int = 0, deterministic: bool = False) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return DMCEpisodePolicy(
            epsilon=0.0 if deterministic else pcfg.epsilon,
            seed=cfg.meta.seed + 11 + instance_id,
            deterministic=deterministic,
        )

    def make_opponent_pool(self, cfg: Any, network: Any) -> OpponentPool:
        """Paradigm-specific factory: build OpponentPool with historical
        DMC-agent factory wired. Called by tools.runs.train (driver itself
        doesn't know about OpponentPool — it just forwards opp_pool
        kwarg to make_collector).
        """
        pcfg = self._resolve_pcfg(cfg)
        mix = pcfg.opponent_mix
        pool_cfg = OpponentPoolConfig(
            random=mix.random,
            f1d2=mix.f1d2,
            f1d4=mix.f1d4,
            historical=mix.historical,
            ring_size=mix.ring_size,
        )

        agent_cfg = AgentConfig(
            n_counter_slots=pcfg.agent.n_counter_slots,
            n_hooks=pcfg.agent.n_hooks,
            max_ops_per_hook=pcfg.agent.max_ops_per_hook,
            max_actions=pcfg.agent.max_actions,
            d_model=pcfg.agent.d_model,
            dropout=pcfg.agent.dropout,
            n_cross_layers=pcfg.agent.n_cross_layers,
        )

        def historical_factory(state_dict: Any) -> Any:
            from training.paradigms.dmc._agent import DmcAgent

            opp = DmcAgent(agent_cfg, device=cfg.meta.device, lr=pcfg.lr, epsilon=0.0)
            opp.load_net_only(state_dict)
            opp.net.eval()
            return opp

        return OpponentPool(pool_cfg, dmc_agent_factory=historical_factory, seed=cfg.meta.seed + 1)

    def step_schedule(self, state: PipelineState, cfg: Any) -> StepPlan:
        """Cadence: per outer iter, collect 1 episode + train ratio
        steps. Matches legacy DMC `n_drained × 4` once data warm-up
        passes batch_size threshold."""
        pcfg = self._resolve_pcfg(cfg)
        # Stop when total_frames reached (frames = total_transitions
        # captured into buffer).
        if state.total_transitions >= pcfg.total_frames:
            return StepPlan(
                collect=False,
                n_episodes=0,
                train=False,
                n_train_batches=0,
                batch_size=pcfg.batch_size,
                eval=False,
                advance_step=0,
            )
        # Warm-up: collect-only until buffer has ≥ batch_size transitions.
        if state.total_transitions < pcfg.batch_size:
            return StepPlan(
                collect=True,
                n_episodes=1,
                train=False,
                n_train_batches=0,
                batch_size=pcfg.batch_size,
                eval=False,
                advance_step=1,
            )
        # Steady: 1 episode + train_ratio batches; eval cadence handled
        # by PeriodicEvalScheduler — we only flip the eval bit and let
        # the scheduler gate.
        return StepPlan(
            collect=True,
            n_episodes=1,
            train=True,
            n_train_batches=pcfg.train_ratio,
            batch_size=pcfg.batch_size,
            eval=True,
            advance_step=1,
        )
