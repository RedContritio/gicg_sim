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
    """``[meta]`` section; seed, paradigm, and run label are required."""

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
    """``[pipeline]`` section.

    ``mode`` is ``serial`` or ``async``. ``actor_backend`` is ``python``
    for the multiprocessing collector or ``go`` for the standalone
    ``cmd/gicg_actor`` subprocess collector. The Go backend is implemented
    for DMC.
    """

    mode: str = 'serial'
    num_actors: int = 1
    actor_backend: str = 'python'  # 'python' | 'go'
    inference: Optional[InferenceCfg] = None
    learner: Optional[LearnerCfg] = None
    actor_seed: Optional[int] = None  # derived per-instance via INHERITED_FIELDS


@dataclass(frozen=True)
class EvalCfg:
    """``[eval]`` section; optional for a serial pipeline.

    ``host`` and ``port`` identify the TCP evaluation service.
    ``cpu_affinity`` is an optional list of CPU identifiers used when
    starting that service; unsupported platforms ignore the hint.
    """

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
    """[scenario] section. Pool + team + max_rounds + deck_padding.

    deck_0 / deck_1 (F4): explicit per-player deck declaration — list of
    card names (multiset, duplicates allowed), every name declared in
    card_pool / pool. None = implicit path: deck is the full eligible
    set, and the engine errors when that exceeds
    deck_padding.target_size (silent truncation removed)."""

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
    deck_0: Optional[list] = None
    deck_1: Optional[list] = None
    random_deck_size: int = 0


@dataclass(frozen=True)
class CheckpointCfg:
    """[checkpoint] section."""

    save_every: int = 1000
    keep_last_n: int = 5
    artifacts_root: str = 'artifacts'


@dataclass(frozen=True)
class DebugCfg:
    """``[debug]`` performance and memory instrumentation controls.

    Instrumentation is disabled by default. ``perf_trace`` enables Python
    pipeline spans, while ``mem_probe`` enables periodic ``tracemalloc``
    summaries in the main process. The Go subprocess manages its own logs.
    """

    perf_trace: bool = False
    mem_probe: bool = False
    perf_trace_flush_n: int = 200
    perf_trace_flush_s: float = 1.0
    perf_trace_dir: Optional[str] = None  # None = trace.py default 'artifacts/_perf_logs'
    mem_probe_interval_s: int = 30
    mem_probe_top_n: int = 15
    # Test-only CFR buffer adapter. Production configurations leave this false.
    cfr_smoke_stub_buffer: bool = False


@dataclass(frozen=True)
class RuntimeCfg:
    """``[runtime]`` process and worker controls.

    ``actor_log_dir`` receives line-buffered per-actor logs from Python
    worker processes.
    """

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
