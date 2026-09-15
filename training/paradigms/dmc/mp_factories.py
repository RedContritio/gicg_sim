"""DMC mp-mode factories — env, opp registry, provider + server decoder.

Wired into spawned actors via ``DMCMultiProcessCollector._bootstrap``:
parent constructs a shared :class:`InferenceServer` (with
``request_decoder_path`` pointing at :func:`decode_dmc_request`) +
attaches N :class:`InferenceClient` handles, and threads each client to
the corresponding actor through the ``inference_client`` kwarg.

**Architecture (post 2026-05-20 decode-offload + I25 response-numpy)**:
the actor side is intentionally torch-free *both ways*. The actor
builds a small numpy payload (raw ``static_obs`` + ``dyn_obs`` + action
refs/payments — ~10 KB) and pickles it over IPC. The server-side
decoder unpickles the numpy payload, re-uses a per-client static cache
for the expensive per-game encoding (hook IR → hook_emb via
:class:`HookIREncoder` forward), parses the dynamic obs into the 7
typed tensors, builds the full 15-tensor obs_dict, and hands it back
to the normal batched/per-request forward path. Server-side encode
lives inside ``inf_server.decode`` so the perf breakdown stays
interpretable.

I25 (2026-05-20) closes the symmetric loop: when ``request_decoder_path``
is set, ``InferenceServer`` returns ``np.ndarray`` bytes instead of
``torch.Tensor`` bytes. Actor unpickle no longer triggers ``import
torch`` (which mmaps ~400 MB of CUDA libs per process); per-actor RSS
drops from ~547 MB to ~150 MB on N=8 Win box bench.

The decode-offload eliminates two costs measured in the N=4/N=8 actor
scaling bench (2026-05-19): (a) torch import + DmcAgent construction in
each actor (~1 GB RSS, ~5-10s startup), (b) torch obs_dict pickling
(15 tensors / 4-13 MB per request → ~10 KB numpy). On N=8 the per-game
static encoding amortises across the whole game (~30-60 steps).

LocalNetworkProvider fallback is intentionally absent — for serial mode
callers must use ``DMCSerialCollector`` directly.

The per-actor provider class lives in ``_provider.py`` (file-budget cap;
pure relocation — see that module's docstring).
"""

from __future__ import annotations

from typing import Any

# Re-export server-side decoder + numpy helpers (split into _decoder.py
# to keep this file under the 300-line budget). The dotted path
# `training.paradigms.dmc.mp_factories.decode_dmc_request` still resolves
# (existing wiring in `_spawn_inference_pool` + tests stays valid).
from training.paradigms.dmc._decoder import (  # noqa: F401
    _capture_obs_np,
    _encode_static_np,
    decode_dmc_request,
)
from training.paradigms.dmc._provider import _DMCObsDictRemoteProvider


def build_dmc_env_factory(cfg: Any, seed: int):
    """Return callable(scenario_seed) -> GicgEnv suitable for the actor
    process. Mirrors ``training.core.env_factory.make_env_factory``; the
    seed argument forwarded by the actor scheduler becomes the master
    seed for this actor's env stream.
    """
    from training.core.env_factory import make_env_factory

    return make_env_factory(cfg, None, master_seed=seed)


def build_dmc_opp_registry(cfg: Any):
    """Return :class:`OpponentRegistry` covering the opponent IDs that
    ``_dmc_spec_sampler`` can emit.

    Registered opponents (R6.3 — unlocks mixed-opp fair bench):

    - ``'random'`` — uniform random over legal actions (cheap baseline).
    - ``'f1d2'`` — :class:`GreedyPlayer` F1 features, depth-2 (~ms/turn).
    - ``'f1d4'`` — :class:`GreedyPlayer` F1 features, depth-4 (deeper
      minimax; production-shape opp_mix's expensive tier).

    Both greedy variants run with ``dice_greedy=True`` to match
    :class:`OpponentPool._build_player` (collapse engine dice fan-out).

    **NOT registered**: ``'historical'`` — Go-side ``gicg_actor/dmc/
    paradigm.go`` treats ``historical`` as a cost-faithful F1-D4 proxy
    (no real ckpt ring across mp.Manager). Python端无等价 (per-actor
    InfClient + ckpt ring 跨 mp.Manager 不可行); ``_dmc_spec_sampler``
    SHALL exclude ``'historical'`` from sampling to avoid lookup failure.
    Production training cfg with ``historical`` weight SHALL re-route
    via in-proc :class:`OpponentPool` (serial mode), not mp pool.
    """
    from training.core.eval.baselines import OpponentRegistry
    from training.core.matchup.greedy_player import GreedyPlayer
    from training.paradigms.dmc._opponent import RandomPlayer

    # C2 (2026-05-25): cross-language fair bench parity — read minimax_node_budget
    # from cfg.paradigm.opponent_mix and forward to GreedyPlayer ctor。 None (default)
    # = 无 cap (production 历史行为); 显式 e.g. 4000 与 Go DMCConfig.OpponentMix.
    # MinimaxNodeBudget 对齐让 bench 测 pipeline 而非 algo shortcut。
    pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
    omix = pdict.get('opponent_mix') or {}
    budget_raw = omix.get('minimax_node_budget')
    minimax_budget = int(budget_raw) if budget_raw is not None else None

    reg = OpponentRegistry()
    reg.register('random', lambda seed=0, params=None: RandomPlayer(seed=int(seed or 0)))
    reg.register(
        'f1d2',
        lambda seed=0, params=None, budget=minimax_budget: GreedyPlayer(
            features='F1',
            depth=2,
            dice_greedy=True,
            seed=int(seed or 0),
            minimax_node_budget=budget,
        ),
    )
    reg.register(
        'f1d4',
        lambda seed=0, params=None, budget=minimax_budget: GreedyPlayer(
            features='F1',
            depth=4,
            dice_greedy=True,
            seed=int(seed or 0),
            minimax_node_budget=budget,
        ),
    )
    return reg


def build_dmc_provider(cfg: Any, actor_id: int, *, inference_client: Any = None) -> Any:
    """Return a per-actor remote provider wired to the shared inference
    server. ``inference_client`` is REQUIRED — parent process must have
    constructed + registered it before spawning this actor. Missing
    client raises loudly (CS4 strict): there is no LocalNetworkProvider
    fallback in mp mode; serial mode owns its own provider via
    ``DMCSerialCollector._ensure_dmc_provider``.
    """
    if inference_client is None:
        raise ValueError(
            f'build_dmc_provider[actor_id={actor_id}]: inference_client kwarg required — '
            f'parent DMCMultiProcessCollector._bootstrap must register a client per actor '
            f'and pass it via actor_kwargs_factory.'
        )
    return _DMCObsDictRemoteProvider(cfg=cfg, actor_id=actor_id, client=inference_client)
