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

AB13 escape hatch (D4=A): two provider modes (see build_az_provider):
- LOCAL (default, ``paradigm.local_inference=True``): the parent publishes
  weights to a WeightsSHM slot; each actor builds a ``_AZLocalProvider``
  around its own CPU Agent copy — MCTS evaluates in-proc, no server, no
  CUDA outside the master.
- SERVER (legacy): the parent constructs a shared ``InferenceServer`` +
  N ``InferenceClient`` and threads each client to its actor
  (``_AZRemoteProvider``).

ExIt fixed_opponent (async): with ``paradigm.fixed_opponent`` set, the
provider ALSO carries an actor-local :class:`FixedOpponentPool` — the pool
is never serialized (snapshot nets too heavy); each actor rebuilds it from
``FixedOpponentCfg`` (in cfg) + ring snapshots (WeightsSHM broadcast,
refreshed in ``update_weights`` between episodes). The runner then plays
``play_vs_opponent_game`` instead of mirror ``play_self_game``. AB13
axis-1: the parent passes both via ``provider_kwargs``
(``inference_client`` + ``opp_ring_shm``) since the bare ``inference_client``
handoff can't carry the ring attach info.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from training.core.protocols import EpisodeSpec
from training.paradigms.az.mp_providers import _AZLocalProvider, _AZRemoteProvider
from training.paradigms.az.mp_utils import derive_seed
from training.paradigms.az.selfplay import SelfPlayResult, play_self_game, play_vs_opponent_game

OPP_SENTINEL = 'self'  # opponent_id sentinel — decorative, never registry-looked-up
RING_TAG = 'az_hist_ring'  # keep in sync with training.paradigms.az._async.RING_TAG
WEIGHTS_TAG = 'latest'  # keep in sync with training.paradigms.az._async.WEIGHTS_TAG


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


def build_az_provider(
    cfg: Any, actor_id: int, *, inference_client: Any = None, weights_shm: Any = None, opp_ring_shm: Any = None
) -> Any:
    """Return a per-actor provider. Two inference modes:

    - LOCAL (``weights_shm`` given, the default per
      ``paradigm.local_inference``): the actor owns a CPU Agent copy
      (``_AZLocalProvider``) — MCTS evaluates in-proc, weights load from
      the WeightsSHM ``latest`` slot between episodes. No InferenceServer,
      no CUDA outside the master.
    - SERVER (``inference_client`` given): the legacy
      ``_AZRemoteProvider`` wired to the shared InferenceServer.
      ``inference_client`` missing in server mode raises loudly (CS4
      strict) — no LocalNetworkProvider fallback in mp mode.

    ExIt fixed_opponent (either mode): the actor builds its OWN
    :class:`FixedOpponentPool` locally from ``FixedOpponentCfg`` (never
    serialize the pool — snapshot nets are too heavy); ``opp_ring_shm``
    is the WeightsSHM attach info for the historical-ring broadcast."""
    if weights_shm is not None:
        from training.core.network import AgentConfig
        from training.paradigms.az.config import AZParadigmConfig
        from training.paradigms.az.network import Agent

        pcfg = AZParadigmConfig.from_dict(cfg.paradigm if isinstance(cfg.paradigm, dict) else {})
        agent = Agent(AgentConfig.from_obs_shape(pcfg.agent), device='cpu')
        provider: Any = _AZLocalProvider(cfg, actor_id, agent=agent, weights_shm_info=weights_shm)
    else:
        if inference_client is None:
            raise ValueError(
                f'build_az_provider[actor_id={actor_id}]: inference_client kwarg required in '
                f'server mode (local_inference=False) — parent AZAsyncCollector._bootstrap must '
                f'construct a shared InferenceServer, attach a client per actor, and pass it via '
                f'actor_kwargs_factory. For local inference pass weights_shm instead.'
            )
        provider = _AZRemoteProvider(cfg, actor_id, client=inference_client)
    if provider.pcfg.fixed_opponent is not None:
        provider.attach_opponent_pool(_build_actor_opponent_pool(cfg, provider, opp_ring_shm))
    return provider


def _build_actor_opponent_pool(cfg: Any, provider: Any, opp_ring_shm: Any) -> Any:
    """Actor-local FixedOpponentPool (ExIt async). The pool itself never
    crosses a process boundary — only FixedOpponentCfg (via cfg) and ring
    snapshots (via the WeightsSHM broadcast) do. Per-actor seed divergence
    keeps opponent sampling independent across actors."""
    from training.core.actor.weights_shm import WeightsSHM
    from training.core.network import AgentConfig
    from training.paradigms.az._opponent import FixedOpponentPool, make_snapshot_factory

    pcfg = provider.pcfg
    fcfg = pcfg.fixed_opponent
    agent_cfg = AgentConfig.from_obs_shape(pcfg.agent)
    snapshot_factory = make_snapshot_factory(
        agent_cfg,
        'cpu',
        provider.mcts_config,
        provider.card_pool_spec,
        seed=fcfg.seed + provider.actor_id,
    )
    pool = FixedOpponentPool(
        fcfg,
        agent_factory=snapshot_factory,
        mcts_cfg=provider.mcts_config,
        card_pool_spec=provider.card_pool_spec,
        seed=derive_seed(int(cfg.meta.seed), 'az_fixed_opp', provider.actor_id),
    )
    if opp_ring_shm is not None:
        provider._opp_ring_shm = WeightsSHM.attach(opp_ring_shm)
        provider._opp_ring_version = -1
    return pool


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
        starting_player=(int(actor_id) + int(seq)) % 2,
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
        opponent_kind = None
        try:
            if getattr(provider, 'opponent_pool', None) is not None:
                # ExIt fixed_opponent (async): opponent seat driven by the
                # actor-local pool player; only agent decisions are
                # recorded, z from the agent seat — identical buffer row
                # format to the serial path.
                opponent = provider.opponent_pool.sample()
                result = play_vs_opponent_game(
                    provider,  # _AZRemoteProvider — game_start / eval_state / game_end
                    env,
                    provider.card_pool_spec,
                    provider.rng,
                    provider.mcts_config,
                    opponent,
                    max_game_steps=provider.max_game_steps,
                    n_counter_slots=provider.n_counter_slots,
                    max_actions=provider.max_actions,
                    agent_player=spec.starting_player,
                )
                opponent_kind = provider.opponent_pool.last_kind
            else:
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
        return _AZRunnerOutput(
            transitions=[],
            selfplay_result=result,
            opponent_kind=opponent_kind,
        )


def build_az_selfplay_runner(env_factory, opp_registry) -> AZSelfPlayRunner:
    """AB14 ``episode_runner_factory`` target (dotted-path resolvable)."""
    return AZSelfPlayRunner(env_factory, opp_registry)


@dataclass
class _AZRunnerOutput:
    """Picklable runner output for IPC transport (SHMRing / IPCQueue).
    ``transitions`` is the empty EpisodeRunner-contract surface; AZ sets
    ``push_episode_record=True`` so the FULL object is pushed and the
    collector reads ``selfplay_result`` (a :class:`SelfPlayResult` of
    dicts/lists/ints + numpy — no torch tensors leak, so it pickles).
    ``opponent_kind`` is the fixed-opponent pool kind sampled for this
    game ('greedy' / 'random' / 'historical'; None in mirror mode)."""

    selfplay_result: SelfPlayResult
    transitions: list = field(default_factory=list)
    opponent_kind: Any = None
