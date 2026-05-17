"""v_loss divergence / warn gate for AZ training runs."""

from __future__ import annotations

import math
from collections import deque


#: Absolute thresholds on v_loss. Value head is tanh-bounded, z in {-1,0,1}
#: so per-sample (v-z)^2 <= 4. Above 5 = noise / divergence; above 7 = broken.
V_LOSS_WARN_THRESH: float = 5.0
V_LOSS_DIVERGE_THRESH: float = 7.0


def health_check(
    stats: dict,
    v_loss_window: deque,
    log,
) -> None:
    """Mini health check on v_loss.

    - ``health_warn``: v_loss > 5.0  (informational; training continues)
    - ``diverged``:    v_loss > 7.0 AND last 10 v_losses monotonically
                       non-decreasing → raise, preserving last checkpoint.
    """
    v = float(stats.get('value', 0.0))
    if not math.isfinite(v):
        raise RuntimeError(f'health_check: v_loss is non-finite ({v})')
    if v > V_LOSS_WARN_THRESH:
        log(
            'health_warn',
            {
                'metric': 'value_loss',
                'value': round(v, 4),
                'threshold': V_LOSS_WARN_THRESH,
            },
        )
    if v > V_LOSS_DIVERGE_THRESH and len(v_loss_window) == v_loss_window.maxlen:
        last10 = list(v_loss_window)[-10:]
        if all(last10[i] <= last10[i + 1] for i in range(len(last10) - 1)):
            log(
                'diverged',
                {
                    'metric': 'value_loss',
                    'value': round(v, 4),
                    'last10': [round(x, 4) for x in last10],
                },
            )
            raise RuntimeError(
                f'train diverged: value_loss={v:.4f} > {V_LOSS_DIVERGE_THRESH} '
                'and last 10 steps are monotonically non-decreasing. '
                'Aborting to preserve the latest checkpoint.'
            )
    v_loss_window.append(v)
