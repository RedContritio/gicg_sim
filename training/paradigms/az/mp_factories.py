"""AZ mp-mode factories — env / opp registry / policy / provider / spec
sampler + a selfplay-lifecycle Runner. Mirrors
``training.paradigms.cfr.mp_factories`` (DMC/CFR template, I31 backlog #88):
top-level spawn-safe factories resolved via dotted-path in the child, parent
owns the handoff. cfg-driven, no env var (``feedback_cfg_driven_only``): child
reconstructs ``AZParadigmConfig.from_dict(cfg.paradigm)``.

AZ's lifecycle is **selfplay** (one full game played through MCTS, BOTH sides
driven by the SAME network via a shared :class:`InferenceServer`), NOT the
single-sided episode model the default ``EpisodeRunner`` hosts. The 2026-05-29
T1 forensic pass (design.md §2.2-CORRECTION) proved the EpisodeRunner path is
unviable (no ``opp_id=='self'`` short-circuit; ``AZEpisodePolicy.act``'s
protocol path is test-only, needs dict-obs with env). So AZ takes the AB14
``episode_runner_factory`` hatch (shipped for CFR) and plugs an
:class:`AZSelfPlayRunner` whose ``run`` calls the EXISTING, proven
``play_self_game(evaluator=provider, env, ...)`` — same shape as CFR's
``CFRTraversalRunner``. ``play_self_game`` itself drives ``game_start`` /
``eval_state`` / ``game_end`` on the evaluator, so the runner does NOT manage
the game lifecycle; the evaluator (here :class:`_AZRemoteProvider`) just
delegates those three calls to its wrapped :class:`InferenceClient`.

selfplay opponent_id='self' is decorative — both sides share the one
InferenceServer through the same client, so the runner never looks anything
up in the (empty) opponent registry. The stub policy / empty opp registry
exist only to satisfy actor_main's non-None builder validation (mirror CFR).

AB13 escape hatch (D4=A): AZ reuses the DMC ``inference_client`` kwarg —
``build_az_provider(cfg, actor_id, *, inference_client)`` matches
``build_dmc_provider``'s signature; the parent collector constructs a shared
``InferenceServer`` + N ``InferenceClient`` and threads each client to its
actor.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from training.core.protocols import EpisodeSpec
from training.paradigms.az.selfplay import SelfPlayResult, play_self_game

OPP_SENTINEL = 'self'  # opponent_id sentinel — decorative, never registry-looked-up


def derive_seed(master_seed: int, *labels: Any) -> int:
    """Deterministic seed from master + labels. Same shape as the serial
    collector's ``derive_seed`` (intentional dup — paradigm isolation per
    ADR-0006)."""
    h = master_seed & 0xFFFFFFFF
    for lab in labels:
        for b in repr(lab).encode('utf-8'):
            h = (h * 1000003) ^ b
            h &= 0xFFFFFFFF
    return int(h & 0x7FFFFFFF)


# ---------- spawn-safe top-level builders(actor_main resolves via dotted path) ---------- #


def build_az_env_factory(cfg: Any, seed: int):
    """Return callable(scenario_seed) -> GicgEnv for the actor process.
    Inlines the canonical GicgEnv construction from cfg.scenario (mirrors
    CFR's ``build_env_factory``); the ``seed`` arg is unused — each episode's
    scenario_seed comes from :func:`az_spec_sampler`."""
    del seed
    from gicg_env import GicgEnv

    from training.core.scenario import decks_arg

    scen = cfg.scenario
    fd = list(scen.fix_dice) if getattr(scen, 'fix_dice', None) else None
    decks = decks_arg(getattr(scen, 'deck_0', None), getattr(scen, 'deck_1', None))

    def _factory(scenario_seed: int):
        env = GicgEnv(
            list(scen.team_0),
            list(scen.team_1),
            card_pool=getattr(scen, 'card_pool', None),
            seed=int(scenario_seed),
            data_dir=str(getattr(scen, 'data_dir', 'data')),
            max_rounds=int(getattr(scen, 'max_rounds', 3)),
            fix_dice=fd,
            deck_padding=getattr(scen, 'deck_padding', None),
            pool=getattr(scen, 'pool', ['v_legacy', 'test_basic']),
            decks=decks,
        )
        env.reset(seed=int(scenario_seed))
        return env

    return _factory


def build_az_opp_registry(cfg: Any):
    """Empty registry — AZ selfplay has no opponent (both sides share the one
    network via the same InferenceClient); the ``'self'`` sentinel is never
    looked up. Returned non-None only to satisfy actor_main's required-builder
    validation."""
    del cfg
    from training.core.eval.baselines import OpponentRegistry

    return OpponentRegistry()


def build_az_policy(cfg: Any, actor_id: int):
    """``_AZSelfPlayPolicy`` stub — AZ's runner drives ``play_self_game``
    directly (the evaluator does the work), never stepping via ``policy.act``.
    Non-None only for actor_main validation; ``act`` raises so a wiring bug
    fails loud (mirror CFR's ``_CFRTraversalPolicy``)."""
    del cfg, actor_id
    return _AZSelfPlayPolicy()


def build_az_provider(cfg: Any, actor_id: int, *, inference_client: Any = None) -> Any:
    """Return a per-actor :class:`_AZRemoteProvider` wired to the shared
    inference server. ``inference_client`` is REQUIRED — parent process must
    have constructed + registered it before spawning this actor. Missing
    client raises loudly (CS4 strict): there is no LocalNetworkProvider
    fallback in mp mode (matches ``build_dmc_provider``)."""
    if inference_client is None:
        raise ValueError(
            f'build_az_provider[actor_id={actor_id}]: inference_client kwarg required — '
            f'parent AZAsyncCollector._bootstrap must construct a shared InferenceServer, '
            f'attach a client per actor, and pass it via actor_kwargs_factory.'
        )
    return _AZRemoteProvider(cfg, actor_id, client=inference_client)


_SPEC_COUNTERS: dict = {}  # per-actor monotonic seq; per-process safe (each actor a spawned proc)


def az_spec_sampler(cfg: Any, actor_id: int) -> EpisodeSpec:
    """One selfplay spec: per-actor monotonic seq → deterministic env seed.
    ``opponent_id='self'`` is decorative (selfplay shares the network; the
    runner ignores the registry). Mirrors the serial ``_az_spec_sampler``."""
    seq = _SPEC_COUNTERS.get(actor_id, 0)
    _SPEC_COUNTERS[actor_id] = seq + 1
    return EpisodeSpec(
        scenario_seed=derive_seed(int(cfg.meta.seed), 'mp_ep', int(actor_id), int(seq)),
        opponent_id=OPP_SENTINEL,
    )


class _AZSelfPlayPolicy:
    """Stub EpisodePolicy — exists only because actor_main requires a non-None
    policy. ``act`` raises so a wiring bug fails loud (AZ drives selfplay via
    ``play_self_game(evaluator=provider, ...)``, not ``policy.act``)."""

    def reset(self, *args: Any, **kwargs: Any) -> None:
        return None

    def act(self, *args: Any, **kwargs: Any):
        raise RuntimeError(
            '_AZSelfPlayPolicy.act called — AZ plays selfplay via play_self_game '
            '(evaluator=_AZRemoteProvider), not policy.act. Likely wired with '
            'EpisodeRunner not build_az_selfplay_runner.'
        )


class _AZRemoteProvider:
    """Per-actor provider with a DUAL role:

    1. **Evaluator** for ``play_self_game`` / its MCTS — ``game_start`` /
       ``eval_state`` / ``game_end`` delegate to the wrapped
       :class:`InferenceClient` (which implements the exact same evaluator
       protocol the on-process ``Agent`` exposes, talking to the shared
       InferenceServer over its mp.Pipe).
    2. **cfg-config holder** for :class:`AZSelfPlayRunner` — the AB14 factory
       signature is ``(env_factory, opp_registry)`` with no cfg, so the runner
       reads ``card_pool_spec`` / ``mcts_config`` / ``n_counter_slots`` /
       ``max_actions`` / ``rng`` / ``max_game_steps`` off the provider.

    ``update_weights`` (called arg-less by actor_main between episodes) is a
    no-op version-read: the InferenceServer owns the weights (the collector
    pushes server-side), so the provider just reports the client's current
    weight version (D3=C poll-based, no barrier)."""

    def __init__(self, cfg: Any, actor_id: int, client: Any) -> None:
        from training.paradigms.az.collector import _build_mcts_config
        from training.paradigms.az.config import AZParadigmConfig
        from training.paradigms.az.pool_spec import make_pool_spec, resolve_pool_refs

        self.cfg = cfg
        self.actor_id = int(actor_id)
        self._client = client

        pcfg = AZParadigmConfig.from_dict(cfg.paradigm if isinstance(cfg.paradigm, dict) else {})
        self.card_pool_spec = make_pool_spec(cfg.scenario, resolve_pool_refs(cfg.scenario))  # A5.4
        self.mcts_config = _build_mcts_config(pcfg)
        self.n_counter_slots = int(pcfg.agent.n_counter_slots)
        self.max_actions = int(pcfg.agent.max_actions)
        self.max_game_steps = int(pcfg.max_game_steps)
        self.rng = random.Random(derive_seed(int(cfg.meta.seed), 'az_selfplay', self.actor_id))

    # --- Evaluator protocol (delegate to the shared inference server) ------ #

    def game_start(self, static_obs: Any) -> dict:
        return self._client.game_start(static_obs)

    def eval_state(self, dyn: Any, refs: Any, payments: Any):
        return self._client.eval_state(dyn, refs, payments)

    def game_end(self) -> None:
        return self._client.game_end()

    # --- Weight lifecycle (server owns weights; client tracks version) ----- #

    def update_weights(self) -> int:
        return self.current_version()

    def current_version(self) -> int:
        ver = getattr(self._client, 'current_weight_version', None)
        return int(ver) if ver is not None and int(ver) >= 0 else 0

    def close(self) -> None:
        close = getattr(self._client, 'close', None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


class AZSelfPlayRunner:
    """AB14 lifecycle-runner — one selfplay game per ``run`` call (replaces
    ``EpisodeRunner``'s single-sided episode lifecycle). Wraps the existing,
    proven ``play_self_game`` (selfplay correctness unchanged; only the mp
    orchestration differs). ``policy`` + ``opp_registry`` are ignored (the
    provider IS the evaluator; both sides share one network), same as
    ``CFRTraversalRunner``."""

    def __init__(self, env_factory, opp_registry) -> None:
        del opp_registry  # selfplay has no opponent — both sides share the network
        self.env_factory = env_factory

    def run(self, spec: EpisodeSpec, policy: Any, provider: Any) -> '_AZRunnerOutput':
        del policy  # selfplay drives via provider (evaluator), not policy.act
        env = self.env_factory(spec.scenario_seed)
        try:
            result = play_self_game(
                provider,  # _AZRemoteProvider — game_start / eval_state / game_end
                env,
                provider.card_pool_spec,
                provider.rng,
                provider.mcts_config,
                max_game_steps=provider.max_game_steps,
                n_counter_slots=provider.n_counter_slots,
                max_actions=provider.max_actions,
            )
        finally:
            if hasattr(env, 'close'):
                env.close()
        return _AZRunnerOutput(transitions=[], selfplay_result=result)


def build_az_selfplay_runner(env_factory, opp_registry) -> AZSelfPlayRunner:
    """AB14 ``episode_runner_factory`` target (dotted-path resolvable)."""
    return AZSelfPlayRunner(env_factory, opp_registry)


@dataclass
class _AZRunnerOutput:
    """Picklable runner output for IPC transport (SHMRing / IPCQueue).
    ``transitions`` is the empty EpisodeRunner-contract surface; AZ sets
    ``push_episode_record=True`` so the FULL object is pushed and the
    collector reads ``selfplay_result`` (a :class:`SelfPlayResult` of
    dicts/lists/ints + numpy — no torch tensors leak, so it pickles)."""

    selfplay_result: SelfPlayResult
    transitions: list = field(default_factory=list)
