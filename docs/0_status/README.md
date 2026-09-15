---
last_updated: 2026-09-15
status: LIVE
---

# 当前状态：新 session 第一站

本页是当前工作入口。旧实验中的“当前/正在运行/下一步”只具有历史意义。规约读 [项目目的](../../openspec/project.md) 和 [开发约定](../../CLAUDE.md)，具体接手读 [HANDOFF](../HANDOFF.md)。

## 已暂停（2026-09-14 两次；2026-09-15 第三次）

三次暂停均已停止全部工作，**不自动续训**。恢复先读[暂停交接](../HANDOFF_PAUSED.md)——它含三
次会话的完整记录（策略保留实验、指纹变化、行数清理、未提交改动清单）与恢复顺序。以下阶段记录
保留作背景，冲突时以暂停交接为准。

### 2026-09-15 会话做了什么

1. **行数清理收尾**：上一轮开的清理全部完成 —— 20 个存量超限文件处理完毕，全仓
   `check_line_limits` **零违规**；顺带清掉 6 个存量 ruff、5 个存量 gofmt 未格式化文件。
2. **`CLAUDE.md` 阈值表新增 Go 测试档**：`*_test.go` 放宽到 500 行，与 Python 测试对齐。
3. **源码指纹再次变更**为 `ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15`
   （拆 `interp/ir/` 下的 Go 文件所致）；`gicg_env/libgicg.dylib` 已重建。
4. **前两轮累积的改动已提交**：按逻辑单元分 9 个 commit 到 `dev`，**尚未 push**，远端仍是
   `dev`=`1e12d97` / `main`=`22c7345` / tag `v0.3.0`。

### 上一轮会话（artifact 戳 20260914 UTC）做了什么

1. **策略保留实验**：方案定稿 + 代码落地（`retention_arms.py` / `policy_retention.py` /
   `representation_drift.py` + 2 个配置 + 17 个测试），本机 6 臂 smoke 全通；**正式对照未上 56**。
   根因定位：`tools/experiments/semantic_training/paired_training.py` 把策略网与规则头的**全部参数**
   放进同一 AdamW、用纯回归目标训练、无主任务保留项 → 预热策略 34.55%→19.09%（−15.45pp）。
2. **源码指纹当时实测为 `d8a0934211db489f…`**（现已再次变更为 `ff423c96…`），与旧记录的
   `c2af135c…` 不同 → 旧 warmup/paired 权重一律不可加载；`artifacts/pause_20260914/checkpoints/`
   已按用户要求清空。**本轮训练必须从头重训初始化**，不得重标旧指纹。
3. **行数清理开工**：20 个存量违规其实是 D7（2026-04-23 已清零）之后的**回归**，CLAUDE.md 里
   "grandfathered" 的措辞已过时。批 1 完成 4/7；顺手清掉全仓 5 个 `gofmt` 未格式化文件。
4. 远端 `git@github.com:RedContritio/gicg_sim.git` 建立：强制推送 `main`+`dev`、删除远端
   `cursor_dev`/`dsl_dev`、推 tag `v0.3.0`。

## 全局位置

长期产品目标：最新正式版七圣召唤 PvE 决策辅助工具，并积累可复现研究证据。当前阶段是**模拟环境、规则表达和训练方法验证**，还不是可交付的正式 PvE 助手。

当前活动目标：**解决学习不到规则的问题，在随机变体下稳定胜过 D2**。未达成。

执行排期见[周/月级路线图](../3_plans/rule_learning_roadmap.md)：前八周逐步任务、六个月里程碑、验收关口与备选方法。日期为计划窗口，未通过验收不自动晋级。

| 领域 | 已完成 | 尚未证明或未完成 |
|---|---|---|
| 模拟环境 | 引擎、Lua DSL、快照恢复、强制切换/反应等规则修复；原生五角色与23张行动牌可运行 | 游戏内边界逐项实测；全官方卡池完整规则覆盖 |
| 当前训练环境 | 凯亚、迪卢克、芭芭拉、砂糖、菲谢尔；3v3；固定30张随机合法牌组；观测布局shuffle | 其他正式角色扩展与PvE关卡接入 |
| NN表达 | 类型化IR、操作数角色、数值编码、技能/卡牌到效果关联；兼容性指纹 | 模型稳定利用规则变化做出更好选择 |
| 训练与评估 | 56远端CUDA、采样/恢复、BC/RL、D2评估、场景聚类置信区间、配对比较 | 当前原生变体环境下稳定超过D2 |
| 产品与研究 | 长期规划、实验记录、已有网页接口 | 网页体验后续优化；真实PvE验证、概率校准、论文结论 |

## 当前证据

- 最新实验 `artifacts/consequence_calibrated_rl_20260914` 已完成，耗时3607秒；完成等待器34391已结束，不再轮询或重启。56根为 `D:/gicg_consequence_20260914`。独立变体96400/440局：初始19.09%，候选第2轮21.36%，对照第4轮24.09%；候选相对初始差值95%区间跨0，对照提升5个百分点、区间[0.45,9.55]个百分点。后果预测特征的额外收益未证明，目标未达成。下一步补所选候选的规则探针，并检查预热到配对学习是否损害策略；完整证据见[残差实验记录](../5_history/consequence_rl_20260914.md)。
- 当前规则变体：每局修改1–2个参数，训练50%原生/50%变体；30个参数覆盖五角色的直接伤害、治疗与指定元素骰费。训练/开发修改值分开。持续回合和禁用技能仍未加入这一阶段。
- 当前保留基线：`artifacts/202609140533_000016_semantic_rl/ckpts/iteration_7.pt`（路径相对56根目录）。不同独立变体开发复核胜率约39–43%，尚未超过D2。
- 普通DAgger和保守DAgger均未改善胜率。凯亚3v3交换普攻/霜袭伤害2↔6、4↔8时，仍固定偏好霜袭；这是受限反事实失败证据，不能等同全规则诊断。
- 新增9字段引擎结算辅助头，与RL共享规则/动作编码。14项相关测试通过；GPU保存/恢复冒烟通过，辅助优化器步数18→32。本轮对照未证明胜率收益，规则数值响应仍不足。

## 最近完成的训练

56主机：`dev@192.168.31.56`；目录`D:/gicg_native`；Python `D:/gicg_native/venv/Scripts/python.exe`。
配置：[native_starter.toml](../../configs/dmc/native_starter.toml)。
任务：`artifacts/native_auxiliary_comparison_20260914`。

同起点、同seed94700：先辅助RL(beta0.5)，再普通RL，各4×256局、8workers；value baseline、温度0.5、D2相同。每轮原生开发93100，变体开发93990选模（含初始），94890独立440局/模型复核。单训练种子的发展阶段对照，不是最终稳定性验收。

流程已成功完成，耗时62.4分钟。辅助臂开发选模退回初始模型；普通RL候选独立胜率29.55%，初始33.64%，差值−4.09个百分点，配对95%区间[−9.55,+1.36]。未证明收益。结果和结算预测审计见[实验报告](../5_history/auxiliary_rule_comparison_20260914.md)。

按需查询（stdout≤200 UTF-8字节）：

```bash
.venv/bin/python -m tools.experiments.semantic_training.progress configs/dmc/native_starter.toml artifacts/native_auxiliary_comparison_20260914
```

状态文件可滞后，不独立证明进程存活。`completion.json`是流程终态，失败时含error。不要因新session无旧工具句柄或查询超时重复启动任务。远端操作使用`tools.runs._host`封装；不用手写SSH/SCP。训练源保持冻结，其他旧远端目录不清理。

## 新实验与并行验收

用户已授权直接并行。56配对反事实结算实验`artifacts/native_paired_20260914`已完成（267.4秒）：双臂各1500步，360对五角色伤害/治疗样本；本轮数值验证差值MAE初始2.755→配对0.555/普通监督0.645，尚非对战收益。原凯亚探针结算排名16/16，策略仍8/16；360对完整观测检查通过。[结果](../5_history/paired_consequence_20260914.md)。冻结旧源码上运行，完成记录已拉回，勿重复启动。[固定协议与恢复说明](../3_plans/cards/paired_consequence_training.md)。本机三项修复集成验收已通过：training 1150 passed，semantic/web 82 passed，Go及五范式完整冒烟均通过。详见[验收证据](../3_plans/inference_consistency_repairs.md)。

## 最新完成：配对监督联合RL

56 的 `artifacts/native_paired_rl_20260914` 已 complete，耗时90.14分钟；等待器80476正常退出，勿重复启动。两臂各4×512局，均选回初始模型，独立440局得分27.27%。辅助最终数值差值MAE改善至0.440，但三模型凯亚探针均为预测16/16、动作响应8/16。[完整结果与限制](../5_history/paired_joint_rl_20260914.md)。

## 最新完成：预测后果残差RL

56新根 `D:/gicg_consequence_20260914`，配置 `configs/dmc/native_consequence.toml`。初始化已完成（621.5秒），残差双臂 `artifacts/consequence_rl_20260914` 亦 complete（57.6分钟），等待器12906正常结束。

两组4×512局均未选出优于初始的候选。独立变体440局初始20.91%；三模型探针预测/技能排名均16/16，但第一步仍选一掷乾坤。每组约5400次更新且无KL早停，最终轮平均anchor KL仅约2.8e-5。下一步校准残差学习率并核查初始化阶段的策略变化。[结果与限制](../5_history/consequence_rl_20260914.md)。校准后对照 artifacts/consequence_calibrated_rl_20260914 已完成；补充评估 consequence_followup_20260914 亦完成。等待器34391和21252均正常退出。

## 下一步

1. **行数清理已完成**（2026-09-15）：20 个存量违规全部处理，`tools/_meta/check_line_limits.py`
   零违反；`gicg_env/libgicg.dylib` 已按新源码重建。此前「清理优先还是训练优先」的待决问题随之
   作废 —— 可直接进入训练。若之后再改 `fingerprint()` 覆盖内的源码，须重新走「改完 → 重建 dylib」。
2. **策略保留实验的正式对照需在 56 上跑**（用户当前占用设备，本会话未启动）。前置：确认
   `configs/dmc/policy_retention.toml` 的 `[remote].root`（现填 `D:/gicg_retention_20260915`，
   未经用户确认）。先在新根上跑 warmup —— **不要**跑 `consequence_bootstrap`，其 paired 阶段
   正是本次要研究的坏配置 —— 再用产出的 `ckpts/latest.pt` + `teacher/` 跑 `policy_retention`。
   跨机只同步 `tools/` 与 `configs/`，不要整树覆盖 56 的指纹目录。
3. 评测纪律：96400 面板已被用于选模，**不能再当独立证据**；开发面板与确认面板分开，正式对比用新
   seed。6 臂 smoke 的机制数字（`cos_ema` 为负、`frozen` 零漂移、门控触发过一次）只是方向性信号，
   面板胜率与凯亚探针都还没跑（smoke 用 `--panel-scenarios 0`），不得当作效果结论。
4. 有可靠收益再扩展训练与多种子验证。既有最终预留训练 seed 971000/981000/991000、最终变体 seed
   971900/981900/991900 仍未被使用。目标需多种子场景聚类 95% 胜率下界 >50%，并有规则响应证据。
5. 规则边界待用户游戏内实测；不阻止已授权的方法实验，但不能宣称全部官方规则已获实测认证。

## 工作区与恢复边界

分支`dev`。2026-09-14用户要求将累积实现提交为开发快照；提交说明与5项未通过回归见[提交验收记录](../5_history/dev_submission_20260914.md)。原5项回归阻塞已处理并通过集成验收，本轮按用户授权将dev压缩合入main，再同步合并基线回dev；最终提交与工作区以Git状态为准。接手时仍先检查git status，不能假定工作区永远干净。**前两轮累积的 92 modified + 36 untracked 改动已在 2026-09-15 按逻辑单元分 9 个 commit 提交到 `dev`；尚未 push，远端 `git@github.com:RedContritio/gicg_sim.git` 仍是 `dev`=`1e12d97` / `main`=`22c7345` / tag `v0.3.0`。**

模型和大部分产物在56及本地被gitignore的`artifacts/`，并非Git备份的一部分。本轮56冻结实验的核心/观测指纹：`7b4ef71f7f13fed5d148fb2df3c21f7260c6375bec99a91daf9caf4dfe104ad1`；额外工具源码hash保存在pipeline报告。本机正在修改观测schema和网络链路，新代码不能直接视为兼容本轮旧权重。不得给旧权重重标指纹。结束聊天不等于停止远端训练，也不承诺关闭客户端后仍有自动唤醒。**2026-09-15 实测 `training.core.artifact_io.fingerprint()` = `ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15`，与上文 7b4ef71f… 、上一轮实测的 `d8a09342…` 及旧 `consequence_*` 的 `c2af135c…` 均不同；旧 warmup/paired 权重一律不可加载，`artifacts/pause_20260914/checkpoints/` 已按用户要求清空。`gicg_env/libgicg.dylib` 已按新源码重建。**

## 资料入口

- [规则辅助联合训练](../3_plans/cards/rule_auxiliary_training.md)
- [随机变体工具与协议](../../tools/rule_validation/VARIANTS.md)
- [原生内容路线](../3_plans/cards/native_content_curriculum.md)
- [待游戏内验证的边界](../3_plans/cards/in_game_rule_verification.md)
- [PvE与研究长期规划](../3_plans/pve_assistant_and_research.md)
- [旧状态页存档](../5_history/status_before_handoff_cleanup_20260914.md)
