# 旧状态页存档（非当前状态）

以下保留旧记录，不能作为当前训练状态。当前见 [实时入口](../0_status/README.md)。

---
last_updated: 2026-09-12 (v15：每局shuffle与三种子试验完成，未通过稳定门槛)
status: LIVE
---

# Status — 现在在哪

## 新 session 第一站

> 进入 docs 的第一站。读完这一页 30 秒应能回答:**现在在干什么 / 困难是什么 / 下一步怎么走**。
>
> 三个入口互补:
> - **OpenSpec**(规约 + change workflow): [`openspec/project.md`](../../openspec/project.md) — 项目层 spec / SHALL invariants
> - **Paradigm landscape**(科研复盘): [`docs/paradigms/README.md`](../paradigms/README.md) — 5 paradigm × verdict × 数据
> - **本页**(LIVE 状态):当前 phase / 困难 / 下一步
>
> docs/ 编号导航(P1 后): `0_status` → `1_specs` (待迁 `openspec/specs/`) → `2_decisions` (已迁 `openspec/changes/archive/`,mirror 保留) → `3_plans` (active only) → `4_runs` (experiment log) → `5_history` (archived plans + 复盘)。
>
> LIVE 状态文件:phase / 里程碑 commit 内更新。

2026-09-12补充：用户已授权v15从3k续训到30k，阶段6k/12k/20k/30k。
新增评估对手“技能滥用者”，按原始费用的能量/异色优先/指定数量/同色/任意排序。
评估已升级v17：16项测试及640局校准通过；加入50%D1、D1，技能滥用者限每技能每回合两次。
当前本机已完成提交前重构v0.1.0及异步种子统计修复；验收见`openspec/changes/submission-refactor/`。
远端已停止的训练仍绑定v17清单与v15生产指纹，续跑须使用其原始代码，不能直接使用本机新来源。
用户已要求停止本机三个分支与监控；保存进度6010/6515/6018，见`artifacts/extended_shuffle_v15/stop_record.json`。
已完整迁移至`.56`并启动三个CUDA serial分支，恢复6010/6515/6018→30k。
用户要求使用电脑，远端已于北京时间19:45:00停止训练、评估与监控，无残留进程；保留检查点，未经指示不自动重启。
开发109000、最终110000及评估v17继续保留。

## 当前推进路线（新 session 必读）

[从动态执行到完成训练的方案与交接清单](../3_plans/dynamic_execution_to_training.md)
是当前执行路线。保留动态计算与可靠的重放恢复，只按正确性、表达或性能证据迁移暂停路径。
**完整解释器帧化及删除重放不再是开训前提**；旧 v7/v9 未完成项不是当前强制顺序。
阶段 1、2 的当前 1v1/2v2 环境 gate 继续通过。v14 已补调和动作语义、数值编码、
DMC 初始化/探索 RNG、CFR/AZ 引用生命周期与 PPO 动作容量保护；serial DMC 现可保存
完整经验池、采样器和历史对手状态，连续/中断恢复逐项一致测试通过。
**当前小范围 RL 前准备已完成**：2153项回归通过、五范式完整smoke 10项通过；
规则/目标辅助任务三个种子全部100%，目标信息抹除后50%。
以下为v14历史验收；当前shuffle增量已冻结为 `episode-layout-v15`。
旧 `tools.experiments.pre_rl` 固定校验v14，不适用于本轮；使用新manifest显式检查。
[v14 验收报告](../../openspec/changes/pre-rl-ready-v14/results.md)与
[验证状态](../../openspec/changes/pre-rl-ready-v14/verification.json)是该版本历史验收入口。
首次小范围 RL 已按 [短程 RL 协议](../../openspec/changes/pre-rl-ready-v14/rl-protocol.md)
完成：run 000001–000003，种子41/42/43实际3009/3004/3006frames，完整896局评估。
**未通过稳定学习门槛**：最终对随机得分84.38%/31.25%/90.63%，种子42明显退步；
对F1-D2平均改善6.77个百分点。详见 [完整实验报告](../5_history/small_rl_v14.md)。
有界诊断已完成：42出现过早结束，32局后验干预将开发集对随机得分43.75%提升至87.5%。
详见 [诊断报告](../5_history/small_rl_v14_diagnosis.md)。用户同意检验“更多训练能否纠正”，
已完成 [固定12000frames续训](../5_history/extended_rl_v14.md)：run 000004–000006，
实际12019/12007/12017frames；外层监测验证不影响训练/RNG，原三组检查点未覆盖。
新测试105000：对随机82.81%/45.31%/93.75%，对F1-D2为34.38%/1.56%/57.81%。
平均F1-D2改善7.81个百分点，但42仍未胜过随机，主判据未通过；不能推断更多训练必然无效。
差异诊断已完成，见 [排列覆盖与策略时间差](../5_history/layout_diagnosis_v14.md)：
serial训练每种子一直保留同一种观测排列；同一游戏状态换排列可改变动作类型。
训练2.6%是历史策略行为；最终权重回放同一批训练状态为18.7%，不能直接与开发30%比较。
v15已拆分排列/对局/双方牌库种子，serial DMC每局重建环境并刷新缓存；评估每scenario换布局。
21项定向测试、五范式默认smoke及2项补充检查通过；三种子随机初始化试验已完成。
实际3008/3007/3004frames，真实不同布局163/168/153；最终对随机47.66%/79.69%/87.50%，
F1-D2平均比初始化提高6.77个百分点，但41未过随机门槛。详见 [v15报告](../5_history/shuffle_rl_v15.md)。
下一步有界诊断41动作价值排序；不自动续训。108000最终已使用，107000仅测试使用。
104000开发、105000最终、106000诊断均已使用。保持1v1，未启动5070Ti或自动增加预算。
v14历史证据位于 `artifacts/small_rl_v14_evaluation/`，旧manifest保留不覆盖；
当前用 `tools.cards.rule_baseline --manifest openspec/changes/episode-layout-v15/source-manifest.json` 检查。
用户确认的强制切换触发“角色变化”效果已在v13实现；主动“切换操作”另以事件上下文
区分，见v14 rules.md。旧权重/数据不复用；首次RL固定为1v1、3种子各3000frames。

## 初训环境准备 v10（已验收）

补充公开技能/卡牌/回合阶段的暂停来源，保留动态计算与重放。修复状态视图顺序不稳定、
文件评估平局误记失败和 DMC 未终局误回填平局的问题。预检工具支持只读查询、逐步
clone/restore、隐私遮罩、真实 NN 前向和失败输入留存，确保预检模型参数没有更新。

新配置 32 场、1610 输入、16 次换人暂停通过；原 DMC 默认配置另 8 场通过。
Python 广泛回归 1323 passed / 6 skipped，DMC 临时目录完整保存恢复测试通过。
[验收与边界](../../openspec/changes/training-readiness-v10/results.md)；
[配置、预检及后续命令](../../openspec/changes/training-readiness-v10/verification.md)。
就绪结论限固定每侧最多两名角色的初训配置，三角色多选死亡暂停需另验收。
该阶段验收时尚未启动小范围学习；当前进展见页首。远端长训尚未启动，旧权重/数据不复用。

## 元任务

**两条主线并行**:
1. **算法可学性验证**:GICG 这种 imperfect-info mirror Nash 游戏,RL/AZ/CFR 哪个栈能学
2. **正式版卡池 + DSL 形态稳定**:引入七圣召唤实际游戏全量卡牌 + 平衡性版本管理,验证 algorithm scalability + 锁定 DSL spec

不是训 SOTA agent。

## 暂停执行帧 v9（第一阶段）

已付费卡牌选目标使用可验证的数据帧，可通过版本 2 检查点恢复；重复调用被拒绝，
选目标不再次扣费。程序入口和允许可见的费用规则已接入 NN 实体编码。
Python 回归 1227 项通过、6 项跳过，五范式完整 smoke 10 项通过。
[设计与剩余工作](../../openspec/changes/nn-target-frame-v9/design.md)；
[验收记录](../../openspec/changes/nn-target-frame-v9/results.md)。

这条兼容选目标路径不是当前训练主要暂停来源。嵌套伤害、DSL locals/返回栈、
延迟队列和回合阶段仍由旧重放恢复，NN 明确收到不完整标记；**完整执行帧迁移未完成**。
是否迁移上述程序栈按新路线中的证据决定，不阻塞所有学习验证。仍未启动 5070 Ti 长训或复用旧产物。

## NN 视角对齐 v8

已确认并修复 P1 动态 counter 与 P0 静态 SID/min/max 错位。Counter 统一采用
canonical 排序，meta 第 18 号字段明确 observer；网络结构化读出按每条样本的
决策方转换。覆盖非对称队伍、敌方骰子遮罩、死亡强制换人、克隆恢复和五范式。
[设计与边界](../../openspec/changes/nn-perspective-v8/design.md)；
[验收报告](../../openspec/changes/nn-perspective-v8/results.md)：1226 项通过、6 项跳过，
完整 smoke 10 项通过；另明确排除一个未改动的无上限 minimax 用例。

旧 v6/v7 观测存在该缺陷，既往学习数值仅为历史记录，不能作为修复后效果的证据；
旧权重和旧采样不兼容，不复用。显式暂停执行帧的当前进度见上方 v9。

## NN 表达 v7（开发验收）

引用 counter、支援区、天赋槽位已接入统一 16 字段实体编码及五范式通道。
引用值不再作为原始卡牌/技能编号输入，使用规则引用与共享 counter SID embedding。
共享技能定义不能推断施放者，保持未知归属。
[实现与边界](../../openspec/changes/nn-entities-v7/design.md)；
[暂停路径与执行帧设计](../../openspec/changes/nn-entities-v7/continuation-design.md)。
暂停执行帧尚未迁移；动作查询实体和公开历史仍在后续。v6 实验仅代表旧观测版本。

## 干净训练验收 v6（2026-09-11）

用户指定的第 1、5 项已完成到有限预算实验验收：来源校验、旧格式拒绝、
本地与已配置远端旧训练产物清理，以及三种子从零训练、留出、微调、遗忘和同预算对照。
[完整报告](../../openspec/changes/clean-training-v6/results.md) 与
[边界说明](../../openspec/changes/clean-training-v6/design.md) 是当前训练证据入口。
引擎规则沿用 v5；本次源码基线为 v6，旧 v5 清单不覆盖新增入口改动。

真实对局：基础训练后对随机平均得分 54.2%，对 F1-D2 8.3%；零样本新环境 38.5%，
接近随机的 37.5%。1000 帧微调为 58.3%，同预算从零为 29.2%，但部分种子严重遗忘。
得分按胜=1、平=0.5 计，不是纯胜率。原语实验仅验证表示词表扩行，未新增引擎机制。
旧评估随机策略和区间口径已修正，正式评估重算；不宜把当前结果当作稳定泛化或长训依据。

v6 后续工作现已推进到 v7：引用/通用槽位已实现，暂停执行帧仍待迁移；继续定位微调崩塌，不恢复旧权重。
用户指定后续正式长程训练使用局域网内的 5070 Ti 游戏主机；本机继续开发与小规模验收。
正式部署前核对该主机与现有远端配置的对应关系，不自行启动长训。

## 当前模拟器验收（2026-09-11）

范围已由用户确认：当前训练配置实际引用的自定义牌/角色及依赖效果。
当前 [v5 规则基线](../../openspec/changes/effect-audit-v5/rules.md) 记录21张用牌及扩展效果；
[实现设计](../../openspec/changes/effect-audit-v5/design.md) 与
[验证记录](../../openspec/changes/effect-audit-v5/verification.md) 对应本次改动。

已实现静态效果定义与有序实例列表、同类别产生顺序、荷花酥优先归零并保留水云、
泼墨队伍归属和蝶印死亡清理。实例的归属、次数、期限、进度、顺序及规则引用已接入
五范式网络与采样回放；回放只存有效行。已有原语词表扩行、引擎费用标签
辅助训练与旧新环境混采/组合留出入口。零样本是评估目标，允许微调和增加原语。
用户已取消旧权重迁移：修复前训练产物全部作废，后续从随机初始化和重新采样开始。

以逸待劳反击归因 Q04 已修复。新增独立叠层、生命周期身份、实际效果 hook 引用与写入 IR。
双方回合排序已由用户再次确认：召唤物先结束方优先，其他 buff 跨双方按产生顺序；NN 可见排序组。
新增自动配置/效果审计：6 配置、692 个槽位绑定；整局随机 656 输入与独立层 3840 操作通过。
公开 meta 已扩至18字段；仍有通用暂停程序、通用支援/天赋槽位及旧式引用语义的 NN 表达缺口，
见 [可观测性审计](../../openspec/changes/effect-audit-v5/observability.md)。
未声称全卡池全部边界可靠，也未完成策略泛化实验。
本轮训练仅为临时目录内的接口、梯度和保存恢复验收。

## 训练结果重置（2026-09-11）

- 受污染训练产生的权重、优化器状态、回放/数据集、对手快照、指标和评估结果均不可复用。
  不用于续训、蒸馏、热启动、对手池、算法优劣判断或新实验基线；旧适配入口不能使其有效。
- 本地 `artifacts/` 下 27 个目录、1325 个文件（2,966,506,341 字节）已删除，含嵌套远端拉取副本。
  仅保留 `.gitignore`、主机标记和锁文件；清理清单见 [记录](../0_status/training-reset-2026-09-11.json)。
  仓库其他目录扫描未发现常用格式的权重/训练缓存文件。
- 已配置远端 D:/gicg_dev/artifacts 已清理：158 个旧目录及 35 个逐项确认条目，共 1739 文件、约 9.68 GB；无 Python 进程，最终只剩 .gitignore 和锁。仓库外其他未知副本未做全盘搜索，不得重新导入。
  本地 run 序号可能从头分配，必须使用带时间戳的完整目录引用，不能凭旧 NNN 对照结果。
- 源码、规则测试及历史问题分析保留。下方旧阶段和其他历史文档内的胜率、收敛结论与继续训练计划全部失效，
  只记录历史，不代表当前路线证据。v5 冻结文档中的旧权重适配描述由本决定覆盖；v6 已移除旧观测形状兼容，仅保留干净权重的显式原语词表扩行。
- 未来在可靠环境中重新训练得到的权重可以微调，并可产生新的历史对手池；当前池从空开始。

下一步优先补齐暂停程序和类型化引用的 NN 表达，再验收通用槽位、扩展交互和公开历史输入。
来源校验和三种子短程实验已完成；正式长训仍需先解决上文的表示缺口及微调不稳定。

## 历史 phase（以下训练结果和续训计划已失效）

### 2026-05-28 EOD

### 0. Stage 3 Win pilot + DMC policy collapse 验证 + 多 perf/safety fix ship(2026-05-28,7 commits)

**Stage 3 Win N=16 production pilot 跑通 → 主动停于 3.7%(iter 2500)** 做 policy 诊断:
- ckpt vs F1-D2 wp **0/256 (CI 上限 1.5%)** vs random ε=1.0 拿 22%(CI 11-39%)— **CI 完全不重叠 → DMC 早期 policy collapse 固化**(PLAN.md §A.2 机制 verified:ε=0.05 + MC return ±1 → MSE depress 被选 action → argmax 永选 never-chosen 烂手 self-reinforcing)
- **C1 决策:走路径 A(继续训 full 1M,12-16h),赌后期 self-recover**;失败则进 PLAN.md §A.4 closure
- 详:私有 memory `project_stage3_pilot_policy_collapse_2026_05_28`

**同 session ship 7 commits(`b5f45e2..836be01`)分三批**:

| 类 | Commit | Scope |
|---|---|---|
| Stage 3 unblock | `b5f45e2` | `tools/eval`:random-baseline policy-collapse 诊断 + Win remote rsync fallback |
| H2 root cause | `d5987d0` | `gicg_actor/dmc/greedy_player`:minimax 热路径 DeepCopy → SnapshotPooled(bench 1.45x ns/op + 16→0 alloc + 32 KB→0 byte;原 budget cap 是 GC churn workaround,改完 root cause 后 production cfg 可恢复 unbounded) |
| C3 cross-lang safety | `a613c6e` | `wire/paradigm-payload`:加 `PayloadVer u8` prefix(DMC/AZ/PPO 各独立版本)+ decode mismatch fail-loud + DMC byte-layout golden test |
| Pre-existing | `b3609b6` | `configs/dmc/eval_stage3_b_v_legacy`:补 `[meta] paradigm = "dmc"`(FU-W1B schema) |
| H3 visibility | `2804539` | `training/core/actor/ipc`:`peek_count_and_full_at_head` race-aware ring 探针 — 返 `(count, n_full_at_head)` 区分 over-reserve race vs actor stall(B-go-sustained-collection-deadlock 调试必备) |
| H1 GPU perf | `049e722` | `training/core/actor`:InferenceServer forward 走 `priority=-1` CUDA stream — 抢占 train backward kernel 间隙,降 inference tail latency(实测 run 149 GPU 7-92% util 抖动信号) |
| Pre-existing | `4e4257a` | `gicg_engine/dsl/audit_test`:补 8 个漏列 builtin whitelist(`declare_reaction` / `set_reaction_kind` / `on_shield_absorb` / 4 个 `on_damage_*` / `remove_support`) |
| Pre-existing | `836be01` | `gicg_engine/tests/set_hidden_state`:sort map iter 消除偶发 fail |

**挂起的项**(估 ROI 排序,本 session 决策不做):
- **H4 GOMEMLIMIT validation**(~50 LOC):Win 长跑 OOM 防 silent regression — *方案 C 折中已规划,下个 session 开*
- **IPC Risk #5 stale-episode 检测**(~30 LOC):`_go_assembler` LRU evict 加 stale + warn log,给 C1 long-run debug visibility — *已规划,下个 session 开*
- **H5 Lua interp 优化**(LONG TERM):LuaJIT 替换违反立约(`openspec/project.md:33` "自研解释器,非 LuaJIT")+ 8000 LOC 自研 + IR 系统全推倒数月工程;真要做需先 profile 验证占比(估 10-15% 待真测),路径是 bytecode cache / hot hook 移到 Go-native,不切外部 VM
- ~~**M1 OpenSpec archive 重复 ID**~~:**done** — `0006-i29-*`/`0007-i29-*` 重命名为 `i29-go-actor-pool`/`i29-r7-n-subprocess`(去数字前缀,对齐新命名惯例)+ 5 文件引用更新
- ~~**M3 docs/1_specs vs openspec/specs truth 重复**~~:**done** — 17 MOVED 文件删除 + 3 training 历史文件迁 `docs/5_history/` + `docs/1_specs/` 整目录删除 + CLAUDE.md/project.md/status 引用更新 + 7 openspec spec 死链修复

### 0a. core/network 重设计 + 5 paradigm 完全统一 ship(2026-05-17,34+ commits)

单 session 跑完 architecture unification 大主线:
- **`core-network-generic-promotion`** parent change(13 commits,Phase 0-6 ship):generic `ActorCritic` thin composition + DI `AgentBase` + `typed_damage` first-class + `core/network/legacy/` 物理删除 + 5 paradigm 全切 generic backbone + ckpt self-describing schema + symmetric smoke template + `tools/runs/` CLI suite
- **6 follow-up changes**(15 commits):docs-pre-redesign-refs-sweep + env-factory-unification(3-arg canonical)+ cfg-schema-unification(ObsShape + ParadigmConfigBase + version)+ ppo-structural-backbone-migration(PPO 切 generic)+ cfg-toml-restructure-paradigm-scoped(hybrid TOML)+ paradigm-smoke-full-tier(opt-in `@pytest.mark.smoke_full`)
- **#7 ppo-cfg-shape-alignment**(1 commit):闭 5/5 paradigm cfg dataclass 完全对称(D3 closure)
- 5 paradigm:**AZ/BC/DMC/CFR/PPO 全部走 `make_actor_critic` generic ActorCritic backbone**(spec invariant A4 100% 闭环)
- 完整统一度 ~92-95%(剩 5% 是 CFR algorithm-inherent paradigm-specific intentional divergence per D-207)
- 详:`project_session_ship_2026_05_17_core_network_redesign` + `project_archive_handoff_2026_05_17` memories

~~待处理:17 spec deltas × 8 capability spec.md merge~~:**audit 确认全部 34 个 spec delta 已 merge 到 live spec**,无遗留。`tools.runs.*` + `tools.ckpt.info` CLI 用法见 CLAUDE.md Build & Test 段。

## 当前 phase(2026-05-16)

**✅ doc 体系全量迁移 OpenSpec(P0 完 + P1 进行)+ v_phase2 / DMC infra 多线 ship**

### 1. 文档体系迁移 OpenSpec(2026-05-15/16,P0+P1 17 commits)

- **P0 完(8 commits)**:`openspec/` scaffold + `project.md` + 3 capability spec(`openspec-policy` / `engine-dsl` / `training-architecture`)+ `tools/_meta/check_openspec_indices.py` + pre-commit hooks 串接
- **P1 进行(9 commits)**:15 ADR 迁 `openspec/changes/archive/` + 8 capability spec(network/search-ismcts/search-parallel/engine-actions/dice/capi/runtime/env-config/eval-protocol)+ 5 paradigm dossier(`docs/paradigms/{az,bc,cfr,dmc,ppo}/`)+ 7 archived plan 迁 `5_history/`
- 旧 `docs/2_decisions/` 作 mirror 保留(ADR 实际权威在 `openspec/changes/archive/`);`docs/1_specs/` 已清理删除(全部迁移至 `openspec/specs/`,3 个 training 历史文件迁 `docs/5_history/`)

### 2. v_phase2 真实卡 e2e 测试 + 支援区生命周期 ship(2026-05-15)

- **support zone lifecycle**(commit `62d641f` + `f8a8529` + `840b9c5` 等):`PlayerState.Supports` state / `MaxSupportSlots=4` / `HookSupportRemove` + `remove_support`/`count_support` builtin + `on_support_remove` DSL hook;6 区生命周期 spike test PASS
- **v_phase2 卡 e2e tests**(commit `c02bc88` 事件 3 卡 + `10ce0c9` 支援 2 卡 + `2fca63b` 装备 2 卡):7 case 覆盖事件/支援/装备真路径 + cleaned yaml ground truth 断言

### 3. DMC Phase 3.5 multi-process actor-learner ship(2026-05-13/14/15)

- **Phase 3.5 multi-process actor-learner**(commit `8cdd56c` DouZero pattern + `ce5049e` 合并 single/mp entry)
- **NaN/inf fail-fast guard**(`5ae3f7c`):dump batch+ckpt+diag 后 raise RuntimeError
- **`tools/eval` + `tools/runs` paradigm-agnostic refactor**(12 task 全 done,见 [`dmc_phase35_infra(archived)`](../5_history/dmc_phase35_infra.md))
- **41 项 DMC review critique 落盘**(2026-05-14,`docs/5_history/reviews/dmc_review.md`)

### 4. v_phase2 RL smoke + DSL v6 strict 仍 LIVE

- v_phase2 池(7 char / 6 卡)+ RL smoke s070 跑通(2026-05-12,commit `a0c26e9`)
- ADR-0019 DSL v6 strict 23 commits 链 2026-05-04~05-07 已落,Accepted de-facto;详 [`dsl_v6_progress.md`](dsl_v6_progress.md)
- v_phase2 deferred 机制 23 项仍 backlog(见 [`../3_plans/v_phase2_deferred.md`](../3_plans/v_phase2_deferred.md))

ADR-0011 pool versioning 仍然有效:`data/pools/{test_basic,v_legacy,v_phase2,spike}/`,manifest fold + 内存 cache。

---

## 已确定方向(2 条主线)

### A. 算法路线 — RL sweep 至 final verdict

| 数据点 | F1-D2 |
|---|---|
| Stage 3 1-card mirror baseline (s064-66, n=3) | 0.104 |
| Stage 3 1-card mirror + BC warm-start (r010-12, n=3) | 0.167 |
| Stage 3 1-card asymmetric (s068, n=3) | 0.271 ← +0.167 vs mirror |
| **s069 5× rollouts asymmetric (seed42 only, n=1)** | **0.5** ← 若 confirm 越过 stricter_pass |
| Production fallback BC alone (r009 ckpt) | 0.75 |

阶梯:s069 → s071 capacity → D2 NFSP / D3 deep CFR

### B. Infra 路线 — 正式版卡池准备

ADR-0011 落地了:
- 目录式版本(`data/pools/<id>/`)
- manifest.toml 描述 parent 链 + remove diff
- loader 沿链 fold + 整目录 override 语义
- pool resolution 走 process-global cache(脱耦磁盘)
- filler 字面量 hardcode 移除(Engine Ignorance 恢复)
- cfg 显式 deck_padding + pool 字段

下一步:渐进录入七圣召唤正式卡池(版本快照 + 平衡 patch)。已找到 `~/Documents/gicg_sim/data/raw/` 含 JSON 形式角色 / action 数据可作录入源。

---

## 主要困难(按严重度)

| # | 困难 | 严重度 | 缓解状态 |
|---|---|---|---|
| 1 | RL plateau 结构性(mirror Nash 锁) | 高 | s068 / s069 显示部分可破,sweep 中 |
| 2 | 数据基础窄(每 cfg n=3,std≈0.078) | 中 | multi-seed required,等 sweep 完整 |
| 3 | 正式卡池录入工作量(300+ 张 × 几十行 Lua) | 高 | infra ready;下一步:从 gicg_sim raw JSON 工具化转 Lua DSL |
| 4 | 旧 replay yaml 跨池引用 | 低 | 临时双池 union 兼容,长期重生成 |
| 5 | bit-exact baseline 兼容脆弱 | 中 | base preset 默认值集中管控 |
| 6 | pre-existing `seeds` field bug | 低 | test_shipped_configs 挂,与 ADR-0011 无关,后续单独 fix |

---

## 解决路径(按时间)

**~3.5h 内** — s069 跑完
- seed43/44 出齐 → s069 mean ± std
- F1-D2 ≥ 0.40 mean → closure 再被推翻,compute 是主因 → 推 production scale
- 0.27-0.39 之间 → s071 capacity probe(d_model 128→256, ~2h)

**1-2 天** — sweep cheap probe phase
- s071 跑完 → 进 / 出 algorithm probe
- capacity 也不行 → D2 NFSP / D3 deep CFR(2-3 周主线)
- 顺手 fix `seeds` field bug

**1-2 周(并行,与 RL sweep 解耦)** — 正式卡池 infra 验证
- 复制 `~/Documents/gicg_sim/` 工具到本仓库,拉取 raw JSON 数据
- 设计 JSON → Lua DSL 转换器(基于 raw schema 分析)
- 选第一个真实游戏版本(建议 v3.3 开服版,基础卡集最小)创建 `data/pools/v3.3/`
- 录 1-2 张真实卡走通端到端,验证 cfg `pool="v3.3"` 训练切换 work

**1-2 月** — 全量录入
- 主流版本(v3.3 → v4.5)所有卡 + 角色入 pool
- 训练 cfg 可 pin 单一版本 / 跨版本 ablation

---

## 上一里程碑

- **2026-05-15/16** OpenSpec 全量迁移 P0+P1 共 17 commits — scaffold + 11 capability spec + 15 ADR archive + 5 paradigm dossier + 7 plan archive (heads `9d8a4af`)
- **2026-05-15** v_phase2 卡 e2e tests ship — 事件/支援/装备 7 case 真路径 + cleaned yaml ground truth (commits `c02bc88` / `10ce0c9` / `2fca63b`)
- **2026-05-15** support zone lifecycle ship — `SlotSupport` state + 6 hooks + 6 区生命周期 spike test (commits `62d641f` / `f8a8529` / `840b9c5`)
- **2026-05-13/14** DMC Phase 3.5 multi-process actor-learner ship — DouZero pattern (commit `8cdd56c`),Phase 3.5 infra plan 12 task 全 done
- **2026-05-14** DMC review 41 项 critique 落盘 (`5_history/reviews/dmc_review.md`)
- **2026-05-12** v_phase2 真实角色 / 卡牌池建立 + RL smoke 跑通 (commits `c43a587` cleansing 链路重做 / `9969f2e` v_phase2 池 + spike test / `0f2a951` training pool_spec 修 / `d011859` smoke cfg)。详见 `../3_plans/v_phase2_deferred.md`
- **2026-04-28 PM** ADR-0011 落地:pool versioning + filler 引擎清理 + multi_seed resume + s069 重启 (commit `525296b`)
- **2026-04-28 PM** s068 D4 mirror-break probe F1-D2=0.271 (n=3),+0.167 vs mirror baseline,**部分推翻 closure**;reopen research(ADR-0010)
- **2026-04-28 AM** ADR-0009 paradigm pivot terminus — RL 三栈 × 5 stage 全失败(被 s068 部分推翻)
- **2026-04-28** r009 BC pretrain ep=3 ckpt vs F1-D2 = 0.75(production fallback)
- **2026-04-26** Stage 0-3 AZ pure self-play 完整 4-stage curriculum 双栈闭环
- **2026-04-25** Stage 1+2 BC→PPO PASS,multi-seed infra 落地
- **2026-04-24** RL paradigm pivot — pure end-to-end 路线证否

更长时间线: [`timeline.md`](../0_status/timeline.md)

## 关键 link

### OpenSpec(P0/P1 落地后的新权威)
- 项目层 spec: [`openspec/project.md`](../../openspec/project.md) — SHALL invariants + 工具入口
- 活规约(capability spec): [`openspec/specs/`](../../openspec/specs/) — 11 capability(engine/search/network/training/env-config/eval-protocol/openspec-policy)
- 决策 archive: [`openspec/changes/archive/`](../../openspec/changes/archive/) — 15 ADR(0001-0019)

### Paradigm 科研复盘
- Paradigm landscape: [`docs/paradigms/README.md`](../paradigms/README.md) — 5 paradigm × verdict × 数据(AZ / BC / CFR / DMC / PPO)

### docs/ legacy 区(迁移中)
- 当前 shipped 代码状态已迁至 [`openspec/specs/`](../../openspec/specs/)
- 设计决策: [`../2_decisions/`](../2_decisions/) (已迁 `openspec/changes/archive/`,mirror 保留)
- 计划与 roadmap: [`../3_plans/`](../3_plans/) (active only;已实施/closed 移到 `5_history/`)
- 训练 run 注册: `python -m tools.runs.list` CLI(live);[`../5_history/runs_pre_redesign_2026_05_17.md`](../5_history/runs_pre_redesign_2026_05_17.md)(pre-redesign 2026-05-17 之前)
- 历史复盘 / archived plan: [`../5_history/`](../5_history/) — 新归档:`curriculum/` / `algorithm_sweep_2026_04_28.md` / `acceptance.md` / `az_plans/` + 3 个 implemented plan(`support_lifecycle_impl.md` / `v_phase2_cards_e2e_impl.md` / `dmc_phase35_infra.md`)
- 术语速查: [`glossary.md`](../0_status/glossary.md)

## 编辑规则

- **本文件 LIVE**,phase 切换/里程碑达成 commit 内更新
- 顶部 `last_updated` 字段必须改
- 旧 phase status 沉淀到 `5_history/`,本文只反映当前
