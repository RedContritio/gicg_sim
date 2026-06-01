"""CFRAsyncCollector — parent side of the I31 #88 CFR mp-pool unification.

N actors run game-tree **traversals** (not episode rollouts) via the shared
``core/actor`` runtime: each spawned ``actor_main`` resolves the CFR
``mp_factories`` builders by dotted path, then drives a
:class:`~training.paradigms.cfr.mp_factories.CFRTraversalRunner` (AB14
``episode_runner_factory``) instead of the default ``EpisodeRunner``. Per
traversal it pushes a :class:`_CFRRunnerOutput` (carrying a ``CFRGameBatch``)
back through the IPCQueue; ``collect`` drains those and returns a
``CollectorOutput`` whose shape is byte-for-byte the serial
``CFRTraversalCollector.collect`` contract so ``_CFRBufferBundle.push``
ingests mp and serial output identically.

**2-slot weights handoff** (D2=A): CFR's regret-matching forward only needs
the per-player advantage heads, so the parent publishes TWO named SHM slots
``cfr_adv_p0`` / ``cfr_adv_p1`` (vs PPO's single ``latest``). The
strategy_net stays trainer-local (design.md §10 uncertainty 3). Actors poll
both slots between traversals (D3=C continuous loop, no barrier).

**Composed escape hatches**: CFR sets BOTH ``provider_kwargs`` (AB13 — the
WeightsSHM info + blueprint tempfile handoff, like PPO) AND
``episode_runner_factory_path`` (AB14 — the traversal runner). They are
orthogonal; this is the intended composition (verified in T1).

**Blueprint correctness**: the network blueprint is built from independent
``deepcopy``-then-``.cpu()`` copies of the two advantage heads — NOT the live
training network. PPO's template does an in-place ``network.cpu()`` which
would silently migrate a GPU/MPS-resident training net to CPU; CFR avoids
that latent bug so the live net's device is untouched.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from training.core.protocols import CollectorOutput


class CFRAsyncCollector:
    """N-actor real-mp CFR traversal collector via the shared core/actor
    runtime. ``env_factory`` is accepted for signature parity but unused —
    actors rebuild env from ``cfg.scenario`` in their own process."""

    requires_network_in_collect = True
    _drain_timeout_s: float = 60.0

    def __init__(self, cfg: Any, paradigm_cfg: Any, network: Any, env_factory: Any = None) -> None:
        del env_factory  # actors rebuild env from cfg.scenario (mp_factories.build_env_factory)
        import copy
        import pickle
        import tempfile

        from training.core.actor.ipc.queue import IPCQueue
        from training.core.actor.runtime import Runtime
        from training.core.actor.weights_shm import WeightsSHM

        n_actors = int(getattr(cfg.pipeline, 'num_actors', 1))
        if n_actors < 1:
            raise ValueError(f'CFRAsyncCollector: num_actors must be ≥ 1, got {n_actors}')

        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self._master_seed = int(cfg.meta.seed)
        self._iter_seq = 0
        self._closed = False
        # Resource handles set to None first so close() (called on a partial
        # __init__ failure below) can tear down whatever got built without
        # AttributeError. The driver builds the collector OUTSIDE its
        # try/finally close() scope, so __init__ must self-clean on failure or
        # the owner SHM / tempdir / already-spawned actors leak.
        self._weights_shm = None
        self._tmpdir = None
        self._queue = None
        self._runtime = None
        try:
            # SHM sized for BOTH advantage heads' state dicts (2x total + margin,
            # floor 64MiB). Publish before spawn (W3a #2) so no actor reads a cold slot.
            nb = 0
            for p in (0, 1):
                nb += sum(t.numel() * t.element_size() for t in network.advantage_head(p).state_dict().values())
            self._weights_shm = WeightsSHM(max_state_dict_bytes=max(64 * 1024 * 1024, 2 * nb + 16384), owner=True)
            self._weights_version = 1
            self._publish_advantage_heads(network, version=1)
            weights_shm_info = self._weights_shm.serialize_for_worker(['cfr_adv_p0', 'cfr_adv_p1'])

            # Blueprint = a 2-element list of CPU AdvantageNet copies. build_provider
            # pickle.loads → list of 2 nets, then overwrites their weights from SHM,
            # so only the architecture must be correct. deepcopy + .cpu() keeps the
            # live training network's device untouched (PPO template's in-place
            # network.cpu() would migrate a GPU/MPS net — CFR does NOT).
            nets_bp = [copy.deepcopy(network.advantage_head(p)).cpu() for p in (0, 1)]
            self._tmpdir = Path(tempfile.mkdtemp(prefix='gicg_cfr_async_'))
            bp_path = self._tmpdir / 'cfr_adv_nets.pkl'
            with open(bp_path, 'wb') as f:
                pickle.dump(nets_bp, f, protocol=pickle.HIGHEST_PROTOCOL)
            network_blueprint_path = str(bp_path)

            # Queue sized for n_actors × traversals_per_iteration (generous ×2).
            tpi = int(paradigm_cfg.traversals_per_iteration)
            self._queue = IPCQueue(maxsize=max(256, n_actors * tpi * 2))
            self._runtime = Runtime(cfg, weights_shm=self._weights_shm)

            m = 'training.paradigms.cfr.mp_factories'
            kw = {f'build_{k}_path': f'{m}.build_{k}' for k in ('env_factory', 'opp_registry', 'policy', 'provider')}
            kw['spec_sampler_path'] = f'{m}.cfr_spec_sampler'
            kw['episode_runner_factory_path'] = f'{m}.build_cfr_traversal_runner'  # AB14 — traversal not episode
            kw['transition_queue'] = self._queue
            kw['push_episode_record'] = True  # push the full _CFRRunnerOutput (carries cfr_batch)
            self._runtime.start_actors(
                n_actors=n_actors,
                actor_kwargs_factory=lambda i: dict(
                    kw,
                    provider_kwargs={
                        'weights_shm_info': weights_shm_info,
                        'network_blueprint_path': network_blueprint_path,
                    },
                ),
            )
        except BaseException:
            self.close()  # tear down partial resources, then propagate
            raise

    def _publish_advantage_heads(self, network: Any, version: int) -> None:
        # CPU detach copies into the 2 named slots (worker reads both).
        for p in (0, 1):
            sd = {k: v.detach().cpu() for k, v in network.advantage_head(p).state_dict().items()}
            self._weights_shm.write(f'cfr_adv_p{p}', sd, version=int(version))

    def collect(self, n_units: int, provider: Any) -> CollectorOutput:
        """Drain ``target`` traversals' ``_CFRRunnerOutput`` from the queue
        (n_units = n_traversals, 0 → pcfg.traversals_per_iteration). provider
        ignored — each actor owns its provider. Output shape matches the serial
        ``CFRTraversalCollector.collect`` so ``_CFRBufferBundle.push`` is identical."""
        del provider
        self._iter_seq += 1
        target = int(n_units) if n_units > 0 else int(self.pcfg.traversals_per_iteration)

        batches: list = []
        traversal_stats: list = []
        n_samples_total = 0
        n_drained = 0
        deadline = time.time() + self._drain_timeout_s
        while n_drained < target and time.time() < deadline:
            try:
                item = self._queue.get(timeout=0.5)
            except Exception:
                continue
            if item is None:
                continue
            batch = item.cfr_batch
            batches.append(batch)
            n_adv0, n_adv1, n_strat, n_val = batch.n_samples()
            n_samples_total += n_adv0 + n_adv1 + n_strat + n_val
            n_drained += 1
            traversal_stats.append(
                {
                    'traversal_idx': n_drained,
                    'iteration': self._iter_seq,
                    'n_adv': int(n_adv0 + n_adv1),
                    'n_strat': int(n_strat),
                    'n_val': int(n_val),
                }
            )

        if n_drained < target:
            # Short drain at deadline — a slow/dead actor pool under-feeds the
            # trainer. Surface it (parity with PPO's n_*_drained metrics) instead
            # of silently returning a thin buffer iteration after iteration.
            print(
                f'[CFRAsyncCollector] short drain: {n_drained}/{target} traversals '
                f'in {self._drain_timeout_s}s (iter {self._iter_seq})'
            )
        return CollectorOutput(
            transitions=[],  # CFR uses cfr_batches in runtime_metrics
            episode_stats=traversal_stats,
            runtime_metrics={
                'cfr_batches': batches,
                'cfr_iteration': self._iter_seq,
                'n_drained': n_drained,
                'target_traversals': target,
            },
            n_units=n_samples_total,
        )

    def sync_weights(self, network: Any) -> None:
        # Publish both advantage heads at the next version; actors poll between
        # traversals via _CFRActorProvider.update_weights (D3=C, no barrier).
        self._weights_version += 1
        self._publish_advantage_heads(network, version=self._weights_version)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        import shutil

        # None-safe: __init__ may call this on a partial-construction failure.
        # The owner WeightsSHM must be closed HERE — Runtime was handed the shm
        # (owns_shm=False), so Runtime.close does NOT unlink it; skipping this
        # leaks the POSIX SHM segment.
        for fn in (
            (self._runtime.close if self._runtime is not None else None),
            (self._queue.close if self._queue is not None else None),
            (self._weights_shm.close if self._weights_shm is not None else None),
            (lambda: shutil.rmtree(self._tmpdir, ignore_errors=True)) if self._tmpdir is not None else None,
        ):
            if fn is None:
                continue
            try:
                fn()
            except Exception:
                pass

    def state_dict(self) -> dict:
        return {'iter_seq': self._iter_seq, 'master_seed': self._master_seed, 'weights_version': self._weights_version}

    def load_state_dict(self, sd: dict) -> None:
        self._iter_seq = int(sd.get('iter_seq', 0))
        self._master_seed = int(sd.get('master_seed', self._master_seed))
        self._weights_version = int(sd.get('weights_version', self._weights_version))
