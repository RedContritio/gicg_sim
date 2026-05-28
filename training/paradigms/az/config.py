"""AZ adapter configuration — two parallel cfg surfaces.

1) ``AZParadigmConfig`` + sub-cfgs (``AgentShapeCfg`` / ``MCTSCfg`` /
   ``TrainStepCfg``) — frozen dataclasses consumed by the unified
   pipeline driver via ``cfg.paradigm`` dict (spec ref:
   paradigm-az/spec.md A1-A6). Phase 1 deliverable.

2) ``AZConfig`` + preset builders (``smoke_config`` / ``fixed_1v1_config``
   / ``random_1v1_config``) — the historic AZ-only run config consumed
   by the standalone ``train_az`` loop. Phase 2-ζ (FU-W4-AZ-rewrite, T2.ζ)
   inlined these from ``training.paradigms.az.legacy.config`` into the
   adapter to achieve the STRICT T2.11 zero-legacy verify.

``legacy/config.py`` stays alive (Phase 5 git rm) because tests + tools
still import from it directly; those callers redirect in Phase 3+.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from training.core.cfg import ObsShape, ParadigmConfigBase, build_shape_from_toml, make_az_default_shape
from training.core.config.legacy import TrainingConfig
from training.core.inference.server import InferenceServerConfig
from training.core.network import AgentConfig
from training.core.scenario import ObsConfig, ScenarioConfig
from training.paradigms.az.mcts import MCTSConfig
from training.paradigms.az.train_step import TrainStepConfig

__all__ = [
    'AZConfig',
    'AZParadigmConfig',
    'AgentShapeCfg',
    'MCTSCfg',
    'TrainStepCfg',
    'fixed_1v1_config',
    'random_1v1_config',
    'smoke_config',
]


# ---------------------------------------------------------------------------
# Phase 1 — unified pipeline driver cfg (frozen dataclasses from TOML dict)
# ---------------------------------------------------------------------------

# Backward-compat alias (cfg-schema-unification CC-202): existing imports
# `from training.paradigms.az.config import AgentShapeCfg` resolve to the
# shared ObsShape dataclass. Field set unchanged (7 fields).
AgentShapeCfg = ObsShape

# Closed enum of supported cfg schema versions (CC-204). Future bump = explicit
# OpenSpec change synchronously updating this set + dataclass default.
_AZ_SUPPORTED_VERSIONS = frozenset({'1.0.0'})


@dataclass(frozen=True)
class MCTSCfg:
    """[paradigm.mcts] section — knobs for IS-MCTS selfplay search.

    Mirrors ``training.paradigms.az.mcts.MCTSConfig`` field-for-field so
    we can build one directly without translation."""

    n_rollouts: int = 200
    c_puct: float = 1.4
    dirichlet_alpha: float = 0.3
    dirichlet_eps: float = 0.25
    temperature: float = 1.0
    temperature_switch_step: int = 15
    max_rollout_depth: int = 400
    parallel_rollouts: int = 1
    value_mix_lambda: float = 1.0
    prior_mix_lambda: float = 1.0
    lambda_anneal_games: int = 0
    lambda_start: float = 0.0
    lambda_end: float = 0.8
    profile: bool = True
    backend: str = 'python'


@dataclass(frozen=True)
class TrainStepCfg:
    """[paradigm.train] section — algorithm-side training knobs.

    Mirrors ``training.paradigms.az.train_step.TrainStepConfig``."""

    l2_coef: float = 1e-4
    max_grad_norm: float = 1.0
    value_target_source: str = 'z'  # 'z' | 'mcts_value' | 'mixed'
    value_mix_lambda: float = 0.5
    entropy_coef: float = 0.0
    delta_aux_coef: float = 0.1


@dataclass(frozen=True)
class AZParadigmConfig(ParadigmConfigBase):
    """Top-level AZ paradigm cfg (cfg-schema-unification N2)."""

    paradigm: str = 'az'
    lr: float = 1e-3
    weight_decay: float = 0.0
    batch_size: int = 64
    buffer_cap: int = 200_000
    priority_weight: float = 3.0
    max_game_steps: int = 400
    total_games: int = 2000
    train_steps_per_game: int = 4
    min_buffer_before_train: int = 256
    init_from_ckpt: Optional[str] = None
    agent: ObsShape = field(default_factory=make_az_default_shape)
    mcts: MCTSCfg = field(default_factory=MCTSCfg)
    train: TrainStepCfg = field(default_factory=TrainStepCfg)

    @classmethod
    def from_dict(cls, d: dict) -> 'AZParadigmConfig':
        """Build from `cfg.paradigm` TOML dict. Validation delegated to
        ``ParadigmConfigBase.from_dict_strict`` (W1-T3 — unknown-key,
        version, paradigm-name template shared across 5 paradigm)."""
        return cls.from_dict_strict(
            d,
            paradigm_name='az',
            supported_versions=_AZ_SUPPORTED_VERSIONS,
            sub_section_factories={
                'agent': lambda dd: build_shape_from_toml(dd, make_az_default_shape),
                'mcts': lambda dd: MCTSCfg(**dd),
                'train': lambda dd: TrainStepCfg(**dd),
            },
        )


# ---------------------------------------------------------------------------
# Phase 2-ζ — legacy-style AZ run cfg + preset builders (inlined from
# legacy/config.py for adapter self-containment).
# ---------------------------------------------------------------------------


@dataclass
class AZConfig(TrainingConfig):
    """AZ top-level run config consumed by ``train_az``.

    Framework defaults: seed=42, n_workers=1, buffer_cap=50_000,
    artifacts_root='artifacts', run_label='run', batch_size=64. AZ
    require-at-construction fields (scenario, agent) have no defaults
    and must be passed by preset builders below.
    """

    scenario: ScenarioConfig = None  # type: ignore[assignment]
    agent: AgentConfig = None  # type: ignore[assignment]
    mcts: MCTSConfig = field(default_factory=MCTSConfig)
    train: TrainStepConfig = field(default_factory=TrainStepConfig)
    obs: ObsConfig = field(default_factory=ObsConfig)
    n_games: int = 50
    max_game_steps: int = 400
    buffer_capacity: int = 50_000
    priority_weight: float = 3.0
    train_steps_per_game: int = 4
    min_buffer_before_train: int = 128
    games_per_arena: int = 10
    arena_games: int = 10
    arena_replace_threshold: float = 0.55
    arena_max_game_steps: int = 400
    games_per_gauntlet: int = 0
    gauntlet_games_per_opponent: int = 10
    gauntlet_mcts_rollouts: tuple = (50, 200)
    gauntlet_max_game_steps: int = 400
    gauntlet_model_opponents: list = field(default_factory=list)
    # GreedyPlayer baselines: {"name", "features", "depth", "dice_greedy"}.
    # Required for direct comparison with PPO ladder (F1-D{1,2,3}).
    gauntlet_greedy_baselines: list = field(default_factory=list)
    inference: InferenceServerConfig = field(default_factory=InferenceServerConfig)
    sync_weights_every_train_steps: int = 10
    sysmon_interval_s: float = 10.0
    checkpoint_every_n_games: int = 0
    write_artifacts: bool = True
    # BC warm-start: if set, load this ckpt into challenger.net at startup.
    # The ckpt must be a state_dict produced by training.paradigms.bc.legacy.bc_train.
    init_from_ckpt: Optional[str] = None


def smoke_config(data_dir: Optional[str] = None) -> AZConfig:
    """Tiny config for the smoke test."""
    return AZConfig(
        scenario=ScenarioConfig(
            team_0=['赤蝶'],
            team_1=['赤蝶'],
            card_pool=None,
            data_dir=data_dir,
            # ADR-0011: preserve pre-existing engine deck shape (15-slot
            # deck with 碌碌无为 padding) for bit-exact baseline behavior.
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            # ADR-0011: union of v_legacy + test_basic mirrors the pre-
            # reorganization "all of data/{cards,characters}" visibility.
            pool=['v_legacy', 'test_basic'],
        ),
        agent=AgentConfig(
            n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
            n_hooks=900,
            max_ops_per_hook=64,
            max_actions=2048,
            d_model=16,
            n_cross_layers=1,
            dropout=0.0,
        ),
        mcts=MCTSConfig(
            n_rollouts=8,
            c_puct=1.4,
            dirichlet_alpha=0.3,
            dirichlet_eps=0.25,
            temperature=1.0,
            temperature_switch_step=15,
            max_rollout_depth=400,
        ),
        train=TrainStepConfig(l2_coef=1e-4, max_grad_norm=1.0, value_target_source='z'),
        n_games=3,
        seed=42,
        max_game_steps=400,
        buffer_capacity=500,
        priority_weight=3.0,
        batch_size=8,
        train_steps_per_game=2,
        min_buffer_before_train=8,
        games_per_arena=0,
        arena_games=0,
        games_per_gauntlet=0,
        gauntlet_games_per_opponent=0,
        artifacts_root='artifacts',
        run_label='az_smoke',
        write_artifacts=False,
    )


def fixed_1v1_config(data_dir: Optional[str] = None) -> AZConfig:
    """Fixed 1v1 baseline preset."""
    base = smoke_config(data_dir=data_dir)
    base.agent.d_model = 128
    base.agent.n_cross_layers = 2
    base.mcts.n_rollouts = 200
    base.mcts.lambda_anneal_games = 1500
    base.mcts.lambda_start = 0.0
    base.mcts.lambda_end = 0.8
    base.n_games = 2000
    base.buffer_capacity = 50_000
    base.batch_size = 256
    base.train_steps_per_game = 4
    base.min_buffer_before_train = 256
    base.games_per_arena = 100
    base.arena_games = 40
    base.games_per_gauntlet = 500
    base.gauntlet_games_per_opponent = 20
    base.gauntlet_mcts_rollouts = (50, 100, 200)
    # F1 ladder mirrors PPO routes (s008/s017/s020 use F1-D{1,2,3}).
    # dice_greedy=True per s007: F1-D2-dice_greedy is the strongest baseline.
    base.gauntlet_greedy_baselines = [
        {'name': 'F1-D1', 'features': 'F1', 'depth': 1, 'dice_greedy': True},
        {'name': 'F1-D2', 'features': 'F1', 'depth': 2, 'dice_greedy': True},
        {'name': 'F1-D3', 'features': 'F1', 'depth': 3, 'dice_greedy': True},
    ]
    base.train = TrainStepConfig(
        l2_coef=1e-4,
        max_grad_norm=1.0,
        value_target_source='z',
        entropy_coef=0.01,
    )
    base.checkpoint_every_n_games = 200
    base.run_label = 'fixed_1v1'
    base.write_artifacts = True
    return base


def random_1v1_config(data_dir: Optional[str] = None) -> AZConfig:
    """1v1 + domain randomization."""
    base = fixed_1v1_config(data_dir=data_dir)
    base.scenario.team_0 = ['赤蝶']
    base.scenario.team_1 = ['墨客']
    base.scenario.char_pool = ['赤蝶', '墨客', '猫咪', '刻师傅', '天星']
    base.scenario.team_size = 1
    base.run_label = 'random_1v1'
    return base
