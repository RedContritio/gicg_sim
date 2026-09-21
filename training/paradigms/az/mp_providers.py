"""Inference providers used by AZ actor processes."""

from __future__ import annotations

import random
from typing import Any

from training.paradigms.az.mp_utils import derive_seed

RING_TAG = 'az_hist_ring'
WEIGHTS_TAG = 'latest'


class _AZRemoteProvider:
    def __init__(self, cfg: Any, actor_id: int, client: Any) -> None:
        from training.paradigms.az.collector import _build_mcts_config
        from training.paradigms.az.config import AZParadigmConfig
        from training.paradigms.az.pool_spec import make_pool_spec, resolve_pool_refs

        self.cfg = cfg
        self.actor_id = int(actor_id)
        self._client = client
        self.pcfg = AZParadigmConfig.from_dict(cfg.paradigm if isinstance(cfg.paradigm, dict) else {})
        self.card_pool_spec = make_pool_spec(cfg.scenario, resolve_pool_refs(cfg.scenario))
        self.mcts_config = _build_mcts_config(self.pcfg)
        self.n_counter_slots = int(self.pcfg.agent.n_counter_slots)
        self.max_actions = int(self.pcfg.agent.max_actions)
        self.max_game_steps = int(self.pcfg.max_game_steps)
        self.rng = random.Random(derive_seed(int(cfg.meta.seed), 'az_selfplay', self.actor_id))
        self.opponent_pool: Any = None
        self._opp_ring_shm: Any = None
        self._opp_ring_version = -1

    def attach_opponent_pool(self, pool: Any) -> None:
        self.opponent_pool = pool

    def game_start(self, static_obs: Any) -> dict:
        return self._client.game_start(static_obs)

    def eval_state(self, dyn: Any, refs: Any, payments: Any):
        return self._client.eval_state(dyn, refs, payments)

    def game_end(self) -> None:
        return self._client.game_end()

    def update_weights(self) -> int:
        self._refresh_ring()
        return self.current_version()

    def _refresh_ring(self) -> None:
        if self._opp_ring_shm is not None and self.opponent_pool is not None:
            payload, version = self._opp_ring_shm.read(RING_TAG)
            if payload is not None and version > self._opp_ring_version:
                self.opponent_pool.load_snapshots(payload.get('snapshots', []))
                self._opp_ring_version = version

    def current_version(self) -> int:
        version = getattr(self._client, 'current_weight_version', None)
        return int(version) if version is not None and int(version) >= 0 else 0

    def close(self) -> None:
        close = getattr(self._client, 'close', None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


class _AZLocalProvider(_AZRemoteProvider):
    def __init__(self, cfg: Any, actor_id: int, agent: Any, weights_shm_info: Any) -> None:
        super().__init__(cfg, actor_id, client=None)
        from training.core.actor.weights_shm import WeightsSHM

        self._agent = agent
        self._local_version = -1
        self._weight_shm = WeightsSHM.attach(weights_shm_info)
        self.update_weights()

    def game_start(self, static_obs: Any) -> dict:
        return self._agent.game_start(static_obs)

    def eval_state(self, dyn: Any, refs: Any, payments: Any):
        return self._agent.eval_state(dyn, refs, payments)

    def game_end(self) -> None:
        return self._agent.game_end()

    def update_weights(self) -> int:
        state_dict, version = self._weight_shm.read(WEIGHTS_TAG)
        if state_dict is not None and version > self._local_version:
            self._agent.net.load_state_dict(state_dict)
            self._local_version = version
        self._refresh_ring()
        return self.current_version()

    def current_version(self) -> int:
        return max(self._local_version, 0)

    def close(self) -> None:
        return None
