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
tools.runs.train [--resume <ckpt>] [--override k=v] <cfg>
  │
  ├── 1. capture leaf cfg bytes (read_bytes 立即,防 cfg edit race)
  ├── 2. resolve cfg(load extends + apply --override → merged dict)
  ├── 3. acquire allocator lock (artifacts/.run_id_lock,O_EXCL create)
  ├──    ├── loop:
  ├──    │     ├── glob `artifacts/<ts>_<6digit>_*` → max NNN(每次 retry 都 re-glob)
  ├──    │     ├── target = max + 1
  ├──    │     └── mkdir `artifacts/<ts>_<target>_<label>` (O_EXCL);成功 break,EEXIST 重 loop
  ├──    └── release lock
  ├── 4. write cfg_leaf.toml (from step 1 bytes) + cfg_resolved.toml
  ├── 5. write metadata.toml(status='running')
  ├── 6. run train(catch all exceptions)
  ├── 7. **read metadata.status before overwrite**(若已非 'running' 则保留,log warn);否则 update status='done'/'failed' + wall_seconds + exit_code
  └── 8. exit 0 (done) / nonzero (failed / setup error / metadata stale)
```

**Atomic 保证**:
- cfg bytes 在 step 1 立即 capture
- NNN 分配 + dir 创建在同一锁临界区(step 3),retry 必须 re-glob(防 inter-process NNN 跳号 silent 冲突)
- metadata 写在中间状态('running')只在 train 运行期间存在
- step 6/7 用 atomic rename(temp + rename)保证写不破坏现有 metadata
- step 7 **read-and-compare before write**:若 user `mark` 在 train running 期间收尾(误判 hang),mark 把 status 转 killed/done/failed;train step 7 检测到非 'running' 不覆盖,log warn `'metadata externally marked, train output discarded'`,exit 0

**关于 --max-steps**:废除该 flag。test 需 cap 通过 cfg fixture 调 `paradigm.total_frames`。生产 train 由 cfg.total_frames 决定停止。

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
| `tools.runs.train [--resume <ckpt>] [--override k=v] <cfg>` | 主入口(atomic 全 lifecycle)|
| `tools.runs.list` | 表格视图扫所有 run |
| `tools.runs.show <NNN>` | 详细 dump(接受 shorthand "69" / "069" / "000069") |
| `tools.runs.sync push\|pull <user@host:path/>` | 跨机 sync metadata + cfg backup(NOT ckpts/);**单源主从**:推荐一台 authoritative,其他 pull-only |
| `tools.runs.mark <NNN> --status {done\|failed\|killed} [--notes ...]` | running 状态手动转 done/failed/killed |

**移除**:`tools.runs.register`(被 train 吸收)、`tools.runs.complete`(被 train 自动闭环吸收)

### Resume 语义

`tools.runs.train --resume artifacts/<dir>/ckpts/ckpt_N.pt <cfg>` 仍接 cfg + 可选 `--override`:
1. 从 ckpt 路径 grandparent (`.parent.parent`) 推断 artifacts_dir = `artifacts/<dir>/`(因 ckpts/ 子目录)
2. 校验 `<dir>/metadata.toml` 存在且 `<dir>/ckpts/` 是直接子目录 → 否则 raise("resume needs registered run; <ckpt parent> 不是合法 artifacts dir")
3. 读 metadata,得 run_id 不变
4. **resume 重 resolve cfg + apply --override**(允许 cfg 漂移,这是 design 决策):
   - 文件命名:**首版固定 `cfg_resolved.toml`(无后缀)**,后续 resume 写 `cfg_resolved_v2.toml` / `v3.toml` / ...
   - N 算法(避免跳号):glob `cfg_resolved*.toml`,若仅 `cfg_resolved.toml` 一个则下一版 N=2;若已有 vN max,下一版 = max+1
   - 同步写 `cfg_leaf.toml`(首版)或 `cfg_leaf_v<N>.toml`(后续)
   - **truth 定义**:**最高版** `cfg_resolved_v<N>.toml` 是 current truth(`cfg_resolved.toml` 是 v1);历史版作 audit trail。`tools.runs.show` 列全部 v 系列
5. status 改回 'running' → train → 'done'/'failed'
6. metadata 字段不重置(timestamp 是首次 start;status 重新转移)

**版本化 cfg backup 原因**:resume 允许 cfg 改动(不强制 bytes-exact),为审计 reproducibility 多次 resume 留每次的 cfg snapshot 序列。

### 跨机 sync 单源主从约定

设计假设:一台 host 是 authoritative(通常 dev box 或 GPU box),其他 host 仅 pull。**不支持双向 push**;若需要,user 手动 resolve NNN 冲突。理由:NNN 单 host allocator 不可能跨 host 协调,简化 trumps 多主灵活性。文档 / `tools.runs.sync` --help 明确这一约定。

---

## Schema

### metadata.toml 字段(10 个,精简到必需)

```toml
run_id = "000069"                           # 6 位 zero-pad
timestamp = "2026-05-18T03:55:21+00:00"     # UTC iso, 首次 train start (resume 不重置)
cfg_file = "configs/dmc/smoke_full.toml"    # repo-relative leaf path(human ref only;truth 在 cfg_resolved.toml)
git_commit = "2c20de8..."
host = "Mac-mini.local"
status = "done"                              # enum {running, done, failed, killed};strict transitions
artifacts_dir = "artifacts/202605180355_000069_dmc_smoke_full"
wall_seconds = 84.3                          # last attempt elapsed(resume 覆盖);running 期间为 0
exit_code = 0
notes = ""                                   # free-form
```

### 移除字段(对比当前 schema)

- `type`(r/s 区分)— 单一 NNN 序列,不区分
- `label`(冗余 with run_id)
- `cfg_checksum`(替代:cfg_resolved.toml 是 truth)
- `cfg_run_label`(替代:cfg_resolved.toml 已含 meta.run_label)
- `summary`(`wall_seconds` 直接顶层)
- `result.gauntlet` / `result.training`(放 artifacts dir 独立文件,不进 metadata)
- `paradigm`(从 cfg_resolved.toml `meta.paradigm` 派生,list/show 实时读)

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
        └── user: tools.runs.mark <NNN> --status {done|failed|killed} [--notes ...]
```

Strict transitions(违反 raise):
- `running` → `done` / `failed`(自动,by train)
- `running` → `done` / `failed` / `killed`(手动,by mark — 仅 user 显式收尾死 running)
- `done` / `failed` / `killed` → **任何**:不允许(全部终态,mark 也拒)

**only `running` 是非终态**。Mark 仅在 running 状态有效;终态 run 若要重跑,新 NNN 重 train。

### Exit codes

| Code | 含义 |
|---|---|
| 0 | train done + metadata closed cleanly |
| 1 | train ran but failed mid-way(metadata=failed) |
| 2 | cfg / setup error(metadata=failed,train 未启动) |
| 3 | train done but final metadata write 失败(metadata 保留 'running' 状态,user 需 `tools.runs.mark <NNN> --status done` 手动收尾) |

---

## Atomic + 并发安全

### run-id allocator

- 文件锁:open `artifacts/.run_id_lock`(`O_EXCL` create)
- 临界区(必须全部在锁内完成):**retry loop**(防 NNN 跳号 + macOS case-insensitive FS + sync stale dir):
  ```
  loop:
    max = glob_max_NNN()                              # 每次 retry 都 re-glob
    target = max + 1
    try mkdir `artifacts/<ts>_<target>_<label>` (O_EXCL)
    if success: break
    if EEXIST: continue                                # 他 process / sync stale / case collide
  ```
- 释放锁:删除 lock file
- 若 lock acquire 失败(他 process 持有):retry up to 10 次,每次 sleep random(0,50)ms;超时 raise `'unable to acquire run-id lock'`

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
| I9 sync 跨机重名 clobber | 单源主从约定,不存在跨机并发 register |
| I10 sync nested dir support | dir 命名标准化,无 nested concern |
| I11 complete 状态机 guard | strict transitions 直接 design 入 + mark 仅 running 可转 |
| I12 sync subdir silent zero | dir 自动 walk parents 找 repo root |
| I13 gauntlet `n` key collision | result 不进 metadata(放 gauntlet.json 独立文件) |
| I14 finally exception mask | already-fixed in round-4 |
| I15 final_summary dead param | 不存在新 helper |
| I16 sync IPv6 reject | regex 扩 IPv6 bracket form(可选) |
| I17 register TOCTOU | allocator atomic lock(glob + mkdir 同一锁内)|
| I18 whitespace override bypass | 不再有 --run-id × --override 冲突(无 register step)|
| I19 extends resolve 重复 | resolve 一次 in train step 2(无 drift guard 重复调用)|
| I20 equivalence-preserving edit blocked | 无 drift guard(cfg_resolved 是 truth);resume 允许重 resolve + versioning |
| I21 underscore import | helpers 设计为 public API |
| I22 drift msg incomplete | 无 drift msg(无 drift guard)|
| I23 BaseException 不对称 | finally 内 BaseException 同步处理 |

I9-I23 全部 close by design 或显式 fix。

## Reviewer-found design 修正(round-5 brainstorming review)

第 1 版 spec 经 adversarial review 发现 4 CRITICAL + 7 HIGH 同型 emergent bug 风险。本版应用如下修订:

- **C-1**:废除 `--max-steps` flag(test cap 走 cfg fixture)
- **C-2**:resume 重 resolve cfg + override,版本化写 `cfg_resolved_v<N>.toml`
- **C-3**:ckpt → artifacts_dir 用 `.parent.parent`(因 ckpts/ 子目录)
- **C-4**:allocator 锁内完成 glob + mkdir(O_EXCL 撞名 retry)
- **H-1**:跨机 sync 改单源主从(不支持双向 push)
- **H-2**:state machine 简化 — 只 `running` 非终态;`done`/`failed`/`killed` 全终态
- **H-3**:保留 `wall_seconds` 字段,语义 = **last attempt elapsed seconds**(resume 触发时被新 attempt 值覆盖,不累计;running 期间为 0)
- **H-4**:mark 接受 done/failed/killed 三种 target(收尾 running 死状态)
- **H-5**:O_EXCL retry +1 处理 macOS case-insensitive FS
- **H-6**:lifecycle step 1 立即 `read_bytes()` 捕获 leaf cfg
- **H-7**:`ckpts/` 含所有 .pt(naming prefix 区分 train vs gauntlet)
- **M-5**:drop `paradigm` 字段(派生自 cfg_resolved.meta.paradigm)
- **M-6**:phase 1+2 同 PR ship(避免 schema 不兼容窗口)
- **L-1**:`tools/run.py` 删除(不留 shim)

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

phase 1+2 **必须同 PR ship**(避免 schema 不兼容窗口):
- schema 重写 + dir 结构改造(checkpoint.py — ckpts/ 子目录)
- tools.runs.train 新写(含 allocator atomic lock + cfg_resolved versioning + 状态机)
- list/show 扫新位置

phase 3: tools.runs.mark 新建(running → done/failed/killed)+ tools.runs.sync include pattern 改 + 单源主从文档

phase 4(可独立 PR): 删除 tools/runs/register.py + tools/runs/complete.py + tools/run.py(都 by design 完全替代,不留 shim)

phase 5: CLAUDE.md + smoke_full template + 全测验证

### ckpts/ 内 naming convention

`ckpts/` 含**所有** `.pt`:
- `ckpts/ckpt_<step>.pt` — train ckpt
- `ckpts/gauntlet_g<g>.pt` — gauntlet eval intermediate(若 paradigm 产)
- `ckpts/latest.pt` — last train ckpt 副本

naming prefix 区分,grep/sync 走通配。
