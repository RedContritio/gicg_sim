"""BCArgmaxPolicy — argmax-over-legal policy for BC eval path.

Spec ref: paradigm-bc/spec.md BC5.1 — BC ``EpisodePolicy`` SHALL be
argmax over policy logits with ``deterministic=True`` default。

BC5.2:BC paradigm SHALL NOT 调 EpisodeRunner 在训练 path — 此 policy
仅供 eval 路径(periodic eval through training/core/eval/)。Training
path 直接 buffer.sample → loss.compute,no env episode loop。
"""

from __future__ import annotations

from typing import Any

import numpy as np


class BCArgmaxPolicy:
    """Argmax-over-legal-mask policy。Stateless,deterministic by default。

    Implementer note: this is the eval-only policy。Training path 走
    BCDataset / DatasetCollector / BCLoss,not through EpisodePolicy。
    """

    transition_schema = 'bc_transition'

    def __init__(self, deterministic: bool = True) -> None:
        self.deterministic = bool(deterministic)

    def reset(self) -> None:
        """No per-episode state to reset(stateless policy)。"""
        return None

    def act(self, obs: Any, mask: Any, provider: Any) -> tuple:
        """Decide one action。

        Args:
            obs: paradigm-shaped observation(forwarded to provider)。
            mask: legal action mask(boolean array length max_actions)。
            provider: NetworkProvider with forward(obs, mask) returning
                logits(either dict with 'policy_logits' or raw tensor)。
        Returns:
            (action_idx, meta_dict)。meta carries argmax logit value + n_legal。
        """
        out = provider.forward(obs, mask)
        if isinstance(out, dict):
            logits = out.get('policy_logits', out.get('logits'))
            if logits is None:
                raise KeyError(
                    f"BCArgmaxPolicy.act: provider returned dict missing 'policy_logits' / 'logits' "
                    f'keys (got {sorted(out.keys())})'
                )
        else:
            logits = out

        try:
            arr = logits.detach().cpu().numpy()
        except AttributeError:
            arr = logits

        flat = np.asarray(arr).reshape(-1)
        if mask is not None:
            mflat = np.asarray(mask).reshape(-1).astype(bool)
            n = min(flat.shape[0], mflat.shape[0])
            legal_indices = np.where(mflat[:n])[0]
        else:
            legal_indices = np.arange(flat.shape[0])

        if legal_indices.size == 0:
            return 0, {'logit_value': 0.0, 'n_legal': 0}

        sub = flat[legal_indices]
        local_idx = int(sub.argmax())
        action = int(legal_indices[local_idx])
        return action, {'logit_value': float(flat[action]), 'n_legal': int(legal_indices.size)}
