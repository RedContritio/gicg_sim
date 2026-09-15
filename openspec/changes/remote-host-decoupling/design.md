---
last_updated: 2026-09-15
status: DRAFT
schema_version: 0
---

# Design — remote-host-decoupling

## 1. Architecture

### 1.1 分层原则

`[remote]` 段的四个字段**全部是设备级**的:

| 信息 | 含义 | 是否设备标识 |
|---|---|---|
| `ssh` | 哪台机器 | **是** |
| `os` | 哪台机器 | **是**(间接) |
| `hostname` | 哪台机器 | **是** |
| `root` | 该机器上唯一的项目根 | **是**(该机器的目录布局) |

`root` 的设备级唯一性有代码依据,不是约定。`tools.runs.list` 与 `tools.runs.show`
扫的都是 `<repo_root>/artifacts/`(`tools/runs/list.py:151`、`tools/runs/show.py:117`),
`allocate_nnn` 的 NNN 计数器与锁文件也在
`<repo_root>/artifacts/.run_id_lock`(`tools/runs/_helpers/allocator.py:113`);而
`artifacts/` 是 gitignored、不参与同步的。故**每个项目根各自持有一套 run 索引与
NNN 计数器**:根一多,NNN 就跨根重复,`show <NNN>` / `mark <NNN>` 的 shorthand
语义随之失效(它不再是全局唯一标识)。

实测 14 个带 `[remote]` 段的 cfg 曾出现 5 种 `root`(`D:/gicg_goal` ×7、
`D:/gicg_dev` ×4、`D:/gicg_native`、`D:/gicg_consequence_20260914`、
`D:/gicg_retention_20260915` 各 ×1)。这是**执行期漂移,不是设计**。`docs/` 记着
机制——每次源码状态大改就另开目录,以免覆盖正在跑的 run:

- `docs/5_history/handoff_20260914_part1.md:75`「56新源码目录 `D:/gicg_goal`…
  旧 `D:/gicg_dev` 保留历史兼容」
- `docs/3_plans/cards/native_first_batch_audit.md:250`「…不能覆盖其目录。原生配置
  改独立 `D:/gicg_native`」
- `docs/3_plans/cards/consequence_policy_rl.md:18`「新独立快照
  `D:/gicg_consequence_20260914`…新模型不能复用旧权重并重标来源」
- 最新的 `D:/gicg_retention_20260915` 连 `docs/HANDOFF.md:25` 自己都标着
  "**未经用户确认**"

用户已手工删除这 4 个多余的根,56 上只保留 `D:/gicg_dev`(也是唯一持有可用 venv
的目录:`docs/5_history/handoff_20260914_part1.md:36` 记着"解释器
`D:/gicg_dev/.venv/Scripts/python.exe`,新目录 venv junction 不可用")。仓库内
**没有任何一处**记录过"每设备一个项目根"这条约定,故本 change 是它首次成文。

**结论:四个字段一起进注册表**,cfg 只写一个 profile 名。隔离由 cfg 参数与
per-run 目录(`artifacts/<ts>_<NNN>_<label>/`)承担,不由根目录承担。

### 1.2 落地形状

```toml
# configs/dmc/native_starter.toml   (tracked)
[meta]
host = "remote"          # 意图开关,语义不变

[remote]
profile = "gpu-win"      # 唯一字段:引用注册表,本身不含任何值
```

```toml
# configs/hosts/hosts.example.toml   (tracked — 新 clone 的形状说明)
[my-box]
ssh = "user@192.0.2.10"     # RFC 5737 文档保留段,不可路由
os = "windows"              # windows | linux | darwin
hostname = "DEV-PC"         # 远端 socket.gethostname(),用于 loopback 判定
root = "D:/project"         # 该设备唯一的项目根
```

真实文件 `configs/hosts/hosts.toml`(gitignored)即去掉 `.example` 的副本,四个键
不变、值换成本机实值。它是仓库内**唯一**承载真实设备值的地方,故本节不复述其
内容 —— 复述等于把真值写进 tracked 文档。

### 1.3 解析契约

`load_remote_from_cfg(cfg_path, registry_path=None)`:

| 条件 | 行为 |
|---|---|
| `meta` 缺失 / `host` 缺失 / `host == "local"` | 返回 `None`(不变) |
| `host` 既非 `local` 也非 `remote` | `ValueError`(不变) |
| `host == "remote"` 且 `[remote]` 缺失 | `ValueError`(不变) |
| `[remote].profile` 缺失或空 | `ValueError` |
| 注册表文件不存在 | `FileNotFoundError` + hint(`cp hosts.example.toml hosts.toml`) |
| profile 名不在注册表 | `ValueError`,列出可用 profile 名 |
| profile 的 `ssh` 空 / `hostname` 空 / `os` 非法 / `root` 缺失 | `ValueError`(复用现有校验) |
| `root` 混用 `/` 与 `\`,或纯 `\` | `ValueError`(不变) |

每条失败路径都 raise,**无静默回退**。注册表路径默认解析为
`<repo_root>/configs/hosts/hosts.toml`(`Path(__file__).resolve().parents[2]`,
不依赖 cwd);`registry_path` 参数仅供测试注入,不做 CLI flag——CLI 覆盖没有
真实用例,属于 YAGNI。

`RemoteCfg` 数据类形状**不变**(仍是 `ssh` / `root` / `os` / `hostname` 四字段,
`root_native` 属性照旧),只有 `load_remote_from_cfg` 的取值来源从
`cfg['remote']` 改为 `registry[profile]`。故直接构造 `RemoteCfg(...)` 的既有测试
无需改动。

### 1.4 远端侧的解析对称性

`tools/runs/train.py:141` 把 **cfg 路径本身**转发到远端重跑,所以远端会再调一次
`load_remote_from_cfg`。若远端拿不到注册表,按 §1.3 会 `FileNotFoundError`。

解法:把注册表并入 `_auto_sync` 构造 `paths` 的那一处(`_remote_sync.py:181-186`)。

关键在于**生产只有这一条同步路径**——`tools/runs/train.py:121` 以无模式参数调用
`python -m tools.runs._remote_sync <cfg>`,落到 `main()` 的默认分支 →
`_auto_sync`;`tools/runs/build_engine.py:105` 直接进程内调 `_auto_sync`。两者同
一入口,首同步与增量同步是 `_auto_sync` 内部的两个子分支,共用同一个 `paths` 列表。
故一处改动即覆盖全部生产同步:

| 同步分支 | 是否需改 | 理由 |
|---|---|---|
| `_auto_sync` 首同步(`base is None` → `git ls-files`) | **改** | git 不跟踪注册表 |
| `_auto_sync` 增量(`git diff base..HEAD`) | **改** | 同上;同一处 `paths` 构造 |
| `--tar-all` | 不改 | `REPO_DIRS` 含 `configs`,而 `_tar_and_send` 是 `tar.add(Path('configs'))` 目录遍历,gitignore 不影响文件系统遍历,注册表本就在内 |
| `--single PATH` | 不改 | 该模式契约是"只推这一个文件",并入第二个文件会破坏其语义 |
| `--git-changed` | 不改 | 文档已标注 legacy、诊断用;非生产路径 |

**不写"注册表存在才加"的条件**:`main()` 第 251 行与 `build_engine` 都先经
`load_remote_from_cfg` 解析 profile,注册表缺失时已经 raise,故到达同步分支时它
必然存在。加存在性判断就是死防御分支。

**为什么是无条件并入,而不是只并入首同步。** 远端对注册表的消费被实测收敛到
**一个字段**:`train.py:156-161` 在远端解析出 profile 后,唯一的消费点是
`is_local_host(remote)`(比较 `hostname`);判定为真即落进原子生命周期
(`train.py:163` 起),那段代码完全不碰 `remote`。其余三个字段在远端都是惰性的:
`ssh` 就是那台机器本身、`os` 只经 `root_native` 用于**本地** scp/ssh 目标构造、
`root` 则被远端忽略(远端自行从 `__file__` 推出仓库根,见下段)。

这意味着"远端注册表陈旧"只在 `hostname` 一个字段上有害,而它恰好是 R1 记录的
失败字段。若改成"只在首同步并入",则下面的链条成立且**无法通过改注册表修复**:
本地 `hostname` 写错 → 首同步把这个错值推过去 → 本地改正 → 远端仍是旧值 →
`is_local_host` 为假 → ssh 到自己 → 成环。要让修正生效,必须另外知道去删远端
`.last_synced_sha` 或跑 `--tar-all`,而没有任何东西提示这一点。

无条件并入使这条链**自愈**:改注册表即修复,不需要额外动作。这 1-2 s 的传输
成本换的是"修正动作即为充分动作"。

**已接受的后果**:`paths` 永不为空,`_auto_sync` 第 207-209 行的
"nothing to push" 快速路径不再触发,每次同步至少传一个约 1 KB 的 tar。代价是
每次 run 多一次 scp + 远端解包(约 1-2 s);而 `train` 与 `build_engine` 各同步
一次,合计约 2-4 s,对多小时训练可忽略。曾考虑先 ssh 读回远端注册表比对再决定
是否推送(可保留快速路径),但那需要在每次同步多付一次 ssh 往返来省一次 scp,
净收益约 1-2 s,却要加约 40 行与"远端文件不存在 / 内容相同 / 内容不同"三态分支
(首态的测试是必配的),属过早优化,不采纳。

**落点必须精确**:注册表以相对路径 `configs/hosts/hosts.toml` 进 tar
(`_tar_and_send` 用 `arcname=str(p)`),远端在 `cd <remote.root>` 后解包,故落在
`<remote.root>/configs/hosts/hosts.toml`。而远端 `_host.py` 的默认路径解析是
`Path(__file__).resolve().parents[2]`,远端 `__file__` 为
`<remote.root>/tools/runs/_host.py`,故 `parents[2] == <remote.root>`。两侧同址,
这正是无需在远端做任何特殊处理的原因。

于是两侧对称,无特例分支:

| 侧 | 解析结果 | `is_local_host` | 动作 |
|---|---|---|---|
| Mac | `RemoteCfg(gpu-win)` | `False`(本机 hostname 不匹配) | 同步 → ssh 转发 |
| 56 | `RemoteCfg(gpu-win)` | `True`(hostname 匹配) | 本地跑完整生命周期 |

**行为变更点**:注册表在 Mac 缺失时直接 raise,而不是静默本地跑——这正是要的
fail-loud。反之,若有人想**直接在 56 上手工执行** `tools.runs.train <remote-cfg>`
而注册表尚未同步过去,会 raise 而非直接本地跑。这条路径不被任何文档描述,且
`train.py` 的转发路径在首次运行时就完成注册表同步,故判为可接受。

### 1.5 指纹中性

`fingerprint()`(`training/core/artifact_io.py:28-43`)对下列 6 个
(`directory`, `suffix`) 组合做 `rglob` 摘要:`data`×`.lua`、`data`×`.toml`、
`gicg_engine`×`.go`、`gicg_env`×`.py`、`training/core`×`.py`、
`training/paradigms`×`.py`(跳过路径含 `tests` 者与 `*_test.go`)。

本 change 触及的路径是 `tools/`、`configs/`、以及 `training/paradigms/dmc/` 下的
`PLAN.md` 与 `notes.md`。前两者不在上表任何组合内;后者虽位于
`training/paradigms/` 之下,但**后缀是 `.md` 而该组合只收 `.py`**,故不进摘要。
即指纹中性成立的原因不是"没碰这些目录",而是"没碰这些组合**收的**后缀"。

具体来说,`MetaCfg` **不**新增 `host_profile` 字段——`profile` 放在 `[remote]`
段里,而 `[remote]` 由 `training/core/config/schema.py:23` 明写为"不参与 schema
校验、由 `tools.runs._host` 负责"。关键是 `ALLOWED_TOP_LEVEL` 只做**顶层键**检查
(`schema.py:163`:`set(cfg.keys()) - ALLOWED_TOP_LEVEL`),**不递归进段内**,故
在 `[remote]` 里加 `profile` 不需要动 `training/core/`。

`ALLOWED_TOP_LEVEL` 里保留 `'remote'` 也不是遗留物:迁移后每个远端 cfg 仍写这个
段(`profile = "gpu-win"`),该允许项仍在使用。而删它会改到 `schema.py`(位于
`training/core/` 摘要范围内),从而触发指纹变更——收益为零。

## 2. Migrations

### 2.1 cfg 迁移(14 个带 `[remote]` 段的 cfg,机器化)

对每个含 `[remote]` 段的 `configs/dmc/*.toml`(共 14 个;第 15 个
`eval_stage3_b_v_legacy.toml` 无该段,只在 Phase 3 改一行注释):

```
- ssh = "dev@192.168.31.56"
- root = "D:/gicg_goal"
- os = "windows"
- hostname = "DESKTOP-GHJCC7Q"
+ profile = "gpu-win"
```

即每个文件 `-4 / +1`。四个字段全部进注册表,**14 个 cfg 的 `root` 一并收敛**
到注册表内的 `D:/gicg_dev`;各文件原本写的值不再保留——它们是 §1.1 的漂移,
且其中 4 个指向已删目录。迁移后 `[remote]` 段只剩 `profile` 一行。

### 2.2 本地一次性动作(不随代码交付)

使用者需在本地创建 `configs/hosts/hosts.toml`,为 `[gpu-win]` 填入 `ssh` /
`os` / `hostname` / `root` 四个真实值。`hosts.example.toml` 与
`FileNotFoundError` 的 hint 共同承担"怎么建"的说明。这不是本 change 的代码
产物,但 tasks.md 把它列为交付前置。

### 2.3 `tools/_bench/run_win_collector_pair.py`

删除模块常量 `_WIN_SSH` / `_WIN_ROOT`,改为经注册表解析(新增 `--host-profile`,
默认 `gpu-win`)。第 158 行的输出行改用解析出的 `ssh`。其 `subprocess` 直接调
`ssh` 的历史问题不动(见 proposal.md §Out of scope)。

## 3. Tradeoffs

### T1 — 不改 `training/core/`,接受 `[remote]` 留在 `ALLOWED_TOP_LEVEL`

| 方案 | 优点 | 缺点 |
|---|---|---|
| **A(选定)** — `profile` 放 `[remote]`,`training/core/` 零改动 | 指纹保持 `ff423c96…`,不额外作废权重;`ALLOWED_TOP_LEVEL` 只查顶层键,故 `profile` 零改动可加;`[remote]` 已有"不参与 schema 校验"的成文先例 | `[remote]` 段内容继续不由 schema 层校验——但这是**改动前就有的状态**(`schema.py:23-24` 早已如此声明),不是本 change 引入的代价 |
| B — `profile` 提为 `[meta].host_profile`,加进 `MetaCfg`;`[remote]` 从 `ALLOWED_TOP_LEVEL` 删除 | cfg 契约更整齐,无死允许 | 触发指纹变更,须同步改 3 个文件 4 处的指纹记录值(`docs/0_status/README.md` ×2、`docs/HANDOFF.md`、`docs/HANDOFF_PAUSED.md`) |

选 A 的理由:本轮权重无论如何都要从头重训(指纹已在上一轮变为 `ff423c96…`,
`artifacts/pause_20260914/checkpoints/` 已清空),所以"省一次指纹"的收益看似
不大;但 B 的另一个后果是**再次全面作废**——即便当下没有有效权重,把指纹变更
混进一次脱敏改造会让"指纹值 ↔ 源码状态"的对应关系多一次无谓跳变,增加日后
回溯成本。而 A 的代价只是"`[remote]` 段继续不由 schema 层校验",这本就是改动前
的状态,故 A 实质零代价。

### T2 — 注册表 vs 每 cfg 一个 local override 文件

| 方案 | 优点 | 缺点 |
|---|---|---|
| **A(选定)** — 单一注册表,cfg 写 profile 名 | 改 IP 或改设备根只改一处;14 个 cfg 共享同一 profile,无漂移;新增 cfg 只需一个不含敏感值的名字 | 多一层间接 |
| B — 每 cfg 一个 gitignored 的 `<name>.local.toml` | 粒度最细;复用现有 `extends` 机制 | 14 份近乎重复的 gitignored 文件,IP 变更要逐个改;且每份各自写 `root`,等于把 §1.1 的多根漂移制度化,故与"每设备一个项目根"直接冲突 |

### T3 — 远端无注册表时的行为

| 方案 | 结论 |
|---|---|
| **同步注册表到远端(选定)** | 两侧解析完全对称,无特例分支 |
| 用 `artifacts/.authoritative_host` 作"本机即权威机"的逃生 | 该 marker 是否已在 56 上存在**无法验证**(设备关机),引入未验证依赖;且注册表同步成功后它就是死代码,违反 CLAUDE.md "Dead defensive code 必须删" |

### T4 — 占位符取值

`192.168.31.56` → `192.0.2.10`(RFC 5737 TEST-NET-1,保留且不可路由),而非
替换成另一个私网段或 `HOST_IP` 之类的非地址串。理由:占位符必须一眼可辨为假,
同时保持示例在形状上可复制。`DESKTOP-GHJCC7Q` → `DEV-PC`,沿用本仓库
`_host.py` docstring 里已有的通用示例值。

## 4. Risks

### R1 — `hostname` 配错导致远端自转发成环(高影响 / 低概率)

若注册表里 `hostname` 与 56 的 `socket.gethostname()` 不符,56 侧 `is_local_host`
返回 `False` → `_dispatch_remote` → ssh 到自己 → 无限转发。

现状同类风险已存在(CLAUDE.md 与 `docs/5_history/handoff_20260914_part3.md:14`
都记着"配 cfg 前必须先 ssh 实测 hostname",并记载过 `DEV-PC` vs
`DESKTOP-GHJCC7Q` 的错配事故)。本 change 把该风险从 14 处收敛到 1 处,是净改善,
但**不引入新的防环机制**——防环需要远端侧的身份自证,超出本 change 范围。

**回滚预案**:注册表是单文件,改错直接改回;不涉及代码回滚。

### R2 — 注册表未同步到远端(中影响 / 低概率)

首次在新机器上跑会走全量同步分支;若漏加注册表,远端会
`FileNotFoundError` 而非静默跑错。**fail-loud 保证失败可见**,不会产生错误产物。
tasks.md 的 Phase 4 用端到端验证覆盖这一路径。

### R3 — 脱敏后的文档可读性下降(低影响 / 确定发生)

`training/paradigms/dmc/notes.md` 等 runbook 里的 `ssh dev@192.168.31.56 '...'`
替换为占位符后不再可直接复制执行。已接受的代价:这些是历史记录,不是活文档。
LIVE 文档(`docs/0_status/README.md:66`)的指引改为指向
`configs/hosts/hosts.example.toml`,不写死值。

### R4 — 脱敏遗漏(中影响 / 中概率)

三项标识分散在 50 个文件的 78 处,人工替换易漏。缓解:tasks.md Phase 3 以
`git grep` 全仓复核为出口条件,列入验收而非仅作为过程检查。

### R5 — 14 个 cfg 收敛到单一根后的共享面扩大(低影响 / 确定发生)

迁移后 14 个 cfg 全部指向 `D:/gicg_dev`,而迁移前只有 4 个指向它。于是这些共享
面从"部分 cfg"扩到"全部 cfg":

- `tools.runs.build_engine <cfg>` 构建的 `libgicg.dll` 落在该根,一次构建影响所有
  以它为目标的 cfg;
- `discover_remote_python` 在该根下探测 `.venv|venv|env|.virtualenv`,故 venv 变更是
  全局的;
- `artifacts/` 与 NNN 计数器同根共享——这正是本设计的目的(§1.1),不是副作用。

这是两条路径各自本来就有的性质,不是本 change 引入的新机制;但覆盖面从 4/14 变
14/14,故记录在案。**不设隔离机制**:按每 cfg 一个根来隔离,正是 §1.1 判定为漂移
而被废止的做法。
