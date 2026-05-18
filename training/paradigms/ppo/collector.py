"""PPORolloutCollector — on-policy rollout per outer iter.

One ``collect`` call = one full PPO rollout iter (``n_games_per_iter``
self-play / asymmetric games), producing typed transition records
(with GAE advantages + returns pre-computed per trajectory).

Per ``ppo-structural-backbone-migration`` invariant A4: Transition
payload SHALL be structured dict (``dyn_obs / refs / payments /
n_legal / log_prob / value / advantage / return``) — flat ``obs``
vector path retired alongside ``_PPOMLPTrunk``.

Rollout primitives live in sibling ``training.paradigms.ppo._rollout``
(line-limit hook split). GAE computation lives in
``training.paradigms.ppo.policy.compute_gae`` (formula preserved from
the retired PPO legacy stack for s021-s054 reproducibility per P6.2,
though numerical reproducibility broken by backbone switch per D-302).

The collector emits ``Transition`` records on
``CollectorOutput.transitions`` (unlike DMC which routes through
``runtime_metrics``) because PPO's buffer is the typed ``RolloutBuffer``
from ``training/core/buffer/rollout.py`` which consumes
``batch.transitions`` directly. ``Transition.obs`` is unused (set None);
all structural inputs live in ``Transition.payload``.

PPOAsyncCollector(FU-W3b-PPO):走 W3a ``core/actor`` 真 mp 的简单接通,
实际 impl 在 sibling module ``training.paradigms.ppo._async``(line-limit
hook 拆分);此模块 re-export 公共 surface。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from training.core.protocols import CollectorOutput, Transition
from training.paradigms.ppo._async import PPOAsyncCollector
from training.paradigms.ppo._collate import transitions_to_collated
from training.paradigms.ppo._rollout import (
    TrajBuf,
    make_rollout_opponent,
    run_training_game,
)
from training.paradigms.ppo.policy import compute_gae

# Test compat: tests reach for the parsing helper by leading-underscore
# name (was a private helper in the pre-W4 collector). Re-export.
_make_rollout_opponent = make_rollout_opponent

__all__ = [
    'PPORolloutCollector',
    'PPOAsyncCollector',
    'derive_seed',
    '_make_rollout_opponent',
    'transitions_to_collated',
]


def derive_seed(master_seed: int, *labels: Any) -> int:
    """Deterministic seed derivation from master + arbitrary labels.

    Lifted from DMC adapter — used by collector to give env / rollout
    rng disjoint seed streams that resume reproducibly."""
    h = master_seed & 0xFFFFFFFF
    for lab in labels:
        s = repr(lab).encode('utf-8')
        for b in s:
            h = (h * 1000003) ^ b
            h &= 0xFFFFFFFF
    return int(h & 0x7FFFFFFF)


def _trajbuf_to_transitions(
    t: TrajBuf,
    gamma: float,
    gae_lambda: float,
) -> tuple[list[Transition], int]:
    """Convert a TrajBuf to a list of Transitions with GAE-filled payload."""
    T = len(t.reward)
    if T == 0:
        return [], 0
    rewards = np.asarray(t.reward, dtype=np.float32)
    values = np.asarray(t.value, dtype=np.float32)
    dones = np.asarray(t.done, dtype=bool)
    advs, rets = compute_gae(rewards, values, dones, gamma, gae_lambda)
    transitions: list[Transition] = []
    for i in range(T):
        transitions.append(
            Transition(
                obs=None,  # structural inputs live in payload; obs vector deprecated
                action=int(t.action[i]),
                legal_mask=None,  # legal_mask is reconstructed from n_legal at collate
                reward=float(rewards[i]),
                done=bool(dones[i]),
                payload={
                    'dyn_obs': t.dyn_obs[i],
                    'refs': t.refs[i],
                    'payments': t.payments[i],
                    'n_legal': int(t.n_legal[i]),
                    'log_prob': float(t.log_prob[i]),
                    'value': float(values[i]),
                    'advantage': float(advs[i]),
                    'return': float(rets[i]),
                },
            )
        )
    return transitions, T


class PPORolloutCollector:
    """On-policy rollout collector for PPO adapter.

    Args:
        cfg: TrainingConfig (driver-level; reads cfg.scenario + cfg.meta.seed).
        paradigm_cfg: PPOParadigmConfig.
        network: PPONetwork (the trainer-side network — sync, no stale
            weights in serial mode).
        env_factory: callable(game_idx) → GicgEnv (built by tools.runs.train).
            Not used by the inlined rollout body (env construction is
            scenario-driven), kept on the ctor for protocol parity.
            Required (None raises).
    """

    requires_network_in_collect = True

    def __init__(
        self,
        cfg: Any,
        paradigm_cfg: Any,
        network: Any,
        env_factory: Any,
    ) -> None:
        if env_factory is None:
            raise ValueError('PPORolloutCollector: env_factory required (None passed)')
        self.cfg = cfg
        self.pcfg = paradigm_cfg
        self.network = network
        self.env_factory = env_factory
        self._iter_seq = 0
        self._master_seed = int(cfg.meta.seed)
        self._rng_seeded = np.random.default_rng(derive_seed(self._master_seed, 'ppo-rollout'))

    def collect(self, n_units: int, provider: Any) -> CollectorOutput:
        """Run one PPO rollout iter.

        ``n_units`` is interpreted as ``n_games`` for PPO (one outer
        iter = pcfg.rollout.n_games_per_iter games by default, but
        driver may pass an override).

        Provider is ignored in serial mode because network forward is
        in-process. Async mode goes through PPOAsyncCollector instead.
        """
        del provider  # serial: in-process forward through self.network
        self._iter_seq += 1
        scen = self.cfg.scenario

        # Per-iter rng (mirrors retired legacy training: numpy default_rng
        # keyed off master + iter_seq for resume reproducibility).
        iter_seed = derive_seed(self._master_seed, 'ppo-iter', self._iter_seq)
        rng = np.random.default_rng(iter_seed)

        n_games = int(n_units) if n_units > 0 else self.pcfg.rollout.n_games_per_iter
        # rollout_opponent may be a single spec or comma-separated mix.
        specs = [s.strip() for s in self.pcfg.rollout.rollout_opponent.split(',') if s.strip()]

        # Resolve the agent (PPONetwork wraps PPOAgent).
        agent = self.network.agent if hasattr(self.network, 'agent') else self.network

        trajectories: list[TrajBuf] = []
        game_infos: list[dict] = []
        for _ in range(n_games):
            spec = specs[int(rng.integers(0, len(specs)))] if len(specs) > 1 else specs[0]
            p1_opp = None if spec == 'self' else make_rollout_opponent(spec, rng)
            bufs, info = run_training_game(agent, scen, self.pcfg, rng, agent.device, p1_opp)
            trajectories.extend(bufs)
            game_infos.append(info)

        transitions: list[Transition] = []
        n_trans_total = 0
        for t in trajectories:
            t_list, T = _trajbuf_to_transitions(t, self.pcfg.gamma, self.pcfg.gae_lambda)
            transitions.extend(t_list)
            n_trans_total += T

        episode_stats: list = []
        for info in game_infos:
            episode_stats.append(
                {
                    'iter_seq': self._iter_seq,
                    'winner': int(info.get('winner', -1)),
                    'rounds': int(info.get('rounds', 0)),
                }
            )

        return CollectorOutput(
            transitions=transitions,
            episode_stats=episode_stats,
            runtime_metrics={'n_games': len(game_infos)},
            n_units=n_trans_total,
        )

    def close(self) -> None:
        return None

    def state_dict(self) -> dict:
        return {'iter_seq': self._iter_seq, 'master_seed': self._master_seed}

    def load_state_dict(self, sd: dict) -> None:
        self._iter_seq = int(sd.get('iter_seq', 0))
        self._master_seed = int(sd.get('master_seed', self._master_seed))
