"""DMCEpisodePolicy — ε-greedy argmax over logit-as-Q + MC return finalize.

Implements core.protocols.EpisodePolicy. The actor side of DMC: at each
step pick argmax_a logit(s, a) with probability 1-ε, uniform random
otherwise (D3.1). At episode end, finalize the recorded transitions
with MC return G ∈ {-1, 0, +1} from acting-player perspective (D1.2,
γ=1).

NOTE: P3-B serial-mode adapter does NOT route episode play through
`core.actor.EpisodeRunner` because GICG's obs capture is owned by
DmcAgent's private static cache; the collector calls
`training.dmc._episode.play_one_episode` directly. This policy class
exists for protocol conformance + tests + future P4 mp wiring (when
`EpisodeRunner` will gain typed obs hook).
"""

from __future__ import annotations

import random
from typing import Any, Optional


class DMCEpisodePolicy:
    """ε-greedy actor policy over logit-as-Q. Stateless across episodes;
    just an action picker — caller owns transition recording."""

    # Schema tag for downstream Buffer compat checks.
    transition_schema = 'dmc_transition'

    def __init__(self, epsilon: float = 0.05, seed: int = 0, deterministic: bool = False) -> None:
        self.epsilon = float(epsilon)
        self.deterministic = bool(deterministic)
        self.rng = random.Random(seed)

    def reset(self) -> None:
        """No per-episode state to reset (policy is memoryless across
        episodes; rng intentionally persistent for diverse ε explore)."""
        return None

    def act(self, obs: Any, mask: Any, provider: Any) -> tuple:
        """Decide one action.

        Args:
            obs: paradigm-shaped observation (forwarded to provider).
            mask: legal action mask (boolean array length max_actions).
            provider: NetworkProvider with forward(obs, mask) returning
                a dict with 'logit_as_q' (or similar) key. For DMC we
                interpret raw policy logits as Q values (D2.1).
        Returns:
            (action_idx, meta_dict). meta carries q_value of chosen
            action + whether ε-explore fired (for diagnostics). When
            the provider exposes ``last_obs_dict`` (mp path —
            :class:`_DMCObsDictRemoteProvider` populates it on every
            ``forward``), the numpy obs_dict is embedded under the
            ``dmc_obs_dict`` key so the collector can reconstruct a
            :class:`DmcTransition` from the actor push.
        """
        out = provider.forward(obs, mask)
        # Accept either dict head output or raw tensor logits.
        logits = out['logit_as_q'] if isinstance(out, dict) and 'logit_as_q' in out else out
        # logits may be torch tensor or numpy; normalize to numpy view for argmax.
        try:
            arr = logits.detach().cpu().numpy()
        except AttributeError:
            arr = logits

        # mask may be boolean array — squeeze invalid logits to -inf for argmax.
        import numpy as np

        flat = np.asarray(arr).reshape(-1)
        if mask is not None:
            mflat = np.asarray(mask).reshape(-1).astype(bool)
            # Defensive: if mask shorter than logits, treat trailing as illegal.
            n = min(flat.shape[0], mflat.shape[0])
            legal_indices = np.where(mflat[:n])[0]
        else:
            legal_indices = np.arange(flat.shape[0])

        # mp path: provider stashes the numpy obs_dict needed to rebuild
        # DmcTransition on the collector side. Serial path's
        # LocalNetworkProvider does NOT expose this attribute (serial
        # collector builds DmcTransition inline via play_one_episode), so
        # absence is expected — no-op then.
        dmc_obs_dict = getattr(provider, 'last_obs_dict', None)

        def _meta(q_value: float, explore: bool, n_legal: int) -> dict:
            m = {'q_value': q_value, 'explore': explore, 'n_legal': n_legal}
            if dmc_obs_dict is not None:
                m['dmc_obs_dict'] = dmc_obs_dict
            return m

        if legal_indices.size == 0:
            return 0, _meta(0.0, False, 0)

        if not self.deterministic and self.epsilon > 0.0 and self.rng.random() < self.epsilon:
            action = int(self.rng.choice(legal_indices.tolist()))
            return action, _meta(float(flat[action]), True, int(legal_indices.size))

        sub = flat[legal_indices]
        local_idx = int(sub.argmax())
        action = int(legal_indices[local_idx])
        return action, _meta(float(flat[action]), False, int(legal_indices.size))

    def finalize_episode(self, transitions: list, winner: int, acting_player: int = 0) -> list:
        """Backfill MC return G on each recorded transition (D1.2, γ=1).

        Args:
            transitions: list of (obs, action, meta) tuples or dicts.
            winner: env winner id (0 / 1 / -1 draw / 2 timeout-draw).
            acting_player: our perspective side (0 or 1).
        Returns:
            list of dicts {obs, action, return, meta} ready for buffer.
        """
        if winner < 0 or winner == 2:
            G = 0.0
        elif winner == acting_player:
            G = 1.0
        else:
            G = -1.0
        out: list = []
        for t in transitions:
            if isinstance(t, dict):
                rec = dict(t)
                rec['return'] = G
            else:
                obs, action, meta = t
                rec = {'obs': obs, 'action': int(action), 'return': G, 'meta': meta}
            out.append(rec)
        return out
