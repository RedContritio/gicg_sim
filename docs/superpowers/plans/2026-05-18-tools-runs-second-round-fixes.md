# tools/runs/ Second-Round Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address all 12 defects from second-round review of `tools/runs/`, organized into 4 phases by design risk.

**Architecture:** Phase 1 batches independent low-risk fixes (docstring / test gaps / underscore-API promotion / sync validation tightening) — no design change, unblock everything else. Phase 2 establishes a policy for the `cfg_run_label` snapshot vs train-time `--override` skew via an explicit register-side override flag + train-side conflict reject. Phase 3 is the load-bearing change: train driver auto-completes metadata on exit, and the dir-name timestamp converts from per-host local to UTC (so cross-host runs land in the same dir). Phase 4 removes the redundant M7 invariant check by consolidating it into `schema.load_file`.

**Tech Stack:** Python 3.14, pytest (smoke / smoke_full / integration markers), tomllib, ruff, rsync (integration tests).

---

## Architecture Decisions

### AD1: Lifecycle 整合 — train driver auto-completes,register stays decoupled

**Chosen:** `tools.run --run-id <id>` 在 driver 完成时(`finally` block 内)自动调一个新 helper `complete_from_train(run_id, artifacts_dir, status, ...)`,写 `metadata.artifacts_dir` + `status='done'/'failed'`。register 仍只写 timestamp + cfg_run_label snapshot,不预 reserve artifacts_dir(register 不该知道 `cfg.checkpoint.artifacts_root`)。

**Alternatives rejected:**
- register 时预 reserve dir:register 越权 read cfg.checkpoint 段;reserve 失败时(权限 / 已存在)无法 graceful;train 还可能不跑导致 stale dir
- 完全 manual:已是当前状态,被 second-round MED 3 直接打脸

### AD2: Timezone — UTC strftime for dir prefix

**Chosen:** `tools.run --run-id` 把 `metadata.timestamp`(UTC iso)转 `%Y%m%d%H%M` 时,先 `.astimezone(timezone.utc)` 确保 UTC,然后 strftime。dir 名跨机一致,代价是 dir 名是 UTC 时间(人读需脑补 +TZ)。

**Alternatives rejected:**
- 保留 `.astimezone()`(无参 = local tz):主机 A(UTC+8)register 后主机 B(UTC-5)train 用同 metadata,artifacts dir 前缀仍不同 → 本意单源被打脸(HIGH 1)
- dir 名带 tz suffix(`202605171844Z_label`):破坏现有 `<ts>_<label>/` glob 约定 + smoke_full template 的 timestamp 正则匹配

### AD3: smoke_full / direct call 不强制 --run-id,文档化 scope

**Chosen:** smoke_full template 保持现状(不 register,artifacts dir 用 `datetime.now()` local — 测试 tmp 一次性,无 cross-host concern)。直接调 `run_pipeline()` 的代码同理。M5 timestamp single-sourcing 仅适用于 production `tools.run --run-id` 流程。CLAUDE.md + smoke_full template docstring 明确这一 scope。

**Alternatives rejected:**
- smoke_full 加 register/complete:需 `tools.run --runs-root` flag 让 metadata 落 tmp_path,scope 蔓延 + 每个 paradigm test 都要 fixture 一份 run-id
- 让 `init_artifacts_dir` 默认从 `cfg.meta.run_id` 读 metadata:register 不强制,引入隐性依赖,坏现状

### AD4: cfg_run_label override — register 加显式 flag + train 拒绝冲突

**Chosen:**
- `tools.runs.register --cfg-run-label-override <slug>` 让 register snapshot 用 override 后值(等同 user 即将 `tools.run --override meta.run_label=<slug>` 的结果)
- `tools.run --run-id <id>` 启动时若 `--override meta.run_label=...` 同时出现 → 拒绝 + 提示用 register flag(避免 snapshot 与实际 dir 脱节)
- 不传 `--run-id` 时 train 自由 override(向后兼容,smoke_full path)

**Alternatives rejected:**
- 静默接受 skew:M3 描述的 metadata.cfg_run_label 与实际 dir run_label 脱节继续存在
- complete 自动同步 cfg_run_label:hidden mutation,违反 snapshot 语义("register 时 cfg 长啥样"是 audit truth)

---

## File Structure

### Modified files

- `training/core/config/loader.py` — promote `_load_with_extends` → `load_with_extends`(public)+ 保留 alias
- `tools/runs/schema.py` — module docstring 同步新字段 + `load_file` 加 filename invariant
- `tools/runs/register.py` — public API import + `json allow_nan=False` + `--cfg-run-label-override` flag + symlink doc
- `tools/runs/complete.py` — 加 `complete_from_train()` 供 driver 调用
- `tools/runs/show.py` — 删除 redundant M7 invariant(挪到 `schema.load_file`)
- `tools/runs/list.py` — 删除 redundant M7 invariant(挪到 `schema.load_file`)
- `tools/runs/sync.py` — `_validate_remote` 用 `user@host:path` regex
- `tools/run.py` — UTC strftime helper + finally auto-complete + reject override conflict
- `training/tests/smoke_full_template.py` — module docstring 加 scope caveat
- `CLAUDE.md` — Artifacts 段加 register/train workflow + scope caveat
- `docs/3_plans/backlog.md` — rewrite I10

### Modified tests

- `tools/runs/tests/test_register_smoke.py` — NaN test + override flag test
- `tools/runs/tests/test_sync_smoke.py` — bad-colon test + mtime-tie integration
- `tools/runs/tests/test_show_smoke.py` — invariant test passes via schema.load_file
- `tools/runs/tests/test_list_smoke.py` — invariant test passes via schema.load_file
- `tools/tests/test_run_smoke.py` (new file)— UTC strftime helper test + override conflict test + auto-complete integration

### No other new files.

---

## Phase 1: Low-risk cleanup (no design change)

### Task 1.1: Promote `_load_with_extends` → `load_with_extends`

**Files:**
- Modify: `training/core/config/loader.py:95-120` + EOF
- Modify: `tools/runs/register.py:48,78` (import + `_resolve_cfg` body)

- [ ] **Step 1: Rename + add deprecation alias**

In `training/core/config/loader.py:95`, rename function `_load_with_extends` → `load_with_extends`. At end of file (after all functions), add:

```python
# Backward-compat alias for the underscore-prefixed name (legacy
# internal use). Remove after grep confirms no callers remain.
_load_with_extends = load_with_extends
```

- [ ] **Step 2: Update register import + call site**

In `tools/runs/register.py:48`, change:

```python
from training.core.config.loader import _load_with_extends
```

to:

```python
from training.core.config.loader import load_with_extends
```

In `tools/runs/register.py:78` (`_resolve_cfg`), change `_load_with_extends(cfg_path)` → `load_with_extends(cfg_path)`.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m pytest tools/runs/tests/ -q`
Expected: 110 PASS, 2 deselected.

Run: `grep -rn '_load_with_extends' --include='*.py' .`
Expected: 1 hit only (the alias at loader.py EOF).

- [ ] **Step 4: Commit**

```bash
git add training/core/config/loader.py tools/runs/register.py
git commit -m "$(cat <<'EOF'
tools/runs + training/core: promote _load_with_extends → load_with_extends (public API)

register.py 跨模块 import 一个 _-prefix internal helper 是脆弱的:loader.py
refactor 时无 deprecation 信号会 silent break register 的 cfg_checksum 路径。
Promote 为公开 API,旧名保留 alias 兜底。

- training/core/config/loader.py: 重命名函数为 load_with_extends + EOF 加旧名 alias
- tools/runs/register.py: 改 import + _resolve_cfg 调用名

验证: pytest tools/runs/tests/ 110 PASS

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.2: `json allow_nan=False` 严格 canonical

**Files:**
- Modify: `tools/runs/register.py:86` (`_cfg_checksum`)
- Test: `tools/runs/tests/test_register_smoke.py` (append at EOF)

- [ ] **Step 1: Failing test**

Append to `test_register_smoke.py`:

```python
def test_register_rejects_nan_in_cfg(tmp_path):
    """C1 strict canonical: NaN in cfg must raise (not silently
    accepted into a stable-but-invalid checksum)."""
    p = tmp_path / 'r013.toml'
    p.write_text(
        '[meta]\nparadigm = "az"\nrun_label = "x"\n[paradigm.az]\nthr = nan\n',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='[Nn][Aa][Nn]|allow_nan|Out of range'):
        register.register(
            run_id='r013',
            cfg_file=str(p),
            root=tmp_path,
            now=_fixed_now(),
            host='h',
            git_commit='abc',
        )
```

- [ ] **Step 2: Run, verify fails**

Run: `.venv/bin/python -m pytest tools/runs/tests/test_register_smoke.py::test_register_rejects_nan_in_cfg -v`
Expected: FAIL — current `_cfg_checksum` accepts NaN (json default `allow_nan=True`).

- [ ] **Step 3: Implement**

In `tools/runs/register.py:86`, change:

```python
canonical = json.dumps(merged, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
```

to:

```python
canonical = json.dumps(merged, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
```

- [ ] **Step 4: Run test + full suite**

Run: `.venv/bin/python -m pytest tools/runs/tests/ -q`
Expected: 111 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/runs/register.py tools/runs/tests/test_register_smoke.py
git commit -m "tools.runs.register: json allow_nan=False, raise on NaN/Inf cfg values (LOW 1)"
```

### Task 1.3: `schema.py` module docstring 同步

**Files:** `tools/runs/schema.py:1-9`

- [ ] **Step 1: Update docstring**

Change `tools/runs/schema.py:1-8` from:

```python
"""Run metadata TOML schema (per spec T5).

Dataclass-based schema + strict validator + minimal hand-rolled TOML
emitter (depend only on stdlib ``tomllib`` for read).

Layout: top-level scalars + nested ``[summary]`` / ``[notes]``;
``[result.gauntlet]`` and ``[result.training]`` are optional.
"""
```

to:

```python
"""Run metadata TOML schema (per spec T5).

Dataclass-based schema + strict validator + minimal hand-rolled TOML
emitter (depend only on stdlib ``tomllib`` for read).

Layout: top-level scalars (incl. ``cfg_run_label`` — snapshot of
``cfg.meta.run_label`` at register time — and ``artifacts_dir`` —
repo-relative path to the artifacts dir, backfilled by ``complete``
or train driver after the run finishes) + nested ``[summary]`` /
``[notes]``; ``[result.gauntlet]`` and ``[result.training]`` optional.
"""
```

- [ ] **Step 2: Commit**

```bash
git add tools/runs/schema.py
git commit -m "tools/runs/schema: sync module docstring with cfg_run_label/artifacts_dir fields (LOW 3)"
```

### Task 1.4: Backlog I10 rewrite

**Files:** `docs/3_plans/backlog.md` (I10 row, near `## 基础设施 / 监控`)

- [ ] **Step 1: Rewrite I10 entry**

Find row starting with `| I10 |` in `docs/3_plans/backlog.md` and replace with:

```
| I10 | `tools.runs.sync` 前向兼容 host namespace | 当前 register/list/schema hardcoded `runs_dir/<id>.toml` flat 顶层,无 nested 路径风险。若 I9(跨机冲突 host namespace)落地为 `artifacts/runs/<host>/<id>.toml`,sync include `*.toml` 会漏 subdir。Pre-decision:I9 决策后,sync include 同步加 `**/*.toml`,或保持 flat 用 host hash 后缀 | 4 | idea (contingent on I9, 2026-05-18) |
```

- [ ] **Step 2: Commit**

```bash
git add docs/3_plans/backlog.md
git commit -m "backlog: rewrite I10 — nested-dir risk doesn't exist today; entry now describes I9 forward-compat (LOW 4)"
```

### Task 1.5: `--update` mtime-tie integration test

**Files:** `tools/runs/tests/test_sync_smoke.py` (append at EOF)

- [ ] **Step 1: Add integration test**

Append to `test_sync_smoke.py`:

```python
@pytest.mark.integration
def test_rsync_update_tie_mtime_keeps_dst(tmp_path):
    """L5: rsync `--update` flag — equal mtime tie → dst content
    preserved (rsync default). If this behavior flips in a future
    rsync version, our T4 cross-host conflict policy needs revisit."""
    if shutil.which('rsync') is None:
        pytest.skip('rsync not on PATH')

    import os

    src = tmp_path / 'src'
    (src / 'artifacts/runs').mkdir(parents=True)
    (src / 'artifacts/runs/r013.toml').write_text('src-bytes\n')
    dst = tmp_path / 'dst'
    (dst / 'artifacts/runs').mkdir(parents=True)
    (dst / 'artifacts/runs/r013.toml').write_text('dst-bytes\n')

    fixed_mtime = 1700000000.0
    os.utime(src / 'artifacts/runs/r013.toml', (fixed_mtime, fixed_mtime))
    os.utime(dst / 'artifacts/runs/r013.toml', (fixed_mtime, fixed_mtime))

    cmd = ['rsync', *sync.RSYNC_FLAGS, f'{src}/', f'{dst}/']
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert (dst / 'artifacts/runs/r013.toml').read_text() == 'dst-bytes\n'
```

- [ ] **Step 2: Run integration**

Run: `.venv/bin/python -m pytest tools/runs/tests/test_sync_smoke.py -m integration -v`
Expected: 2 PASS(local-to-local + mtime-tie)+ 1 SKIPPED(ssh)or 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/runs/tests/test_sync_smoke.py
git commit -m "tools/runs/tests: integration test for rsync --update mtime-tie behavior (LOW 5)"
```

### Task 1.6: sync `_validate_remote` 更严

**Files:**
- Modify: `tools/runs/sync.py:28-55` (imports + `_validate_remote`)
- Test: `tools/runs/tests/test_sync_smoke.py`

- [ ] **Step 1: Failing test**

Add to `test_sync_smoke.py` (after `test_build_command_rejects_path_without_trailing_slash`):

```python
def test_validate_remote_rejects_macos_local_path_with_colon():
    """MED 4: `/Volumes/X:/foo/` (macOS) contains `:` but is a local
    path, not <user>@<host>:<path>. Must reject."""
    with pytest.raises(ValueError, match='user@host'):
        sync.build_command('push', '/Volumes/X:/foo/')


def test_validate_remote_rejects_bare_host_colon_path():
    """A `host:path/` form without `user@` is technically legal SSH
    syntax but our policy requires user@host (cross-host audit trail)."""
    with pytest.raises(ValueError, match='user@host'):
        sync.build_command('push', 'somehost:/repo/')
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tools/runs/tests/test_sync_smoke.py::test_validate_remote_rejects_macos_local_path_with_colon -v`
Expected: FAIL — current code accepts (only checks `:` presence).

- [ ] **Step 3: Implement**

In `tools/runs/sync.py`, add `import re` near top (after `import subprocess`). Replace `_validate_remote`:

```python
_REMOTE_RE = re.compile(r'^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:.+/$')


def _validate_remote(remote: str) -> None:
    """Remote must be ``<user>@<host>:<path>/`` (path ends with /).
    ``:`` alone is not sufficient — macOS paths like ``/Volumes/X:/foo/``
    contain ``:`` but are local."""
    if not _REMOTE_RE.match(remote):
        raise ValueError(
            f'remote {remote!r} must be of form user@host:path/ '
            f'(user@host + colon + path + trailing slash)'
        )
```

- [ ] **Step 4: Run, verify pass + full suite**

Run: `.venv/bin/python -m pytest tools/runs/tests/test_sync_smoke.py -q`
Expected: all PASS (existing tests should still pass — their fixtures use `dev@host:/repo/` form which matches the regex).

- [ ] **Step 5: Commit**

```bash
git add tools/runs/sync.py tools/runs/tests/test_sync_smoke.py
git commit -m "tools.runs.sync: stricter remote validation — require user@host: form, reject /Volumes/X:/ path (MED 4)"
```

### Task 1.7: `_normalize_repo_relative` symlink behavior 文档化

**Files:** `tools/runs/register.py:118-130`

- [ ] **Step 1: Update docstring only**

Replace `_normalize_repo_relative` docstring:

```python
def _normalize_repo_relative(p: Path, repo_root: Path, *, label: str = 'path') -> str:
    """Return repo-relative path string. Reject paths outside repo root
    (cross-host metadata sync needs portable references; absolute paths
    on dev machine are meaningless on the receiver). ``label`` appears
    in the error message (e.g. 'cfg_file', 'artifacts_dir').

    Symlink behavior: uses ``Path.resolve()`` which follows symlinks.
    A repo-internal symlink targeting an external path (e.g.
    ``configs/x.toml`` → ``/external/x.toml``) resolves to its target
    and is rejected as outside repo root. If you need to register a
    cfg via symlink, copy it into the repo first (so the symlink lives
    nowhere)."""
```

- [ ] **Step 2: Commit**

```bash
git add tools/runs/register.py
git commit -m "tools.runs.register: document Path.resolve symlink-following behavior (MED 5)"
```

### Task 1.8: Phase 1 verification — full suite + ruff

- [ ] **Step 1: Run all tests + format check**

```bash
.venv/bin/python -m pytest tools/runs/tests/ -q
.venv/bin/python -m pytest -m smoke training/tests/ -q
.venv/bin/ruff format --check tools/runs/ tools/run.py training/core/checkpoint.py training/core/pipeline.py training/core/config/loader.py
```

Expected: all PASS, 0 reformats needed.

- [ ] **Step 2: If ruff needs reformat, apply + amend**

```bash
.venv/bin/ruff format <flagged-files>
git add -u && git commit --amend --no-edit
```

(Only if needed; otherwise skip.)

---

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

## Phase 4: M7 invariant consolidation

### Task 4.1: 删除 show/list 的 invariant,挪到 `schema.load_file`

**Files:**
- Modify: `tools/runs/schema.py` (`load_file`)
- Modify: `tools/runs/show.py` (remove redundant block)
- Modify: `tools/runs/list.py` (remove redundant block)
- Modify: `tools/runs/tests/test_show_smoke.py` + `test_list_smoke.py` (tests still pass via schema)

- [ ] **Step 1: Update schema.load_file to enforce invariant**

In `tools/runs/schema.py`, replace `load_file`:

```python
def load_file(path: Path) -> RunMetadata:
    """Load + validate. Also enforces M7 filename invariant:
    `path.stem` MUST equal `meta.run_id` (a hand-rename or copy-paste
    mislabel is corruption, not a legitimate query miss)."""
    meta = loads(path.read_text(encoding='utf-8'))
    if meta.run_id != path.stem:
        raise ValueError(
            f'metadata at {path} has run_id={meta.run_id!r} != filename stem {path.stem!r} '
            f'(file mislabeled)'
        )
    return meta
```

- [ ] **Step 2: Remove redundant check in show.py**

In `tools/runs/show.py:main()`, **delete** the block:

```python
    # M7 invariant: filename stem must match internal run_id; a hand-
    # edited or copy-paste mislabeled file is corruption, not a query miss.
    if meta.run_id != args.run_id:
        print(
            f'tools.runs.show: file {path} internal run_id={meta.run_id!r} '
            f'!= requested {args.run_id!r}; file mislabeled',
            file=sys.stderr,
        )
        return 1
```

The existing `except (ValueError, OSError)` around `schema.load_file(path)` now catches the new invariant raise — but the error message is slightly different. Verify the show mislabeled test still asserts something present in the new message ("mislabeled" word is in the new schema message, so existing assertion holds).

- [ ] **Step 3: Remove redundant check in list.py**

In `tools/runs/list.py:_collect`, **delete** the block:

```python
        # M7 invariant: filename stem must equal internal run_id; otherwise
        # `show <run_id>` opens a different file than `list` reports.
        if p.stem != meta.run_id:
            print(
                f'tools.runs.list: skipping {p.name}: filename stem {p.stem!r} '
                f'!= metadata.run_id {meta.run_id!r}',
                file=sys.stderr,
            )
            continue
```

The existing `except (ValueError, OSError) as e:` around `schema.load_file(p)` now catches the new invariant ValueError and skips with stderr message. Update the test expectation if needed.

- [ ] **Step 4: Update test_list_smoke.py assertion**

In `tools/runs/tests/test_list_smoke.py::test_list_skips_mislabeled_file`, the existing assertion:

```python
    assert "metadata.run_id 'r013'" in captured.err
```

…now reads metadata via schema.load_file which raises with a slightly different message. Update assertion to match new wording:

```python
    assert 'mislabeled' in captured.err
    assert 'r013' in captured.err  # internal run_id still mentioned
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tools/runs/tests/ -q`
Expected: 113 PASS (no regression — invariant moved, not lost).

- [ ] **Step 6: Commit**

```bash
git add tools/runs/schema.py tools/runs/show.py tools/runs/list.py tools/runs/tests/test_show_smoke.py tools/runs/tests/test_list_smoke.py
git commit -m "tools/runs: consolidate M7 filename invariant into schema.load_file (LOW 2)"
```

---

## Final Verification

### Task F.1: Full sweep + ruff + integration

- [ ] **Step 1: All test tiers**

```bash
.venv/bin/python -m pytest tools/runs/tests/ -q
.venv/bin/python -m pytest tools/tests/ -q
.venv/bin/python -m pytest -m smoke training/tests/ -q
.venv/bin/python -m pytest -m integration tools/runs/tests/ -v
.venv/bin/ruff format --check tools/runs/ tools/run.py training/core/checkpoint.py training/core/pipeline.py training/core/config/loader.py
```

Expected:
- tools/runs/tests/: 113 PASS
- tools/tests/: 3 PASS (new file from Phase 2/3)
- -m smoke: 5/5 paradigm PASS
- -m integration: 2-3 PASS (local rsync + mtime-tie always; ssh-localhost depending on env)
- ruff: 0 reformats

- [ ] **Step 2: End-to-end production sanity**

Manually verify the full new lifecycle:

```bash
# clean
rm -f artifacts/runs/s999.toml

# register
.venv/bin/python -m tools.runs.register --run-id s999 --cfg configs/dmc/smoke_full.toml --type s --label dmc_phase4_sanity --description "phase 1-4 sanity"

# train (timestamp single-sourced UTC + auto-complete)
.venv/bin/python -m tools.run configs/dmc/smoke_full.toml --max-steps 5 --run-id s999

# verify metadata closed loop
.venv/bin/python -m tools.runs.show s999 | grep -E 'status|artifacts_dir|cfg_run_label'
```

Expected output includes:
- `status       : done`
- `artifacts_dir: artifacts/<UTC_ts>_dmc_smoke_full`(`<UTC_ts>` matches `metadata.timestamp` converted to UTC strftime)
- `cfg_run_label: dmc_smoke_full`

---

## Self-Review

### 1. Spec coverage

12 缺陷 ↔ task mapping:

| # | 缺陷 | Task |
|---|---|---|
| HIGH 1 | cross-tz astimezone | Task 3.1 |
| HIGH 2 | smoke_full 未接 --run-id | Task 3.3(文档化 scope,不强制注入) |
| MED 1 | underscore promote | Task 1.1 |
| MED 2 | cfg_run_label vs override | Task 2.1 + 2.2 |
| MED 3 | complete 必手填 | Task 3.2(auto-complete) |
| MED 4 | sync `:` validate | Task 1.6 |
| MED 5 | symlink resolve | Task 1.7(文档化) |
| LOW 1 | NaN allow | Task 1.2 |
| LOW 2 | show invariant 冗余 | Task 4.1 |
| LOW 3 | schema docstring | Task 1.3 |
| LOW 4 | backlog I10 | Task 1.4 |
| LOW 5 | mtime-tie test | Task 1.5 |

12/12 covered。

### 2. Placeholder scan

- 没有 "TBD" / "implement later" / "add appropriate error handling"
- Task 3.2 integration test 的 cfg 是完整 inline TOML(无 `...similar to`)
- 每个 code-changing step 都有 actual code block

### 3. Type / name consistency

- `cfg_run_label_override` Task 2.1 register signature + CLI flag dest + body 检查 都用同一名 ✓
- `_metadata_timestamp_to_dir_prefix` Task 3.1 helper 名 + import 一致 ✓
- `complete_from_train` Task 3.2 函数名 + import + 调用一致 ✓
- `load_with_extends` Task 1.1 rename 后所有 site 同名 ✓

---

## Execution Notes

- **Phase ordering**:Phase 1 任务彼此独立,可任意顺序;Phase 2 → Phase 3 单向(Task 3.1 复用 helper,Task 3.2 复用 register flag);Phase 4 独立,可放最后
- **Commit cadence**:每个 Task 一个 commit(per CLAUDE.md §4),18 commits total
- **不要 squash**:每个 task 是一个完整改动单元,squash 会丢 audit trail
- **若 Phase 3 Task 3.2 integration test 超时**:可改 `--max-steps 3` 进一步缩短(DMC 3 step ≤ 3s);或将 test 标 `@pytest.mark.smoke_full` 移出默认 collection
