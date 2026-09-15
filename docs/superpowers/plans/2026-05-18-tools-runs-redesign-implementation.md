# tools/runs/ Clean-Slate Redesign — Implementation Plan

**Status:** Draft (writing-plans, 2026-05-18)
**Spec:** `docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md` (主卷)
+ `docs/superpowers/specs/2026-05-18-tools-runs-redesign-design-rollout.md` (续卷)

---

## Header

**Goal**: 用 single-command atomic lifecycle 替代 `register/train/complete` 三步分离,消除多 feature 协调下的 emergent bug;每 run 完全 self-contained;helpers 公共 API 复用;Phase 1+2 同 PR 不可拆。

**Architecture(spec §Architecture 摘要)**:
1. `tools.runs.train` 是唯一入口:8-step lifecycle (validate label / capture leaf bytes / resolve cfg / mkdir artifacts / flock-allocate NNN / write cfgs / write metadata=running / run train / lock+compare+overwrite metadata)
2. Per-run dir `artifacts/<YYYYMMDDHHMM>_<NNNNNN>_<run_label>/` 自含 metadata + cfg_resolved + cfg_leaf + ckpts/ + metrics + tb/
3. 状态机 strict transitions `{running, done, failed, killed, unknown}`;resume 是唯一显式例外允许 `{done|failed|killed|unknown} → running`

**Tech stack**: Python 3.14 + `tomllib`/`tomli_w` + `fcntl.flock` (Linux/macOS) / `msvcrt.locking` (Windows) + pytest (`-n 4`, `xdist`-safe per-test tmp) + 现有 `training/core/{pipeline,checkpoint,gauntlet}` paradigm dispatch infrastructure。

---

## File structure

| 路径 | 操作 | 责任 |
|---|---|---|
| `tools/runs/train.py` | **Create** | 主入口 atomic lifecycle wrapper + paradigm dispatch (内迁 `tools/run.py` ~200-400 LOC) |
| `tools/runs/mark.py` | **Create** | 手动 status 转 done/failed/killed(终态收尾)|
| `tools/runs/recover.py` | **Create** | metadata 缺失时从 cfg + ckpts 重建 |
| `tools/runs/helpers.py` | **Create** | 7 个 Public API helper(allocate_nnn / acquire_metadata_lock / write_metadata_atomic / resolve_nnn_to_dir / normalize_repo_relative / cfg_checksum / extract_meta_field) |
| `tools/runs/schema.py` | **Modify** | 11 字段(含 `cfg_resolved_version`);status enum 加 `unknown`;strict transitions hard-code |
| `tools/runs/list.py` | **Modify** | 扫 `artifacts/*/metadata.toml`;`--status` / `--paradigm` flag + default sort desc;malformed skip + warn |
| `tools/runs/show.py` | **Modify** | shorthand NNN zero-pad 6 位;列 cfg_resolved_v1..vN 全系列;malformed raise |
| `tools/runs/sync.py` | **Modify** | timestamp 字段比对(非 mtime);case-collide detection;IPv6 bracket regex;`init-authoritative` 子命令;include pattern 改 |
| `tools/runs/register.py` | **Delete** | 功能并入 `train.py` |
| `tools/runs/complete.py` | **Delete** | 功能并入 `train.py` + `mark.py` |
| `tools/run.py` | **Delete** | 功能完全并入 `tools/runs/train.py`(CRIT-X-1,no shim)|
| `training/core/checkpoint.py` | **Modify** | ckpt 路径改 `<artifacts_dir>/ckpts/ckpt_<step>.pt` |
| `training/core/gauntlet.py` | **Modify** | gauntlet ckpt 改 `<artifacts_dir>/ckpts/gauntlet_g<NNNN>.pt` prefix |
| `CLAUDE.md` | **Modify** | Artifacts 段重写,移除 `runs.register`/`runs.complete` 速查 |
| `tools/runs/tests/test_*` | **Create** | Test 矩阵新文件(Phase 1+2/3/5 内每 task 列出) |

---

## Public API helper 表(reference,spec §Public API helper 表)

| Helper | 签名 | 用途 |
|---|---|---|
| `normalize_repo_relative` | `(path, repo_root, label) -> str` | repo-relative + forward-slash posix |
| `cfg_checksum` | `(cfg_path) -> str` | audit only,no drift guard |
| `extract_meta_field` | `(cfg_path, field) -> str \| None` | 纯本地读 `cfg.meta.<field>`,无 extends resolve |
| `allocate_nnn` | `(repo_root) -> int` | flock + glob + retry,返新 NNN |
| `acquire_metadata_lock` | `(artifacts_dir) -> ContextManager` | per-run flock `<artifacts_dir>/.metadata_lock` |
| `write_metadata_atomic` | `(artifacts_dir, metadata) -> None` | 同 dir temp + rename + 内部锁 |
| `resolve_nnn_to_dir` | `(repo_root, nnn) -> Path` | shorthand → 严格 6 位 match;0/≥2 raise |

train/mark/sync/list/show/recover **必须复用**,禁止 inline 复制实现。

---

## Phase 1+2(同 PR,不可拆)

Phase 1 = schema + dir 结构;Phase 2 = lifecycle + helpers + paradigm dispatch 迁移 + list/show。**15 tasks,~700-900 LOC**。

### T-01: schema.py 重写
- **Files**: Modify `tools/runs/schema.py`;Test `tools/runs/tests/test_schema.py` (new)
- **Goal**: 11 字段定义 + status enum 含 `unknown` + strict transitions table
- **Spec ref**: §Schema metadata.toml 字段 / §Status 状态机 / CRIT-2-A resume 例外
- **TDD**: 写 11 字段 dataclass + status enum + `validate_transition(old, new, *, resume=False) -> None` raise `InvalidTransition`;test `done → running` 仅 `resume=True` 允许
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_schema.py -v`
- **依赖**: 无

### T-02: helpers.py — normalize_repo_relative + cfg_checksum + extract_meta_field
- **Files**: Create `tools/runs/helpers.py`;Test `tools/runs/tests/test_helpers_basic.py`
- **Goal**: 3 个无锁 helper(纯 path / IO,无 concurrency 关注)
- **Spec ref**: §Public API helper 表 R1-R3 / HIGH-5-A
- **TDD**: Windows-form `configs\\dmc\\x.toml` → `.as_posix()` forward-slash;`extract_meta_field` 不解析 extends,直接读 leaf toml
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_helpers_basic.py -v`
- **依赖**: T-01

### T-03: helpers.py — allocate_nnn(flock allocator)
- **Files**: Modify `tools/runs/helpers.py`;Test `tools/runs/tests/test_helpers_allocator.py`
- **Goal**: `fcntl.flock(LOCK_EX | LOCK_NB)` + 10 次 retry backoff (0-50ms);Windows `msvcrt.locking` 分支
- **Spec ref**: §Atomic allocator / CRIT-4-A flock kernel-tracked
- **TDD**: 2 thread parallel `allocate_nnn` → 2 不同 NNN;retry timeout raise `'unable to acquire run-id lock'`;单线程序列分配单调递增
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_helpers_allocator.py -v`
- **依赖**: T-02

### T-04: helpers.py — acquire_metadata_lock + write_metadata_atomic
- **Files**: Modify `tools/runs/helpers.py`;Test `tools/runs/tests/test_helpers_metadata_write.py`
- **Goal**: per-run flock context manager + 同 dir temp file + atomic rename;两 writer 串行化
- **Spec ref**: §Atomic metadata 写 / CRIT-2-B / CRIT-3-A / HIGH-5-B 同 dir 约束
- **TDD**: 2 thread 同时 write → 串行;temp file 路径 assert 与 target 同 dir;禁止 `tempfile.NamedTemporaryFile()` 默认参数(grep 测)
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_helpers_metadata_write.py -v`
- **依赖**: T-01, T-02

### T-05: helpers.py — resolve_nnn_to_dir
- **Files**: Modify `tools/runs/helpers.py`;Test `tools/runs/tests/test_helpers_resolve_nnn.py`
- **Goal**: shorthand `69` / `069` / `000069` 全 zero-pad 6 位严格 match;0 / ≥2 raise
- **Spec ref**: §CLI show 细则 HIGH-1-C / §CLI mark 细则 HIGH-6-A
- **TDD**: fixture 2 dir 含同 NNN → raise + 列候选;0 match raise `'NNN not found'`;`69` ↔ `000069` 等价
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_helpers_resolve_nnn.py -v`
- **依赖**: T-02

### T-06: training/core/checkpoint.py — ckpts/ 子目录改造
- **Files**: Modify `training/core/checkpoint.py`;Test `training/tests/test_checkpoint_path.py`
- **Goal**: train ckpt 路径改 `<artifacts_dir>/ckpts/ckpt_<step>.pt`;`latest.pt` 也进 `ckpts/`
- **Spec ref**: §Per-run dir 结构 / H-7 ckpts 含所有 .pt
- **TDD**: `save_ckpt(artifacts_dir, step=30)` → 文件在 `<artifacts_dir>/ckpts/ckpt_30.pt`;`latest.pt` 在 `<artifacts_dir>/ckpts/latest.pt`
- **Verify**: `.venv/bin/python -m pytest training/tests/test_checkpoint_path.py -v`
- **依赖**: 无

### T-07: training/core/gauntlet.py — gauntlet_g<NNNN>.pt prefix
- **Files**: Modify `training/core/gauntlet.py`;Test `training/tests/test_gauntlet_path.py`
- **Goal**: gauntlet ckpt 改 `<artifacts_dir>/ckpts/gauntlet_g<NNNN>.pt`(4 位 g number)
- **Spec ref**: §ckpts 内 naming convention / HIGH-X-1
- **TDD**: fixture trigger gauntlet save → 路径 prefix `gauntlet_g0001.pt`;grep 无残留旧 pattern
- **Verify**: `.venv/bin/python -m pytest training/tests/test_gauntlet_path.py -v`
- **依赖**: T-06

### T-08: train.py — Phase A (steps 0-3 setup + allocator)
- **Files**: Create `tools/runs/train.py`;Test `tools/runs/tests/test_train_setup.py`
- **Goal**: lifecycle step 0-3 — run_label regex 校验 + leaf bytes capture + resolve cfg + artifacts.mkdir + flock-allocate NNN + mkdir per-run dir;失败 cleanup
- **Spec ref**: §Architecture step 0-3 / CRIT-1-A / CRIT-1-B / HIGH-2-A / HIGH-2-B / HIGH-1-A `<label>` 来自 resolved cfg / HIGH-X-3 UTC ts
- **TDD**: invalid `run_label`(含 `../`) → exit 2 + raise;mkdir fail 模拟 → orphan dir rollback (rmtree);`--override meta.run_label=X` 改 dir 名;UTC ts 与 metadata.timestamp 同源
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_train_setup.py -v`
- **依赖**: T-01, T-02, T-03

### T-09: train.py — Phase B (steps 4-5 cfg + metadata write)
- **Files**: Modify `tools/runs/train.py`;Test `tools/runs/tests/test_train_cfg_metadata.py`
- **Goal**: 写 `cfg_leaf.toml` (from step 1 bytes) + `cfg_resolved.toml`;写 metadata.toml status='running'(用 `write_metadata_atomic`);失败 cleanup
- **Spec ref**: §Architecture step 4-5 / HIGH-2-B orphan dir rollback
- **TDD**: 模拟 cfg_resolved write 失败 → dir rmtree + exit 2;cfg 无 extends 时 cfg_leaf 与 cfg_resolved 同内容(各写一份);metadata.status='running' + 11 字段全
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_train_cfg_metadata.py -v`
- **依赖**: T-04, T-08

### T-10: train.py — Phase C (steps 6-7 run + lock/compare/close metadata)
- **Files**: Modify `tools/runs/train.py`;Test `tools/runs/tests/test_train_close.py`
- **Goal**: 调 paradigm pipeline (placeholder OK 此 task);step 7 acquire metadata_lock + read status + compare → 若非 'running' 保留 + warn,否则写 status=done/failed + wall_seconds + exit_code
- **Spec ref**: §Architecture step 6-7 / read-and-compare-before-write / Exit codes 0/1/2/3
- **TDD**: train succeed → status='done' exit 0;mid raise → status='failed' exit 1;外部 mark 模拟 → 不覆盖 + warn `'metadata externally marked, train output discarded'`;final write fail → exit 3 + status='running' 保留
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_train_close.py -v`
- **依赖**: T-09

### T-11: train.py — paradigm dispatch 迁移 (from tools/run.py)
- **Files**: Modify `tools/runs/train.py`;Read `tools/run.py` 全;Test `tools/runs/tests/test_train_dispatch_smoke.py`
- **Goal**: 内迁 `load_cfg` → resolve paradigm → 5 paradigm registry → `run_pipeline` 完整逻辑,no thin shim;~200-400 LOC
- **Spec ref**: §Architecture CRIT-X-1 方案 A / Phase 1+2 同 PR / L-1 删 `tools/run.py`
- **TDD**: 5 paradigm parametrize 各起最小 cfg train 跑到 status='done'(az/bc/cfr/dmc/ppo);paradigm 由 `cfg.meta.paradigm` 派生
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_train_dispatch_smoke.py -v -n 1`(paradigm dispatch 启子进程,n=1 防 oversub)
- **依赖**: T-10

### T-12: train.py — resume 路径 (step 1.5 + status exception + cfg_resolved_v<N>)
- **Files**: Modify `tools/runs/train.py`;Test `tools/runs/tests/test_train_resume.py`
- **Goal**: `--resume <ckpt>` 推断 artifacts_dir (`.parent.parent`);校验 leaf cfg 存在;走 allocator lock 分配 cfg_resolved_v<N>;状态机 exception `{done|failed|killed|unknown} → running`;wall_seconds 覆盖语义
- **Spec ref**: §Resume / C-2 / C-3 / CRIT-2-A / CRIT-6-A / HIGH-2-C / HIGH-3-A / H-3
- **TDD**: `train` → `train --resume <ckpt> <cfg>` → metadata.run_id 不变,cfg_resolved_v2.toml + cfg_leaf_v2.toml 同步出现;resume 缺 cfg → exit 2 + `'leaf cfg 缺失...'`;`status='running' already` warn + no-op + 继续;done 状态 resume 转回 running
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_train_resume.py -v -n 1`
- **依赖**: T-11

### T-13: train.py — authoritative host enforcement
- **Files**: Modify `tools/runs/train.py`;Test `tools/runs/tests/test_train_authoritative.py`
- **Goal**: step 0 后 step 1 前读 `artifacts/.authoritative_host`;若内容 ≠ `socket.gethostname()` raise `'this host is pull-only ...'`;不存在则允许
- **Spec ref**: §Cross-host sync HIGH-2-D / `init-authoritative` 子命令(T-19 处理 sync 子命令本体)
- **TDD**: fixture 写 `.authoritative_host` 含 'other-host' → train raise + exit 2;不存在 → allowed;hostname 一致 → allowed
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_train_authoritative.py -v`
- **依赖**: T-08

### T-14: list.py 重写
- **Files**: Modify `tools/runs/list.py`;Test `tools/runs/tests/test_list.py`
- **Goal**: 扫 `artifacts/*/metadata.toml`(非旧 `artifacts/runs/`);`--status` / `--paradigm` flag + default sort `timestamp desc`;malformed skip + stderr warn
- **Spec ref**: §CLI list 细则 HIGH-1-B / §错误处理 HIGH-4-A / paradigm 派生自 cfg_resolved.meta.paradigm (M-5)
- **TDD**: fixture 3 run (running/done/failed) + 1 malformed → 默认列 4 个;`--status done` 仅 1 个;malformed stderr `'skipping ... malformed metadata'`;sort desc 验证
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_list.py -v`
- **依赖**: T-01

### T-15: show.py 重写
- **Files**: Modify `tools/runs/show.py`;Test `tools/runs/tests/test_show.py`
- **Goal**: shorthand NNN 6 位 zero-pad;复用 `resolve_nnn_to_dir`;输出 metadata 全 + cfg_resolved_v1..vN 全系列(标 "N = current");malformed raise
- **Spec ref**: §CLI show 细则 HIGH-1-C / CRIT-6-A cfg_resolved 全列
- **TDD**: `show 69` ↔ `show 000069` 等价;multi-version cfg_resolved 全列 + 标 current;malformed metadata raise(不 skip)
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_show.py -v`
- **依赖**: T-05, T-14(共享 fixture)

**Phase 1+2 ship 时单 PR**:per `git commit -F <message-file>`(HEREDOC banned);commit footer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`;`git add` 仅 explicit file(无 `-A`);commit 前 user 显式确认。

---

## Phase 3(mark / recover / sync 改造)

Phase 1+2 ship 之后独立 PR。**5 tasks**。

### T-16: mark.py 新建
- **Files**: Create `tools/runs/mark.py`;Test `tools/runs/tests/test_mark.py`
- **Goal**: `mark <NNN> --status {done|failed|killed} [--notes ...]`;走 `resolve_nnn_to_dir` + `acquire_metadata_lock` + `write_metadata_atomic`;TOML escape notes(raw newline / control char 自动 escape);transition `{running, unknown} → 终态` 否则 raise
- **Spec ref**: §CLI mark 细则 HIGH-1-D / HIGH-6-A / §状态机 strict transitions
- **TDD**: notes 含 `\n` → escape 后写入 不破坏 toml 结构;done mark 一次再 mark raise(终态不可转);0 / ≥2 match NNN 各自 raise
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_mark.py -v`
- **依赖**: T-01, T-04, T-05

### T-17: recover.py 新建
- **Files**: Create `tools/runs/recover.py`;Test `tools/runs/tests/test_recover.py`
- **Goal**: `recover <dir>` 从 `cfg_leaf*.toml` + `cfg_resolved*.toml` + `ckpts/` 重建 metadata.toml,status='unknown';走 `write_metadata_atomic`
- **Spec ref**: §CLI recover 细则 HIGH-4-C / §状态机 unknown 仅 recover 可写
- **TDD**: fixture dir 含 cfg + ckpts/ 但删 metadata.toml → recover 后 status='unknown';list 立即可见;`mark --status killed --notes 'recovered'` 转走;recover 已有 metadata 的 dir → raise(不覆盖)
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_recover.py -v`
- **依赖**: T-01, T-04

### T-18: sync.py — timestamp 字段比对 + include pattern
- **Files**: Modify `tools/runs/sync.py`;Test `tools/runs/tests/test_sync_pattern.py`
- **Goal**: rsync include 改新 layout(`artifacts/*/metadata.toml` + `cfg_resolved*.toml` + `cfg_leaf*.toml`,exclude `.authoritative_host` / `.run_id_lock` / `.metadata_lock` / `ckpts/` / `metrics.jsonl` / `tb/`);conflict 用 `metadata.timestamp` 字段比对,mtime 忽略
- **Spec ref**: §Cross-host sync include/exclude / HIGH-2-E timestamp 比对
- **TDD**: build rsync command line 含期望 `--include` / `--exclude`;mock 比对 — local newer 覆盖,remote newer skip + warn,完全等 raise + 列冲突
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_sync_pattern.py -v`
- **依赖**: T-01

### T-19: sync.py — init-authoritative + IPv6 regex + case-collide detection
- **Files**: Modify `tools/runs/sync.py`;Test `tools/runs/tests/test_sync_authoritative.py`, `test_sync_ipv6.py`, `test_sync_case_collide.py`
- **Goal**: `sync init-authoritative` 写 `artifacts/.authoritative_host` = `socket.gethostname()`;remote regex 加 `\[[0-9a-fA-F:]+\]` alternative;sync 前 lowercase dir name list 扫 collision,有则 raise
- **Spec ref**: HIGH-2-D init-authoritative / I16 HIGH-6-B IPv6 强制 / CRIT-5-A case-collide
- **TDD**: `init-authoritative` 后文件存在 + 内容 = hostname;`user@[::1]:/p` / `user@[fe80::1]:/p` regex match pass;`user@:/p` malformed reject;fixture `A/` 和 `a/` 模拟跨 OS → raise + 列对
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_sync_authoritative.py tools/runs/tests/test_sync_ipv6.py tools/runs/tests/test_sync_case_collide.py -v`
- **依赖**: T-18

### T-20: sync.py — local-to-local + ssh integration tests
- **Files**: Create `tools/runs/tests/test_sync_integration.py`(marker `@pytest.mark.integration`)
- **Goal**: local-to-local rsync 真实跑;ssh-localhost 跑(需 sshd,skip if missing)
- **Spec ref**: §测试矩阵 Sync tests
- **TDD**: 2 个 tmp dir 互 sync → metadata + cfg_*.toml 传,ckpts/ + metrics.jsonl 不传;`.authoritative_host` 不传
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_sync_integration.py -v -m integration`
- **依赖**: T-18, T-19

---

## Phase 4(删除 legacy entry points)

可独立 PR(Phase 3 ship 之后)。**3 tasks**。

### T-21: 删 `tools/runs/register.py`
- **Files**: Delete `tools/runs/register.py`;grep `from tools.runs.register import` / `tools.runs.register` 全 repo 改 import 或删 reference
- **Goal**: 功能已并入 `train.py`(分配 NNN 走 `helpers.allocate_nnn`)
- **Spec ref**: §File structure Delete / L-1 no shim
- **TDD**: grep `tools.runs.register` 整 repo 0 hit(除 `docs/5_history/` + `.claude/`);guard test rglob 排除 `.claude/`(per memory feedback_guard_test_rglob_exclude_claude)
- **Verify**: `git grep 'tools\.runs\.register' -- ':!docs/5_history/**' ':!.claude/**'` empty;`.venv/bin/python -m pytest tools/runs/tests/ -v`
- **依赖**: T-08, T-11

### T-22: 删 `tools/runs/complete.py`
- **Files**: Delete `tools/runs/complete.py`;grep `tools.runs.complete` 全 repo
- **Goal**: 功能并入 `train.py`(自动 status close)+ `mark.py`(手动收尾)
- **Spec ref**: §File structure Delete / L-1
- **TDD**: grep `tools.runs.complete` 0 hit(除 `docs/5_history/` + `.claude/`)
- **Verify**: `git grep 'tools\.runs\.complete' -- ':!docs/5_history/**' ':!.claude/**'` empty
- **依赖**: T-10, T-16

### T-23: 删 `tools/run.py`
- **Files**: Delete `tools/run.py`;grep `tools.run` / `python -m tools.run` 全 repo + smoke_full + CLAUDE.md + `docs/`
- **Goal**: `tools.runs.train` 完全替代,no shim
- **Spec ref**: §File structure Delete / CRIT-X-1 / L-1
- **TDD**: grep `python -m tools\.run\b` 0 hit(除 `tools.runs.*`);CLAUDE.md 引用全改 `tools.runs.train`
- **Verify**: `git grep -E 'python -m tools\.run( |$)' -- ':!docs/5_history/**' ':!.claude/**'` empty;`.venv/bin/python -m pytest training/tests/test_*_smoke.py -v -m smoke`(防 smoke 引用断)
- **依赖**: T-11, T-21, T-22

---

## Phase 5(CLAUDE.md + smoke_full + 全测验证)

**5 tasks**。

### T-24: CLAUDE.md Artifacts 段重写
- **Files**: Modify `/Users/redcontritio/Projects/gicg_mono/CLAUDE.md`(Artifacts + Running Python scripts + Run registry 速查)
- **Goal**: 速查改 `tools.runs.train` 主入口;移除 `tools.runs.register` / `tools.runs.complete`;加 `tools.runs.mark` / `tools.runs.recover` / `tools.runs.sync init-authoritative`;dir 命名改 `<ts>_<NNNNNN>_<label>` + ckpts/ 子目录
- **Spec ref**: §迁移策略 CLAUDE.md 更新 / §File structure Modify
- **TDD**: 无 unit test;grep 无残留 `tools.runs.register` / `tools.runs.complete` / `tools/run.py`
- **Verify**: `git grep -E 'tools\.runs\.(register|complete)|tools/run\.py' CLAUDE.md` empty;CLAUDE.md size hook (`tools._meta.check_line_limits`) pass
- **依赖**: T-23

### T-25: smoke_full template 改造
- **Files**: Modify `training/tests/test_*_smoke_full.py`(5 paradigm files);grep `tools.run` / `artifacts/<ts>_<label>` pattern;改 ckpt 期望路径
- **Goal**: 5 paradigm smoke_full 全走 `tools.runs.train`;ckpt 期望路径加 `ckpts/` 中间段;resume verify 走 `--resume <new path>`
- **Spec ref**: §迁移策略 / §Per-run dir / Phase 5 全测验证
- **TDD**: dmc smoke_full PASS(已知 baseline);其他 4 paradigm 若 pre-existing skip 保留(per memory `project_smoke_full_discovered_bugs_2026_05_17`);ckpt 路径 assert 含 `ckpts/`
- **Verify**: `.venv/bin/python -m pytest training/tests/test_dmc_smoke_full.py -v`(DMC 必 PASS);其他 paradigm `.venv/bin/python -m pytest -m smoke_full training/tests/ -q`(skip 保留)
- **依赖**: T-23, T-24

### T-26: 并发测试(2 parallel train + lock 竞争)
- **Files**: Create `tools/runs/tests/test_concurrency.py`
- **Goal**: 2 subprocess parallel `tools.runs.train` → 2 不同 NNN + 2 个 artifacts dir;allocator lock 模拟竞争 → retry + 最终成功
- **Spec ref**: §测试矩阵 Concurrency tests / §Atomic allocator retry
- **TDD**: `subprocess.Popen` × 2 起 `tools.runs.train <minimal-cfg>` → 完成后 list 含 2 个新 NNN(连续 +1 / +2);手动持 flock 模拟 → 第 3 个 train retry 10 次后 raise
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_concurrency.py -v -n 1`
- **依赖**: T-11

### T-27: Windows path test
- **Files**: Create `tools/runs/tests/test_windows_path.py`
- **Goal**: `helpers.normalize_repo_relative` Windows-form `configs\\dmc\\x.toml` → forward-slash (`.as_posix()`)
- **Spec ref**: §测试矩阵 Windows path tests
- **TDD**: `normalize_repo_relative(Path('configs\\\\dmc\\\\x.toml'), repo_root, 'cfg')` → `'configs/dmc/x.toml'`;PosixPath / WindowsPath 跨平台覆盖
- **Verify**: `.venv/bin/python -m pytest tools/runs/tests/test_windows_path.py -v`
- **依赖**: T-02

### T-28: 全测 + line-limit hook + paradigm smoke 全跑
- **Files**: 无 modify(verification gate)
- **Goal**: 全 `tools/runs/tests/` PASS;全 smoke marker PASS;line-limit + openspec index hook pass
- **Spec ref**: §测试矩阵 全部
- **TDD**: 无新 test
- **Verify**:
  - `.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/ tools/runs/tests/ -q`
  - `.venv/bin/python -m pytest -m smoke training/tests/ -q`
  - `.venv/bin/python -m tools._meta.check_line_limits`
  - `.venv/bin/python -m tools._meta.check_openspec_indices`
- **依赖**: T-25, T-26, T-27

---

## Self-review

### Spec → Task 矩阵

| Spec section | Task IDs |
|---|---|
| §Motivation / Architecture 总论 | T-08, T-09, T-10, T-11(8-step lifecycle 完整)|
| §Architecture step 0 run_label regex (CRIT-1-B) | T-08 |
| §Architecture step 1 leaf bytes (H-6) | T-08, T-09 |
| §Architecture step 2 cfg resolve + extends immutable (HIGH-2-G) | T-08 |
| §Architecture step 2.5 artifacts.mkdir (HIGH-2-A) | T-08 |
| §Architecture step 3 allocator flock + retry (CRIT-1-A, CRIT-4-A) | T-03, T-08 |
| §Architecture step 4-5 cfg + metadata write + rollback (HIGH-2-B) | T-09 |
| §Architecture step 6-7 train + read-and-compare-and-write | T-10 |
| §Architecture step 7 exit codes 0/1/2/3 | T-10 |
| §Architecture dir 名 `<label>` 来自 resolved cfg (HIGH-1-A) | T-08 |
| §Architecture UTC ts (HIGH-X-3) | T-08 |
| §Architecture `tools.runs.train` = wrapper + paradigm dispatch (CRIT-X-1) | T-11 |
| §Per-run dir 自含 + ckpts/ 子目录 | T-06, T-07, T-09 |
| §CLI 接口 全表 | T-11 (train), T-14 (list), T-15 (show), T-16 (mark), T-17 (recover), T-18+T-19 (sync) |
| §CLI list 细则 (HIGH-1-B + HIGH-4-A) | T-14 |
| §CLI show 细则 (HIGH-1-C) | T-05, T-15 |
| §CLI mark 细则 (HIGH-1-D + HIGH-6-A) | T-05, T-16 |
| §CLI recover 细则 (HIGH-4-C) | T-17 |
| §Resume 1.5 cfg 存在校验 (HIGH-2-C) | T-12 |
| §Resume cfg_resolved_v<N> 版本化 (CRIT-6-A) | T-12 |
| §Resume allocator lock 守 N 分配 (HIGH-3-A) | T-12(复用 T-03 allocate_nnn) |
| §Resume 状态机例外 (CRIT-2-A) | T-01, T-12 |
| §Resume wall_seconds 语义 (H-3) | T-12 |
| §Cross-host sync 单源主从 (H-1) | T-13 (enforce), T-19 (init-authoritative) |
| §Cross-host sync timestamp 比对 (HIGH-2-E) | T-18 |
| §Cross-host sync IPv6 (HIGH-6-B / I16) | T-19 |
| §Cross-host sync case-collide (CRIT-5-A) | T-19 |
| §Cross-host sync include/exclude pattern | T-18 |
| §Schema 11 字段 + cfg_resolved_version | T-01, T-09, T-12 |
| §Schema 状态机 strict + unknown | T-01, T-16, T-17 |
| §无 ckpt dead running 路径 (HIGH-2-F) | T-16(mark killed + 新 NNN 重跑 doc 通过) |
| §Atomic allocator flock (CRIT-4-A) | T-03 |
| §Atomic per-run metadata_lock (CRIT-2-B / CRIT-3-A) | T-04 |
| §Atomic temp file 同 dir (HIGH-5-B) | T-04 |
| §错误处理 用户友好 message | T-08, T-12, T-16, T-19 |
| §错误处理 malformed metadata | T-14 (list skip), T-15 (show raise), T-16 (mark raise) |
| §Public API helper 表 (HIGH-5-A) | T-02, T-03, T-04, T-05 |
| §测试矩阵 Workflow | T-11 dispatch smoke + T-14 list + T-15 show + T-16 mark |
| §测试矩阵 Resume | T-12 |
| §测试矩阵 Override | T-08(override 改 dir 名）+ T-09（cfg_resolved 含 override）|
| §测试矩阵 Failure | T-08, T-09, T-10(exit 1/2/3) |
| §测试矩阵 Concurrency | T-26 |
| §测试矩阵 Sync (integration) | T-20 |
| §测试矩阵 Windows path | T-27 |
| §迁移策略 (no compat fallback) | T-21, T-22, T-23, T-24, T-25 |
| §File structure Create/Modify/Delete | 全 task 覆盖 |
| §ckpts/ naming convention | T-06, T-07 |
| §不在 scope | 不需 task |
| §Phase 拆分 (M-6 同 PR) | Phase 1+2 = T-01..T-15 同 PR;Phase 3 = T-16..T-20;Phase 4 = T-21..T-23;Phase 5 = T-24..T-28 |

### 检查清单

- 无 "TBD" / "implement later" / "similar to Task N" — 全 task 独立完整定义
- helper / state / 字段名 spec ↔ plan 一致(allocate_nnn / acquire_metadata_lock / write_metadata_atomic / resolve_nnn_to_dir / normalize_repo_relative / cfg_checksum / extract_meta_field;status enum `{running, done, failed, killed, unknown}`;11 字段含 cfg_resolved_version)
- 所有 Verify 命令用 `.venv/bin/python -m pytest`,无 `python -c`
- Commit message HEREDOC banned,改 `git commit -F <message-file>`;footer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`;`git add` 仅 explicit file
- 每次 commit 前 user 显式确认(per user policy "每次 commit 都需显式确认")
- Phase 1+2 同 PR 强制约束(M-6)在 Phase 拆分 + 矩阵 explicit
- guard test rglob exclude `.claude/`(per memory)在 T-21 / T-22 / T-23 grep verify 命令体现
- Concurrency / Windows path / Sync integration / smoke_full 全覆盖

### Ambiguity / 假设

- T-11 paradigm dispatch 迁移精确 LOC 未在 spec 量化,plan 取 spec §CRIT-X-1 上界 200-400;若实施超 400 LOC 需停下 report(per "范围扩张前先问")
- Phase 3 内部 task 顺序(T-16 / T-17 / T-18 / T-19 / T-20)无强依赖,可 parallel implementer dispatch(per memory feedback_parallel_first_workflow + worktree 隔离);plan 列序仅 reviewer 友好
- 测试 fixture 复用:T-14 / T-15 / T-16 / T-17 共享 `artifacts_fixture` builder(写 3 个 sample run dir);可在 T-14 时 create 入 conftest.py,后续 task 直接 import(实施细节不独立 task)

---

## 总规模与预期

- **task 数**: 28(T-01..T-28)
- **预期实施 LOC**:
  - Phase 1+2(T-01..T-15): ~700-900 LOC(paradigm dispatch 200-400 + helpers ~150 + schema ~100 + train ~250 + list/show ~150)
  - Phase 3(T-16..T-20): ~300-400 LOC
  - Phase 4(T-21..T-23): -300 LOC(删除)
  - Phase 5(T-24..T-28): ~50 LOC(测试 + doc)
- **预期 PR 数**: 4(Phase 1+2 / Phase 3 / Phase 4 / Phase 5,Phase 3 可拆 2 PR 若 mark / recover / sync 分头 implement)
- **总 commit 数**: ≥ task 数(每 task 至少一 commit,符合 "每个逻辑单元一个 commit")
