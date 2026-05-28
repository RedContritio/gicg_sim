"""PipelineTuningCfg — collector + spawn_pipeline tuning knob 收纳 dataclass。

I29 R7 audit C1 finding:`DMCGoSubprocessCollector.__init__` 现 11 个 tuning 字段
(shm_capacity / inf_max_batch / ready_timeout_s 等),ctor signature noise + reader
难 quick scan。 生产 caller (`paradigm.py:_make_go_collector`) 只传 4 核心字段,
其余 fall to default;仅 test fixture override 部分字段。 本 dataclass 收纳所有 tuning
字段 + default,让 ctor signature clean + 可选 explicit production tuning passthrough。

设计:
- `PipelineTuningCfg()` = 全 default,production caller 用此
- override via `dataclasses.replace(cfg, shm_capacity=16)` 或直接 kwargs
  `PipelineTuningCfg(shm_capacity=16, device='cpu')`
- frozen=True 防意外修改 (collector + spawn_pipeline 内只读)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PipelineTuningCfg:
    """Tuning knobs for DMC Go subprocess collector + InfServer + SHM ring。

    分 4 类:
    - SHM ring sizing:capacity (slots) + slot size (bytes/slot)
    - InfServer batching:max_batch (None = n_actors) + batch_timeout_ms
    - Subprocess lifecycle timeouts:ready_timeout_s (READY 信号) + io_timeout_ms (TCP I/O)
    - Collect loop tuning:collect_deadline_s (单次 collect 墙钟 cap) + poll_interval_s (SHM poll)
    - Device + Go runtime:device (InfServer torch device) + go_gomaxprocs (Go GOMAXPROCS cfg)
    """

    # SHM ring sizing — DMC episode batch ~1.4 MB peak (v_legacy 全 pool max_actions=2048
    # padded refs/pay × ~10-15 trans);1ep smoke 实测 4 MB 留 2.5x headroom。
    #
    # capacity 32: 给 train cycle burst headroom 减少 push_wait_ns 触发频率;但 correctness
    # 已不依赖 capacity — Go side TransitionWriterShm.Push 改为 blocking retry (spin until
    # ring 有空位 或 30s timeout),与 Python mp.Queue.put() default blocking 同语义,fix
    # 2026-05-27 N=19 pilot frames 卡 5862 的根因 ("drop on full" 是 wrong port of mp.Queue
    # semantics 违反 [[python_arch_mimicry_for_go_port]])。 backpressure metric 经 Go stderr
    # emit + Python parse 进 metrics.jsonl "backpressure" kind,可观测 train-vs-collect 失衡。
    shm_capacity: int = 32
    shm_slot_size: int = 4 * 1024 * 1024

    # InfServer batch — N actor 并发 inference,batch 满即 forward。 None = n_actors
    # (spawn_pipeline 内 resolve)。
    inf_max_batch: Optional[int] = None
    inf_batch_timeout_ms: int = 2

    # Go subprocess READY 信号超时 (cold-start InfServer torch import + spawn ~3-5s,
    # Go inf connect + paradigm.Configure ~500ms,30s 留足 headroom)。
    ready_timeout_s: float = 30.0
    # Go subprocess TCP I/O deadline (socket Read/Write deadline)。 production 30s。
    io_timeout_ms: int = 30_000

    # Per-collect poll deadline — collect() loop 等 n_episodes 攒齐最长墙钟。
    # 5 ep × Mac N=2 ~10-15s actor (1 ep ~3-5s),deadline 60s 留 4x headroom。
    collect_deadline_s: float = 60.0
    # SHM poll 间隔 — InfServer cold-start 第一 forward ~50-200ms,过紧 busy-loop
    # 抢 CPU 干扰 Go subprocess。 5ms 等 PushBatch 周期 (per-ep ~1 次 push)。
    poll_interval_s: float = 0.005

    # InfServer torch device (cpu / cuda:0 / mps)。 None = 从 network.parameters() 读。
    device: Optional[str] = None
    # I29 R6.1 → R7.2 → I29-D6 (2026-05-26) 演变:
    #   - R6.1 (pre-R7.2): default 0 = Go runtime NumCPU。 mixed-opp workload R6.1 Bench 2
    #     verify GOMAXPROCS=1 跌 76% — 因 1 Go subprocess containing N goroutine 拓扑,
    #     N goroutine 并发 minimax 需多 P context
    #   - R7.2 (post-2026-05-25): N independent Go subprocess each NActors=1 → 每 subprocess
    #     仅 1 actor goroutine,R6.1 多 P 需求消失。 default 0 = NumCPU=10 (Mac M4) × N=8
    #     subprocess = 80 P contexts,严重 oversub Mac 10-core
    #   - I29-D6 (2026-05-26): N=8 scaling 0.66x audit 识别 GOMAXPROCS oversub 是次因 H3
    #     (主因 H1 = InfServer N+2 GIL threads 留 Stage 2 reactor fix)。 default 0 → 1 = 单 P
    #     per subprocess,与 Python mp _mp_helpers.py 的 OMP=1 + torch.set_num_threads(1) 对齐
    go_gomaxprocs: int = 1

    # GOMEMLIMIT — Go runtime soft memory cap per actor subprocess (MB)。 H4 (2026-05-28)
    # 切 cfg-driven (per [[feedback_cfg_driven_only]],不走 env var),Go binary 启动期
    # debug.SetMemoryLimit + print stderr 报告生效 cap。
    #
    # 2026-05-27 Win N=16 stage3 production 实测 default (无 cap) 下每 actor RSS 1-7 GB 峰值
    # 14 GB,16 actor 总 ~41 GB host RSS → Win 64 GB host OOM at 70min(host_used 55 GB 持续上
    # 涨)。 不是真 leak (代码 audit:GreedyPlayer + runEpisode 全 stateless 局部),纯 Go heap
    # GOGC=100 default 让 heap doubles 前不触发 GC + Win VirtualFree 不眼疾还 OS → working set
    # 涨。 设 1024 → Go runtime 在 heap > 1 GiB 时强制激进 GC,16 actor × 1 GiB = 16 GB 总,
    # 加 InfServer ~5 GB + master ~3 GB = ~25 GB,远低 63 GB Win host cap。 设 0 = 显式
    # unbounded (Go GC default 行为;dev/smoke 用)。 production cfg 必须显式 declare,Go
    # binary parseConfig fail-loud on missing (H4 visibility safety net)。
    go_mem_limit_mb: int = 1024
