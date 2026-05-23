"""DMC adapter buffer — in-memory FIFO of acting-player transitions.

FU-W4-DMC: ``DmcTransition`` + ``DmcReplayBuffer`` relocated here from
``legacy/replay.py`` so the adapter buffer path is self-contained.
``DMCBuffer`` wraps the FIFO behind the core ``Buffer`` protocol.

The buffer holds ``DmcTransition`` records produced by the collector;
``sample(batch_size)`` returns a Batch whose data carries
``{collated, action_idx, returns}`` consumed by ``DMCLogitAsQLoss``.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from training.core.protocols import Batch, CollectorOutput


@dataclass
class DmcTransition:
    """One acting-player decision step within an episode.

    obs_dict: full dynamic obs + static obs + legal action refs / payments.
        Stored as numpy arrays for easy batching.
    action_idx: index into legal actions chosen by actor.
    G: MC return from acting player's perspective (±1 typically).
        Backfilled at episode end by ``DmcReplayBuffer.push_episode``.
    """

    obs_dict: dict[str, Any]
    action_idx: int
    G: float = 0.0


class DmcReplayBuffer:
    """FIFO bounded buffer of ``DmcTransition``. Thread-safe via callers'
    own locking (single-process smoke does not need locks)."""

    def __init__(self, capacity: int, seed: int = 0):
        self.capacity = capacity
        self.buf: deque[DmcTransition] = deque(maxlen=capacity)
        self.rng = random.Random(seed)
        self.total_seen = 0

    def __len__(self) -> int:
        return len(self.buf)

    def push_episode(self, transitions: list[DmcTransition], G: float) -> None:
        """Backfill ``G`` on all transitions, then append to buffer."""
        for t in transitions:
            t.G = G
            self.buf.append(t)
            self.total_seen += 1

    def sample(self, batch_size: int) -> list[DmcTransition]:
        """Uniform random sample without replacement."""
        if batch_size > len(self.buf):
            raise ValueError(
                f'DmcReplayBuffer.sample: requested {batch_size} but buffer has only {len(self.buf)} transitions'
            )
        return self.rng.sample(list(self.buf), batch_size)

    def clear(self) -> None:
        self.buf.clear()


class DMCBuffer:
    """Wraps :class:`DmcReplayBuffer`; presents the core ``Buffer`` protocol.

    ``push(CollectorOutput)`` consumes the legacy ``DmcTransition``
    records the DMC collector stashes on
    ``runtime_metrics['dmc_episodes']`` (list of ``(transitions, G)``
    pairs). We do NOT repurpose ``CollectorOutput.transitions`` (typed
    core Transition) because GICG obs capture is too rich to fit there
    cleanly until an EpisodeRunner obs redesign lands.

    I29 P2 (wire v3): per-trans refs/pay/legal_mask 不 padded(nlegal-sized)。
    sample 时 ``collate_batch`` pad 到 ``max_actions`` 出 batch tensor;
    ``max_actions`` 必须 == 网络 ``AgentConfig.max_actions``(否则 padding 大小
    与网络 forward 期望不符)。
    """

    def __init__(self, capacity: int, *, max_actions: int, seed: int = 0, device: str = 'cpu') -> None:
        if max_actions <= 0:
            raise ValueError(f'DMCBuffer: max_actions must be positive, got {max_actions}')
        self.capacity = capacity
        self.device = device
        self.max_actions = int(max_actions)
        self._buf = DmcReplayBuffer(capacity=capacity, seed=seed)

    def __len__(self) -> int:
        return len(self._buf)

    def push(self, batch: CollectorOutput) -> None:
        eps = batch.runtime_metrics.get('dmc_episodes', [])
        for transitions, G in eps:
            self._buf.push_episode(transitions, G)

    def sample(self, batch_size: int, rng: Optional[np.random.Generator] = None) -> Batch:
        """Uniform random sample → collated batch."""
        # Import here to avoid module-load-time cycle with _episode.
        from training.paradigms.dmc._episode import collate_batch

        if batch_size > len(self._buf):
            raise ValueError(f'DMCBuffer.sample: have {len(self._buf)} < batch_size={batch_size}')
        transitions = self._buf.sample(batch_size)
        collated, action_idx, returns = collate_batch(transitions, device=self.device, max_actions=self.max_actions)
        return Batch(
            data={'collated': collated, 'action_idx': action_idx, 'returns': returns},
            weights=None,
            size=batch_size,
        )

    def clear(self) -> None:
        self._buf.clear()

    def state_dict(self) -> dict:
        return {'capacity': self.capacity, 'size': len(self)}

    def load_state_dict(self, sd: dict) -> None:
        # ``DmcReplayBuffer`` does not persist; ckpt restore is warm-up only.
        if sd.get('capacity') != self.capacity:
            raise ValueError(
                f'DMCBuffer.load_state_dict: capacity mismatch sd={sd.get("capacity")} self={self.capacity}'
            )
