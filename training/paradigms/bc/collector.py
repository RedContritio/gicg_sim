"""DatasetCollector — BC one-shot push collector(BC3.1).

BC3.1 / BC3.3:no env episode loop;dataset 静态 NPZ。``collect()`` 一次性
读 dataset → push 全量 transitions 到 buffer → 后续 collect call 是 no-op
(driver 看到 n_units=0 visually 但 buffer 已 ready)。

Dataset decoding is implemented by the sibling
``training.paradigms.bc.dataset.BCDataset`` module.

requires_network_in_collect = False — driver SHALL NOT 建 NetworkProvider
在 BC collect path(BC1.3 / BC3.3)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from training.core.protocols import CollectorOutput, Transition


class DatasetCollector:
    """BC paradigm Collector. One-shot load + push;后续 collect 是 no-op。

    Args:
        dataset_path: NPZ path(BCDataset format)。
        n_counter_slots / n_hooks / max_ops_per_hook: ActorCritic
            shape;sed dataset 静态 obs 解码。
    """

    requires_network_in_collect = False

    def __init__(
        self,
        dataset_path: str,
        n_counter_slots: int,
        n_hooks: int,
        max_ops_per_hook: int,
    ) -> None:
        if not dataset_path:
            raise ValueError('DatasetCollector: dataset_path must be non-empty')
        p = Path(dataset_path)
        if not p.exists():
            raise FileNotFoundError(f'DatasetCollector: dataset not found at {p}')

        # Lazy import to keep collector module light;BCDataset 触发 NPZ load。
        from training.paradigms.bc.dataset import BCDataset

        self._dataset = BCDataset(p, n_counter_slots, n_hooks, max_ops_per_hook)
        self._exhausted = False
        self._n_transitions = len(self._dataset)

    @property
    def dataset(self) -> Any:
        """Expose underlying BCDataset for buffer / loss to share batch
        builder。Driver 不 read 此 attr,只 paradigm.make_collector / make_buffer
        共用。"""
        return self._dataset

    def collect(self, n_units: int, provider: Any = None) -> CollectorOutput:
        """One-shot: emit all transitions on first call;后续 no-op。

        ``provider`` is ignored(BC1.3 — no network forward during collect)。
        ``n_units`` is also ignored;BC 一次性 push 全 dataset。
        """
        del provider, n_units
        if self._exhausted:
            return CollectorOutput(
                transitions=[],
                episode_stats=[],
                runtime_metrics={'bc_exhausted': 1},
                n_units=0,
            )

        n = self._n_transitions
        # Produce one Transition per dataset decision。obs is the
        # decision index(buffer dedupe by indices not by full obs)。
        transitions: list = []
        for i in range(n):
            transitions.append(
                Transition(
                    obs=i,  # dataset row index
                    action=int(self._dataset.chosen_action[i]),
                    legal_mask=self._dataset.legal_mask[i],
                    reward=float(self._dataset.terminal_z[i]),
                    done=True,  # static dataset — no episode continuation
                    payload={
                        'dataset_idx': i,
                        'tied_mask': self._dataset.tied_mask[i],
                    },
                )
            )

        self._exhausted = True
        return CollectorOutput(
            transitions=transitions,
            episode_stats=[],
            runtime_metrics={'bc_dataset_size': n, 'bc_pushed': 1},
            n_units=n,
        )

    def build_batch(self, indices: np.ndarray) -> dict:
        """Delegate to BCDataset.build_batch so BCLoss can rebuild full
        obs dict from sampled indices(driver path:Buffer.sample 返回
        indices → loss compute via build_batch)。"""
        return self._dataset.build_batch(indices)

    def close(self) -> None:
        return None

    def state_dict(self) -> dict:
        return {'exhausted': self._exhausted, 'n_transitions': self._n_transitions}

    def load_state_dict(self, sd: dict) -> None:
        self._exhausted = bool(sd.get('exhausted', False))
