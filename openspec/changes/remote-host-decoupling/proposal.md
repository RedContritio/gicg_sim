---
last_updated: 2026-09-15
status: DRAFT
schema_version: 0
---

# remote-host-decoupling — 把远端主机标识移出公开仓库

## Why

`git@github.com:RedContritio/gicg_sim.git` 是 **public** 仓库(`gh repo view`
实测 `isPrivate: false`,fork 0 / star 0 / watcher 1)。当前 HEAD 已跟踪设备
与网络标识:

| 标识 | 已跟踪文件数 | 命中处数 | 主要载体 |
|---|---|---|---|
| `192.168.31.56` | 43 | 54 | `configs/dmc/*.toml` 的 `[remote].ssh`、`tools/runs/_host.py`、`tools/eval/daemon.py`、`tools/_bench/run_win_collector_pair.py`、`docs/`、openspec archive、`training/paradigms/dmc/` |
| `DESKTOP-GHJCC7Q` | 33 | 33 | 同上(cfg `[remote].hostname` + 各 bench 报告页首) |
| `Mac-mini.local` | 3 | 3 | `docs/5_history/small_rl_v14.md`、`docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`、`tools/runs/tests/test_schema.py` |

按**标识**分别计 54 / 33 / 3 处,但 12 行同时含前两项(全部是
`tools/_bench/p2_results/*.md:5` 的 `Box:` 行),故去重后并集为
**50 个文件 / 78 处**。按目录:`configs/` 15 文件 29 处、`tools/` 20 文件 23 处、
`docs/` 10 文件 14 处、`openspec/` 3 文件 4 处、`training/` 2 文件 8 处。

全类别审计(12 类正则 × `git ls-files`)未发现任何凭据:无私钥、无 API
token(`sk-` / `ghp_` / `github_pat_` / `AKIA` / `xox`)、无密码或 key 赋值、
无 MAC 地址、无凭据类文件名(`.env` / `id_rsa` / `known_hosts` / `*.pem`)。
故泄露面是**网络拓扑与设备标识**,不是访问权。

真正的问题是形状:`[remote]` 的四个字段**全是设备级**的(`ssh` / `os` /
`hostname` 决定是哪台机器,`root` 决定该机器上唯一一个项目根),却被逐 cfg 抄了
14 份。后果有两层:一是每次新增实验 cfg 都继续扩散设备标识;二是 `root` 一旦被
当作 cfg 级字段,就会被执行期随意另开目录——实测曾出现 5 种取值,而每个项目根各自
持有一套 run 索引与 NNN 计数器(`artifacts/` 不参与同步),多根会直接使
`show <NNN>` / `mark <NNN>` 的 shorthand 失效(design.md §1.1)。

## What

1. **设备级字段全部外置。** `[remote]` 的 `ssh` / `os` / `hostname` / `root`
   四字段移入 gitignored 的 `configs/hosts/hosts.toml`,cfg 侧只留一个
   `profile = "gpu-win"`。用户已手工删除 4 个多余的远端根,56 上只保留
   `D:/gicg_dev`。
2. **注册表随同步到远端。** `_remote_sync._auto_sync` 在构造待推送文件列表处
   并入该文件(gitignored 文件不在 `git ls-files` / `git diff` 里,必须显式加),
   使远端与本地用同一份 profile 解析,不引入特例分支。生产两条入口
   (`train.py` / `build_engine.py`)都经此处。
3. **HEAD 脱敏。** 把三项标识在已跟踪文件中的出现替换为占位符
   (`192.0.2.10` / `DEV-PC` / `macbox.local`)。
4. **不重写历史。**

## Affected specs

- `openspec/specs/tools-layout/spec.md` —— 不变量 #17 被 MODIFY,并新增
  #22–#24(注册表归属、fail-loud 契约、同步义务)。

## Out of scope

- **`git filter-repo` / force push / tag 重打。** 用户明确选择不重写历史。已
  发布的 `dev`=`1e12d97` / `main`=`22c7345` / tag `v0.3.0` 保留原样。因此
  `1f6e3c4`(2026-04-11)的 author email `redcontritio@Mac-mini.local` 保留在
  commit 元数据里,不清理——这是本 change 无法覆盖的唯一残留项。
- **macOS 用户名与本地绝对路径。** `/Users/redcontritio/...`、
  `redcontritio@qq.com`、`RedContritio`(GitHub 身份,远端 URL 本身就是它)
  保留。
- **远端目录名。** 已入库文档中的 `D:/gicg_*`(历史记录,如 `docs/5_history/`、
  `docs/3_plans/cards/`)保留,用户判定为非敏感。cfg 层迁移后不再出现任何 `root`。
- **远端多根目录的清理。** 用户已手工删除 `D:/gicg_goal` / `D:/gicg_native` /
  `D:/gicg_consequence_20260914` / `D:/gicg_retention_20260915`,56 上只留
  `D:/gicg_dev`。本 change 只把"每设备唯一一个项目根"这一事实写进规约与注册表,
  **不列任何远端清理任务**,也不处置那 4 个根里遗留的 `artifacts/`。
- **代码层零改动**:`training/core/` 完全不碰;`training/paradigms/` 下只改两个
  `.md`(`dmc/PLAN.md`、`dmc/notes.md` 里的 runbook 命令),不动任何 `.py`。
  `fingerprint()` 因此保持
  `ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15`,
  不额外作废权重。详见 design.md §1.5 与 §Tradeoffs T1。
- **`tools/_bench/run_win_collector_pair.py` 绕过 `tools/runs` ssh wrapper。**
  该脚本直接 `subprocess.run(['ssh', ...])`,与"走 `tools/runs/*` ssh
  wrappers"的约定相抵触。本 change 只把它的硬编码主机常量改为注册表解析,
  不重写其 ssh 调用路径。
- **远端 e2e 验证。** 设备当前关机,无法执行。它是本 change 的真验收门槛,
  见 tasks.md §Phase 4。
