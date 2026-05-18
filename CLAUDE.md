# CLAUDE.md

## Repo Layout

Monorepo root. Top-level trees:

- `data/` — DSL game data (characters, cards, system)
- `gicg_engine/` — Go engine + interpreter + c-shared binding
- `gicg_env/` — Python binding for the engine (ctypes wrapper + `GicgEnv` RL env class)
- `gicg_mcts/` — Go MCTS (L3; tree + PUCT + backup; uses `gicg_engine` directly)
- `training/` — RL training pipeline. Core + paradigm split:
  - `training/core/` — 算法无关(protocols / actor / network / buffer / inference / eval / matchup)
  - `training/paradigms/<name>/` — 5 paradigm adapters: az / ppo / cfr / dmc / bc, 各含 paradigm.py + collector.py + policy.py + loss.py + network.py + config.py 等
  - 5 paradigm 互不 import,均只 import core。细节见 `openspec/specs/training-architecture/` + `docs/2_decisions/adr-0006-training_layout.md`(history)。
- `tools/` — ad-hoc diagnostic / evaluation scripts (tournament, attention analysis)
- `docs/` — design docs, training log
- `artifacts/` — run outputs: `checkpoints/` (model weights) and `replays/` (game record YAML). Gitignored.

Dependency direction:
  `training/` → `gicg_env/` → `gicg_engine` (via libgicg.dylib); `tools/` → both.
  `gicg_mcts/` → `gicg_engine/` (Go-to-Go direct import). `training/` → `gicg_mcts` via cgo.

**All commands run from the repo root** — paths inside scripts (`artifacts/checkpoints/...`) assume this cwd.

## Build & Test

```bash
# Go engine
go test ./gicg_engine/tests/ -v -count=1
go build ./...
# Python c-shared library (output lives next to gicg_env/engine.py):
go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/
# Python tests (parallel, xdist-safe — per-test tmp sockets/dirs).
# n=4 is the sweet spot: tests spawn internal subprocesses, n>4 oversubscribes CPU.
.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/ -q
```

### Smoke test tiers (post `paradigm-smoke-full-tier` 2026-05-17)

Two smoke tiers — default `smoke` (≤ 60s/paradigm) + opt-in `smoke_full` (5-15min/paradigm,**not collected by default**)。

```bash
# Default smoke (collector → forward → backward → optimizer.step + eval probe + paradigm-specific invariant)
.venv/bin/python -m pytest -m smoke training/tests/ -q                   # all 5 paradigm,total ~5s wall

# Full smoke (real 100-step train + auto-save ckpt + resume verify via tools.runs.train driver e2e)
# Opt-in only — run before big release / cfg schema change / network architecture change
.venv/bin/python -m pytest -m smoke_full training/tests/ -q              # all 5 paradigm,total ~25-50min wall
.venv/bin/python -m pytest training/tests/test_dmc_smoke_full.py -v      # single paradigm probe

# Default `pytest` (no marker) excludes smoke_full via addopts -m "not smoke_full"
```

## Running Python scripts

**Always invoke Python code as modules from repo root** — never `python path/to/file.py`.
Python's `-m` mode sets `sys.path[0]` to cwd, so imports like `from gicg_env import ...` resolve without any `sys.path` hacks in the source files.

```bash
.venv/bin/python -m tools.runs.train <config.toml>                       # 主入口:atomic 全 lifecycle(allocate NNN + snapshot cfg + train + close metadata)
.venv/bin/python -m tools.send_matchup --help

# Run registry (post 2026-05-18 clean-slate redesign — per-run dir self-contained):
.venv/bin/python -m tools.runs.list                                              # 表格视图,扫 artifacts/*/metadata.toml
.venv/bin/python -m tools.runs.show <NNN>                                        # 详细 dump(NNN shorthand,1-6 位 zero-pad)
.venv/bin/python -m tools.runs.mark <NNN> --status done|failed|killed [--notes …] # running/unknown → 终态(外部死亡 / 救援收尾)
.venv/bin/python -m tools.runs.recover <dir>                                     # metadata 缺失救援:从 cfg + ckpts 重建(status='unknown')
.venv/bin/python -m tools.runs.sync push|pull <user@host:path/>                  # rsync metadata + cfg backup(NOT ckpts/)
.venv/bin/python -m tools.runs.sync init-authoritative                           # 写当前 hostname 到 artifacts/.authoritative_host(本 host 可 train)

# Ckpt inspection (self-describing schema):
.venv/bin/python -m tools.ckpt.info <path>.pt                            # paradigm/cfg/git_commit/state_dict 元数据
```

## Pre-commit hooks (enforced on staged files)

Enable once:

    git config core.hooksPath .githooks

Four checks per commit:

**1. Size limits** (fail if EITHER line OR byte threshold exceeded):

| Pattern                                            | Lines | Bytes |
|----------------------------------------------------|-------|-------|
| ``CLAUDE.md``                                      | 200   | 30 KB |
| ``docs/**/*.md``                                   | 500   | 50 KB |
| Python test files (``**/tests/`` or ``test_*.py``) | 500   | —     |
| Other Python / Go files                            | 300   | —     |

Full-repo audit: ``.venv/bin/python -m tools._meta.check_line_limits``.

**2. Python format** — ``ruff format --check`` on staged ``.py``. Config in ``pyproject.toml`` (line-length 120, single quotes). Fix with ``.venv/bin/ruff format .``.

**3. Go format** — ``gofmt -l`` on staged ``.go``. Fix with ``gofmt -w ./gicg_engine ./gicg_mcts``.

**4. OpenSpec index** — ``tools/_meta/check_openspec_indices.py --staged`` 校验 subtopic 索引完整性(R1+R2+R3)。Full-tree audit: ``.venv/bin/python -m tools._meta.check_openspec_indices``.

Bypass individual checks with ``SKIP_LINE_LIMIT_HOOK=1`` / ``SKIP_RUFF_HOOK=1`` / ``SKIP_GOFMT_HOOK=1`` / ``SKIP_OPENSPEC_INDEX_HOOK=1`` (sparingly — expected only for mass mechanical edits). Existing-file violators grandfathered; hook checks staged files only. Refactor opportunistically when touched — see backlog D7 for the violator list.

## Artifacts

Per-run dir 名 `artifacts/<YYYYMMDDHHMM>_<NNNNNN>_<cfg.meta.run_label>/`(UTC 分钟时间戳 + 6 位 zero-pad NNN + run_label slug)。dir self-contained:

```
artifacts/<ts>_<NNN>_<label>/
├── metadata.toml         # run-lifecycle 索引(11 字段)
├── cfg_resolved.toml     # 完整展开 cfg(post extends + --override),reproducibility truth
├── cfg_leaf.toml         # user 提供的 leaf cfg 拷贝(immutable snapshot)
├── ckpts/                # ckpts 单独子目录(ckpt_<step>.pt + latest.pt + gauntlet_g<NNNN>.pt)
├── metrics.jsonl
└── tb/                   # TB logs(可选)
```

例:`artifacts/202605180355_000069_dmc_smoke_full/`。

Workflow(单命令 atomic lifecycle):

```bash
# train 全 lifecycle 自闭环 — allocate NNN + mkdir + snapshot cfg + run + close metadata
.venv/bin/python -m tools.runs.train <cfg>

# resume(reuse 原 NNN,allocate cfg_resolved_v<N>;状态机 exception 转回 running)
.venv/bin/python -m tools.runs.train --resume <artifacts_dir>/ckpts/latest.pt <cfg>

# 外部死亡(SIGKILL / power loss)→ status 卡 'running' → user 手动收尾
.venv/bin/python -m tools.runs.mark <NNN> --status killed --notes 'OOM'

# metadata.toml 丢失救援:重建 status='unknown' + 后 mark 收尾
.venv/bin/python -m tools.runs.recover artifacts/<ts>_<NNN>_<label>/
```

Pre-redesign runs(r001-r012 + s001-s068,旧 `artifacts/runs/<id>.toml` 索引 + `<r|s><NNN>` 命名)live in `docs/5_history/runs_pre_redesign_2026_05_17.md`,不在 live index;clean-slate 后 NNN 6 位 zero-pad,无 r/s 前缀。

## Architecture

Three-layer: **DSL** (game data, Lua syntax subset) → **Go engine + interpreter** (generic executor) → **Python** (RL training).

DSL files live in `data/` and are loaded by the native Go interpreter in `gicg_engine/interp/` — there is no LuaJIT or cgo bridge.

### Engine Ignorance

Go engine knows: characters, hand, deck, round, turn.
Go engine does NOT know: HP, energy, elements, shields, freeze, AP.
All game mechanics = counter + hook in DSL.

### Core Model

- **Counter**: flat `[]Counter` array. Value/Init/Min/Max with auto-clamp.
- **Hook**: flat hook array. Dispatched by HookType, ordered by Priority (high first, default 0), then registration order.
- **No filter matching in Go.** DSL callbacks do their own filtering (early return on ctx fields).
- **Skill ID**: globally unique auto-increment. `ctx.skill_index` is sufficient to identify any skill.

Full DSL reference (counter scopes, damage pipeline, file isolation, skill-pattern / mirror-filter rules, `on_damage_reduce` shields, API list, Project Layout) → **[`docs/1_specs/engine/dsl/conventions.md`](docs/1_specs/engine/dsl/conventions.md)**.

## Documentation structure

> 新 session 第一站:**`openspec/project.md`(项目层 spec)+ `docs/0_status/README.md`(当前 phase)**,两者互补。
>
> 内容归属规则(详 `openspec/specs/openspec-policy/content-boundary.md`):
> - "系统现在是什么 / 必须是什么" → `openspec/`(SHALL / IS 句)
> - "我们发现 / 尝试 / 学到了什么" → `docs/`(实验 / 复盘 / 历史)

**OpenSpec(规约 + 变更工作流)**:

- 项目层 spec → `openspec/project.md`
- 活的能力规约 → `openspec/specs/<capability>/spec.md`(+ subtopic .md)
- Active change(proposal + design + tasks) → `openspec/changes/<id>/`
- 历史 change(已 archive) → `openspec/changes/archive/<id>/`
- OpenSpec 自身规约 → `openspec/specs/openspec-policy/`
- Slash commands → `/opsx:{propose,apply,archive,explore}`(随 `.claude/commands/opsx/` 携带)

**docs/(实验 / 复盘)** — P1 阶段大部分内容会逐步走 OpenSpec change 迁移,过渡期保留旧结构:

- 现在做什么 / 上里程碑 / 下决策点 → `docs/0_status/README.md`
- 当前 shipped 代码状态 → `docs/1_specs/` (engine / env / network / search / training / eval)(P1 后逐步迁 `openspec/specs/`)
- 决策日志 (ADR) → `docs/2_decisions/` (adr-NNNN-*.md)(P1 后新 ADR 走 OpenSpec change;旧 ADR 迁 `docs/history/adr/`)
- 计划与 roadmap → `docs/3_plans/` (curriculum / az / backlog / acceptance)
- 训练 run lifecycle → `tools.runs.train / list / show / mark / recover / sync` CLI(`tools/runs/`,metadata 落 `artifacts/<ts>_<NNN>_<label>/metadata.toml` per-run self-contained);pre-redesign 历史 → `docs/5_history/runs_pre_redesign_2026_05_17.md`
- 历史复盘 / review / audit / ablation / 已废 epoch → `docs/5_history/`(留 docs)

**其他**:

- 跨项目通用工作风格 → `~/.claude/CLAUDE.md`
- 项目特定约定(本文件)→ `CLAUDE.md`
- 临时计划 → `Plan`/`Task` 工具,不落盘

## Debug 工作流

- **Retry → subagent 审查规则**：同一个错误在**重试一次之后仍未解决**，必须调 subagent（`general-purpose` 或 `Plan`）做第三视角 review。subagent 输入要包含：(a) 错误现象/测试输出，(b) 相关代码片段与行号，(c) 已尝试的修法与为什么失败。subagent 的作用是打破单一思路 — 我方只在问题表层打转时，独立 reviewer 更容易发现隐藏前提或代数不一致。典型触发：测试挂 2 次仍失败、修复 commit 后 regression、理论推导"对了但现象不对"。
