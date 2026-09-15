"""Private per-actor remote provider for DMC mp mode。

Split out of ``mp_factories.py`` for the file-budget cap (pure relocation —
no behavioural change). ``build_dmc_provider`` in
:mod:`training.paradigms.dmc.mp_factories` is the public entry point; this
module owns the implementation class it constructs.

See ``mp_factories.py`` module docstring for the decode-offload /
I25 response-numpy architecture rationale.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from training.paradigms.dmc._decoder import _capture_obs_np, _encode_static_np


class _DMCObsDictRemoteProvider:
    """Per-actor provider — pure-numpy obs encoding + numpy IPC payload.

    No torch imports. Sends raw env data (static_obs only on game_start,
    then dyn_obs + refs + payments per turn) to the server via
    :class:`InferenceClient`; the server's ``request_decoder`` handles
    static-cache encoding + tensor materialisation.

    Each :meth:`observe_env` call may trigger a game_start: detected by
    ``id(env._engine)`` change. On game_start the next ``forward`` sends
    a payload tagged ``static_obs_changed=True`` and embeds the raw
    static_obs bytes; subsequent turns send ``static_obs_changed=False``
    + the server pulls from its cache.

    Buffer-side obs capture: :meth:`forward` also computes the numpy
    obs_dict via :func:`_capture_obs_np` and stashes it on
    ``self.last_obs_dict``. :class:`DMCEpisodePolicy` reads it into
    ``meta['dmc_obs_dict']`` so the collector reconstructs
    :class:`DmcTransition` from the actor push. The two obs payloads are
    independent: server-side payload routes to the GPU forward, buffer
    payload routes to training (collator → forward_batch).
    """

    transition_schema = 'dmc_transition'

    def __init__(self, cfg: Any, actor_id: int, client: Any) -> None:
        from training.paradigms.dmc.config import DMCParadigmConfig

        self.cfg = cfg
        self.actor_id = actor_id
        self.client = client
        pdict = cfg.paradigm if isinstance(cfg.paradigm, dict) else {}
        pcfg = DMCParadigmConfig.from_dict(pdict)
        self.agent_cfg = pcfg.agent
        self.n_counter_slots = int(pcfg.agent.n_counter_slots)
        self.max_actions = int(pcfg.agent.max_actions)
        self.n_hooks = int(pcfg.agent.n_hooks)
        self.max_ops_per_hook = int(pcfg.agent.max_ops_per_hook)
        self.fields_per_op = int(pcfg.agent.fields_per_op)

        self._env_ref: Any = None
        self._last_static_id: int = -1
        self._static_obs_np: np.ndarray = None  # type: ignore[assignment]
        # static_obs hash (16-byte sha256-truncated) — server's shared_cache key.
        # Same hash across actors/episodes sharing one scenario, so the
        # server's hook_encoder runs ONCE for the whole fleet, not once
        # per actor×episode. Computed on game_start; sent every forward.
        self._static_obs_hash: bytes = b''
        # Numpy-form static fields cached per game — used by buffer-side
        # capture_obs (server holds its own torch cache for forward).
        self._static_np_fields: dict = {}
        # On the next forward, send static_obs bytes to server so its
        # cache can rebuild the torch static tensors. Cleared after first
        # forward of a new game.
        self._static_dirty: bool = False
        self.version = 0
        self.last_obs_dict: Any = None

    def observe_env(self, env: Any) -> None:
        """Called by the actor loop hook before each policy.act. Caches
        env reference + detects new episode via ``env._engine`` identity
        change. On change, re-parse static fields into numpy and flag
        ``_static_dirty`` so the next forward ships the static_obs.
        """
        self._env_ref = env
        eid = id(getattr(env, '_engine', env))
        if eid != self._last_static_id:
            static = env.static_obs if hasattr(env, 'static_obs') else env._get_static_obs()
            self._static_obs_np = np.ascontiguousarray(static, dtype=np.float32)
            # Hash the canonical bytes (fixed dtype) so two actors with the
            # same scenario produce the same key. 16-byte sha256-truncated
            # (sha256[:16]) used so Go actor side(I29)能用 crypto/sha256 stdlib
            # 算同 hash 而不引入 blake2b external dep。 Collision-safe enough for
            # this cache;2^64 birthday bound on 16-byte trunc remains > production
            # scenario diversity by many OOMs。
            import hashlib

            self._static_obs_hash = hashlib.sha256(self._static_obs_np.tobytes()).digest()[:16]
            self._static_np_fields = _encode_static_np(
                self._static_obs_np,
                n_counter_slots=self.n_counter_slots,
                n_hooks=self.n_hooks,
                max_ops_per_hook=self.max_ops_per_hook,
                fields_per_op=self.fields_per_op,
            )
            self._static_dirty = True
            self._last_static_id = eid

    def forward(self, obs: Any, mask: Any) -> Any:
        if self._env_ref is None:
            raise RuntimeError(
                '_DMCObsDictRemoteProvider.forward: observe_env(env) must be called per turn '
                'before policy.act so the obs_dict can be encoded with cached static fields.'
            )
        from training.core.step_encoding import (
            pad_action_payments,
            pad_action_refs,
        )

        env = self._env_ref
        dyn_obs = np.ascontiguousarray(env._get_obs(), dtype=np.float32)
        kinds, _ = env.get_legal_actions()
        n_legal = int(len(kinds))
        refs_np = np.asarray(env.get_action_refs(), dtype=np.int64)
        pay_np = np.asarray(env.get_legal_action_payments(), dtype=np.float32)
        # InfServer payload 仍走 padded(server-side batched forward 要 fixed shape)。
        refs_padded = pad_action_refs(refs_np, self.max_actions)
        pay_padded = pad_action_payments(pay_np, self.max_actions)
        # Buffer-side obs_dict (I29 P2 wire v3) — nlegal-sized;collate_batch pad 到
        # cfg.max_actions for batch forward。 per-trans mem ~10x 降。
        refs_nlegal = refs_np[:n_legal]
        pay_nlegal = pay_np[:n_legal]

        # Buffer-side numpy obs_dict: must mirror DmcAgent.build_obs_dict
        # shapes (pure numpy version of capture_obs).
        self.last_obs_dict = _capture_obs_np(
            dyn_obs=dyn_obs,
            n_legal=n_legal,
            refs_nlegal=refs_nlegal,
            pay_nlegal=pay_nlegal,
            n_counter_slots=self.n_counter_slots,
            static_np=self._static_np_fields,
        )

        # Server-side numpy payload — small (~10 KB vs ~4-13 MB torch).
        # static_obs_hash is the server's shared_cache key (same across
        # actors/episodes sharing the scenario → encode runs ONCE total).
        # Embedded static_obs only on dirty turn (game_start) so the
        # server can resolve cache misses without round-tripping back to
        # the actor.
        payload = {
            'static_obs_hash': self._static_obs_hash,
            'static_obs': self._static_obs_np if self._static_dirty else None,
            'dyn_obs': dyn_obs,
            'refs_padded': refs_padded.astype(np.int64),
            'pay_padded': pay_padded.astype(np.float32),
        }
        self._static_dirty = False
        out = self.client.request(payload, None)
        # Server-side ``request_decoder_path`` path returns numpy bytes
        # (I25 — actor stays torch-free, saves ~400 MB CUDA mmap RSS per
        # actor). ``out`` is a ``np.ndarray`` of shape (1, max_actions).
        # DMC policy expects ``{'logit_as_q': arr}``; ``arr[0]`` slices the
        # batch dim away to match the in-proc forward's per-step shape.
        if isinstance(out, np.ndarray):
            return {'logit_as_q': out[0]}
        # Defensive: in case the server is rewired with no decoder path
        # (legacy torch response) we still return ``out`` unwrapped so
        # the policy's existing ``out['logit_as_q'] if dict else out``
        # branch covers both response shapes without crashing.
        return out

    def update_weights(self, version_tag: Any = None, state_dict: Any = None) -> int:
        # Server owns weights. Server also clears its per-client static
        # cache on weight load (hook_emb depends on hook_encoder
        # weights). Actor just bumps its own version counter.
        self.version += 1 if version_tag is not None else 0
        return self.version

    def current_version(self) -> int:
        return self.version

    def device(self) -> Any:
        # Actor doesn't import torch at top-level. Return a stringly
        # typed device — callers either ignore this or pass it back into
        # torch later (where torch is already loaded).
        if hasattr(self.client, 'server_device'):
            return self.client.server_device()
        return 'cpu'

    def close(self) -> None:
        if hasattr(self.client, 'close'):
            try:
                self.client.close()
            except Exception:
                pass
