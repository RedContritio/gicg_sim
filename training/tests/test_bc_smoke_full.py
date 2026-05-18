"""BC paradigm smoke_full — full driver e2e + ckpt save/load (A1.6).

OpenSpec ref: ``openspec/changes/paradigm-smoke-full-tier/specs/
training-architecture/spec.md`` invariant A1.6 + DECISIONS SF-105
+ ``openspec/changes/bc-smoke-dataset-fixture`` (fixture closure)
+ ``openspec/changes/bc-pipeline-collect-gate-fix`` (collect gate
fix closure — let BC's ``n_episodes=0`` plan still trigger the
DatasetCollector one-shot push).

BC paradigm requires ``paradigm.bc.dataset_path`` pointing to an
existing NPZ file (``training/paradigms/bc/collector.py:42`` raises
ValueError on empty path; ``BCDataset`` requires actual NPZ data).
The repo ships no committed smoke-tier NPZ dataset (production
datasets live in gitignored ``artifacts/`` and are GB-sized).

Per ``bc-smoke-dataset-fixture``: generate a tiny on-the-fly NPZ
via in-process ``tools.dataset.gen_bc.collect()`` (sister test
``tools/dataset/tests/test_gen_bc_schema.py::test_collect_produces_
az_shape_only`` proves the cfg recipe works at ~1.3 s wall) and
inject the path via ``extra_overrides=['paradigm.bc.dataset_path=
<tmp>/dataset.npz']`` on the driver subprocess.

Post ``bc-pipeline-collect-gate-fix`` (this archive): the metrics
assertion below asserts ``train_steps > 0`` to lock the regression
— if ``pipeline.py:83`` collect gate is ever broken again the
BC smoke_full test fails fast instead of silently writing
random-init ckpts (the pre-fix failure mode).

T-25 rewrite: template now owns workspace/ subdir + artifacts/
allocation; we only need a sibling ``fixture/`` subdir for the NPZ.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from training.tests.smoke_full_template import (
    REPO_ROOT,
    resume_and_continue,
    run_paradigm_train_via_driver,
    verify_ckpt_files,
)


def _assert_train_steps_positive(artifacts: Path) -> None:
    """Lock bc-pipeline-collect-gate-fix regression.

    Read ``<artifacts>/metrics.jsonl``, find the last ``kind='iter'`` row,
    assert ``train_steps > 0``. Pre-fix BC smoke_full silently wrote
    random-init ckpts because ``pipeline.py:83`` collect gate
    ``if plan.collect and plan.n_episodes > 0`` blocked BC's
    ``n_episodes=0`` plan — collector never invoked, buffer empty,
    all train batches skipped on ``len(buffer) < batch_size``.

    The metrics row format is owned by ``training/core/logging.py::
    MetricsLogger.log_iter`` — fields step / frames / episodes /
    train_steps emitted once per outer iter in pipeline.py.
    """
    metrics_path = artifacts / 'metrics.jsonl'
    assert metrics_path.exists(), f'metrics.jsonl missing in {artifacts}'
    last_iter = None
    for line in metrics_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get('kind') == 'iter':
            last_iter = row
    assert last_iter is not None, f'no iter rows in {metrics_path} — driver loop never logged an iteration'
    assert last_iter.get('train_steps', 0) > 0, (
        f'BC smoke_full produced train_steps=0 — collector / buffer / train path broken '
        f'(likely pipeline.py:83 collect gate regression — bc-pipeline-collect-gate-fix). '
        f'Last iter row: {last_iter!r}'
    )


def _gen_bc_npz_for_smoke(tmp_path: Path) -> Path:
    """Generate a tiny BC NPZ dataset for smoke_full fixture.

    Mirrors the cfg recipe from ``tools/dataset/tests/test_gen_bc_schema``
    smoke (20 decisions / 5 games) but uses the BC smoke scenario (赤蝶
    mirror with v_legacy + test_basic pool) so the resulting NPZ encodes
    obs / actions consistent with ``configs/bc/smoke_full.toml`` shape.

    In-process ``collect()`` call (no subprocess) — ~1.3 s wall on Mac
    CPU per sister test measurement.

    Returns: path to the written NPZ file under ``tmp_path``.
    """
    from tools.dataset.gen_bc import collect

    cfg = {
        'run_label': 'bc_smoke_fixture',
        'seed': 0,
        # Scenario — 赤蝶 mirror (lives in v_legacy pool); matches
        # configs/bc/smoke.toml [scenario] verbatim except pool is a
        # list (gen_bc accepts list or str via cfg.get('pool')).
        'teams': ['赤蝶'],
        'card_pool': [],  # no cards — faster gen + matches BC smoke spirit
        'fix_dice': 'none',
        'max_rounds': 3,
        'data_dir': 'data',
        'obs_mask': [],
        'pool': ['v_legacy', 'test_basic'],
        # Teacher — F1-D2 production default (BC pre-train teacher).
        'teacher': 'F1-D2',
        'teacher_dice_greedy': True,
        'opponent_mix': ['F1-D2', 'F1-D1'],
        # Collection target — 20 decisions covers batch_size=8 with
        # held_out_frac=0.1 (~2 holdout + 18 train → 2 batches/epoch).
        'target_decisions': 20,
        'max_games': 5,
        'max_actions': 128,
        'meta': {'paradigm': 'bc'},
    }
    data = collect(cfg)
    n = int(data['chosen_action'].shape[0])
    assert n > 0, f'gen_bc smoke fixture produced 0 decisions (cfg={cfg!r}) — env / teacher misconfigured'

    npz_path = tmp_path / 'dataset.npz'
    np_kwargs = {k: v for k, v in data.items() if k != 'meta'}
    np.savez_compressed(npz_path, **np_kwargs)
    return npz_path


@pytest.mark.smoke_full
def test_bc_smoke_full(tmp_path) -> None:
    """BC full smoke — driver train (100 epoch) + ckpt save + resume.

    ``fixture/`` subdir holds the on-the-fly NPZ; template owns the
    ``workspace/`` subdir with symlinks for the subprocess cwd.

    Resume bumps ``paradigm.bc.n_epochs`` from 100 → 130 so the
    resumed run has room to land a new ckpt step (BC's terminus is
    fixed by ``n_epochs``; without the bump the resumed run exits at
    the same step as the resume ckpt → final save overwrites and
    ``len(post) > len(pre)`` fails). DMC-style paradigms whose
    terminus is dynamic (``total_frames``) don't need this trick — their
    step counter naturally advances past existing ckpt steps on resume.
    """
    cfg = REPO_ROOT / 'configs' / 'bc' / 'smoke_full.toml'
    assert cfg.exists(), f'cfg missing: {cfg}'

    fixture_dir = tmp_path / 'fixture'
    fixture_dir.mkdir()
    npz_path = _gen_bc_npz_for_smoke(fixture_dir)

    dataset_override = f'paradigm.bc.dataset_path={npz_path}'

    artifacts = run_paradigm_train_via_driver(
        cfg,
        tmp_path,
        extra_overrides=[dataset_override],
    )
    ckpts = verify_ckpt_files(artifacts, expected_min_count=2)
    _assert_train_steps_positive(artifacts)

    # Resume: bump n_epochs to give the resumed run room for a new ckpt.
    # save_every=30 + n_epochs=130 + resume from lex-first ckpt (= ckpt_100
    # since lex sort puts ckpt_100 before ckpt_30 / ckpt_60 / ckpt_90) →
    # train continues 100 → 130; save_every triggers SAVE ckpt_130 at the
    # 130-100=30 boundary; finally-save also writes ckpt_130 (idempotent
    # overwrite). Pre-resume ckpts at {30,60,90,100}; post-resume gain
    # ckpt_130 → 4 → 5.
    new_ckpts = resume_and_continue(
        ckpts[0],
        extra_overrides=[dataset_override, 'paradigm.bc.n_epochs=130'],
    )
    assert len(new_ckpts) > len(ckpts), (
        f'expected new ckpt(s) after resume from {ckpts[0].name}, got {len(ckpts)} → {len(new_ckpts)} files'
    )
