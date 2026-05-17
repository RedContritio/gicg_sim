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

废 `tools.runs.register` + `tools.runs.complete`,合并入新 `tools.runs.train`。

**`tools.runs.train` 与现 `tools/run.py` 关系(round-4 CRIT-X-1)**:`tools/run.py` 当前是 paradigm dispatch driver(`load_cfg` → `resolve paradigm` → `run_pipeline`)。本 redesign 选 **方案 A**:`tools.runs.train` 即 lifecycle wrapper + **内部 import paradigm dispatch 完整逻辑**(从 `tools/run.py` 迁过来或调用其 internal helper)。`tools/run.py` 整个删除,不留 thin shim。具体含义:
- `tools.runs.train` 包含完整 paradigm dispatch(load_cfg + 5 paradigm registry 加载 + run_pipeline 调用)
- 不再有独立的 `tools/run.py` 入口
- **phase 2 涉及 paradigm dispatch 迁移,工作量较大(~200-400 LOC),不能拆**;phase 1(schema + dir structure)与 phase 2 仍然同 PR ship(见后)

```
tools.runs.train [--resume <ckpt>] [--override k=v] <cfg>
  │
  ├── 0. validate cfg.meta.run_label 符合 regex `^[a-zA-Z0-9_-]{1,64}$`
  │     失败 → raise + exit 2(防 dir 名注入,如 `../../etc` 路径逃逸 / shell metachar)
  ├── 1. capture leaf cfg bytes (read_bytes 立即,防 cfg edit race)
  ├── 2. resolve cfg(load extends + apply --override → merged dict)
  ├── 2.5. ensure artifacts/ dir 存在:`artifacts.mkdir(parents=True, exist_ok=True)`
  │       (fresh repo first-train 防 mkdir 挂)
  ├── 3. **临界区**:`with fcntl.flock(artifacts/.run_id_lock)`:
  ├──    ├── loop:
  ├──    │     ├── glob `artifacts/<ts>_<6digit>_*` → max NNN(每次 retry 都 re-glob)
  ├──    │     ├── target = max + 1
  ├──    │     └── mkdir `artifacts/<ts>_<target>_<label>` (O_EXCL);成功 break,EEXIST 重 loop
  ├──    └── **锁在 step 3 末尾自动释放(with 退出)**
  │     ↓
  │     (step 4-7 不再持 allocator lock,但 metadata write 自带 per-run `<artifacts_dir>/.metadata_lock` flock)
  ├── 4. write cfg_leaf.toml (from step 1 bytes) + cfg_resolved.toml
  │     失败 → cleanup(`rmtree artifacts/<ts>_<NNN>_<label>` + raise + exit 2)
  ├── 5. write metadata.toml(status='running',持 per-run metadata_lock)
  │     失败 → cleanup(rmtree dir + raise + exit 2)
  ├── 6. run train(catch all exceptions)
  ├── 7. **持 per-run metadata_lock + read metadata.status before overwrite**(若已非 'running' 则保留,log warn);否则 update status='done'/'failed' + wall_seconds + exit_code
  └── 8. exit 0 (done) / nonzero (failed / setup error / metadata stale)
```

**Atomic 保证**:
- cfg bytes 在 step 1 立即 capture
- step 0 enforce `run_label` 不含路径 traversal / shell metachar(`^[a-zA-Z0-9_-]{1,64}$`,与 H-6 leaf bytes 共同 close 注入面)
- NNN 分配 + dir 创建在 allocator 锁临界区(step 3),retry 必须 re-glob(防 inter-process NNN 跳号 silent 冲突);**锁仅守 allocate 阶段**,step 4-7 在锁外但用 per-run `<artifacts_dir>/.metadata_lock` 守 metadata 写(允许 N 个 run 并发 train,不让 NNN allocator 长持锁)
- step 4/5 失败 → orphan dir rollback(rmtree + lock release + exit 2),不留 incomplete artifacts dir
- metadata 写在中间状态('running')只在 train 运行期间存在
- step 5/7 用 atomic rename(temp + rename)保证写不破坏现有 metadata
- step 7 **read-and-compare before write**:若 user `mark` 在 train running 期间收尾(误判 hang),mark 把 status 转 killed/done/failed;train step 7 检测到非 'running' 不覆盖,log warn `'metadata externally marked, train output discarded'`,exit 0

**dir 名 `<label>` 来源**:lifecycle step 3 mkdir 用的 `<label>` = **resolved cfg 的 `meta.run_label` 字段**(post step 2 `--override` apply 后的最终值),不是 leaf cfg 的字段值。这保证 `--override meta.run_label=foo` 真正改变 dir 名。

**dir 名 `<YYYYMMDDHHMM>` 时区**:`ts = datetime.fromisoformat(metadata.timestamp).astimezone(timezone.utc).strftime('%Y%m%d%H%M')`,UTC 整分钟。**metadata.timestamp 与 dir 名 ts 同源**(单一 metadata.timestamp 字段派生 dir 名,不分别 wall-clock 取两次,避免跨午夜 drift)。

**extends parent immutable assumption**(round-4 HIGH-2-G):step 2 resolve 期间,假定 extends parent cfg files immutable。若 user 在 step 2 resolve 中途修改 parent,train 写入的 `cfg_resolved.toml` 反映 step 2 当时 in-memory merged dict(snapshot 语义),后续读 parent 看到的可能与 cfg_resolved 不一致 — **这是 user 责任**(spec 不加 parent bytes capture,因 extends 链可能多层,开销不值)。

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
| `tools.runs.list [--status <s>] [--paradigm <p>]` | 表格视图扫所有 run(详 §list 细则)|
| `tools.runs.show <NNN>` | 详细 dump(接受 shorthand,详 §show 细则)|
| `tools.runs.sync push\|pull <user@host:path/>` | 跨机 sync metadata + cfg backup(NOT ckpts/);**单源主从**:推荐一台 authoritative,其他 pull-only |
| `tools.runs.sync init-authoritative` | 写当前 hostname 到 `artifacts/.authoritative_host`,让本 host 可 train |
| `tools.runs.mark <NNN> --status {done\|failed\|killed} [--notes ...]` | running 状态手动转 done/failed/killed(详 §mark 细则)|
| `tools.runs.recover <dir>` | metadata 缺失救援:从 `<dir>/cfg_*.toml` + ckpts/ 重建 metadata.toml(详 §recover 细则)|

**移除**:`tools.runs.register`(被 train 吸收)、`tools.runs.complete`(被 train 自动闭环吸收)

#### list 细则(round-4 HIGH-1-B)

- default sort: `timestamp desc`(最新 run 在最上方)
- flag `--status running|done|failed|killed`:仅显示该 status 的 run
- flag `--paradigm az|bc|dmc|cfr|ppo`:仅显示该 paradigm 的 run(从 cfg_resolved.meta.paradigm 派生,实时读)
- output format: 表格,列 `NNN | status | paradigm | started(date) | wall | run_label | notes`
- 若 metadata.toml malformed(TOML parse fail):catch + stderr warn `'skipping <NNN>: malformed metadata'` + skip(round-4 HIGH-4-A,**不让一坏全坏**)

#### show 细则(round-4 HIGH-1-C)

- NNN shorthand: 接受任何 6 位前缀(`69` / `069` / `000069`)→ 内部 zero-pad 到 6 位严格 match
- 若多个 dir 匹配同一 NNN(跨 host sync 后罕见 case):raise + 列候选 dirs,user 手动选
- 若单个 dir 的 metadata.toml malformed:直接 raise(不像 list 那样 skip — show 单 NNN 失败不影响他人)
- 输出含:metadata 全字段 + cfg_resolved_v1 ... v<N> 全系列(标 "N = current")

#### mark 细则(round-4 HIGH-1-D / HIGH-6-A)

- mark 内部 NNN → artifacts_dir lookup:`glob artifacts/*_<NNN>_*/` 找 dir
  - 若 0 match → raise `'NNN not found'`
  - 若 ≥2 match → raise + 列候选(防跨 host NNN 冲突 silent 写错 dir)
- `--notes` 输入必经 TOML escape(canonical schema emitter),**不允许 raw newline / control char**:
  - 若含 → 自动 escape(`\n` → `\\n` 等)或 raise(实现选 escape,user 友好)
  - 防止 notes 含 `]\n[other_section]` 注入破坏 toml 结构
- mark 必须先 acquire `<artifacts_dir>/.metadata_lock`(per-run flock,见 §Atomic 并发)再写

#### recover 细则(round-4 HIGH-4-C)

`tools.runs.recover <dir>`:metadata.toml 缺失但 dir 在 的救援路径
- 读 `<dir>/cfg_resolved.toml` + cfg_leaf + ckpts/ 重建 metadata.toml
- 重建后 status 字段:**新增 enum 值 `unknown`**(metadata.toml 缺失 → 无法判定 train 是 done / failed / killed),或 user 手动 mark
- status enum 扩展:`{running, done, failed, killed, unknown}` — `unknown` 仅 recover 命令可写入,正常 train lifecycle 不会产生
- recovered metadata 立即可被 list/show 读;后续若 user 知道实情 → `mark --status killed/done/failed --notes 'recovered from <dir>'`

### Resume 语义

`tools.runs.train --resume artifacts/<dir>/ckpts/ckpt_N.pt <cfg>` 仍接 cfg + 可选 `--override`:
1. 从 ckpt 路径 grandparent (`.parent.parent`) 推断 artifacts_dir = `artifacts/<dir>/`(因 ckpts/ 子目录)
1.5. **校验 leaf cfg 存在 + 可读**(round-4 HIGH-2-C):若 `<cfg>` 路径不存在 → raise `'leaf cfg 缺失,不支持纯 ckpt 续训(必须提供 cfg 才能 resume)'` + exit 2。本设计**不**支持 "只有 ckpt 没有 cfg" 的恢复路径
2. 校验 `<dir>/metadata.toml` 存在且 `<dir>/ckpts/` 是直接子目录 → 否则 raise("resume needs registered run; <ckpt parent> 不是合法 artifacts dir")
3. 读 metadata,得 run_id 不变
4. **resume 重 resolve cfg + apply --override**(允许 cfg 漂移,这是 design 决策):
   - 文件命名:**首版固定 `cfg_resolved.toml`(无后缀)**,后续 resume 写 `cfg_resolved_v2.toml` / `v3.toml` / ...
   - N 算法(避免跳号):glob `cfg_resolved*.toml`,若仅 `cfg_resolved.toml` 一个则下一版 N=2;若已有 vN max,下一版 = max+1
   - **N 分配走 allocator lock**(round-4 HIGH-3-A):`with fcntl.flock(artifacts/.run_id_lock)`:glob → compute N → write `cfg_resolved_v<N>.toml` + `cfg_leaf_v<N>.toml`(同步对成对),防 2 resume 同时进行时 N collision
   - 同步写 `cfg_leaf.toml`(首版)或 `cfg_leaf_v<N>.toml`(后续);**cfg_leaf 与 cfg_resolved 同版本号成对**(v1 不带后缀,vN≥2 带 `_v<N>` 后缀)
   - **truth 定义 + metadata 字段(round-4 CRIT-6-A)**:**最高版** `cfg_resolved_v<N>.toml` 是 current truth(`cfg_resolved.toml` 是 v1);历史版作 audit trail
   - metadata 加新字段 `cfg_resolved_version: int = 1`(默认 1,resume 时递增),use case 见 §Schema
   - metadata 字段 `cfg_file` 语义:**last leaf path used**(可能不存在/已改;实质 truth 仍是最高版 `cfg_resolved_v<N>.toml`)
   - `tools.runs.show` 列 cfg_resolved_v1 ... v<N> 全系列,显式标 "N = current"
5. status 改回 'running' → train → 'done'/'failed';**注意 resume 触发的 status 转换是状态机 exception**(详 §状态机)
6. metadata 字段不重置(timestamp 是首次 start;status 重新转移;wall_seconds 见 H-3 语义 = last attempt elapsed)

**版本化 cfg backup 原因**:resume 允许 cfg 改动(不强制 bytes-exact),为审计 reproducibility 多次 resume 留每次的 cfg snapshot 序列。

### 跨机 sync 单源主从约定

设计假设:一台 host 是 authoritative(通常 dev box 或 GPU box),其他 host 仅 pull。**不支持双向 push**;若需要,user 手动 resolve NNN 冲突。理由:NNN 单 host allocator 不可能跨 host 协调,简化 trumps 多主灵活性。文档 / `tools.runs.sync` --help 明确这一约定。

---

## Schema

### metadata.toml 字段(11 个,精简到必需)

```toml
run_id = "000069"                           # 6 位 zero-pad
timestamp = "2026-05-18T03:55:21+00:00"     # UTC iso, 首次 train start (resume 不重置);dir 名 ts 派生于此字段
cfg_file = "configs/dmc/smoke_full.toml"    # **last leaf path used**(可能不存在/已改;truth 仍是最高版 cfg_resolved_v<N>.toml)
cfg_resolved_version = 1                     # 当前 truth 的 cfg_resolved 版本号,首版 = 1,resume 递增 (round-4 CRIT-6-A)
git_commit = "2c20de8..."
host = "Mac-mini.local"
status = "done"                              # enum {running, done, failed, killed, unknown};strict transitions(unknown 仅 recover 命令可写,详 §recover)
artifacts_dir = "artifacts/202605180355_000069_dmc_smoke_full"
wall_seconds = 84.3                          # last attempt elapsed(resume 覆盖);running 期间为 0
exit_code = 0
notes = ""                                   # free-form
```

### 无 ckpt dead running 恢复路径

无 ckpt 的 dead running(train 启动后 status='running' 期间被 SIGKILL,未保存任何 ckpt)无法 resume — `--resume` 需 ckpt 路径作为入口。处理方式:
- user 用 `tools.runs.mark <NNN> --status killed --notes 'no ckpt, dead'` 把状态转 killed
- 新分配 NNN 重跑(老 dir 留 audit,**不重用**老 dir 因终态不可再 mutate)
- 老 dir 的 cfg_leaf / cfg_resolved 可手动 cp 出来作新 NNN 的 cfg 输入

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
  ├── 外部 SIGTERM/SIGKILL → metadata 留 'running'(死状态)
  │     │
  │     └── user: tools.runs.mark <NNN> --status {done|failed|killed} [--notes ...]
  │
  └── recover 重建 → status='unknown'(recover 命令入口,详 §recover 细则)
        │
        ├── user: tools.runs.mark <NNN> --status {done|failed|killed}(知实情后收尾)
        └── user: tools.runs.train --resume(转回 running,resume 例外)
```

Strict transitions(违反 raise):
- `running` → `done` / `failed`(自动,by train succeed / raise)
- `running` → `done` / `failed` / `killed`(手动,by mark — 仅 user 显式收尾死 running)
- `unknown` → `done` / `failed` / `killed`(手动,by mark — recover 重建后 user 知实情后收尾)
- `done` / `failed` / `killed` → **任何**:**默认不允许**(全部终态,mark 也拒,resume 例外见下)
- `unknown` → `running`(resume 例外,同 `{done, failed, killed} → running`)

**only `running` 与 `unknown` 是非终态**(`unknown` 是 recover 重建态,等 user mark 或 resume 转走)。Mark 仅在 running / unknown 状态有效;终态 run 若要重跑,新 NNN 重 train。

### Resume 例外规则(round-4 CRIT-2-A)

resume 是状态机的唯一例外:
- **resume 显式转换 `{done, failed, killed, unknown} → running`** 允许,仅 resume code path 触发
- 该 transition 在 schema validate 中 hard-code(no user-facing flag,no `mark` 入口 — `mark` 仍只可走 `{running, unknown} → 终态`)
- resume 启动时:
  1. 读 metadata,得 current status
  2. 若 status ∈ {done, failed, killed, unknown} → 写 status='running'(resume exception transition)
  3. 若 status='running' already(罕见:resume 启动一个 metadata 状态本来就 running 的 run,可能因前次 train 死前没收尾)→ no-op + warn `'metadata already running; assuming prev attempt crashed unrecorded, proceeding to resume'`
  4. 写完 status='running' 后继续 lifecycle step 5 onwards
- **理由**:resume 是 "重启已死/已收尾/未知态 run" 这一明确意图,不是 mistake,设计上必须 first-class 支持

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

- 文件锁(round-4 CRIT-4-A):用 **`fcntl.flock(LOCK_EX | LOCK_NB)`**(kernel-tracked,process 死自动释)替代 O_EXCL file create+delete 模式。理由:O_EXCL stale lock 可永久 fail(process 崩溃没 unlink lock file → 后续永久无法 acquire);kernel flock 在 process 死时自动释,**stale 风险消失**
- 实现:`open('artifacts/.run_id_lock', 'a+')` + `fcntl.flock(fd, LOCK_EX | LOCK_NB)`;file close 时 kernel 自动释。Linux/macOS 原生支持;Windows 用 `msvcrt.locking` 替代
- 临界区(必须全部在锁内完成):**retry loop**(防 NNN 跳号 + macOS case-insensitive FS + sync stale dir):
  ```
  with open('artifacts/.run_id_lock', 'a+') as fd:
      fcntl.flock(fd, LOCK_EX | LOCK_NB)              # 失败立即 raise; retry-backoff 见下
      loop:
        max = glob_max_NNN()                              # 每次 retry 都 re-glob
        target = max + 1
        try mkdir `artifacts/<ts>_<target>_<label>` (O_EXCL)
        if success: break
        if EEXIST: continue                                # 他 process / sync stale / case collide
      # fd close 时 kernel 自动释 flock
  ```
- 若 `flock` LOCK_NB 失败(他 process 持有):retry up to 10 次,每次 sleep random(0,50)ms;超时 raise `'unable to acquire run-id lock'`
- **resume 也走 allocator lock**(用于 cfg_resolved_v<N> N 分配,见 §Resume step 4 HIGH-3-A);allocator lock 同时守 "fresh NNN 分配" 与 "resume vN 分配",不区分

### metadata 写(per-run lock)

- **per-run advisory lock**(round-4 CRIT-2-B / 3-A):metadata 写入(无论 train step 7 还是 `mark`)必须**先 acquire** `<artifacts_dir>/.metadata_lock`(`fcntl.flock` LOCK_EX)
- 临界区语义:read-and-compare-and-write 在 lock 内 atomic,两 writer(如 mark 与 train step 7 撞)串行化
- temp file + atomic rename:`metadata.toml.tmp` → `metadata.toml`
- 写中断不破坏现有 metadata
- **atomic rename 同 dir 约束**(round-4 HIGH-5-B):temp file 必须与 target 同 dir(`<artifacts_dir>/metadata.toml.tmp` → `<artifacts_dir>/metadata.toml`),**不可跨 mount point** — 否则 rename 退化为 copy+delete 非 atomic,write 中断会丢失 metadata
- temp file 路径写死在同 dir 内,实现禁止用 `tempfile.NamedTemporaryFile()` 默认参数(默认 /tmp 可能跨 fs)

### Resume 并发

- resume 与 fresh train 不冲突(fresh train allocator lock 内 mkdir 新 dir,resume 不动新 dir;resume 走 allocator lock 仅做 cfg_resolved_v<N> N 分配,临界区短)
- 两 resume 同一 run 同时进行:per-run metadata_lock 防 metadata 撞写;allocator lock 防 cfg_resolved_v<N> N collision。设计上仍不推荐(一 run 一 train process),但 lock 提供安全网

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
- resume leaf cfg 缺失(HIGH-2-C):`'leaf cfg 缺失,不支持纯 ckpt 续训(必须提供 cfg 才能 resume)'`
- mark NNN 0 match(HIGH-6-A):`'NNN not found'`
- mark NNN ≥2 match:`'multiple dirs match <NNN>: <list>; please pass full dir path'`
- authoritative host mismatch(HIGH-2-D):`'this host is pull-only; cannot allocate new NNN. To make this host authoritative, run tools.runs.sync init-authoritative'`
- run_label 非法(CRIT-1-B):`'cfg.meta.run_label \"<value>\" 不符合 regex ^[a-zA-Z0-9_-]{1,64}$;路径 traversal / shell metachar / 空 / 超长 均拒'`

### Malformed metadata 处理(round-4 HIGH-4-A)

- `list` 扫到 broken metadata(`tomllib.TOMLDecodeError`):skip 该 NNN + stderr warn `'skipping <NNN>: malformed metadata'`,**不让一坏全坏**
- `show <NNN>` 单 NNN broken:**直接 raise**(用户明确请求该 NNN,不该 silent skip)
- `mark <NNN>` 单 NNN broken:raise(同 show)
- `recover <dir>`:这是修复入口,本来就允许 metadata 不存在/坏(详 §CLI recover 细则)

---

## Cross-host sync

### 设计

`tools.runs.sync push|pull <user@host:path/>`:
- rsync 全量 `artifacts/*/metadata.toml` + `artifacts/*/cfg_*.toml`(metadata + cfg backup)
- **不传**:`artifacts/*/ckpts/`、`artifacts/*/metrics.jsonl`、`artifacts/*/tb/`(数据大,跨机不必要)
- Remote regex strict `user@host:path/`(round-3 已修)

### Conflict resolution(round-4 HIGH-2-E)

**不用 mtime,改用 `metadata.timestamp` 字段比对**(rsync `--update` mtime 在跨时区 / clock drift 下可能颠倒,导致旧覆盖新):
- **push**:遍历 local `metadata.toml`,与 remote 同 NNN 文件对比 `timestamp` 字段;local 新 → 覆盖 remote;remote 新 → skip(不覆盖)+ stderr warn
- **pull**:同理,remote 新 → 覆盖 local,local 新 → skip + warn
- **timestamp 完全等(同毫秒)**:NNN allocator 单 host 不可能同 ts,跨 host 同 ts 极罕见(分钟粒度);若发生,raise + 列冲突 NNN,user 手动 resolve
- mtime 完全忽略(rsync `--update` flag 仍可保留作 fallback,但比对决定走 timestamp 字段)

### Case-collide detection(round-4 CRIT-5-A)

macOS APFS 默认 case-insensitive(`A/` 与 `a/` 视为同 dir),Linux ext4 默认 case-sensitive。跨这两 OS sync 时:
- pull 到 target dir 若已有不同 case 的 sibling dir(`<artifacts>/202605180355_000069_DMC_smoke/` vs 已存在 `..._dmc_smoke/`)→ **raise** 而非覆盖
- 实现:sync 前先 lower-case 化所有 source / target dir name list,扫 collision;有 collision raise + 列冲突 dir 对
- 替代方案(更激进,本设计不采纳):dir 名 enforce lowercase 在 step 0 validate — 但 user 可能想 mixed case label,故保守做 detection-only

### Authoritative host enforcement(round-4 HIGH-2-D)

单源主从约定不靠口头规约,**代码 enforce**:
- `tools.runs.train` 启动前(step 0 后,step 1 前):检查 `artifacts/.authoritative_host` 文件
- 若存在 + 内容 ≠ 当前 `socket.gethostname()` → raise `'this host is pull-only; cannot allocate new NNN. To make this host authoritative, run tools.runs.sync init-authoritative'`
- 若文件不存在 → 允许 train(初始/无约束模式)
- 若内容 == 当前 hostname → 允许 train(正常)
- Setup CLI:**`tools.runs.sync init-authoritative`** 子命令 — 写当前 hostname 到 `artifacts/.authoritative_host`(覆盖 / overwrite OK,user 决策)。`.authoritative_host` 本身**不跨 host sync**(每 host 应有独立的 authoritative 标记,见 sync exclude)

### Include / exclude pattern

```python
RSYNC_FLAGS = (
    '-av',
    '--include=artifacts/',
    '--include=artifacts/*/',                    # 进入每 run 子目录
    '--include=artifacts/*/metadata.toml',       # metadata
    '--include=artifacts/*/cfg_resolved*.toml',  # reproducibility backup(含 v2/v3 等所有版本)
    '--include=artifacts/*/cfg_leaf*.toml',      # leaf snapshot(含 v2/v3)
    '--exclude=artifacts/.authoritative_host',   # host-local 不跨机
    '--exclude=artifacts/.run_id_lock',          # host-local lock
    '--exclude=artifacts/*/.metadata_lock',      # per-run lock 也不跨
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
