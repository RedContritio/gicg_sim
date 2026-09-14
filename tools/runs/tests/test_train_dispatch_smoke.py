"""T-11 — 5-paradigm dispatch smoke for ``tools.runs.train``.

Spec ref: ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:

- 行 28-32 §Architecture CRIT-X-1 方案 A (paradigm dispatch 完整迁移
           from ``tools/run.py``; ``tools.runs.train`` 内含 cfg load +
           5 paradigm registry + ``run_pipeline``,no thin shim)
- 行 382-385 §测试矩阵 Workflow tests — ``train <cfg>`` → assert
             artifacts dir 创建 + ``metadata.status='done'`` +
             ``ckpts/`` 有内容

Subprocess-invokes ``python -m tools.runs.train <cfg>`` against each
paradigm's existing ``configs/<paradigm>/smoke.toml``. Tests run in a
tmp cwd so they share no state with the repo's real ``artifacts/``
tree (Phase A allocates dirs under ``cwd/artifacts/`` regardless of
``cfg.checkpoint.artifacts_root``, by design).

Wall budget: each paradigm bound to 180s subprocess timeout (DMC smoke
historically ~67s on Mac CPU; others ≤ 30s). Marked ``smoke`` so
default ``pytest`` collects it. **Run with ``-n 1``** — each test
spawns a paradigm subprocess that internally fans out into its own
collector / optimizer / GPU oversub risk → outer ``-n > 1`` would
oversubscribe.

Fixture strategy: symlink the repo's ``configs/`` / ``data/`` /
``tools/`` / ``training/`` / ``gicg_env/`` / ``gicg_engine/`` into the
tmp cwd so the subprocess sees a working-tree copy. Subprocess'
``artifacts/`` lives under tmp_path and is throwaway.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / 'gicg_engine').is_dir() and (p / 'tools').is_dir() and (p / 'configs').is_dir():
            return p
    raise RuntimeError(f'test_train_dispatch_smoke: cannot locate repo root from {here}')


REPO_ROOT = _find_repo_root()
PARADIGM_SUBPROCESS_TIMEOUT_S = 180


def _prepare_isolated_workspace(tmp_path: Path) -> Path:
    """Stage a working-tree-shaped subset of the repo at ``tmp_path``.

    ``configs/`` is **copied** (not symlinked) so the cfg paths passed to
    the subprocess resolve to a path INSIDE ``tmp_path`` — Phase B's
    ``normalize_repo_relative`` (helpers/paths.py) calls ``Path.resolve()``
    which follows symlinks, and a symlinked configs/ would resolve back
    out to the real repo, tripping the "outside repo root" guard.

    Everything else (``data/`` + python packages + ``gicg_env/`` C-shared
    lib) is symlinked since the subprocess only imports / reads from
    those — never writes, never resolves their path against ``cwd``.

    ``artifacts/`` is left to Phase A's mkdir under tmp_path so each
    test gets a clean allocator state without polluting the real
    ``artifacts/`` tree.
    """
    configs_dst = tmp_path / 'configs'
    shutil.copytree(REPO_ROOT / 'configs', configs_dst, symlinks=False)
    for name in ('data', 'tools', 'training', 'gicg_env', 'gicg_engine'):
        src = REPO_ROOT / name
        if not src.exists():
            raise RuntimeError(f'test_train_dispatch_smoke: source dir {src} missing')
        (tmp_path / name).symlink_to(src, target_is_directory=True)
    return tmp_path


def _gen_bc_npz(fixture_dir: Path) -> Path:
    """Mirror ``test_bc_smoke_full._gen_bc_npz_for_smoke`` — 20 decisions /
    5 games NPZ for BC dispatch. ~1.3 s wall on Mac CPU."""
    from training.core.artifact_io import save_dataset

    from tools.dataset.gen_bc import collect

    cfg = {
        'run_label': 'bc_dispatch_smoke_fixture',
        'seed': 0,
        'teams': ['赤蝶'],
        'card_pool': [],
        'fix_dice': 'none',
        'max_rounds': 3,
        'data_dir': 'data',
        'obs_mask': [],
        'pool': ['v_legacy', 'test_basic'],
        'teacher': 'F1-D2',
        'teacher_dice_greedy': True,
        'opponent_mix': ['F1-D2', 'F1-D1'],
        'target_decisions': 20,
        'max_games': 5,
        'max_actions': 128,
        'meta': {'paradigm': 'bc'},
    }
    data = collect(cfg)
    assert int(data['chosen_action'].shape[0]) > 0, 'gen_bc dispatch fixture produced 0 decisions'
    npz_path = fixture_dir / 'dataset.npz'
    save_dataset(npz_path, **{k: v for k, v in data.items() if k != 'meta'})
    return npz_path


# cfg_rel: cfg under configs/; extra_env: subprocess env additions
# (CFR stub buffer flag per cfr-driver-buffer-multihead-fix C6.4);
# pre_fixture: marker for in-test fixture prep (BC dataset injection);
# skip_reason: not None ⇒ pytest.skip with that message (kept as a hook
# for future paradigm-specific cfg quality issues; all 5 paradigms are
# currently active after T-31 raised AZ/CFR ``max_game_steps`` caps from
# the legacy ``tools/run.py --max-steps``-era value of 30).
_PARADIGM_MATRIX: dict[str, dict[str, Any]] = {
    'dmc': {
        'cfg_rel': 'configs/dmc/smoke.toml',
        'extra_env': {},
        'pre_fixture': None,
        'skip_reason': None,
    },
    'bc': {
        'cfg_rel': 'configs/bc/smoke.toml',
        'extra_env': {},
        'pre_fixture': 'bc_dataset',
        'skip_reason': None,
    },
    'ppo': {
        'cfg_rel': 'configs/ppo/smoke.toml',
        'extra_env': {},
        'pre_fixture': None,
        'skip_reason': None,
    },
    'cfr': {
        'cfg_rel': 'configs/cfr/smoke.toml',
        # cfg.debug.cfr_smoke_stub_buffer=true baked into configs/cfr/smoke.toml
        # [debug] section (post 2026-05-24 env-var 砍 — cfg-driven only)。
        'extra_env': {},
        'pre_fixture': None,
        'skip_reason': None,
    },
    'az': {
        'cfg_rel': 'configs/az/smoke.toml',
        'extra_env': {},
        'pre_fixture': None,
        'skip_reason': None,
    },
}


@pytest.mark.smoke
@pytest.mark.parametrize('paradigm', list(_PARADIGM_MATRIX.keys()))
def test_paradigm_dispatch_subprocess_runs_done(paradigm: str, tmp_path: Path) -> None:
    """``tools.runs.train <cfg>`` exits 0 with ``status='done'`` metadata +
    at least one ckpt file in ``ckpts/``.

    Verifies the full atomic lifecycle including the T-11 paradigm
    dispatch step: Phase A allocates dir → Phase B writes cfg + metadata
    (status='running') → Phase C step 6 dispatches via
    ``dispatch.run_paradigm_train`` → Phase C step 7 closes to status=done.

    Subprocess-invoked because in-process re-imports of the training
    stack leak module state between parametrize cases (paradigm registries
    are lazy + memoized).
    """
    matrix = _PARADIGM_MATRIX[paradigm]
    if matrix['skip_reason']:
        pytest.skip(matrix['skip_reason'])
    workspace = _prepare_isolated_workspace(tmp_path)
    cfg_path = workspace / matrix['cfg_rel']
    assert cfg_path.exists(), f'cfg missing in isolated workspace: {cfg_path}'

    extra_overrides: list[str] = []
    if matrix['pre_fixture'] == 'bc_dataset':
        fixture_dir = workspace / 'fixture'
        fixture_dir.mkdir()
        npz_path = _gen_bc_npz(fixture_dir)
        extra_overrides.append(f'paradigm.bc.dataset_path={npz_path}')

    env = os.environ.copy()
    env.update(matrix['extra_env'])

    cmd = [sys.executable, '-m', 'tools.runs.train', str(cfg_path)]
    for ov in extra_overrides:
        cmd.extend(['--override', ov])

    completed = subprocess.run(
        cmd,
        cwd=str(workspace),
        env=env,
        timeout=PARADIGM_SUBPROCESS_TIMEOUT_S,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f'paradigm={paradigm} dispatch exit={completed.returncode}\n'
        f'STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}'
    )

    artifacts_root = workspace / 'artifacts'
    run_dirs = [p for p in artifacts_root.iterdir() if p.is_dir() and not p.name.startswith('.')]
    assert len(run_dirs) == 1, (
        f'paradigm={paradigm}: expected 1 per-run dir, got {len(run_dirs)}: {[d.name for d in run_dirs]}'
    )
    run_dir = run_dirs[0]

    # Metadata: status='done' + exit_code=0 + wall_seconds set (spec §Schema).
    metadata = tomllib.loads((run_dir / 'metadata.toml').read_text(encoding='utf-8'))
    assert metadata['status'] == 'done', (
        f'paradigm={paradigm}: status={metadata["status"]!r}\nSTDERR:\n{completed.stderr}'
    )
    assert metadata['exit_code'] == 0
    assert metadata['wall_seconds'] >= 0.0

    # Phase B cfg snapshots present (spec §Per-run dir 行 78-82).
    assert (run_dir / 'cfg_leaf.toml').exists()
    assert (run_dir / 'cfg_resolved.toml').exists()

    # T-06 ckpts/ subdir layout — at least one ckpt_*.pt + latest.pt.
    ckpts_dir = run_dir / 'ckpts'
    assert ckpts_dir.is_dir(), f'paradigm={paradigm}: ckpts/ subdir missing'
    ckpt_files = sorted(ckpts_dir.glob('ckpt_*.pt'))
    assert len(ckpt_files) >= 1, (
        f'paradigm={paradigm}: expected ≥ 1 ckpt_*.pt in {ckpts_dir}, '
        f'got {len(ckpt_files)}; all: {[p.name for p in ckpts_dir.iterdir()]}'
    )
    assert (ckpts_dir / 'latest.pt').exists()


# ---- In-process unit tests (no subprocess) ----------------------------------


def test_run_train_placeholder_delegates_to_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The placeholder is a one-line shim over ``dispatch.run_paradigm_train``
    — patching dispatch must intercept all calls through the placeholder.
    Pins the delegation so Phase C tests' monkeypatch on the placeholder
    symbol stays equivalent to patching the dispatch entry directly.
    """
    import tools.runs._train.dispatch as dispatch_mod
    import tools.runs._train.run as run_mod

    captured: list[Any] = []
    monkeypatch.setattr(dispatch_mod, 'run_paradigm_train', lambda s: captured.append(s))

    sentinel = object()
    run_mod._run_train_placeholder(sentinel)  # type: ignore[arg-type]
    assert captured == [sentinel]


def test_dispatch_module_imports_training_lazily() -> None:
    """``dispatch`` module's top-level surface SHALL NOT pre-import the
    training stack — heavy ``training.*`` imports live inside
    ``run_paradigm_train`` so Phase C tests that monkeypatch the
    placeholder to a no-op never pay the cost.
    """
    import tools.runs._train.dispatch as dispatch_mod

    top_names = {n for n in dir(dispatch_mod) if not n.startswith('_')}
    leaked = top_names & {'load_cfg', 'run_pipeline', 'make_env_factory', 'resolve'}
    assert not leaked, f'dispatch leaked training-stack symbols at top level: {leaked}'


@pytest.mark.parametrize('paradigm', ['dmc', 'bc', 'cfr', 'ppo', 'az'])
def test_dispatch_wiring_resolves_paradigm_and_passes_prebuilt_dir(
    paradigm: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-process wiring check for ALL 5 paradigms — proves
    ``run_paradigm_train`` reaches ``run_pipeline`` with the right
    ``cfg.meta.paradigm`` + ``prebuilt_artifacts_dir=state.artifacts_dir``
    without actually running any episode.

    Complements the subprocess matrix for paradigms whose smoke cfg has
    cfg-quality issues (AZ + CFR's max_game_steps caps): even though we
    can't drive a full game, we can prove the dispatch path:
    cfg_resolved.toml read → load_cfg → resolve_paradigm(name) →
    make_env_factory / make_opponent_pool branch → run_pipeline call
    with the prebuilt dir wired through.

    Stubs ``run_pipeline`` to capture its kwargs instead of running. Real
    paradigm.make_network / make_opponent_pool still execute (the
    branching on ``hasattr(paradigm, 'make_opponent_pool')`` is the
    primary thing under test), so this catches regressions like
    accidentally dropping the prebuilt_artifacts_dir kwarg.
    """
    # Build a minimal cfg_resolved.toml that load_cfg will accept for
    # this paradigm. We reuse the real configs/<paradigm>/smoke.toml so
    # we don't have to re-invent paradigm-specific schemas, but read +
    # resolve extends locally so the file we hand to load_cfg has no
    # `meta.extends` left (mirrors Phase B's behaviour).
    from training.core.config.loader import load_with_extends
    from tools.runs._train import dispatch as dispatch_mod
    from tools.runs._train import setup as setup_mod
    from tools.runs._train.cfg_toml import dict_to_toml
    from tools.runs._train.setup import SetupState
    from datetime import datetime, timezone

    cfg_src = REPO_ROOT / 'configs' / paradigm / 'smoke.toml'
    cfg_dict = load_with_extends(cfg_src)
    artifacts_dir = tmp_path / 'run'
    artifacts_dir.mkdir()
    (artifacts_dir / 'cfg_resolved.toml').write_text(dict_to_toml(cfg_dict), encoding='utf-8')
    if paradigm == 'bc':
        # BC paradigm requires a non-empty dataset_path; satisfy validator
        # without actually loading data — we stub run_pipeline before any
        # collector touches it.
        cfg_dict.setdefault('paradigm', {}).setdefault('bc', {})['dataset_path'] = str(tmp_path / 'unused.npz')
        (artifacts_dir / 'cfg_resolved.toml').write_text(dict_to_toml(cfg_dict), encoding='utf-8')

    state = SetupState(
        artifacts_dir=artifacts_dir,
        cfg_resolved=cfg_dict,
        cfg_leaf_bytes=b'',
        nnn=1,
        label=cfg_dict['meta']['run_label'],
        timestamp_utc=datetime.now(timezone.utc),
    )

    captured: dict[str, Any] = {}

    def _stub_run_pipeline(cfg: Any, paradigm_obj: Any, **kwargs: Any) -> None:
        captured['cfg_paradigm_name'] = cfg.meta.paradigm
        captured['paradigm_class'] = type(paradigm_obj).__name__
        captured['kwargs'] = kwargs

    # CFR's make_buffer reads cfg.debug.cfr_smoke_stub_buffer but make_buffer
    # is called from run_pipeline (not dispatch) — we stub run_pipeline
    # itself so the cfg flag never matters here。 Production cfg path is
    # exercised by the parametrize matrix subprocess case above。
    monkeypatch.setattr('training.core.pipeline.run_pipeline', _stub_run_pipeline)

    dispatch_mod.run_paradigm_train(state)

    assert captured['cfg_paradigm_name'] == paradigm
    assert captured['kwargs']['prebuilt_artifacts_dir'] == artifacts_dir, (
        f'paradigm={paradigm}: prebuilt_artifacts_dir kwarg dropped or wrong'
    )
    # Suppress unused-import-after-monkeypatch warning.
    _ = setup_mod
