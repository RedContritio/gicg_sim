"""Driver async weight-republish gating — `pipeline-async-weight-sync` T1.

`run_pipeline` train block 后(clear_buffer 前)按 `StepPlan.sync_weights` flag
honor `collector.sync_weights(network)`,让 async actor 下一轮 collect 拿到新
权重。serial collector 无 `sync_weights` method → hasattr-guard no-op。

测真 production helper `pipeline._maybe_sync_weights`(非 logic-mirror 副本) —
gating 4 组合:flag True/False × collector 有/无 method。位置正确性(train 后
clear 前)由跨-paradigm async e2e (T4) 真跑 driver 覆盖。
"""

from __future__ import annotations

from training.core.pipeline import _maybe_sync_weights
from training.core.protocols import StepPlan


class _SpyCollector:
    """Records sync_weights(network) calls (async collector contract)。"""

    def __init__(self) -> None:
        self.sync_calls: list = []

    def sync_weights(self, network) -> None:
        self.sync_calls.append(network)


class _SerialCollector:
    """Serial collector — no sync_weights method (hasattr guard target)。"""


def _plan(sync_weights: bool) -> StepPlan:
    return StepPlan(
        collect=False,
        n_episodes=0,
        train=True,
        n_train_batches=1,
        batch_size=4,
        eval=False,
        sync_weights=sync_weights,
    )


def test_sync_weights_honored_when_flag_true():
    """flag True + collector 有 method → 调 sync_weights(network) 一次,传 network。"""
    collector = _SpyCollector()
    network = object()
    _maybe_sync_weights(_plan(True), collector, network)
    assert collector.sync_calls == [network]


def test_sync_weights_skipped_when_flag_false():
    """flag False → 不调(默认 serial paradigm / async warm-up 分支)。"""
    collector = _SpyCollector()
    _maybe_sync_weights(_plan(False), collector, object())
    assert collector.sync_calls == []


def test_sync_weights_skipped_when_collector_lacks_method():
    """flag True 但 collector 无 sync_weights → hasattr guard,不 raise。"""
    collector = _SerialCollector()
    # must not raise — serial stub collector 不实现 sync_weights
    _maybe_sync_weights(_plan(True), collector, object())


def test_sync_weights_default_false_no_call():
    """StepPlan 不显式给 sync_weights → default False → 不调(行为不变 invariant)。"""
    plan = StepPlan(
        collect=False,
        n_episodes=0,
        train=True,
        n_train_batches=1,
        batch_size=4,
        eval=False,
    )
    collector = _SpyCollector()
    _maybe_sync_weights(plan, collector, object())
    assert collector.sync_calls == []
