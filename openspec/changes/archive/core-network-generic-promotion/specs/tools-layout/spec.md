---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: tools-layout
---

# Spec delta — tools-layout

本 delta 新增 `tools/runs/` capability — run metadata workflow + 跨机 sync。详 `../../proposal.md` + `../../design.md` 第 4 节。

## ADD

### A1. `tools/runs/` 子目录结构

> **T1. tools/runs/ layout**:Run metadata workflow tools SHALL live in
> `tools/runs/`:
>
> ```
> tools/runs/
> ├── __init__.py
> ├── schema.py       Run metadata TOML schema(dataclass + validator)
> ├── register.py     tools.runs.register CLI
> ├── complete.py     tools.runs.complete CLI
> ├── list.py         tools.runs.list CLI
> ├── show.py         tools.runs.show CLI
> ├── sync.py         tools.runs.sync pull/push rsync wrapper
> └── tests/
>     ├── test_register_smoke.py
>     ├── test_complete_smoke.py
>     ├── test_list_smoke.py
>     ├── test_show_smoke.py
>     └── test_sync_smoke.py
> ```

### A2. Run metadata source-of-truth invariant

> **T2. Run metadata SoT**:Run metadata SHALL live in
> `artifacts/runs/<run_id>.toml`(gitignored,与 ckpt / replays 同
> lifecycle)。SHALL NOT 进 git tracking。SHALL NOT 维护并行
> markdown registry — `tools.runs.list` CLI 取代 `registry.md`。

### A3. Run lifecycle CLI 强制

> **T3. CLI enforced workflow**:Run metadata file SHALL only be created /
> updated by `tools.runs.{register,complete}` CLI,SHALL NOT 人手直接
> 编辑 `artifacts/runs/<id>.toml`(虽然 gitignored 不会被 review,但
> schema drift 会让 list / sync 失败)。
>
> - `tools.runs.register --run-id <id> --cfg <path>` 创建 status=pending
>   record,自动注入 `git_commit` + `host` + `cfg_checksum`
> - `tools.runs.complete --run-id <id> --status <done|failed|killed>
>   [--gauntlet-json <p>] [--wall <s>]` 更新 result + status

### A4. 跨机 sync 协议

> **T4. Cross-machine sync via rsync wrapper**:`tools.runs.sync` SHALL
> wrap rsync with hardcoded include / exclude:
>
> - `--include artifacts/runs/` `--exclude *`(只同步 metadata)
> - **SHALL NOT** 同步 `artifacts/checkpoints/` 或 `artifacts/replays/`
> - `--update`(只覆盖 newer file)防 timestamp 倒推
>
> CLI:
> ```bash
> tools.runs.sync pull <user>@<host>:<remote_repo_root>/
> tools.runs.sync push <user>@<host>:<remote_repo_root>/
> ```

### A5. Run metadata TOML schema

> **T5. Run metadata schema**:`artifacts/runs/<run_id>.toml` SHALL
> conform to schema defined in `tools/runs/schema.py`:
>
> ```toml
> run_id        = "<str, matches r|s + NNN>"
> label         = "<str, slug>"
> type          = "r" | "s"
> timestamp     = "<iso8601>"
> paradigm      = "az" | "bc" | "cfr" | "dmc" | "ppo"
> cfg_file      = "<path relative to repo root>"
> cfg_checksum  = "sha256:<hex>"
> git_commit    = "<full hash>"
> host          = "<uname -n>"
> status        = "pending" | "running" | "done" | "failed" | "killed"
>
> [summary]
> wall          = "<str, e.g. '16.3min'>"
> description   = "<str>"
>
> [result.gauntlet]              # optional, populated by complete
> n             = <int>
> # arbitrary metric_name = <float> pairs
>
> [result.training]              # optional
> final_loss        = <float>
> n_games_completed = <int>
>
> [notes]
> text          = "<str>"
> ```

## MODIFY

### M1. `.gitignore` 增 `artifacts/runs/`

若现 `.gitignore` 不含 `artifacts/runs/`(目前 `artifacts/` 整目录 ignore,新子目录自动包含)SHALL verify。若 `.gitignore` 有反向 include rule 漏 `artifacts/runs/`,SHALL 加显式 ignore。

### M2. `docs/4_runs/registry.md` 删除

旧人手维护 markdown registry SHALL be deleted(git rm)。历史 11 行 r001-r012 一次性 dump 到 `docs/5_history/runs_pre_redesign_2026_05_17.md`(per `../../design.md` Migrations 节)。

## REMOVE

### R1. `docs/4_runs/registry.md` 进 git 的现状

`tools-layout/spec.md` 若引用 `docs/4_runs/registry.md` 作 git tracked run history,SHALL 全部改为 `tools.runs.list` CLI + `artifacts/runs/<id>.toml`(gitignored)。

## Cross-references

- `../../proposal.md` — registry 升级动机
- `../../design.md` 第 4 节 — `tools/runs/` 详细形态 + sync 协议
- `../../tasks.md` Phase 5 — `tools/runs/` 实施
- 现有 `tools/_meta/check_openspec_indices.py` — 同形态 pre-commit hook 工具(本 change 不新增 hook,只新增 CLI 工具)
