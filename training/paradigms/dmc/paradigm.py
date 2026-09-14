"""DMCParadigm — implements training.core.protocols.Paradigm for DMC.

Bridges the unified pipeline driver to current DMC components. The collector
dispatch supports serial Python, async Python multiprocessing, and async Go
subprocess actors.

Spec ref: paradigm-dmc/spec.md D1-D7 + training-architecture SHALL #2
(Paradigm protocol).
"""

from __future__ import annotations

from typing import Any

import torch

from training.core.protocols import PipelineState, StepPlan, async_sync_weights_due
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
        if self._network is not None:
            return self._network
        torch.manual_seed(int(cfg.meta.seed))
        pcfg = self._resolve_pcfg(cfg)
        agent_cfg = AgentConfig.from_obs_shape(pcfg.agent)
        self._network = DMCNetwork(agent_cfg, device=cfg.meta.device, epsilon=pcfg.epsilon)
        self._network._agent.rng.seed(int(cfg.meta.seed))
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
        # max_actions 必须 == 网络 AgentConfig.max_actions:per-trans nlegal-sized
        # refs/pay 在 sample time pad 到 max_actions 才进网络 forward(I29 P2)。
        return DMCBuffer(
            capacity=pcfg.buffer_cap,
            max_actions=pcfg.agent.max_actions,
            seed=cfg.meta.seed + 2,
            device=cfg.meta.device,
        )

    def make_loss(self, cfg: Any) -> Any:
        pcfg = self._resolve_pcfg(cfg)
        return DMCLogitAsQLoss(pcfg)

    def make_collector(self, cfg: Any, env_factory: Any, network: Any, opp_pool: Any) -> Any:
        """Serial / Python mp / Go-subprocess collector based on cfg.pipeline.{mode,actor_backend}.

        env_factory: callable(game_idx) → GicgEnv, built by tools.runs.train.
        opp_pool: paradigm-built OpponentPool from ``make_opponent_pool``。

        Dispatch matrix:
        - mode='serial':DMCSerialCollector(Python in-proc,no actor pool)
        - mode='async' + actor_backend='python'(默认):DMCMultiProcessCollector
          (现 Python mp.Process pool)
        - mode='async' + actor_backend='go'(I29 redesign 2026-05-25):
          DMCGoSubprocessCollector (cmd/gicg_actor standalone OS subprocess + SHMRing
          transition,master 0 cgo lib loaded — design.md §3 deal-breaker invariant #1)。
          Pre-redesign cgo path (libgicg_actor.dylib + DMCGoActorCollector) P3 退役 by
          this commit。
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
        return DMCSerialCollector(cfg, pcfg, agent, opp_pool, env, env_factory)

    def _make_go_collector(self, cfg: Any, pcfg: Any, network: Any) -> Any:
        """Build DMCGoSubprocessCollector with paradigm_cfg_dict assembled from cfg + pcfg。

        Scenario walk cfg.scenario;对手按 pcfg.opponent_mix 透传给 Go subprocess
        (per-episode 按权重抽 random/f1d2/f1d4/historical)。 I29 redesign P3 退役 cgo path
        (DMCGoActorCollector + libgicg_actor),改走 cmd/gicg_actor standalone subprocess +
        SHMRing transition。 Inference 走 TCP (I29 R7.1 删 SHM inference path,与 Python mp
        wire 等价)。
        """
        from training.paradigms.dmc.go_subprocess_collector import DMCGoSubprocessCollector
        from training.paradigms.dmc.inference_net import DMCInferenceNet

        sc = cfg.scenario
        # F4: players[i].deck mirrors [scenario].deck_0/deck_1 — the Go
        # subprocess unmarshals the same factory.GameConfig wire format,
        # so omitting it here would fork deck behavior across backends
        # (the Go side would fail loud on implicit overflow).
        players = []
        for team, deck in ((sc.team_0, sc.deck_0), (sc.team_1, sc.deck_1)):
            p = {'chars': [{'name': n} for n in team]}
            if deck is not None:
                p['deck'] = list(deck)
            players.append(p)
        game_spec = {
            'pools': [sc.pool] if isinstance(sc.pool, str) else sc.pool or ['v_legacy'],
            'seed': cfg.meta.seed,
            'players': players,
        }
        if sc.card_pool is not None:
            game_spec['card_pool'] = sc.card_pool
        if sc.deck_padding is not None:
            game_spec['deck_padding'] = sc.deck_padding
        if sc.max_rounds:
            game_spec['max_rounds'] = sc.max_rounds

        # 对手按 cfg 的 opponent_mix 透传 — Go actor per-episode 按权重抽对手。
        # 旧实现硬编码 F1-D2(无视 opponent_mix)→ 100% D2 minimax,episode 被
        # minimax 吞掉(I29 T-R3 吞吐崩溃根因)。 historical 在 Go 路径走当前 net
        # 推理代理(cost-faithful;真 historical-net ring 是 follow-up)。
        omix = pcfg.opponent_mix
        # C2 (2026-05-25): minimax_node_budget 透传到 Go side (DMCConfig.OpponentMix.
        # MinimaxNodeBudget)。 None → 0 (Go 端 0 视作无 cap, 与 Python None 语义对齐)。
        # bench cfg explicit 设值才 cap; production cfg 不设字段 → 0 = uncapped, Go
        # 端历史 const minimaxNodeBudget=4000 在 C2 后改 cfg-driven default 0 (无 cap),
        # production cfg 期望两边 algo 一致 (Python 历史也 no cap)。
        _budget = int(omix.minimax_node_budget) if omix.minimax_node_budget is not None else 0
        paradigm_cfg = {
            'game_spec': game_spec,
            'opponent_mix': {
                'random': float(omix.random),
                'f1d2': float(omix.f1d2),
                'f1d4': float(omix.f1d4),
                'historical': float(omix.historical),
                'minimax_node_budget': _budget,
            },
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
        # Wrap raw DMCNetwork in DMCInferenceNet for InferenceServer host —
        # DMCNetwork.forward is NotImplemented (training-only;use forward_batch),
        # InfServer 在 socket forward_cb 走 raw `network(...)` call → 需要 InferenceNet
        # 的 forward 实现。 与 perf_smoke test fixture 同模式 (test_go_subprocess_perf_smoke
        # _build_dmc_inference_net)。 .net 取 ActorCritic underlay (DMCNetwork 包了 DmcAgent
        # 含 .net actor_critic) — DMCInferenceNet 期待 ActorCritic 不是 DMCNetwork。
        actor_critic = network.net if hasattr(network, 'net') else network
        inf_network = DMCInferenceNet(actor_critic)
        return DMCGoSubprocessCollector(
            cfg=cfg,
            network=inf_network,
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

        agent_cfg = AgentConfig.from_obs_shape(pcfg.agent)

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
            sync_weights=async_sync_weights_due(cfg, state, pcfg.sync_weights_every_train_steps),
        )
