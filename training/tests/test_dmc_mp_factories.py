"""End-to-end DMC mp mode wiring smoke (E target / P2-PoC).

Verifies the parent → actor InferenceClient threading + shared
InferenceServer path:

- ``DMCMultiProcessCollector._bootstrap`` constructs the
  :class:`InferenceServer` and N :class:`InferenceClient` instances.
- Each actor receives its client through the ``inference_client``
  kwarg (added to ``actor_main`` in this commit).
- ``build_dmc_provider`` returns a remote provider routed via the
  client; actor forwards go to the shared server.

device='cpu' verifies the architecture compiles + actors spawn on Mac
without GPU dependency. GPU benchmark is deferred to the Windows-side
follow-up (see ``training/paradigms/dmc/PLAN.md`` E target).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from training.core.config.loader import load_cfg


def test_dmc_mp_factories_end_to_end():
    cfg = load_cfg(Path('configs/dmc/gpu_async.toml'), overrides=[])
    assert cfg.meta.paradigm == 'dmc'
    assert cfg.pipeline.mode == 'async'

    from training.core.env_factory import make_env_factory
    from training.paradigms import resolve as resolve_paradigm

    paradigm = resolve_paradigm('dmc')
    network = paradigm.make_network(cfg)
    opp_pool = paradigm.make_opponent_pool(cfg, network)
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)
    collector = paradigm.make_collector(cfg, env_factory, network, opp_pool)

    try:
        # First collect triggers _bootstrap (spawns InferenceServer +
        # clients + actors). Subsequent polls drain the ring as actors
        # push transitions.
        out = collector.collect(n_episodes=4, provider=None)
        n_trans = out.n_units
        deadline = time.time() + 20
        while n_trans == 0 and time.time() < deadline:
            time.sleep(0.5)
            out = collector.collect(n_episodes=4, provider=None)
            n_trans = out.n_units
        # Architectural wiring assertion — at least one transition must
        # round-trip through actor → server → response. If this fails,
        # the InferenceClient threading or obs_dict adapter is broken.
        assert n_trans > 0, 'no transitions collected within 20s — mp wiring broken'
    finally:
        collector.close()


def test_build_dmc_provider_requires_inference_client():
    """``build_dmc_provider`` raises if ``inference_client`` kwarg is
    missing — CS4 strict (no LocalNetworkProvider fallback in mp mode).
    """
    from training.paradigms.dmc.mp_factories import build_dmc_provider

    class _Cfg:
        pass

    with pytest.raises(ValueError, match='inference_client kwarg required'):
        build_dmc_provider(_Cfg(), actor_id=0)
