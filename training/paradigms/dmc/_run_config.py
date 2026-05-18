"""DMC eval-run configuration (kept for tools/eval ckpt + daemon paths).

DMC-specific fields. Shared fields come from
``training.core.config.legacy.TrainingConfig``. Reuses
``training.core.scenario.ScenarioConfig`` for env config (char_pool /
team_size / fix_dice / obs_mask / max_rounds / deck_padding / pool).

FU-W4-DMC-pt2: relocated from ``legacy/config.py`` to top-level adapter.
``OpponentPoolConfig`` is re-exported from
``training/paradigms/dmc/_opponent.py`` so existing ckpt loaders /
tests that read ``cfg.opponent_pool`` continue working.

``load_config`` is the TOML entry consumed by tools/eval/_paradigm.py
``dmc.load_config`` registry slot (restored after the deletion of
``training.dmc.config_loader`` in P5-A). Mirrors the AZ legacy loader
pattern: ``base = "<preset>"`` + nested dict overrides applied onto
the resulting DmcConfig dataclass.

Eval-only surface: the unified pipeline driver uses
``training.paradigms.dmc.config.DMCParadigmConfig`` instead; this
``DmcConfig`` only feeds the standalone ``tools/eval/_dmc_evaluator``
+ ``tools/eval/ckpt`` flow that predates the driver.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Optional, Union

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore

from training.core.config.legacy import TrainingConfig
from training.core.network import AgentConfig
from training.core.scenario import ScenarioConfig
from training.paradigms.dmc._opponent import OpponentPoolConfig  # re-export


@dataclass
class EvalConfig:
    """Periodic eval protocol, per decision #8.

    Fixed-seed pre-generated scenarios; each eval run replays them
    with swap_sides for both baselines. Runs every
    ``interval_minutes`` of wall time during training.

    ``enabled``: in-process eval 开关。Stage 3 GPU train 走 Mac eval daemon
    架构(`tools/eval/daemon.py`),enabled=False 让 train_loop 跳过
    PeriodicEvaluator 节省 wall time。Mac smoke 默认 True 验证 pipeline。
    """

    enabled: bool = True
    interval_minutes: int = 60
    n_scenarios: int = 128
    baselines: list[str] = field(default_factory=lambda: ['F1-D2', 'F1-D4'])
    scenarios_seed: int = 42
    swap_sides: bool = True


@dataclass
class DmcConfig(TrainingConfig):
    """DMC top-level run config.

    Inherits from TrainingConfig (seed / n_workers / buffer_cap /
    artifacts_root / run_label / batch_size).
    """

    scenario: ScenarioConfig = None  # type: ignore[assignment]
    agent: AgentConfig = None  # type: ignore[assignment]
    opponent_pool: OpponentPoolConfig = field(default_factory=OpponentPoolConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)

    # DMC training hparams
    total_frames: int = 100_000_000
    num_actors: int = 4
    num_buffers: int = 50  # replay buffer slots (DouZero pattern)
    # ε-greedy actor explore. 0.05 over ~340-step episode ≈ 17 random actions,
    # 约 5% explore rate(review C.6:0.01 太小,期望 3.4 步实际"基本 deterministic")。
    exp_epsilon: float = 0.05
    learning_rate: float = 1e-4
    # MSE on ±1 target → typical grad norm < 1.0; 5.0 给 AdamW 一些 headroom
    # 而不真实裁(review C.9:40.0 等于不裁)。train_loop 仍 log grad_norm 到 TB。
    max_grad_norm: float = 5.0
    save_interval_minutes: int = 10
    checkpoint_dir: Optional[str] = None  # default: artifacts_root/<ts>_<run_label>/

    # Env episode bound
    max_game_steps: int = 400

    # Compute device. 'cpu' / 'cuda' / 'cuda:0' / 'mps' etc.
    device: str = 'cpu'

    # Resume from checkpoint. Accepts either:
    #   - Specific ckpt file: `artifacts/<run>/ckpt_12345.pt` or `final.pt`
    #   - Artifacts dir: `artifacts/<run>/` — auto-finds `latest.pt` first,
    #     falls back to highest-frames `ckpt_<N>.pt`
    # Resume 继承原 artifacts dir(metrics.jsonl 追加 / TB events 续 dir),
    # 不开新 timestamped 目录,这样 learning curve 跨 resume 边界连贯。
    # 持久化范围:net weights + optimizer state + TrainState counters + **全 RNG states**
    #   (Python global random / numpy / torch / 5 个独立 Random instances)。
    # 不持久化:replay buffer / opp_pool historical ring(restart 后 warm up)。
    resume_from: Optional[str] = None

    # Discount: DMC uses γ=1 (sparse terminal reward, no bootstrap).
    gamma: float = 1.0

    use_jit_trace: bool = False  # smoke off, full train on

    write_artifacts: bool = True


def _data_root(data_dir: Optional[str]) -> str:
    return data_dir or 'data'


def smoke_config(data_dir: Optional[str] = None) -> DmcConfig:
    """Tiny config for the Mac CPU smoke test, Phase 3.4."""
    return DmcConfig(
        scenario=ScenarioConfig(
            team_0=['赤蝶'],
            team_1=['墨客'],
            card_pool=['测试卡_增幅', '测试卡_碎片'],
            data_dir=_data_root(data_dir),
            char_pool=None,  # 1-char asymmetric: fixed teams, no random sampling
            team_size=1,
            max_rounds=10,  # 统一 10 round (timeout.lua tiebreak 在 round 10)
            obs_mask=['enemy_dice'],
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            pool=['v_legacy', 'test_basic'],
        ),
        agent=AgentConfig(
            n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
            n_hooks=900,
            max_tokens_per_hook=120,
            max_actions=2048,
            d_model=64,
            n_cross_layers=2,
            dropout=0.0,
        ),
        opponent_pool=OpponentPoolConfig(
            random=0.30,
            f1d2=0.30,
            f1d4=0.10,
            historical=0.30,
            ring_size=10,
        ),
        eval=EvalConfig(
            interval_minutes=5,
            n_scenarios=32,
            baselines=['F1-D2', 'F1-D4'],
            scenarios_seed=42,
        ),
        total_frames=5_000_000,
        num_actors=4,
        num_buffers=50,
        exp_epsilon=0.05,
        learning_rate=1e-4,
        max_grad_norm=5.0,
        save_interval_minutes=2,
        max_game_steps=400,
        seed=42,
        n_workers=1,
        buffer_cap=50_000,
        batch_size=32,
        artifacts_root='artifacts',
        run_label='dmc_smoke',
        write_artifacts=True,
        use_jit_trace=False,
    )


def stage3_config(data_dir: Optional[str] = None) -> DmcConfig:
    """Stage 3 — 1 char asymmetric + simple cards, full train target.

    Per README decision #5: PASS criterion vs F1-D2 WP ≥ 0.50.
    """
    base = smoke_config(data_dir=data_dir)
    base.agent.d_model = 128
    base.agent.n_cross_layers = 2
    base.total_frames = 2_000_000_000
    base.num_actors = 24  # Windows 9950X3D CCD0 16 logical + spillover
    base.batch_size = 32
    base.save_interval_minutes = 10
    base.eval.interval_minutes = 60
    base.eval.n_scenarios = 128
    base.run_label = 'dmc_stage3'
    base.use_jit_trace = True
    return base


BASE_PRESETS = {
    'smoke': smoke_config,
    'stage3': stage3_config,
}

# Top-level keys the loader must strip before dataclass override application.
# `meta` is the unified-pipeline section (FU-W1B): every cfg now carries
# `[meta] paradigm = "dmc"`. This eval-side loader doesn't consume meta;
# the unified loader at `training.core.config.loader.load_cfg` does.
# `seeds` / `seed_labels` belong to `tools._meta.multi_seed_launch`.
_LAUNCHER_ONLY_FIELDS = frozenset({'seeds', 'seed_labels', 'meta'})


def load_config(path: Union[str, Path], data_dir: str = 'data') -> DmcConfig:
    """Load a TOML config file into a fully-populated DmcConfig.

    Restored from the deleted ``training.dmc.config_loader.load_config``
    (P5-A) so that ``tools/eval/_paradigm.py`` ``dmc.load_config``
    registry slot resolves. Used by ``tools/eval/ckpt.py`` +
    ``tools/eval/daemon.py``.
    """
    text = Path(path).read_text(encoding='utf-8')
    data: dict[str, Any] = tomllib.loads(text)

    base_name = data.pop('base', 'smoke')
    if base_name not in BASE_PRESETS:
        raise ValueError(f'config {path}: unknown base preset {base_name!r}; valid = {sorted(BASE_PRESETS)}')
    for k in _LAUNCHER_ONLY_FIELDS:
        data.pop(k, None)
    cfg = BASE_PRESETS[base_name](data_dir=data_dir)
    _apply_overrides(cfg, data, path=str(path), trail='')
    return cfg


def _apply_overrides(target: Any, overrides: dict, *, path: str, trail: str) -> None:
    """Recursively apply a nested dict of overrides onto a dataclass."""
    if not is_dataclass(target):
        raise TypeError(
            f'config {path}: cannot apply overrides to non-dataclass {type(target).__name__} at {trail or "<root>"}'
        )

    known_fields = {f.name for f in fields(target)}
    for key, val in overrides.items():
        dotted = f'{trail}.{key}' if trail else key
        if key not in known_fields:
            raise ValueError(
                f'config {path}: unknown field {dotted!r}; '
                f'valid fields on {type(target).__name__} = {sorted(known_fields)}'
            )
        if isinstance(val, dict):
            sub = getattr(target, key)
            if is_dataclass(sub):
                _apply_overrides(sub, val, path=path, trail=dotted)
            else:
                # Leaf dict field (e.g. Optional[dict] like deck_padding):
                # the override replaces wholesale instead of merging.
                setattr(target, key, val)
        else:
            setattr(target, key, val)
