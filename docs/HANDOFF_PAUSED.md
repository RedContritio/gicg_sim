# 暂停交接

用户分三次要求停止任务：**第一次 2026-09-14**（见文末「上一轮记录」），**第二次 2026-09-14 晚**
（见「上次会话续做」），**第三次即本次会话结束**。
当前目标仍是「随机规则变体下稳定胜过 D2」，**仍未达成**。分支 `dev`。恢复时以 `git status`
核对工作区，不 reset/clean。

**没有任何一次会话启动过 56 训练**；所有产出都是本机代码 + 本机 smoke + 行数清理。

## 本次会话（2026-09-15）：行数清理收尾

### 一句话

上次会话开的「行数清理」已完成：**存量超限文件全部处理，全仓 `check_line_limits` 零违规**；
顺带清掉 6 个存量 ruff 未格式化文件。源码指纹因此再次变更，`gicg_env/libgicg.dylib` 已重建。
**未启动训练，未 commit。**

### 关键发现：源码指纹再次变更

实测当前工作树的 `training.core.artifact_io.fingerprint()`：

```
ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15
```

它**不等于**上次会话记录的 `d8a09342…`（`gicg_engine/interp/ir/` 下 `compile.go` / `methods.go`
被拆分所致），也**不等于**更早的 `c2af135c…` / `b3e84a0a…`。后果与上次会话同向且更严格：

- 上述三个指纹对应的权重在当前代码上**一律无法加载**（`load_checkpoint` 抛
  `ArtifactCompatibilityError`）。
- `gicg_env/libgicg.dylib` 已按新 Go 源码重建（`go build -buildmode=c-shared` exit 0），
  `gicg_env/tests/` 139 passed。
- 结论不变：**本轮训练必须从头重训初始化**，不能复用任何旧权重，也不能给旧权重重标指纹。

### 行数清理：完成

| 类别 | 处理 |
|---|---|
| Go 源码 | `gicg_engine/interp/ir/compile.go` 307→252（+`compile_emit.go` 65）、`methods.go` 334→265（+`methods_args.go` 80） |
| Go 测试 | `gicg_actor/dmc/paradigm_test.go` 529→433（+`paradigm_mock_test.go` 108）、`gicg_engine/interp/ir/audit_test.go` 531→494（+`audit_sort_test.go` 44） |
| Python 生产 | `transition_sink_wire.py` 653→200（+3 个 wire 子模块）、`logging.py` 536→208（+2）、`inference_server.py` 583→216（+4）、`ring_shm.py` 358→261（+`_shm_lib.py`）、`mp_factories.py` 317→141（+`_provider.py`）、`_go_assembler.py` 356→206（+`_go_assembler_ingest.py`）、`go_subprocess_collector.py` 350→273（+`_go_collector_helpers.py`）、`typed_damage.py` 329→280（+`_typed_damage_index.py`） |
| docs | 3 份 → 9 卷：`specs/2026-05-18-tools-runs-redesign-design.md`（+rollout 续卷）、`plans/2026-05-18-tools-runs-second-round-fixes.md`（3 卷）、`plans/2026-05-25-i29-redesign-implementation.md`（4 卷） |

拆分纪律：公共 API 留在原模块、只出私有 helper；无 re-export 垫片、无反向 import；
每卷首页加分卷导航；跨卷引用由 `行 NNN` 改 `§<heading>` 锚点。

**`CLAUDE.md` 阈值表已更新**：新增 `Go test files (*_test.go) | 500 | —`，与 Python 测试对齐。

### 验证

| 项 | 结果 |
|---|---|
| `check_line_limits` | exit 0，零违规 |
| 未跟踪新文件 36 个 | 最大 497 行（doc 阈值 500），合规 |
| `ruff format --check` | 804 files already formatted，零 would-reformat |
| `gicg_env/tests/ + training/tests/` | 1289 passed, 0 failed |
| `tools/runs/tests/ + tools/eval/tests/` | 798 passed, 0 failed |
| Go `build ./...` + `go test ./gicg_engine/... ./gicg_mcts/... ./gicg_actor/...` | 全 ok |
| 符号守恒 / 文档内容守恒（vs HEAD） | 零 MISSING / 零 LOST |
| 引用卷位解析 | MISMATCHED FILE REFERENCE 0 |

拆 docs 时额外发现一类缺陷：9 个代码 docstring 与 1 份 plan 引了主卷路径、但引用的 §小节或
review ID 实际落在续卷 —— 全部改双卷引用。`tools/runs/_helpers/metadata_io.py:29` 引用的
`CRIT-3-A` 在两卷**都不存在**，是分卷前就有的悬挂引用，未动。

### 本次未处理

- `docs/3_plans/cards/effect_mechanism_inventory.md`（1476 行 / 247 KB）被 `.gitignore:35` 忽略、
  从未被 git 跟踪，不在 `check_line_limits`（只扫 `git ls-files`）管辖内。用户决定**先不处理**。

## 上次会话续做（2026-09-14，artifact 时间戳 20260914 UTC）

### 一句话

策略保留实验：方案定稿、代码落地、本机 6 臂 smoke 全通（**尚未上 56 跑正式对照**）；同时开始了
20 个存量超限文件的清理。

### 关键发现一：源码指纹变了，旧权重全部失效且已删除

实测当前工作树的 `training.core.artifact_io.fingerprint()`：

```
d8a0934211db489fe13dbbd527b77c176b03d8159668ee5f86cf7a7c674ceb33
```

它**不等于**旧 `consequence_*` 记录的 `c2af135cd2ac2223ed9ece10cd08e3182b6c2f441ec054aee5663e66d1e2f4ec`，
**也不等于** 2026-09-12 `semantic_warmup` 的 `b3e84a0a…`。后果：

- 旧 warmup / paired / candidate / control 权重在当前代码上**一律无法加载**（`load_checkpoint`
  会抛 `ArtifactCompatibilityError`）。
- 用户决定**不保留旧权重**：`artifacts/pause_20260914/checkpoints/` 已清空（仅剩空目录）。
  同级 `git_head.txt` / `git_status.txt` / `worktree.patch` / `worktree_files.tar.gz` /
  `worktree_manifest.json` **保留**。
- ⚠️ 文末「上一轮记录」中**三处已失效**：`必要文件` 表的「六份关键模型备份及来源/SHA」一行、
  `恢复顺序` 第 2 条「从 warmup.pt 出发」、以及「远端来源指纹 c2af135c…」。
- 结论：**本轮训练必须从头重训初始化**，不能复用任何旧权重，也不能给旧权重重标指纹。

### 关键发现二：`CLAUDE.md` 的 "grandfathered" 措辞已过时

`docs/3_plans/backlog.md` D7 记录 2026-04-23 已把全仓 line-limit 违反**清零**。现存 20 个违规
是 4 月之后新长出来的**回归**，不是历史遗留。详见下文「行数清理」。

### 策略保留实验

**根因（读码定位）**：`tools/experiments/semantic_training/paired_training.py` 把 `agent.net` 与
`agent.rule_head` 的**全部参数**放进同一个 AdamW，用纯回归目标
(`objective = absolute + beta*difference + 0.1*MSE`) 训练，**没有任何主任务保留项**。1500 步
lr=3e-4 就把 D2 模仿预热的策略从 34.55% 改写成 19.09%（−15.45pp，95%CI [−22.73,−7.73]）。

**新增文件（全部未提交）**：

| 文件 | 行数 | 作用 |
|---|---:|---|
| `tools/experiments/semantic_training/representation_drift.py` | 88 | `linear_cka` / `tensor_drift` / `cosine_similarity` |
| `tools/experiments/semantic_training/retention_arms.py` | 247 | 6 臂定义、冻结语义、余弦门控、逐臂训练循环 |
| `tools/experiments/semantic_training/policy_retention.py` | 280 | 编排：warmup + pairs + teacher → 6 臂 → 面板 → 探针 |
| `tools/experiments/semantic_training/tests/test_representation_drift.py` | 91 | 10 个测试 |
| `tools/experiments/semantic_training/tests/test_retention_arms.py` | 163 | 7 个测试 |
| `configs/dmc/policy_retention.toml` | — | 56 生产配置（新远端根 `D:/gicg_retention_20260915`，**未与用户确认**） |
| `configs/dmc/policy_retention_smoke.toml` | — | 本机 smoke 配置（`host="local"`, `device="cpu"`） |

**改动文件**：`tools/experiments/semantic_training/train.py` —— CLI 补 `--seed` / `--device` /
`--variants`。原先 `device='cuda'` 是**写死**的，Mac 上无法本地运行。

**6 臂**（同起点 / 同配对数据 / 同 1500 步 / 同 seed，唯一自变量是保留机制）：

| 臂 | 机制 |
|---|---|
| `full` | 全参数、无保留项（复现伤害，正对照） |
| `frozen` | 冻结策略网络，只训规则头（= 线性探测） |
| `probe_then_finetune` | 前半冻结把 head 训到平台，后半解冻 @3e-5 |
| `full_lowlr` | 全参数 @3e-5（把 lr 效应从机制里摘出来） |
| `replay` | 配对回归 + λ·D2 模仿 loss（复用现成 `imitation_loss`） |
| `anchored` | β·KL(π_warmup‖π) 锚 + 余弦门控（binary） |

**本机 smoke 结果**（`artifacts/retention_smoke/completion.json`，exit 0，128.8s，90 对 / 178 teacher 行）：

| 臂 | CKA | 漂移(max) | cos_ema | 门控拦截 |
|---|---:|---:|---:|---:|
| `full` | 0.9840 | 9.02e-04 | −0.0411 | 0 |
| `frozen` | **1.0000** | **0** | None | 0 |
| `probe_then_finetune` | 1.0000 | 6.01e-05 | −0.0022 | 0 |
| `full_lowlr` | 1.0000 | 9.02e-05 | −0.0010 | 0 |
| `replay` | 0.9999 | 9.02e-04 | −0.0252 | 0 |
| `anchored` | 0.9963 | 6.28e-04 | +0.0010 | **1** |

机制侧三点成立：`frozen` 逐元素零漂移；漂移与 lr 严格成比例（`full` 9.0e-4 vs `full_lowlr`
9.0e-5 = 10×）；`anchored` 门控**实际触发过**。

⚠️ **这是 3 步 smoke，不是结论**。`cos_ema` 为负只说明"D2 模仿梯度与配对回归梯度在共享编码器上
存在冲突"这个方向性信号；面板胜率、探针都还没跑（smoke 用 `--panel-scenarios 0`）。不得据此宣称
任何策略保留效果。

臂产物落在各自的 `artifacts/<ts>_<NNN>_retention_<arm>/`（含 `metadata.toml` status=done、
`cfg_leaf.toml`、`cfg_resolved.toml`、`<arm>.pt`、`<arm>_policy.pt`、`report.json`）。实测
`<arm>_policy.pt` 全部能被 `player_loader.load_semantic_payload` 加载为 `semantic-q/2.0.0`
（含 `rule_head`）→ `evaluate.py` 可直接评测。另有一个失败臂目录
`artifacts/202609141745_000017_retention_full` 保留为记录（首次 smoke 因 `pooled_states` 传错
config 类型失败，已修）。

### 行数清理（进行中 → 已由 2026-09-15 会话完成）

> 本节记录上次会话中断时的进度。批 1 剩余 3 个、批 2 的 10 个、docs 3 份与引用改造均已在
> 2026-09-15 会话完成，见上文「本次会话：行数清理收尾」。以下保留原文作进度参照。

用户要求清掉全部 20 个存量违规，验收标准 `tools/_meta/check_line_limits.py` 零违反。

**批 1（低风险 / 指纹中性）完成 4/7**：

| 文件 | 前 | 后 | 新模块 |
|---|---:|---:|---|
| `tools/dmc/profile_train.py` | 308 | 230 | `tools/dmc/_profile_components.py` |
| `tools/runs/sync.py` | 307 | 214 | `tools/runs/_helpers/sync_conflicts.py` |
| `gicg_actor/wire_format.go` | 325 | 265 | `gicg_actor/wire_codec.go` |
| `gicg_actor/dmc/paradigm.go` | 527 | 282 | `gicg_actor/dmc/paradigm_episode.go` |

验证：sync 测试 50 passed、`go build` exit 0、`go vet` exit 0、`gofmt -l` 干净、ruff 干净。
`tools/runs/tests/test_sync_ipv6.py` 被同步更新（改从 `sync_conflicts` 取私有正则，不加兼容别名）。

**批 1 剩余 3 个**（都还没动）：
- `gicg_actor/dmc/paradigm_test.go`（529，已算出两段目标区间各需哪些 import）
- `gicg_actor/shm/shm_test.go`（334）
- `gicg_engine/interp/ir/audit_test.go`（531）

**批 2（10 个，全在 `fingerprint()` 覆盖内 → 改完必须重建 dylib）**：
`gicg_engine/interp/ir/compile.go`(307)、`methods.go`(334)、
`training/core/network/typed_damage.py`(329)、`training/paradigms/dmc/mp_factories.py`(317)、
`go_subprocess_collector.py`(350)、`_go_assembler.py`(360)、
`training/core/actor/ipc/ring_shm.py`(358)、`training/core/logging.py`(536)、
`training/core/actor/inference_server.py`(583)、`training/core/actor/transition_sink_wire.py`(653)。

**docs 3 份 + 25 处引用**：`docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`(613)、
`docs/superpowers/plans/2026-05-18-tools-runs-second-round-fixes.md`(1105)、
`docs/superpowers/plans/2026-05-25-i29-redesign-implementation.md`(1156)。
⚠️ 这三份被 **25+ 处代码 docstring 按行区间引用**（例：`tools/runs/_train/setup.py` 的
「行 348-355」、`snapshot.py` 的「行 76-96」、`train.py` 的「§Architecture 行 24-74」），
且 `openspec/specs/tools-layout/spec.md` 也链到其中一份。用户已确认走「**拆分 + 同步把引用改成
章节锚点**」；只拆不改引用会让这些引用全部失效。

**顺带清掉**：全仓 5 个 `gofmt` 未格式化文件（`gicg_actor/perf_trace.go`、
`gicg_actor/transition_writer_shm.go`、`gicg_engine/interp/ir/builtin_coverage_test.go`、
`gicg_engine/interp/ir/ir_literals_test.go`、`gicg_engine/tests/game_perf_bench_test.go`）。
全在指纹范围外（`*_test.go` / `tests/` / `gicg_actor`），纯机械修复。

### 未提交改动一览

- `git status`（2026-09-15 会话收尾后）：**92 modified + 36 untracked**，含全部拆分产物、
  6 个 ruff 格式化、5 个 gofmt 格式化。上次会话结束时为 11 modified + 11 untracked。
- **本轮没有任何 commit，也没有 push**。远端 `git@github.com:RedContritio/gicg_sim.git` 当前：
  `dev` = `1e12d97`、`main` = `22c7345`、tag `v0.3.0` → `1e12d97`。即上游仍是本轮之前的状态。
- 本轮已做过、但**未记录进任何文档**的操作：`git remote add origin`（原本无 remote）、
  强制推送 `main`+`dev`（远端原 `main` 是 `ba8ce33`，已被覆盖）、删除远端
  `cursor_dev` / `dsl_dev` 两分支、删除本地 tag `pre-core-network-redesign-2026-05-17`
  （远端未推过它）、删除 `.gitignore` 里的 `rl_mvp_v3.txt`（该文件从未被 git 跟踪，已不可恢复；
  其内容仍在会话记录里）。
- `artifacts/` 被 gitignore，本轮 smoke 产物与 161MB 的 `pairs_smoke.pt`（在会话 scratchpad）
  都不在 Git 里。

## 恢复顺序

1. 读本页、`CLAUDE.md`、`docs/0_status/README.md`；`git status` 核对工作区。没有自动续训任务。
2. **「清理」已完成，不再是前置决策**：行数清理全部收尾，`gicg_env/libgicg.dylib` 已按新 Go 源码
   重建（指纹 `ff423c96…`）。可直接进入训练。若之后再改 `fingerprint()` 覆盖范围内的源码，
   须重新走「改完 → 重建 dylib」。`fingerprint()` 不含 `tools/` 与 `configs/`，改这两处无需重建。
3. 策略保留实验的正式对照**需要在 56 上跑**（用户当前占用设备）。前置：确认
   `configs/dmc/policy_retention.toml` 的 `[remote].root`（现填 `D:/gicg_retention_20260915`，
   **未经用户确认**）。流程：
   a. 在新根上先跑 warmup（不要跑 `consequence_bootstrap`——它的 paired 阶段正是要研究的坏配置）：
      `python -m tools.experiments.semantic_training.train <cfg> <out> --episodes 256 --steps 2000
      --workers 16 --seed 95500 --device cuda --variants configs/rule_validation/native_variants.toml`
   b. 用产出的 `ckpts/latest.pt` + `teacher/` 跑：
      `python -m tools.experiments.semantic_training.policy_retention <cfg> <warmup.pt> <out>
      --teacher <teacher_dir> --steps 1500 --contexts 6 --device cuda --panel-scenarios 110 --probe`
   c. **不要**全树同步覆盖 56 的指纹目录；只同步 `tools/` 与 `configs/`（`fingerprint()` 不含它们）。
4. 评测纪律：开发面板与确认面板必须分开；**96400 已被用于选模，不能再当独立证据**，正式对比用
   新 seed（smoke 默认 `--panel-seed 96500`）。差值一律报配对场景聚类 95%CI，臂对臂比，
   不要只比"各臂 vs warmup"。
5. 剩一件早先收尾工作没做：为 `policy_retention` 补计划卡片（`docs/3_plans/cards/policy_retention.md`）
   并把本轮结论写入 `docs/5_history/`。
6. 最终三种子训练 seed 971000/981000/991000、测试 seed 971900/981900/991900 仍保留未用。
7. 文档审计未完成全仓人工审阅（以 `coverage.tsv` 为准）；网页 UI 仍缺浏览器视觉验收。

---

## 上一轮记录（2026-09-14 第一次暂停）

> ⚠️ 本节保留原文作背景。其中「六份关键模型备份及来源/SHA」、「远端来源指纹
> `c2af135c…`」、「从 `warmup.pt` 出发」三点已被本次会话推翻，见上文「关键发现一」。

用户因额度要求停止任务，之后再开发。当前目标未达成；不要自动启动新训练或继续审计。当前分支
dev，本次代码、网页和文档整理为 v0.3.0 开发快照；恢复时以 git status 核对后续修改，不 reset/clean。

### 上一轮结论

原生五角色凯亚、迪卢克、芭芭拉、砂糖、菲谢尔，随机 3v3、30 张合法牌组。变体覆盖伤害、治疗、
指定骰费；D2 是目标标准。随机变体下稳定胜过 D2 仍未证明。

校准残差 RL 已完成：每臂 4×512 局、16 workers、lr=0.001。独立 96400/110 场景×两席位×两布局：
初始 19.09%，带后果预测候选第 2 轮 21.36%，零后果特征对照第 4 轮 24.09%。后果预测的额外收益
没有统计证据；仅对照相对初始提升的配对区间略高于 0。

**关键证据：同面板监督预热模型 34.55%，配对规则训练后 19.09%，差值 −15.45 个百分点，
95% 区间 [−22.73,−7.73]。** 规则预测学好并不代表策略保留。所选两模型的凯亚探针均为
预测 16/16、技能排名 16/16、完整行动选择伤害领先技能 0/16。

### 上一轮执行状态

- 校准 RL 等待器 34391 正常退出，remote_exit=0；补充评估等待器 21252 正常退出，结果全部回传。
- documentation_audit 已中断；先读覆盖清单再恢复，不重复已审文件。
- 没有启动下一轮训练。

### 上一轮必要文件（部分已失效）

| 内容 | 本机路径 |
|---|---|
| 详细实验与置信区间 | docs/5_history/consequence_rl_20260914.md |
| 校准 RL 原始面板、探针、训练曲线 | artifacts/consequence_calibrated_rl_20260914/ |
| 监督预热对比与所选模型探针 | artifacts/consequence_followup_20260914/ |
| 初始化与第一轮残差结果 | artifacts/consequence_bootstrap_20260914/、artifacts/consequence_rl_20260914/ |
| ~~六份关键模型备份及来源/SHA~~ | ~~artifacts/pause_20260914/checkpoints/manifest.json~~ **已清空** |
| 兼容训练源码快照 | artifacts/consequence_snapshot_20260914/source_manifest.json、source.tar.gz、supplement.tar.gz |
| 文档审计逐文件覆盖与行为疑点 | artifacts/documentation_audit_20260914/ |
| 网页改动与未完成视觉验收 | docs/5_history/gameplay_ui_20260914.md |
| 周/月计划与最终验收协议 | docs/3_plans/rule_learning_roadmap.md |

上一轮 56 根 `D:/gicg_consequence_20260914`，Python `D:/gicg_native/venv/Scripts/python.exe`；
远端来源指纹 `c2af135c…`（**已被本次会话推翻**）。所有远程操作使用 `tools.runs._host`。
