> 分卷导航:回到 [← Part 1](2026-05-18-tools-runs-second-round-fixes.md) · 续见 [Part 3](2026-05-18-tools-runs-second-round-fixes-part3.md)

## Phase 2: cfg_run_label override 规则化

### Task 2.1: `register --cfg-run-label-override` flag

**Files:**
- Modify: `tools/runs/register.py` (signature + body + CLI)
- Test: `tools/runs/tests/test_register_smoke.py`

- [ ] **Step 1: Failing test**

Append to `test_register_smoke.py`:

```python
def test_register_cfg_run_label_override(tmp_path, cfg_file):
    """Allow register to override cfg.meta.run_label snapshot so the
    metadata matches what user will train with via `tools.run --override
    meta.run_label=...` (AD4)."""
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        cfg_run_label_override='r013_first_real',
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    assert meta.cfg_run_label == 'r013_first_real'
    # cfg file itself unchanged
    assert 'az_smoke' in cfg_file.read_text()
```

- [ ] **Step 2: Run, verify fail**

Expected: FAIL — `cfg_run_label_override` not in signature.

- [ ] **Step 3: Implement**

In `tools/runs/register.py`, modify `register()` signature — add `cfg_run_label_override: str | None = None` param between `paradigm:` and `description:`:

```python
def register(
    *,
    run_id: str,
    cfg_file: str,
    label: str | None = None,
    type_: str | None = None,
    paradigm: str | None = None,
    cfg_run_label_override: str | None = None,
    description: str = '',
    root: Path | None = None,
    now: datetime.datetime | None = None,
    host: str | None = None,
    git_commit: str | None = None,
) -> schema.RunMetadata:
```

After the `cfg_run_label = _extract_run_label(...)` block + the no-run_label raise, add:

```python
    if cfg_run_label_override is not None:
        if not cfg_run_label_override:
            raise ValueError('--cfg-run-label-override must be non-empty')
        cfg_run_label = cfg_run_label_override
```

In `main()`, add CLI flag (after `--paradigm`):

```python
    ap.add_argument(
        '--cfg-run-label-override',
        default=None,
        dest='cfg_run_label_override',
        help='override cfg.meta.run_label in the metadata snapshot (matches what train will run with via --override)',
    )
```

And in the `register(...)` call inside `main()`:

```python
        meta = register(
            run_id=args.run_id,
            cfg_file=args.cfg_file,
            label=args.label,
            type_=args.type_,
            paradigm=args.paradigm,
            cfg_run_label_override=args.cfg_run_label_override,
            description=args.description,
            root=Path(args.root) if args.root else None,
        )
```

- [ ] **Step 4: Run test + full suite**

Run: `.venv/bin/python -m pytest tools/runs/tests/ -q`
Expected: 112 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/runs/register.py tools/runs/tests/test_register_smoke.py
git commit -m "tools.runs.register: --cfg-run-label-override flag for snapshot/train alignment (MED 2 part 1)"
```

### Task 2.2: `tools.run --run-id` 拒绝 `--override meta.run_label=...`

**Files:**
- Create: `tools/tests/test_run_smoke.py` (new test file)
- Modify: `tools/run.py:60` (around argparse / before run_pipeline)

- [ ] **Step 1: Failing test (new file)**

Create `tools/tests/test_run_smoke.py`:

```python
"""Smoke tests for `tools.run` entry."""

from __future__ import annotations

import pytest

from tools import run as tools_run


def test_run_rejects_run_id_and_run_label_override_conflict(tmp_path, capsys):
    """AD4: --run-id pins cfg_run_label snapshot in metadata; allowing
    a runtime --override meta.run_label would silently desync the
    metadata.cfg_run_label from the actual artifacts dir suffix. Reject
    with a clear hint to use register's --cfg-run-label-override."""
    # cfg path must exist for the parser; minimal cfg fine
    p = tmp_path / 'cfg.toml'
    p.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "x"\n[paradigm.dmc]\n',
        encoding='utf-8',
    )
    rc = tools_run.main(
        [
            str(p),
            '--run-id',
            's999',
            '--override',
            'meta.run_label=s999_x',
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert 'conflict' in err.lower() or 'cfg-run-label-override' in err
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tools/tests/test_run_smoke.py -v`
Expected: FAIL — current code accepts both.

- [ ] **Step 3: Implement**

In `tools/run.py:main()`, after `args = parser.parse_args(argv)` and **before** the `cfg_path = Path(args.config)` line, add:

```python
    if args.run_id:
        conflicting = [o for o in args.override if o.startswith('meta.run_label=')]
        if conflicting:
            print(
                '[tools.run] --override meta.run_label=... conflicts with --run-id '
                '(metadata.cfg_run_label snapshot already taken at register time). '
                'Re-register with `--cfg-run-label-override <slug>` or drop --run-id.',
                file=sys.stderr,
            )
            return 2
```

- [ ] **Step 4: Run test + integration sanity**

Run: `.venv/bin/python -m pytest tools/tests/test_run_smoke.py tools/runs/tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/run.py tools/tests/test_run_smoke.py
git commit -m "tools.run: reject --run-id + --override meta.run_label= conflict (MED 2 part 2)"
```

---

## Phase 3: Lifecycle 整合(M5 完整 + M3 闭环)

### Task 3.1: UTC strftime helper(fix HIGH 1)

**Files:**
- Modify: `tools/run.py:64-83` (extract helper + use)
- Test: `tools/tests/test_run_smoke.py`

- [ ] **Step 1: Failing test**

Append to `tools/tests/test_run_smoke.py`:

```python
def test_metadata_timestamp_to_dir_prefix_uses_utc_always():
    """HIGH 1: dir-name prefix must be UTC (cross-host consistent),
    NOT local tz — otherwise register on host A (UTC+8) + train on
    host B (UTC-5) yield different dir prefixes for the same run."""
    from tools.run import _metadata_timestamp_to_dir_prefix

    # UTC iso → UTC strftime
    assert _metadata_timestamp_to_dir_prefix('2026-05-17T18:44:21+00:00') == '202605171844'
    # Non-UTC iso (e.g. registered on UTC+8 host) → still UTC strftime
    # 18:44 +08:00 = 10:44 UTC
    assert _metadata_timestamp_to_dir_prefix('2026-05-17T18:44:21+08:00') == '202605171044'
    # UTC-5 → 23:44 UTC
    assert _metadata_timestamp_to_dir_prefix('2026-05-17T18:44:21-05:00') == '202605172344'
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tools/tests/test_run_smoke.py::test_metadata_timestamp_to_dir_prefix_uses_utc_always -v`
Expected: FAIL — helper not defined.

- [ ] **Step 3: Implement helper + use in main**

In `tools/run.py`, add module-level helper (after imports, before `def main`):

```python
def _metadata_timestamp_to_dir_prefix(ts: str) -> str:
    """Convert RunMetadata.timestamp (iso8601 with TZ) to artifacts
    dir prefix in `%Y%m%d%H%M` UTC form. UTC chosen so the dir prefix
    is identical on every host that picks up the same metadata —
    `.astimezone()` (per-host local) would defeat the single-source
    intent under cross-tz dev/CI."""
    dt = datetime.datetime.fromisoformat(ts)
    return dt.astimezone(datetime.timezone.utc).strftime('%Y%m%d%H%M')
```

In `main()`, replace the `artifacts_timestamp_local` block (around `tools/run.py:64-78`) — change:

```python
        artifacts_timestamp_local = dt.astimezone().strftime('%Y%m%d%H%M')
        print(f'[tools.run] linked to run {args.run_id} (artifacts ts={artifacts_timestamp_local} local)')
```

to:

```python
        try:
            artifacts_timestamp_local = _metadata_timestamp_to_dir_prefix(run_meta.timestamp)
        except ValueError as e:
            print(f'[tools.run] run {args.run_id} timestamp malformed: {e}', file=sys.stderr)
            return 2
        print(f'[tools.run] linked to run {args.run_id} (artifacts ts={artifacts_timestamp_local} UTC)')
```

Remove the now-dead inline `dt = datetime.datetime.fromisoformat(...)` block above it (it lived inline before the helper extraction). Keep `import datetime` import.

- [ ] **Step 4: Run test + full suite**

Run: `.venv/bin/python -m pytest tools/tests/test_run_smoke.py tools/runs/tests/ -q`
Expected: 113 + tools/runs PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/run.py tools/tests/test_run_smoke.py
git commit -m "tools.run: dir-prefix uses UTC strftime, cross-host consistent (HIGH 1)"
```

### Task 3.2: `complete_from_train` + auto-complete in driver(fix M3 / C2 闭环)

**Files:**
- Modify: `tools/runs/complete.py` (add `complete_from_train`)
- Modify: `tools/run.py` (try/finally + invocation)
- Test: `tools/tests/test_run_smoke.py` (integration test)

- [ ] **Step 1: Failing integration test**

Append to `tools/tests/test_run_smoke.py`:

```python
def test_run_auto_completes_artifacts_dir_on_success(tmp_path, monkeypatch):
    """M3 / C2 闭环: --run-id + successful train must update
    metadata.artifacts_dir + status='done' WITHOUT user manually
    invoking `tools.runs.complete --artifacts-dir`."""
    from tools.runs import register, schema

    # 1. register a smoke run in tmp_path
    cfg = tmp_path / 's999_cfg.toml'
    cfg.write_text(
        '[meta]\nparadigm = "dmc"\nrun_label = "auto_complete_smoke"\n'
        'seed = 42\ndevice = "cpu"\n'
        '[pipeline]\nmode = "serial"\nnum_actors = 1\n'
        '[scenario]\nteam_0 = ["赤蝶"]\nteam_1 = ["墨客"]\nteam_size = 1\n'
        'max_rounds = 5\ndeck_padding = { card = "碌碌无为", target_size = 15 }\n'
        'pool = ["v_legacy", "test_basic"]\ndata_dir = "data"\n'
        '[paradigm.dmc]\nversion = "1.0.0"\nparadigm = "dmc"\n'
        'epsilon = 0.05\ngamma = 1.0\nlr = 1e-4\nweight_decay = 0.0\n'
        'batch_size = 16\nmax_grad_norm = 5.0\nbuffer_cap = 1000\n'
        'max_game_steps = 30\ntotal_frames = 100\ntrain_ratio = 4\n'
        'eval_interval_episodes = 30\neval_n_scenarios = 8\n'
        'eval_baselines = ["F1-D2"]\n'
        '[paradigm.dmc.agent]\nd_model = 32\nn_cross_layers = 1\ndropout = 0.0\n'
        '[paradigm.dmc.opponent_mix]\nrandom = 1.0\nf1d2 = 0.0\nf1d4 = 0.0\n'
        'historical = 0.0\nring_size = 5\n'
        '[checkpoint]\nsave_every = 500\nkeep_last_n = 1\n'
        f'artifacts_root = "{tmp_path}/artifacts"\n',
        encoding='utf-8',
    )
    register.register(
        run_id='s999',
        cfg_file=str(cfg),
        root=tmp_path,
        host='test-host',
        git_commit='deadbeef',
    )

    # 2. run train --run-id s999 (driver auto-completes on exit)
    monkeypatch.chdir(tmp_path)
    rc = tools_run.main([str(cfg), '--run-id', 's999', '--max-steps', '3'])
    assert rc == 0

    # 3. verify metadata.artifacts_dir filled + status='done' WITHOUT
    #    a manual `complete --artifacts-dir` call
    meta = schema.load_file(schema.run_path('s999', root=tmp_path))
    assert meta.status == 'done'
    assert meta.artifacts_dir.startswith('artifacts/')
    assert (tmp_path / meta.artifacts_dir / 'latest.pt').exists()
```

This is a heavy integration test (real DMC train, ~5s). Mark with `@pytest.mark.smoke_full` to opt-out from default — but actually we want it in the default sweep so behavior regressions surface. Compromise: keep in default (no marker), trust 3-step train is fast enough.

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tools/tests/test_run_smoke.py::test_run_auto_completes_artifacts_dir_on_success -v`
Expected: FAIL — metadata.artifacts_dir still empty after run.

- [ ] **Step 3a: Implement `complete_from_train` in `complete.py`**

In `tools/runs/complete.py`, after the existing `complete()` function (around line 110), add:

```python
def complete_from_train(
    run_id: str,
    artifacts_dir: Path,
    status: str,
    *,
    wall_seconds: float | None = None,
    final_summary: str | None = None,
    root: Path | None = None,
) -> None:
    """Driver-side auto-complete after train finishes (success or
    failure). Idempotent; if no metadata file (user bypassed
    `register`), silently no-op."""
    path = schema.run_path(run_id, root=root)
    if not path.exists():
        return  # user skipped register; nothing to update
    repo_root = root if root is not None else Path.cwd()
    artifacts_dir_rel = _normalize_repo_relative(artifacts_dir, repo_root, label='artifacts_dir')
    meta = schema.load_file(path)
    if status not in schema.STATUSES:
        raise ValueError(f'status {status!r} must be one of {sorted(schema.STATUSES)}')
    meta.status = status
    meta.artifacts_dir = artifacts_dir_rel
    if wall_seconds is not None:
        meta.summary.wall = f'{wall_seconds:.1f}s'
    if final_summary:
        meta.notes.text = (meta.notes.text + '\n' + final_summary).strip()
    schema.save_file(meta, path)
```

- [ ] **Step 3b: Wire into `tools/run.py` main()**

In `tools/run.py:main()`, replace the existing block:

```python
    final_state = run_pipeline(
        cfg,
        paradigm,
        env_factory=env_factory,
        opp_pool=opp_pool,
        eval_server=None,
        resume_from=resume_path,
        max_steps=args.max_steps,
        artifacts_timestamp_local=artifacts_timestamp_local,
    )

    print(
        f'[tools.run] final: step={final_state.step} '
        ...
    )
    return 0
```

with:

```python
    auto_status = 'done'
    try:
        final_state = run_pipeline(
            cfg,
            paradigm,
            env_factory=env_factory,
            opp_pool=opp_pool,
            eval_server=None,
            resume_from=resume_path,
            max_steps=args.max_steps,
            artifacts_timestamp_local=artifacts_timestamp_local,
        )
    except BaseException:
        auto_status = 'failed'
        raise
    finally:
        if args.run_id:
            from tools.runs.complete import complete_from_train

            artifacts_root = Path(getattr(cfg.checkpoint, 'artifacts_root', 'artifacts'))
            # `artifacts_timestamp_local` is None only when --run-id absent (already guarded above)
            actual_dir = artifacts_root / f'{artifacts_timestamp_local}_{cfg.meta.run_label}'
            wall = getattr(locals().get('final_state', None), 'wall_seconds', None)
            complete_from_train(
                run_id=args.run_id,
                artifacts_dir=actual_dir,
                status=auto_status,
                wall_seconds=wall,
            )

    print(
        f'[tools.run] final: step={final_state.step} '
        f'frames={final_state.total_transitions} '
        f'episodes={final_state.total_episodes} '
        f'train_steps={final_state.train_steps} '
        f'wall_s={final_state.wall_seconds:.1f}'
    )
    return 0
```

Note: `getattr(locals().get('final_state', None), 'wall_seconds', None)` is defensive — on exception path `final_state` may not be bound.

- [ ] **Step 4: Run integration test + full suite**

Run: `.venv/bin/python -m pytest tools/tests/test_run_smoke.py -v`
Expected: 3 PASS (the new auto-complete test + 2 from Tasks 2.2 / 3.1).

Run: `.venv/bin/python -m pytest tools/runs/tests/ -q`
Expected: 113 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/runs/complete.py tools/run.py tools/tests/test_run_smoke.py
git commit -m "tools.run: auto-complete metadata.artifacts_dir + status on driver exit (M3 / C2 闭环)"
```

### Task 3.3: smoke_full template + CLAUDE.md scope caveat

**Files:**
- Modify: `training/tests/smoke_full_template.py` (module docstring)
- Modify: `CLAUDE.md` (Artifacts 段加 scope note)

- [ ] **Step 1: smoke_full_template docstring**

In `training/tests/smoke_full_template.py`, locate the module docstring at top and append (or add if missing):

```python
"""
...existing docstring...

Scope caveat (M5 single-sourced timestamp):
smoke_full tests subprocess-invoke `tools.run` WITHOUT `--run-id` (no
register/complete round-trip — tmp_path artifacts dir is throwaway).
The dir prefix therefore uses `datetime.now()` local, NOT a metadata-
sourced UTC timestamp. This is intentional — there's no cross-host
metadata consumer for these dirs, so single-sourcing has no value
here. Production runs use `tools.run --run-id <id>` and get the
UTC-strftime single-source path.
"""
```

(Use the actual existing docstring; only append the scope-caveat paragraph.)

- [ ] **Step 2: CLAUDE.md scope note**

In `CLAUDE.md`, locate the `## Artifacts` section (rewritten in earlier round). After the 4-step workflow code block, add:

```markdown
Note: smoke_full / direct `run_pipeline()` callers don't run through `--run-id` —
their artifacts dirs use local `datetime.now()` (not UTC), and they don't write
back to any metadata. M5 timestamp single-sourcing applies only to the
`register → train --run-id → auto-complete` production flow above.
```

- [ ] **Step 3: Commit**

```bash
git add training/tests/smoke_full_template.py CLAUDE.md
git commit -m "docs: scope-caveat M5 timestamp single-sourcing (smoke_full + direct callers excluded)"
```

---
