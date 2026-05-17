"""PPO rollout primitives — opponent parsing + per-game play loop.

Split from collector.py for the 300-line cap. Per
``ppo-structural-backbone-migration`` invariant A2: rollout SHALL go
through ``agent.game_start(env.static_obs) cache + per-step
agent.act(env, rng)`` (matching AZ / DMC / BC), NOT the legacy
``env._get_obs() → net.forward(obs_flat)`` flat-MLP path.

Rollout semantics:

- ``rollout_opponent='self'`` → classic self-play (both sides use the
  training agent, both trajectories collected).
- Any other value → asymmetric — P0 uses the training agent (collected),
  P1 uses a fixed non-learning opponent (random or GreedyPlayer parsed
  from the string, e.g. 'F1-D1'). Used to break self-play collapse on
  stochastic stages where random-init self-play reaches a degenerate
  equilibrium.
- Comma-separated specs ('F1-D1,F1-D2') mix opponents uniform-random
  per game (breaks opponent-overfit).

Terminal handling: on game end the acting player sees the terminal
reward (reward_shaping.terminal_win/terminal_loss); the OTHER player's
last transition is tagged ``done=True`` so GAE bootstraps next_value=0.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from gicg_env import GicgEnv
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.step_encoding import pad_action_payments, pad_action_refs


def make_rollout_opponent(spec: str, rng: np.random.Generator) -> Callable[[GicgEnv], int]:
    """Parse a rollout_opponent spec into a P1 action callable.

    Accepts 'random' or 'F{i}-D{j}' / 'F{i}-D{j}-nogreedy'. 'self'
    must be handled by the caller (shortcut to self-play path)."""
    if spec == 'random':

        def act(env: GicgEnv) -> int:
            kinds, _ = env.get_legal_actions()
            if len(kinds) == 0:
                return 0
            return int(rng.integers(0, len(kinds)))

        return act
    parts = spec.split('-')
    if len(parts) < 2 or not parts[0].startswith('F') or not parts[1].startswith('D'):
        raise ValueError(f'unknown rollout_opponent {spec!r}; examples: self, random, F1-D1, F1-D2')
    features = parts[0]
    depth = int(parts[1][1:])
    dice_greedy = not (len(parts) >= 3 and parts[2] == 'nogreedy')
    seed = int(rng.integers(0, 2**31 - 1))
    player = GreedyPlayer(features=features, depth=depth, seed=seed, dice_greedy=dice_greedy)
    return player.select_action


class TrajBuf:
    """Per-player per-game transition accumulator (structural payload).

    Each push records the per-step structural inputs (dyn_obs / refs /
    payments / n_legal) the loss path needs to replay
    ``agent.forward_batch`` on a batched collated dict, plus the
    rollout-time (action / log_prob / value / reward) for GAE.

    Done flag is set on the LAST transition of this player by
    ``set_last_done`` so GAE bootstrap V_{T+1}=0 fires correctly.
    """

    def __init__(self) -> None:
        self.dyn_obs: list[np.ndarray] = []
        self.refs: list[np.ndarray] = []
        self.payments: list[np.ndarray] = []
        self.n_legal: list[int] = []
        self.action: list[int] = []
        self.log_prob: list[float] = []
        self.value: list[float] = []
        self.reward: list[float] = []
        self.done: list[bool] = []

    def push(
        self,
        dyn_obs: np.ndarray,
        refs: np.ndarray,
        payments: np.ndarray,
        n_legal: int,
        action: int,
        log_prob: float,
        value: float,
        reward: float,
    ) -> None:
        self.dyn_obs.append(np.asarray(dyn_obs, dtype=np.float32))
        self.refs.append(np.asarray(refs, dtype=np.int64))
        self.payments.append(np.asarray(payments, dtype=np.float32))
        self.n_legal.append(int(n_legal))
        self.action.append(int(action))
        self.log_prob.append(float(log_prob))
        self.value.append(float(value))
        self.reward.append(float(reward))
        self.done.append(False)

    def set_last_done(self) -> None:
        if self.done:
            self.done[-1] = True


def run_training_game(
    agent: Any,
    scen: Any,
    pcfg: Any,
    rng: np.random.Generator,
    device: Any,
    p1_opponent: Callable[[GicgEnv], int] | None,
) -> tuple[list[TrajBuf], dict]:
    """Play one training game. Returns (per-player bufs, info dict).

    If ``p1_opponent`` is None: self-play, returns 2 bufs (P0, P1).
    Else: asymmetric, returns [P0_buf] only.

    Per A2: uses ``agent.game_start(env.static_obs)`` + per-step
    ``agent.act(env, rng)`` — replacing the legacy
    ``net.forward(obs_flat)`` flat-MLP path.
    """
    del device  # agent owns its own device; legacy arg kept for caller compat
    fix_dice = list(scen.fix_dice) if getattr(scen, 'fix_dice', None) else None
    card_pool = list(getattr(scen, 'card_pool', None) or ())
    obs_mask = list(getattr(scen, 'obs_mask', None) or ()) or None
    env = GicgEnv(
        list(scen.team_0),
        list(scen.team_1),
        card_pool=card_pool,
        seed=int(rng.integers(0, 2**31 - 1)),
        data_dir=str(getattr(scen, 'data_dir', 'data')),
        max_rounds=int(getattr(scen, 'max_rounds', 3)),
        fix_dice=fix_dice,
        obs_mask=obs_mask,
        deck_padding=getattr(scen, 'deck_padding', None),
        pool=getattr(scen, 'pool', ['v_legacy', 'test_basic']),
        reward_shaping=dict(pcfg.reward_shaping),
    )
    is_self_play = p1_opponent is None
    bufs = [TrajBuf() for _ in range(2)]
    try:
        # Per A3: encode_static + cache once per game.
        agent.game_start(env.static_obs)
        for _ in range(pcfg.rollout.max_steps_per_game):
            if env.done:
                break
            kinds, _ = env.get_legal_actions()
            n_legal = int(len(kinds))
            if n_legal == 0:
                break
            actor = env.acting_player
            use_net = is_self_play or actor == 0

            if use_net:
                # Snapshot the structural inputs before action — loss
                # path replays forward_batch on these tensors. refs +
                # payments padded to agent.max_actions so stacked
                # tensors are uniform shape across transitions.
                dyn_obs_np = env._get_obs()
                refs_np = env.get_action_refs()
                pay_np = env.get_legal_action_payments()
                ma = int(agent.cfg.max_actions)
                refs_padded = pad_action_refs(refs_np, ma)
                pay_padded = pad_action_payments(pay_np, ma)
                a, meta = agent.act(env, rng, deterministic=False)
                log_prob = float(meta['log_prob'])
                v = float(meta['value'])
            else:
                # Fixed opponent path — no value/log_prob needed (not collected).
                a = int(p1_opponent(env))
                log_prob = 0.0
                v = 0.0
                dyn_obs_np = None
                refs_padded = None
                pay_padded = None

            _, reward, done, _ = env.step(a)

            if use_net:
                bufs[actor].push(
                    dyn_obs=dyn_obs_np,
                    refs=refs_padded,
                    payments=pay_padded,
                    n_legal=n_legal,
                    action=a,
                    log_prob=log_prob,
                    value=v,
                    reward=float(reward),
                )
            if done:
                if use_net:
                    bufs[actor].set_last_done()
                break

        for b in bufs:
            b.set_last_done()
        info = {
            'winner': env._engine.winner if env.done else -1,
            'rounds': env._engine.get_current_round(),
        }
    finally:
        agent.game_end()
        env.close()
    if is_self_play:
        return bufs, info
    return [bufs[0]], info
