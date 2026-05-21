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
    | 'go' (I29 Go-native goroutine pool,DMCGoActorCollector,1.5-2x speedup vs
    Python baseline,Win box N=16 fps≥70 + mem≤2 GB gate)。 仅 DMC paradigm 完整支持,
    AZ/PPO scaffold ship,production 暂走 'python'。
    """

    mode: str = 'serial'
    num_actors: int = 1
    actor_backend: str = 'python'  # 'python' | 'go'
    inference: Optional[InferenceCfg] = None
    learner: Optional[LearnerCfg] = None
    actor_seed: Optional[int] = None  # derived per-instance via INHERITED_FIELDS


@dataclass(frozen=True)
class EvalCfg:
    """[eval] section. Optional when pipeline.mode='serial' smoke."""

    n_workers: int = 1
    schedule: str = 'every_1000_steps'
    inference: Optional[InferenceCfg] = None
    scenario_seed: Optional[int] = None
    worker_seed: Optional[int] = None


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
class TrainingConfig:
    """Top-level frozen cfg. Driver reads this; paradigm reads
    cfg.paradigm dict + cfg.meta.paradigm to dispatch its own schema."""

    meta: MetaCfg
    pipeline: PipelineCfg
    scenario: ScenarioCfg
    paradigm: dict  # paradigm-specific schema; dataclass picked by meta.paradigm
    eval: Optional[EvalCfg] = None
    checkpoint: CheckpointCfg = field(default_factory=CheckpointCfg)
    artifacts_dir: Optional[str] = None  # resolved at runtime
