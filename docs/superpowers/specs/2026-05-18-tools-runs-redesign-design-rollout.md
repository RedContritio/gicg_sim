> 分卷导航:回到 [← Part 1](2026-05-18-tools-runs-redesign-design.md)

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
| I16 sync IPv6 reject | regex 扩 IPv6 bracket form(**强制支持**,round-4 HIGH-6-B):remote 校验 regex 加 `\[[0-9a-fA-F:]+\]` alternative,如 `user@[::1]:/path/`、`user@[fe80::1]:/path/` 均必须接受 |
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

## Reviewer-found design 修正(round-4 exhaustive review,v2.2 → v3)

第 2 版 spec 经更深一轮 exhaustive review,在已修 14 缺陷之外发现 8 CRITICAL + 20 HIGH 余项。本 v3 应用如下:

**§Architecture(8 处)**
- **CRIT-1-A**:lifecycle step 3 lock release 显式 try/finally(`with fcntl.flock(...)`),锁仅守 allocate 阶段;step 4-7 用 per-run metadata_lock
- **CRIT-1-B**:step 0 新增 `cfg.meta.run_label` regex 校验 `^[a-zA-Z0-9_-]{1,64}$`,防 dir 注入
- **CRIT-X-1**:明示 `tools.runs.train` = lifecycle wrapper + 内部 paradigm dispatch(方案 A);`tools/run.py` 删除,phase 2 ~200-400 LOC 不可拆
- **HIGH-2-A**:lifecycle step 2.5 新增 `artifacts.mkdir(parents=True, exist_ok=True)`,fresh repo 不挂
- **HIGH-2-B**:step 4/5 raise → orphan dir rollback(rmtree + lock release + exit 2)
- **HIGH-1-A**:step 3 mkdir 用的 `<label>` 明示 = resolved cfg 的 `meta.run_label`(post --override)
- **HIGH-2-G**:extends parent 在 step 2 假定 immutable,中途 user 改 parent → cfg_resolved 反映 step 2 当时 snapshot,user 责任
- **HIGH-X-3**:dir 名 `<YYYYMMDDHHMM>` 时区与派生公式明示(UTC 整分钟,与 metadata.timestamp 同源)

**§Resume(3 处)**
- **CRIT-6-A**:metadata 新增 `cfg_resolved_version: int = 1`,`cfg_file` 语义改 "last leaf path used",show 列全部 cfg_resolved_v 系列,cfg_leaf 与 cfg_resolved 成对版本号
- **HIGH-3-A**:resume cfg_resolved_v<N> N 分配走 allocator lock,防 2 resume collision
- **HIGH-2-C**:resume step 1.5 校验 leaf cfg 存在 + 可读,不支持纯 ckpt 续训

**§Schema(3 处)**
- **HIGH-2-F**:加 §"无 ckpt dead running 恢复路径"段,user mark killed + 新 NNN 重跑
- 字段总数 10 → 11(`cfg_resolved_version`)
- **HIGH-6-B(I16)**:IPv6 改强制支持,regex 加 `\[[0-9a-fA-F:]+\]` alternative

**§状态机(1 处)**
- **CRIT-2-A**:resume 是状态机唯一例外,显式允许 `{done, failed, killed, unknown} → running`,hard-code 在 schema validate,no user-facing flag;status='running' already 时 no-op + warn

**§Atomic + 并发(3 处)**
- **CRIT-4-A**:allocator 改 `fcntl.flock(LOCK_EX | LOCK_NB)`(kernel-tracked),stale lock 风险消失;Windows 用 `msvcrt.locking`
- **CRIT-2-B/3-A**:per-run `<artifacts_dir>/.metadata_lock` 守 metadata 写,mark 与 train step 7 串行化
- **HIGH-5-B**:metadata temp file 必须同 dir(`<artifacts_dir>/metadata.toml.tmp`),禁止跨 mount point

**§Cross-host sync(3 处)**
- **CRIT-5-A**:case-collide detection,macOS APFS vs Linux ext4 跨 sync 不 silent overwrite
- **HIGH-2-D**:authoritative host 代码 enforce(`artifacts/.authoritative_host`),pull-only host train 直接 raise;新增 `tools.runs.sync init-authoritative` 子命令
- **HIGH-2-E**:sync 改用 `metadata.timestamp` 字段比对,完全忽略 mtime

**§File structure(2 处)**
- **HIGH-X-1**:`training/core/gauntlet.py` ckpts 进 `<artifacts_dir>/ckpts/` 用 `gauntlet_g<NNNN>.pt` prefix
- **HIGH-5-A**:新增 §"Public API helper 表",train/mark/sync/list/show/recover 必须复用 helper

**§CLI 接口(4 处)**
- **HIGH-1-B**:list 加 default sort + `--status` / `--paradigm` flags + 列定义
- **HIGH-1-C**:show NNN shorthand 严格 6 位 zero-pad match,多 match raise
- **HIGH-1-D**:mark `--notes` TOML escape,不允许 raw newline / control char
- **HIGH-6-A**:mark NNN → artifacts_dir lookup 严格 glob,0/≥2 match raise

**§错误处理(2 处)**
- **HIGH-4-A**:list malformed metadata skip + warn,show / mark 单 NNN broken raise
- **HIGH-4-C**:新增 `tools.runs.recover <dir>` 命令,status enum 加 `unknown`,从 cfg + ckpts 重建 metadata.toml

---

## 不在 scope

- 老 metadata 迁移工具(后续 backlog,需另一个 plan)
- 多 paradigm 同时 train 的协调(out of scope,user 责任)
- ckpt 跨机 sync(不传 ckpts/ 是 design 决策,user 若需可手动 scp / rsync)
- gauntlet result schema 标准化(放 artifacts dir 独立文件,本 redesign 不规定 schema)

---

## Public API helper 表(round-4 HIGH-5-A)

实施时所有命令(train / mark / sync / list / show / recover)**必须复用**以下 helper,不重复实现:

| Helper | 签名 | 用途 |
|---|---|---|
| `tools.runs.helpers.normalize_repo_relative` | `(path: Path, repo_root: Path, label: str) -> str` | 把 path 标准化为 repo-relative + forward-slash posix(Windows 也走 `.as_posix()`)|
| `tools.runs.helpers.cfg_checksum` | `(cfg_path: Path) -> str` | 仅 audit 用(无 drift guard,不强制 — 不要再走老 cfg_checksum drift guard 路径)|
| `tools.runs.helpers.extract_meta_field` | `(cfg_path: Path, field: str) -> str \| None` | 提取 `cfg.meta.<field>`(无 extends resolve,纯本地 file 读)|
| `tools.runs.helpers.allocate_nnn` | `(repo_root: Path) -> int` | 锁内分配新 NNN(走 allocator lock + glob + retry,见 §Atomic allocator)|
| `tools.runs.helpers.acquire_metadata_lock` | `(artifacts_dir: Path) -> ContextManager` | per-run flock context manager(`with` 进入获 `<artifacts_dir>/.metadata_lock` LOCK_EX,退出释放)|
| `tools.runs.helpers.write_metadata_atomic` | `(artifacts_dir: Path, metadata: dict) -> None` | 同 dir temp file + rename;内部已用 `acquire_metadata_lock`|
| `tools.runs.helpers.resolve_nnn_to_dir` | `(repo_root: Path, nnn: str) -> Path` | NNN shorthand → 严格 dir 解析;0/≥2 match 各自 raise(见 §mark / show 细则)|

train.py / mark.py / sync.py / list.py / show.py / recover.py 所有这些 helper 必须复用,不允许内联复制实现。

---

## File structure(实施时)

### 新建文件

- `tools/runs/train.py` — 新主入口(atomic lifecycle + paradigm dispatch,见 §Architecture CRIT-X-1)
- `tools/runs/mark.py` — 新罕用工具(status 手动 fix)
- `tools/runs/recover.py` — metadata 缺失救援(round-4 HIGH-4-C)
- `tools/runs/helpers.py` — Public API helper(round-4 HIGH-5-A,见上表)
- `docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md` — 本文档
- `docs/superpowers/plans/2026-05-18-tools-runs-redesign-implementation.md` — 实施 plan(下一步写)

### 重写文件

- `tools/runs/schema.py` — 简化字段(11 个,含 `cfg_resolved_version`),strict status enum 含 `unknown`(recover 用)
- `tools/runs/list.py` — 扫新位置(`artifacts/*/metadata.toml`),malformed skip + warn
- `tools/runs/show.py` — 接受 shorthand NNN
- `tools/runs/sync.py` — 改 include pattern,timestamp 字段比对(非 mtime),case-collide detection,IPv6 regex,init-authoritative 子命令
- `training/core/checkpoint.py` — ckpts 进入 `ckpts/` 子目录(`<artifacts_dir>/ckpts/ckpt_N.pt`)
- `training/core/gauntlet.py` — gauntlet ckpts 也进 `<artifacts_dir>/ckpts/`,**用 `gauntlet_g<NNNN>.pt` prefix**(round-4 HIGH-X-1);旧 paths 全 grep 改
- `tools/run.py` — **删除**(被 `tools/runs/train.py` 完全替代;CRIT-X-1 方案 A,不留 shim)
- `CLAUDE.md` — Artifacts 段重写

### 删除文件

- `tools/runs/register.py` — 功能并入 train.py
- `tools/runs/complete.py` — 功能并入 train.py(`mark.py` 接管手动 status)
- `tools/run.py` — 功能完全并入 `tools/runs/train.py`(CRIT-X-1)

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

phase 1+2 **必须同 PR ship**(避免 schema 不兼容窗口;CRIT-X-1 phase 2 不可再拆,~200-400 LOC 含 paradigm dispatch 迁移):
- schema 重写 + dir 结构改造(checkpoint.py + gauntlet.py — ckpts/ 子目录)
- tools.runs.train 新写(含 allocator atomic lock + cfg_resolved versioning + 状态机 + paradigm dispatch 完整迁移 from tools/run.py)
- tools.runs.helpers 公共 API 实现(round-4 HIGH-5-A)
- list/show 扫新位置 + malformed handling

phase 3: tools.runs.mark 新建(running → done/failed/killed)+ tools.runs.recover 新建(metadata 救援)+ tools.runs.sync include pattern 改 + timestamp 比对 + case-collide detection + init-authoritative 子命令 + IPv6 regex + 单源主从文档

phase 4(可独立 PR): 删除 tools/runs/register.py + tools/runs/complete.py + tools/run.py(都 by design 完全替代,不留 shim)

phase 5: CLAUDE.md + smoke_full template + 全测验证

### ckpts/ 内 naming convention

`ckpts/` 含**所有** `.pt`:
- `ckpts/ckpt_<step>.pt` — train ckpt
- `ckpts/gauntlet_g<g>.pt` — gauntlet eval intermediate(若 paradigm 产)
- `ckpts/latest.pt` — last train ckpt 副本

naming prefix 区分,grep/sync 走通配。
