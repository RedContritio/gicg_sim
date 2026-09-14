"""run_pipeline async weight-sync driver-integration e2e — `pipeline-async-weight-sync` T4.

证明**driver 集成链**:真跑 `run_pipeline` async 完整循环 → step_schedule 设
`sync_weights` → driver `_maybe_sync_weights` → `collector.sync_weights` 被调
(version republish),非永 version-0。serial mode → 不调。

覆盖 T1(driver honor)× T3(step_schedule bit)× run_pipeline plan→helper wiring
的集成 link(单测各覆盖一段,此处验全链在真 driver loop 跑通)。fake paradigm +
spy collector,**无 mp spawn → sandbox-safe**,本 session 可跑。

real-spawn actor-side version(SHM/server republish 真到达 actor)由独立
smoke_full/CFR/PPO async mp e2e 覆盖；受限 sandbox 可能禁止
``bind()`` / ``nice()``。
"""

from __future__ import annotations

from pathlib import Path

import torch

from training.core.config import load_cfg
from training.core.pipeline import run_pipeline
from training.core.protocols import (
    Batch,
    CollectorOutput,
    LossResult,
    StepPlan,
    Transition,
    async_sync_weights_due,
)

_REPO = Path(__file__).resolve().parents[2]


class _SpyCollector:
    """Records driver-issued sync_weights calls (async collector contract)。"""

    def __init__(self) -> None:
        self.sync_calls = 0

    def collect(self, n_units, provider):
        trans = [Transition(obs=None, action=0, legal_mask=None, reward=0.0, done=True) for _ in range(8)]
        return CollectorOutput(transitions=trans, episode_stats=[{}], runtime_metrics={}, n_units=len(trans))

    def sync_weights(self, network) -> None:
        self.sync_calls += 1

    def close(self) -> None:
        pass


class _ListBuffer:
    def __init__(self) -> None:
        self._n = 0

    def push(self, out) -> None:
        self._n += out.n_transitions

    def sample(self, bs):
        return Batch(data={}, size=bs)

    def __len__(self) -> int:
        return self._n

    def clear(self) -> None:
        self._n = 0

    def state_dict(self) -> dict:
        return {}

    def load_state_dict(self, sd) -> None:
        pass


class _FakeLoss:
    def compute(self, network, batch):
        loss = network(torch.zeros(1, 2)).sum()
        return LossResult(loss=loss, breakdown={'loss': float(loss.item())})


class _FakeParadigm:
    """Minimal Paradigm satisfying run_pipeline's 6 make_* + step_schedule with
    trivial torch objects — isolates the driver loop's sync_weights wiring."""

    name = 'fake'
    requires_network_in_collect = False

    def __init__(self) -> None:
        self.collector: _SpyCollector | None = None

    def make_network(self, cfg):
        return torch.nn.Linear(2, 2)

    def make_optimizer(self, cfg, network):
        return torch.optim.SGD(network.parameters(), lr=0.01)

    def make_buffer(self, cfg):
        return _ListBuffer()

    def make_loss(self, cfg):
        return _FakeLoss()

    def make_collector(self, cfg, env_factory, network, opp_pool):
        self.collector = _SpyCollector()
        return self.collector

    def step_schedule(self, state, cfg):
        if state.step >= 3:
            # done — empty plan breaks the driver loop
            return StepPlan(collect=False, n_episodes=0, train=False, n_train_batches=0, batch_size=4, eval=False)
        # steady: collect (fills buffer) + 1 train batch + cadence-0 sync bit
        return StepPlan(
            collect=True,
            n_episodes=1,
            train=True,
            n_train_batches=1,
            batch_size=4,
            eval=False,
            sync_weights=async_sync_weights_due(cfg, state, 0),
        )


def _cfg(mode: str):
    # load serial dmc smoke(valid cfg 结构:checkpoint/meta/pipeline)后强制 mode —
    # 绕 async 的 CS1.1「需 [eval]」load-time 校验(与本测试正交)。
    cfg = load_cfg(str(_REPO / 'configs' / 'dmc' / 'smoke.toml'))
    object.__setattr__(cfg.pipeline, 'mode', mode)
    return cfg


def test_run_pipeline_async_driver_calls_sync_weights(tmp_path):
    """async + steady cadence-0 → driver 跨 train iter 调 collector.sync_weights。

    这是 weight-sync gap 的核心修复验证:此前 run_pipeline 从不调 sync_weights
    (actor 永用 version-0);现 driver 在每 train iter republish。"""
    cfg = _cfg('async')
    paradigm = _FakeParadigm()
    run_pipeline(cfg, paradigm, prebuilt_artifacts_dir=tmp_path, max_steps=10)
    assert paradigm.collector.sync_calls > 0, 'run_pipeline async 未调 collector.sync_weights — weight-sync gap 未修复'


def test_run_pipeline_serial_driver_skips_sync_weights(tmp_path):
    """serial mode → step_schedule sync bit 恒 False → driver 不调 sync_weights。"""
    cfg = _cfg('serial')
    paradigm = _FakeParadigm()
    run_pipeline(cfg, paradigm, prebuilt_artifacts_dir=tmp_path, max_steps=10)
    assert paradigm.collector.sync_calls == 0
