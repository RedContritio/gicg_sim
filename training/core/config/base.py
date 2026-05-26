"""TrainingConfig + nested dataclasses (frozen).

Spec: config-schema/spec.md §3 (CS1 顶层段 + CS2 INHERITED_FIELDS +
CS3 placement R1-R7 + CS4 loader strictness).

Each dataclass owns ONE section of the TOML. Loader builds them by
``cls(**section_dict)`` after strict field validation. Frozen=True
so the running pipeline cannot accidentally mutate a value mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


PLACEMENT_VALUES = ('local', 'remote')
DEVICE_VALUES_PREFIX = ('cpu', 'cuda', 'mps')  # 'cuda:N' suffix allowed
PARADIGM_VALUES = ('az', 'dmc', 'cfr', 'ppo', 'bc')


@dataclass(frozen=True)
class MetaCfg:
    """[meta] section. seed + paradigm 必填,device 默认 'cpu'."""

    seed: int
    paradigm: str
    run_label: str
    device: str = 'cpu'
    extends: Optional[str] = None


@dataclass(frozen=True)
class RemoteInferenceCfg:
    """[*.inference.remote] sub-section. Only present when
    placement == 'remote'. R3 enforces all 3 fields required."""

    pool_size: int
    max_batch: int
    batch_timeout_ms: int
    device: Optional[str] = None  # falls back via INHERITED_FIELDS
    socket_path: Optional[str] = None


@dataclass(frozen=True)
class InferenceCfg:
    """[pipeline.inference] / [eval.inference] section.

    R1: placement enum required. R4: closed set {placement, device,
    version_tag, remote}. R7: dataclass = these 4 fields exactly."""

    placement: str  # 'local' | 'remote'
    version_tag: str = 'latest'
    device: Optional[str] = None  # INHERITED_FIELDS fallback chain
    remote: Optional[RemoteInferenceCfg] = None


@dataclass(frozen=True)
class LearnerCfg:
    """[pipeline.learner] — learner-side compute placement."""

    device: Optional[str] = None  # INHERITED_FIELDS fallback
    seed: Optional[int] = None  # derived from meta.seed


@dataclass(frozen=True)
class PipelineCfg:
    """[pipeline] section. mode = 'serial' | 'async'.

    actor_backend = 'python' (默认 Python mp.Process pool,DMCMultiProcessCollector)
    | 'go' (I29 redesign Go subprocess pool,DMCGoSubprocessCollector via
    cmd/gicg_actor standalone OS subprocess + SHMRing transition,master 0 cgo lib
    loaded)。 仅 DMC paradigm 完整支持,AZ/PPO/CFR/BC port 留 Phase 2 follow-up。
    """

    mode: str = 'serial'
    num_actors: int = 1
    actor_backend: str = 'python'  # 'python' | 'go'
    inference: Optional[InferenceCfg] = None
    learner: Optional[LearnerCfg] = None
    actor_seed: Optional[int] = None  # derived per-instance via INHERITED_FIELDS


@dataclass(frozen=True)
class EvalCfg:
    """[eval] section. Optional when pipeline.mode='serial' smoke.

    host/port: eval_service bind + gauntlet client connect address
    (TCP localhost, post 2026-05-24 env var 砍 — 替代 GICG_EVAL_HOST /
    GICG_EVAL_PORT)。 production cfg 不写则走 'localhost' / 9100 default。

    cpu_affinity: comma-separated CPU id list to pin eval_service worker
    process (e.g. [16, 17, 18])。 None = unpinned (Mac 上 silent skip,
    cpu_affinity is hint not contract)。 替代 GICG_EVAL_CPU_AFFINITY。"""

    n_workers: int = 1
    schedule: str = 'every_1000_steps'
    inference: Optional[InferenceCfg] = None
    scenario_seed: Optional[int] = None
    worker_seed: Optional[int] = None
    host: str = 'localhost'
    port: int = 9100
    cpu_affinity: Optional[list] = None


@dataclass(frozen=True)
class ScenarioCfg:
    """[scenario] section. Pool + team + max_rounds + deck_padding."""

    team_0: list
    team_1: list
    pool: Any = None  # str | list[str] | None
    max_rounds: int = 0
    deck_padding: Optional[dict] = None
    char_pool: Optional[list] = None
    team_size: int = 1
    disjoint_teams: bool = False
    card_pool: Optional[list] = None
    data_dir: Optional[str] = None
    fix_dice: Optional[list] = None
    obs_mask: Optional[list] = None


@dataclass(frozen=True)
class CheckpointCfg:
    """[checkpoint] section."""

    save_every: int = 1000
    keep_last_n: int = 5
    artifacts_root: str = 'artifacts'


@dataclass(frozen=True)
class DebugCfg:
    """[debug] section — perf / mem instrumentation toggles。

    全 default False:production cfg 不写 [debug] 时所有 instrumentation 关闭,
    与未启 env var 时旧行为等价。 dev cfg 写 ``[debug] perf_trace=true`` 启 Python
    pipeline + actor + InfServer span trace;``mem_probe=true`` 启 master tracemalloc
    heap 分项 probe。 I29 redesign P3 (2026-05-25): 旧 ``go_perf_trace`` field 删
    (cgo path 退役,master 不 load libgicg_actor;Go-side perf trace 由 cmd/gicg_actor
    standalone subprocess 自管,经 stderr / log dump 不进 master metrics.jsonl)。

    配套参数默认沿用旧 env var 默认值(perf_trace_flush_n=200 / _s=1.0 / dir 由
    `trace.py` 走 'artifacts/_perf_logs' fallback;mem_probe_interval_s=30, top_n=15)。
    """

    perf_trace: bool = False
    mem_probe: bool = False
    perf_trace_flush_n: int = 200
    perf_trace_flush_s: float = 1.0
    perf_trace_dir: Optional[str] = None  # None = trace.py default 'artifacts/_perf_logs'
    mem_probe_interval_s: int = 30
    mem_probe_top_n: int = 15
    # CFR smoke-only stub buffer dispatch — production cfg 不写则 False。
    # 替代 GICG_CFR_SMOKE_STUB_BUFFER env var (post 2026-05-24)。 仅 smoke_full
    # cfg + tools/runs/tests cfr smoke cfg 写 true,production CFR 走真 buffer。
    cfr_smoke_stub_buffer: bool = False


@dataclass(frozen=True)
class RuntimeCfg:
    """[runtime] section — process / worker runtime knobs (post 2026-05-24
    env var 砍后新建)。

    actor_log_dir: 子 actor 进程 per-actor 文件日志根 dir。 替代 ACTOR_LOG_DIR
    env var。 mp child stdout/stderr 不可靠 (pytest 抓 / ssh strip / sandbox 抑),
    每 actor tee 到 ``<dir>/actor_<id>.log`` line-buffered 写出供事后 debug。

    I29 redesign P3 (2026-05-25): 旧 ``actor_lib_path`` field 删 (cgo path 退役,
    master 不再 ctypes load libgicg_actor;Go-actor 走 cmd/gicg_actor standalone
    OS subprocess 由 spawn_pipeline 起,binary 路径 build-on-demand 不需 cfg knob)。"""

    actor_log_dir: str = 'artifacts/_actor_logs'


@dataclass(frozen=True)
class TrainingConfig:
    """Top-level frozen cfg. Driver reads this; paradigm reads
    cfg.paradigm dict + cfg.meta.paradigm to dispatch its own schema."""

    meta: MetaCfg
    pipeline: PipelineCfg
    scenario: ScenarioCfg
    paradigm: dict  # paradigm-specific schema; dataclass picked by meta.paradigm
    eval: Optional[EvalCfg] = None
    checkpoint: CheckpointCfg = field(default_factory=CheckpointCfg)
    debug: DebugCfg = field(default_factory=DebugCfg)
    runtime: RuntimeCfg = field(default_factory=RuntimeCfg)
    artifacts_dir: Optional[str] = None  # resolved at runtime
