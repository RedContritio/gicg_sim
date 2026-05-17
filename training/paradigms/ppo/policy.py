"""PPOEpisodePolicy — sample from policy logits + record log_prob/value
+ finalize GAE on episode end.

Implements core.protocols.EpisodePolicy. The actor side of PPO: at each
step sample a∼Categorical(masked_logits) and record (action, log_prob,
value) into transition meta (P3.1, P3.3). At episode end, compute GAE
advantages + returns from the recorded (reward, value, done) sequence
(per P1.1 — λ=0.95 default).

Eval policy SHALL be deterministic argmax (P3.2) — controlled by
``deterministic=True`` ctor flag.

GAE formula (preserved from the retired PPO legacy stack, FU-W4-PPO):
  δ_t = r_t + γ·V(s_{t+1})·(1-done_t) − V(s_t)
  A_t = δ_t + γ·λ·(1-done_t)·A_{t+1}
  R_t = A_t + V(s_t)
Episode boundary handling: bootstrap V_{T} = 0 (no next-state value).
"""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np


def compute_gae(
    rewards: np.ndarray,
    values: np.ndarray,
    dones: np.ndarray,
    gamma: float,
    lam: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generalized Advantage Estimation. Returns (advantages, returns).

    Formula preserved from the retired PPO legacy stack (FU-W4-PPO) for
    s021-s054 reproducibility (P6.2). Episode boundaries are the True
    entries in ``dones``; bootstrap V=0 at episode end (no next-state
    value).
    """
    T = len(rewards)
    advs = np.zeros(T, dtype=np.float32)
    last_gae = 0.0
    for t in reversed(range(T)):
        if dones[t]:
            next_value = 0.0
            next_nonterminal = 0.0
        else:
            next_value = values[t + 1] if t + 1 < T else 0.0
            next_nonterminal = 1.0
        delta = rewards[t] + gamma * next_value * next_nonterminal - values[t]
        last_gae = delta + gamma * lam * next_nonterminal * last_gae
        advs[t] = last_gae
    returns = advs + values
    return advs, returns


class PPOEpisodePolicy:
    """Categorical-sample actor over masked policy logits.

    Stateful per episode: collects (action, log_prob, value, reward,
    done) tuples in a buffer, finalizes GAE at episode end. PPO is on-
    policy so old_log_prob recorded here is the importance-ratio
    reference for the loss step (P3.3)."""

    # Schema tag for downstream Buffer compat checks.
    transition_schema = 'ppo_transition'

    def __init__(
        self,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        seed: int = 0,
        deterministic: bool = False,
    ) -> None:
        self.gamma = float(gamma)
        self.gae_lambda = float(gae_lambda)
        self.deterministic = bool(deterministic)
        self.rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)
        self._buf: list[dict] = []

    def reset(self) -> None:
        """Clear per-episode rollout buffer."""
        self._buf = []

    def act(self, obs: Any, mask: Any, provider: Any) -> tuple:
        """Decide one action.

        Args:
            obs: paradigm-shaped observation (forwarded to provider).
            mask: legal action mask (boolean array length max_actions).
            provider: NetworkProvider; ``provider.forward(obs, mask)``
                must return dict with 'logits' (or raw tensor logits)
                and 'value' (scalar).
        Returns:
            (action_idx, meta_dict). meta carries log_prob + value +
            n_legal for diagnostics.
        """
        out = provider.forward(obs, mask)

        # Accept either dict head output or raw tuple (logits, value).
        if isinstance(out, dict):
            logits = out['logits'] if 'logits' in out else out['policy']
            value = out.get('value', 0.0)
        elif isinstance(out, tuple) and len(out) == 2:
            logits, value = out
        else:
            raise TypeError(
                f'PPOEpisodePolicy.act: provider output must be dict with logits+value '
                f'or (logits, value) tuple; got {type(out).__name__}'
            )

        try:
            arr = logits.detach().cpu().numpy()
        except AttributeError:
            arr = np.asarray(logits)
        flat = np.asarray(arr, dtype=np.float64).reshape(-1)

        # Coerce scalar value (may be 0-d tensor / ndarray / float).
        try:
            value_f = float(value.detach().cpu().item())
        except AttributeError:
            try:
                value_f = float(np.asarray(value).item())
            except (TypeError, ValueError):
                value_f = float(value)

        if mask is not None:
            mflat = np.asarray(mask).reshape(-1).astype(bool)
            n = min(flat.shape[0], mflat.shape[0])
            legal_indices = np.where(mflat[:n])[0]
        else:
            legal_indices = np.arange(flat.shape[0])

        if legal_indices.size == 0:
            return 0, {'log_prob': 0.0, 'value': value_f, 'n_legal': 0}

        # Numerically stable softmax over legal logits only.
        sub = flat[legal_indices]
        sub_max = float(sub.max())
        sub_exp = np.exp(sub - sub_max)
        sub_sum = float(sub_exp.sum())
        probs = sub_exp / sub_sum  # over legal subset

        if self.deterministic:
            # P3.2: eval = deterministic argmax over legal.
            local_idx = int(np.argmax(probs))
        else:
            # P3.1: sample Categorical over legal.
            local_idx = int(self._np_rng.choice(len(probs), p=probs))

        action = int(legal_indices[local_idx])
        # log_prob in the legal-only softmax = log(p_chosen).
        log_prob = float(math.log(max(probs[local_idx], 1e-12)))

        return action, {
            'log_prob': log_prob,
            'value': value_f,
            'n_legal': int(legal_indices.size),
        }

    def record(self, obs: Any, legal_mask: Any, action: int, meta: dict, reward: float) -> None:
        """Append a transition to the per-episode buffer (called by
        collector after env.step). The done flag is set on the LAST
        transition by ``finalize_episode``."""
        self._buf.append(
            {
                'obs': obs,
                'legal_mask': legal_mask,
                'action': int(action),
                'log_prob': float(meta.get('log_prob', 0.0)),
                'value': float(meta.get('value', 0.0)),
                'reward': float(reward),
                'done': False,
            }
        )

    def finalize_episode(self, winner: int, acting_player: int = 0) -> list[dict]:
        """Mark last transition as done, compute GAE advantages +
        returns, return list of finalized transition dicts.

        Args:
            winner: env winner id (0 / 1 / -1 draw / 2 timeout-draw).
                Unused here — terminal reward is already in self._buf
                via env.step (PPO uses dense shaping from env, not the
                AZ-style ±1 backfill).
            acting_player: our perspective side (0 or 1). Unused here
                for the same reason; kept for protocol symmetry.
        Returns:
            list of dicts {obs, legal_mask, action, log_prob, value,
            reward, done, advantage, return}.
        """
        del winner, acting_player  # info already in env-returned rewards
        if not self._buf:
            return []
        # Mark last transition done so GAE bootstrap V_{T+1}=0 fires.
        self._buf[-1]['done'] = True

        rewards = np.array([t['reward'] for t in self._buf], dtype=np.float32)
        values = np.array([t['value'] for t in self._buf], dtype=np.float32)
        dones = np.array([t['done'] for t in self._buf], dtype=bool)

        advantages, returns = compute_gae(rewards, values, dones, self.gamma, self.gae_lambda)

        out: list[dict] = []
        for i, t in enumerate(self._buf):
            rec = dict(t)
            rec['advantage'] = float(advantages[i])
            rec['return'] = float(returns[i])
            out.append(rec)
        return out
