# tools/runs/ Second-Round Fixes Implementation Plan

> 分卷导航:本文档共 3 卷 · 续见 [Part 2](2026-05-18-tools-runs-second-round-fixes-part2.md) → [Part 3](2026-05-18-tools-runs-second-round-fixes-part3.md)

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
