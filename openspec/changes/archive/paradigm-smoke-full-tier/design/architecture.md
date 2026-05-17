---
last_updated: 2026-05-17
status: ARCHIVE
schema_version: 0
change_id: paradigm-smoke-full-tier
---

# Architecture detail — smoke_full tier layered design

## 1. Layered architecture

```
                  ┌─────────────────────────────────────┐
                  │ test_<paradigm>_smoke_full.py × 5   │
                  │ (15-20 LOC each, marker smoke_full) │
                  └────────────┬────────────────────────┘
                               │ uses
                               ▼
            ┌──────────────────────────────────────────────┐
            │ smoke_full_template.py                       │
            │  • run_paradigm_train_via_driver(cfg)        │
            │  • verify_ckpt_files(artifacts, min_count)   │
            │  • resume_and_continue(artifacts, ckpt, cfg) │
            └─────────────┬────────────────────────────────┘
                          │ subprocess
                          ▼
       ┌────────────────────────────────────────────────────┐
       │ tools.run <cfg.toml> [--resume <ckpt>]            │
       │  • paradigm dispatch (existing)                    │
       │  • CheckpointManager.should_save / save / resume   │
       │  • per-paradigm step_schedule + train loop         │
       └────────────────────────────────────────────────────┘
                          │ reads
                          ▼
            ┌────────────────────────────────────────────────┐
            │ configs/<paradigm>/smoke_full.toml × 5         │
            │  meta.extends = "smoke.toml" +                 │
            │  [checkpoint] save_every = N (short cadence)   │
            │  + termination override (total_games etc.)     │
            └────────────────────────────────────────────────┘
```

**Reuse first**:全部 production driver / CheckpointManager / paradigm
adapter / cfg loader 都不动。本 change 只加 test 层与 cfg override 层。

## 2. CheckpointManager save cadence(关键)

`CheckpointManager.should_save(state)` 用 `cfg.checkpoint.save_every` 作为
step delta threshold:

```python
def should_save(self, state: PipelineState) -> bool:
    save_every = getattr(self.cfg.checkpoint, 'save_every', 1000)
    if save_every <= 0:
        return False
    if state.last_ckpt_at_step < 0:
        return state.step >= save_every
    return state.step - state.last_ckpt_at_step >= save_every
```

driver 每 outer iter 后 call `state.advance(plan)` 把 `state.step += 1`,
然后 call `should_save`。所以**要触发 ≥ 2 ckpt save,需要**:

- `cfg.checkpoint.save_every = N` 设小
- paradigm 跑足够 outer iter 让 `state.step >= 2 * N`(approx)

每 paradigm 的 outer iter terminus(`step_schedule` stop 条件)各异:

| Paradigm | Terminus 字段 | Step semantics |
|----------|---------------|----------------|
| AZ | `total_games` | step++ per game, stop when `total_episodes >= total_games` |
| PPO | `total_iterations` | step++ per iter, stop when `state.step >= total_iterations` |
| DMC | `total_frames` | step++ per iter, stop when `total_transitions >= total_frames` |
| CFR | `n_iterations` | step++ per iter, stop when `state.step >= n_iterations` |
| BC | `n_epochs` | step++ per epoch, stop when `state.step >= n_epochs` |

smoke_full toml 调 cadence + terminus 让每 paradigm 产 ≥ 2 ckpt files。

## 3. smoke_full toml structure(以 DMC 为例)

```toml
# configs/dmc/smoke_full.toml — smoke_full tier (D-601).
# Extends smoke.toml; only overrides ckpt cadence + frames.

[meta]
extends = "smoke.toml"
run_label = "dmc_smoke_full"

[paradigm.dmc]
total_frames = 2000           # ≥ 100 step (smoke=1000 → 76 step;double it)

[checkpoint]
save_every = 30               # 76+ step / 30 = ≥ 2 ckpt files
keep_last_n = 5
```

注:`meta.extends` 在 cfg loader 已支持(`training/core/config/loader.py:_load_with_extends`),
路径 relative to cfg dir。

## 4. Test 文件 structure(每 paradigm)

```python
"""Test <paradigm> smoke_full — 100-step train + ckpt save + resume."""
import pytest
from pathlib import Path
from training.tests.smoke_full_template import (
    run_paradigm_train_via_driver,
    verify_ckpt_files,
    resume_and_continue,
    REPO_ROOT,
)


@pytest.mark.smoke_full
def test_<paradigm>_smoke_full(tmp_path):
    cfg = REPO_ROOT / 'configs' / '<paradigm>' / 'smoke_full.toml'
    artifacts = run_paradigm_train_via_driver(cfg, tmp_path)
    verify_ckpt_files(artifacts, expected_min_count=2)

    # Resume from first ckpt + verify continues
    ckpts = sorted(artifacts.glob('ckpt_*.pt'))
    new_ckpts = resume_and_continue(ckpts[0])
    assert len(new_ckpts) > len(ckpts), 'expected new ckpt(s) after resume'
```

## 5. smoke_full_template.py helpers

```python
REPO_ROOT = Path(__file__).resolve().parents[2]

def run_paradigm_train_via_driver(
    cfg_path: Path, tmp_artifacts_root: Path, timeout_s: int = 900
) -> Path:
    """subprocess `tools.run <cfg>` with artifacts_root redirected to
    tmp_path. Returns the artifacts dir created by driver."""
    # Override artifacts root via --override CLI (loader supports it).
    result = subprocess.run(
        [
            sys.executable, '-m', 'tools.run', str(cfg_path),
            '--override', f'checkpoint.artifacts_root={tmp_artifacts_root}',
        ],
        cwd=REPO_ROOT, capture_output=True, text=True,
        check=True, timeout=timeout_s,
    )
    # Find the new artifacts dir (driver names by timestamp + run_label).
    dirs = list(tmp_artifacts_root.iterdir())
    if len(dirs) != 1:
        raise RuntimeError(
            f'expected single artifacts dir, got {len(dirs)}: {dirs}'
        )
    return dirs[0]


def verify_ckpt_files(artifacts: Path, expected_min_count: int = 2):
    """Verify ≥ N ckpt files written + latest.pt exists."""
    ckpts = list(artifacts.glob('ckpt_*.pt'))
    assert len(ckpts) >= expected_min_count, (
        f'expected ≥ {expected_min_count} ckpt files, got {len(ckpts)} '
        f'in {artifacts}'
    )
    assert (artifacts / 'latest.pt').exists()


def resume_and_continue(ckpt_file: Path, timeout_s: int = 600) -> list[Path]:
    """subprocess `tools.run --resume <ckpt>` (cfg comes from sibling).

    Returns new ckpt files post-resume. CheckpointManager.init_artifacts_dir
    REUSES the ckpt's parent dir (per its resume_from branch), so resume
    writes new ckpt_*.pt into the same dir."""
    artifacts = ckpt_file.parent
    # Recreate cfg path from cfg_snapshot.json (driver wrote it on first run).
    cfg_snap = json.loads((artifacts / 'cfg_snapshot.json').read_text())
    # We need a real cfg path to drive paradigm again. Strategy: use the
    # original smoke_full.toml since we know which paradigm ran.
    paradigm = cfg_snap['meta']['paradigm']
    cfg_path = REPO_ROOT / 'configs' / paradigm / 'smoke_full.toml'
    subprocess.run(
        [
            sys.executable, '-m', 'tools.run', str(cfg_path),
            '--resume', str(ckpt_file),
        ],
        cwd=REPO_ROOT, check=True, timeout=timeout_s,
    )
    return list(artifacts.glob('ckpt_*.pt'))
```
