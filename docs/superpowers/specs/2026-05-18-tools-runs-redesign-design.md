# tools/runs/ Clean-Slate Redesign Design

**Status:** Approved (brainstorming complete 2026-05-18)
**Supersedes:** `feature/tools-runs-fixes` branch (5 rounds of incremental review + patches, did not converge)

---

## Motivation

5 轮 adversarial review 找到 30+ 缺陷,大部分是**多 feature 组合下的 emergent bug**:
- C2 (artifacts_dir link) × M5 (timestamp 单源) × M3 (auto-complete) → 3 阶段 lifecycle 协调 bug 多
- Phase 2 (`--cfg-run-label-override`) × Phase 3 (`tools.run --run-id`) → snapshot 与 train 永久不一致
- `--resume` × `--run-id` × `--override` → 组合从未在 plan 考虑
- `cfg_checksum` drift guard → 过严(blocks equivalence-preserving 编辑)/ 过松(checksum-only)

**根因**:lifecycle 拆 3 步(register / train / complete),协调点全是 bug 来源。每步独立 design 看不出问题,组合时 emergent。

**redesign 策略**:single-command atomic lifecycle + cfg full snapshot inline + 极简 schema。从设计阶段消除整类协调 bug。

---

## Architecture

### 单命令 atomic lifecycle

废 `tools.runs.register` + `tools.runs.complete`,合并入新 `tools.runs.train`:

```
tools.runs.train [--resume <ckpt>] [--max-steps N] [--override k=v] <cfg>
  │
  ├── 1. resolve cfg(load extends + apply --override → merged dict)
  ├── 2. allocate next NNN via `O_EXCL` lock(并发安全)
  ├── 3. create artifacts dir + write cfg_resolved.toml + cfg_leaf.toml
  ├── 4. write metadata.toml(status='running')
  ├── 5. run train(catch all exceptions)
  ├── 6. update metadata.toml(status='done'/'failed' + wall_seconds + exit_code)
  └── 7. exit 0 (done) / nonzero (failed)
```

**Atomic 保证**:cfg / NNN / timestamp / artifacts_dir 在 step 1-4 一次性 capture,中间不允许其他工具介入修改。中间状态('running' metadata)只在 train 运行期间存在。

### Per-run 完全 self-contained

```
artifacts/<YYYYMMDDHHMM>_<NNNNNN>_<cfg.meta.run_label>/
├── metadata.toml         # run-lifecycle 索引
├── cfg_resolved.toml     # 完整展开 cfg(post extends + --override),reproducibility truth
├── cfg_leaf.toml         # user 提供的 leaf cfg 拷贝(immutable snapshot)。若 cfg 无 extends,cfg_resolved == cfg_leaf 内容相同,仍各写一份保持结构对称
├── ckpts/                # ckpts 单独子目录
│   ├── ckpt_30.pt
│   ├── ckpt_60.pt
│   └── latest.pt
├── metrics.jsonl
└── tb/                   # TB logs(可选)
```

例:`artifacts/202605180355_000069_dmc_smoke_full/`

- ❌ 删除 `artifacts/runs/<NNN>.toml` separate index 目录
- ✅ 每 run 一个目录,自包含 metadata + ckpt + cfg backup + logs
- ✅ ckpts 进 `ckpts/` 子目录,与 metadata + cfg 分层
- ✅ dir 名:`<ts>_<NNN>_<label>`,时间在前(ls chrono sort 友好),6 位 zero-pad NNN(scalability)

### CLI 接口

| 命令 | 作用 |
|---|---|
| `tools.runs.train [--resume <ckpt>] [--max-steps N] [--override k=v] <cfg>` | 主入口(atomic 全 lifecycle) |
| `tools.runs.list` | 表格视图扫所有 run |
| `tools.runs.show <NNN>` | 详细 dump(接受 shorthand "69" / "069" / "000069") |
| `tools.runs.sync push\|pull <user@host:path/>` | 跨机 sync metadata + cfg backup(NOT ckpts/) |
| `tools.runs.mark <NNN> --status killed [--notes ...]` | 罕见:外部 kill 后手动 fix status |

**移除**:`tools.runs.register`(被 train 吸收)、`tools.runs.complete`(被 train 自动闭环吸收)

### Resume 语义

`tools.runs.train --resume artifacts/<dir>/ckpts/ckpt_N.pt <cfg>`:
1. 从 ckpt 路径 parent 推断 artifacts_dir = `artifacts/<dir>/`
2. 读 `<dir>/metadata.toml`,找到 run_id
3. 继续写**同一**metadata,不分配新 NNN
4. status 改回 'running' → train → 'done'/'failed'

若 ckpt parent dir 没 metadata → error("resume 需要 registered run;not found")

---

## Schema

### metadata.toml 字段(11 个)

```toml
run_id = "000069"                           # 6 位 zero-pad
timestamp = "2026-05-18T03:55:21+00:00"     # UTC iso, train start
cfg_file = "configs/dmc/smoke_full.toml"    # repo-relative leaf path(human ref only;truth 在 cfg_resolved.toml)
git_commit = "2c20de8..."
host = "Mac-mini.local"
status = "done"                              # enum {running, done, failed, killed}
artifacts_dir = "artifacts/202605180355_000069_dmc_smoke_full"
wall_seconds = 84.3
exit_code = 0
paradigm = "dmc"
notes = ""                                   # free-form
```

### 移除字段(对比当前 schema)

- `type`(r/s 区分)— 单一 NNN 序列,不区分
- `label`(冗余 with run_id)
- `cfg_checksum`(替代:cfg_resolved.toml 是 truth)
- `cfg_run_label`(替代:cfg_resolved.toml 已含 meta.run_label)
- `summary`(flatten 为顶层 `wall_seconds`)
- `result.gauntlet` / `result.training`(放 artifacts dir 独立文件,不进 metadata)

### Status 状态机(strict)

```
[start]
  │
  ├── train 启动 → status='running'(metadata 写)
  │
  ├── train succeed → status='done' + exit_code=0
  ├── train raise → status='failed' + exit_code∈{1,2}
  └── 外部 SIGTERM/SIGKILL → metadata 留 'running'(死状态)
        │
        └── user: tools.runs.mark <NNN> --status killed [--notes ...]
```

Strict transitions(违反 raise):
- 'running' → 'done' / 'failed'(by train)
- 'running' / 'failed' / 'killed' → 'killed'(by mark,仅 user 显式)
- 'done' → 不允许任何转移(终态)

### Exit codes

| Code | 含义 |
|---|---|
| 0 | train done + metadata closed |
| 1 | train ran but failed mid-way(metadata=failed) |
| 2 | cfg / setup error(metadata=failed,train 未启动) |
| 3 | train done but auto-complete metadata 失败(metadata 可能 stale,需手动 mark) |

---

## Atomic + 并发安全

### run-id allocator

- 文件锁:open `artifacts/.run_id_lock`(`O_EXCL` create)
- 临界区:glob `artifacts/<ts>_<6digit>_*` 找 max NNN → max+1
- 若 lock 已存在:retry up to 10 次,每次 sleep random(0,50)ms
- 释放锁:删除 lock file

### metadata 写

- temp file + atomic rename:`metadata.toml.tmp` → `metadata.toml`
- 写中断不破坏现有 metadata

### Resume 并发

- resume 与 fresh train 不冲突(resume 不分配新 NNN,只更新已有 metadata)
- 两 resume 同一 run 同时进行:不防护,user 责任(应不会发生 — 一个 run 一个 train process)

---

## 错误处理 + 日志

### train 失败时

- run_pipeline raise → status='failed',exit_code=1 设置,metadata 关闭
- cfg 解析 / load_cfg raise → status='failed',exit_code=2(setup error,train 未启动)
- 任何 finally block 自身 raise → log stderr,**不替换 in-flight train exception**(round-4 finally try/except 教训)
- auto-complete fail → 标记 `auto_complete_failed=True`,exit 3(round-5 教训)

### 用户友好 error message

- run-id allocator 锁等待超时:`'unable to acquire run-id lock after 10 retries; check artifacts/.run_id_lock'`
- metadata 写失败:`'metadata.toml write failed: <reason>; run continued, manually mark via tools.runs.mark'`
- resume 找不到 metadata:`'resume needs registered run; <ckpt parent> contains no metadata.toml'`

---

## Cross-host sync

### 设计

`tools.runs.sync push|pull <user@host:path/>`:
- rsync 全量 `artifacts/*/metadata.toml` + `artifacts/*/cfg_*.toml`(metadata + cfg backup)
- **不传**:`artifacts/*/ckpts/`、`artifacts/*/metrics.jsonl`、`artifacts/*/tb/`(数据大,跨机不必要)
- `--update` mtime-tie:fail 而非 silent clobber(round-3 backlog I9 修复)
- Remote regex strict `user@host:path/`(round-3 已修)

### Include / exclude pattern

```python
RSYNC_FLAGS = (
    '-av',
    '--update',
    '--include=artifacts/',
    '--include=artifacts/*/',                    # 进入每 run 子目录
    '--include=artifacts/*/metadata.toml',       # metadata
    '--include=artifacts/*/cfg_resolved.toml',   # reproducibility backup
    '--include=artifacts/*/cfg_leaf.toml',       # leaf snapshot
    '--exclude=*',                                # 其他全部排除
)
```

---

## 测试矩阵

CI 必跑(全 PASS 才 merge):

### Workflow tests

- `train <cfg>` → assert artifacts dir 创建 + metadata.status='done' + ckpts/ 有内容
- `train + list` → assert 新 run 出现
- `train + show <NNN>` → assert 输出含 status / artifacts_dir / cfg_file
- `train + mark <NNN> --status killed` → assert 状态转移 + notes 写入

### Resume tests

- `train cfg` → `train --resume <ckpt> <cfg>` → assert metadata.run_id 不变,artifacts_dir 不变
- `train --resume <nonexistent-parent>` → assert error("resume needs registered run")

### Override tests

- `train --override paradigm.epsilon=0.1 <cfg>` → assert `cfg_resolved.toml` 含 override 值,`cfg_leaf.toml` 不含

### Failure tests

- `train <invalid-cfg>` → assert exit 2 + metadata.status='failed'
- `train <cfg>` 中途 RuntimeError → assert exit 1 + metadata.status='failed'
- `train` finally auto-complete fail → assert exit 3 + stderr warn

### Concurrency tests

- 2 parallel `train` → assert 2 不同 NNN 分配 + 2 个 artifacts dir
- run-id lock 模拟竞争 → assert retry + 最终成功

### Sync tests

- local-to-local rsync(`@pytest.mark.integration`)→ assert metadata + cfg_*.toml 传,ckpts/ 不传
- ssh-localhost rsync(`@pytest.mark.integration`,需 sshd)→ assert 同上

### Windows path tests

- Windows-form path `configs\\dmc\\x.toml` → `register.normalize_repo_relative` 返 forward-slash(`.as_posix()`)

---

## 迁移策略

per `feedback_no_compat_fallback`(用户决策 2026-05-05),不留兼容 fallback:

- 不自动迁移老 `artifacts/runs/<id>.toml` + `artifacts/<ts>_<label>/`
- 老 run 留原位(`artifacts/` 仍在),新 train 走新 dir 命名
- 新 `list` / `show` / `sync` 扫新位置(`artifacts/*/metadata.toml`)— 老 metadata 在 `artifacts/runs/`,**不被新 CLI 看到**(invisible,not error)。若需访问老 run:`cat artifacts/runs/<id>.toml` 手动查
- Migration script(optional backlog,以后做):batch convert 老格式 → 新格式
- CLAUDE.md 同步更新 Artifacts 段落

---

## 解决的已知 backlog 项(I9-I23)

| Backlog | 新设计如何 close |
|---|---|
| I9 sync 跨机重名 clobber | mtime-tie fail 不 clobber(同前修) |
| I10 sync nested dir support | dir 命名标准化,no nested concern |
| I11 complete 状态机 guard | strict transitions 直接 design 入 |
| I12 sync subdir silent zero | dir 自动 walk parents 找 repo root |
| I13 gauntlet `n` key collision | result 不进 metadata(放 gauntlet.json 独立文件) |
| I14 finally exception mask | already-fixed in round-4 |
| I15 final_summary dead param | 不存在新 helper |
| I16 sync IPv6 reject | regex 扩 IPv6 bracket form(可选) |
| I17 register TOCTOU | run-id allocator 文件锁 + O_EXCL |
| I18 whitespace override bypass | 不再有 --run-id × --override 冲突(无 register step) |
| I19 extends resolve 重复 | resolve 一次 cache(可选) |
| I20 equivalence-preserving edit blocked | 无 drift guard(cfg_resolved 是 truth) |
| I21 underscore import | helpers 设计为 public API |
| I22 drift msg incomplete | 无 drift msg(无 drift guard) |
| I23 BaseException 不对称 | finally 内 BaseException 同步处理 |

I9-I23 全部 close by design 或显式 fix。

---

## 不在 scope

- 老 metadata 迁移工具(后续 backlog,需另一个 plan)
- 多 paradigm 同时 train 的协调(out of scope,user 责任)
- ckpt 跨机 sync(不传 ckpts/ 是 design 决策,user 若需可手动 scp / rsync)
- gauntlet result schema 标准化(放 artifacts dir 独立文件,本 redesign 不规定 schema)

---

## File structure(实施时)

### 新建文件

- `tools/runs/train.py` — 新主入口(atomic lifecycle)
- `tools/runs/mark.py` — 新罕用工具(status 手动 fix)
- `docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md` — 本文档
- `docs/superpowers/plans/2026-05-18-tools-runs-redesign-implementation.md` — 实施 plan(下一步写)

### 重写文件

- `tools/runs/schema.py` — 简化字段(11 个),strict status enum
- `tools/runs/list.py` — 扫新位置(`artifacts/*/metadata.toml`)
- `tools/runs/show.py` — 接受 shorthand NNN
- `tools/runs/sync.py` — 改 include pattern
- `training/core/checkpoint.py` — ckpts 进入 `ckpts/` 子目录(`<artifacts_dir>/ckpts/ckpt_N.pt`)
- `tools/run.py` — **删除**(被 `tools/runs/train.py` 替代)或保留为 thin shim
- `CLAUDE.md` — Artifacts 段重写

### 删除文件

- `tools/runs/register.py` — 功能并入 train.py
- `tools/runs/complete.py` — 功能并入 train.py(`mark.py` 接管手动 status)

---

## 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| Per-run 完全 self-contained = ls artifacts/ 难找特定 cfg 的 run | `tools.runs.list` 提供 filter / sort;dir 名含 label 也方便 grep |
| ckpts/ 子目录改 = smoke_full + 已有 tools 路径假设全 break | implementation plan 必须扫 grep 所有 'artifacts/<ts>_<label>/' pattern,统一改 |
| 迁移期老 run 不可访问 | 迁移 script 入 backlog;过渡期用 git history 找老 commit 的 artifacts/ |
| 单 train.py 文件可能膨胀 | implementation plan 必须拆为 train.py + lifecycle.py + allocator.py 等 |

---

## 实施 phase 拆分(供 writing-plans 参考)

phase 1: schema 重写 + dir 结构改造(checkpoint.py + 测试 fixture)
phase 2: tools.runs.train 新写 + list/show 扫新位置
phase 3: tools.runs.mark 新建 + tools.runs.sync include pattern 改
phase 4: 删除 register.py / complete.py / tools/run.py(或改 shim)
phase 5: CLAUDE.md + smoke_full template + 全测验证
