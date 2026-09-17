---
last_updated: 2026-09-17
status: LIVE
---

# 当前状态：新 session 第一站

本页只写**当前状态与下一步**；每次会话做了什么由 `git log` 与 `docs/5_history/` 承担，本页不复述。规约读 [项目目的](../../openspec/project.md) 与 [开发约定](../../CLAUDE.md)，具体接手读 [HANDOFF](../HANDOFF.md)，暂停期恢复读 [暂停交接](../HANDOFF_PAUSED.md)。

**训练仍暂停，不自动续训。** 2026-09-16 已完成策略保留六臂正式对照和文档收尾；
结果见[策略保留报告](../5_history/policy_retention_20260916.md)。

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

- **当前规则变体**：每局修改1–2个参数，训练50%原生/50%变体；30个参数覆盖五角色的直接伤害、治疗与指定元素骰费。训练/开发修改值分开。持续回合和禁用技能仍未加入这一阶段。
- **当前保留基线**：`artifacts/202609140533_000016_semantic_rl/ckpts/iteration_7.pt`（路径相对56根目录）。不同独立变体开发复核胜率约39–43%，尚未超过D2。
- **受限反事实失败**：普通DAgger和保守DAgger均未改善胜率。凯亚3v3交换普攻/霜袭伤害2↔6、4↔8时，仍固定偏好霜袭；这是受限证据，不能等同全规则诊断。
- **规则响应仍不足**：9字段引擎结算辅助头与RL共享规则/动作编码（14项测试通过，GPU保存/恢复冒烟通过）；本轮对照未证明胜率收益。
- **策略保留已选臂**：`full` 和 `anchored` 同时通过规则留出与相对warmup不明确退化；两臂直接差值`anchored-full=+1.36pp [-6.82,+9.55]`，没有证据支持anchored更好。按更简单机制选择`full`进入下一轮等预算RL。`96600`已消耗，不能复用于晋级验收。
- **四条已收尾的实验线**（数字与限制见各自报告，勿重复启动）：

  | 实验 | 56 产物 | 报告 |
  |---|---|---|
  | 辅助RL对照 | `artifacts/native_auxiliary_comparison_20260914` | [报告](../5_history/auxiliary_rule_comparison_20260914.md) |
  | 五角色配对结算 | `artifacts/native_paired_20260914` | [报告](../5_history/paired_consequence_20260914.md) |
  | 配对监督联合RL | `artifacts/native_paired_rl_20260914` | [报告](../5_history/paired_joint_rl_20260914.md) |
  | 预测后果残差RL（含校准学习率、补充评估） | `artifacts/consequence_calibrated_rl_20260914`、`artifacts/consequence_followup_20260914` | [报告](../5_history/consequence_rl_20260914.md) |

## 下一步

1. **进入 Week 2 的等预算 RL**：从`artifacts/202609160202_000021_retention_full/full_policy.pt`开始；先同步代码到56，再按单个任务串行执行。本轮不自动启动训练。
2. `anchored`只有在新独立seed下与`full`直接复核后，才能作为显式KL与梯度门控方案支持未来RL；`96600`不能复用。
3. 评测纪律：96400与96600面板均已被用于选模，**不能再当独立证据**；开发面板与确认面板分开，正式对比用新seed。差值报配对场景聚类95%CI，并做臂对臂比较。
4. 有可靠收益再扩展训练与多种子验证。既有最终预留训练 seed 971000/981000/991000、最终变体 seed 971900/981900/991900 仍未被使用。目标需多种子场景聚类 95% 胜率下界 >50%，并有规则响应证据。
5. 规则边界待用户游戏内实测；不阻止已授权的方法实验，但不能宣称全部官方规则已获实测认证。

## 工作区与恢复边界

分支`dev`，本地 ahead 14。工作区仍有 `remote-host-decoupling` 实现与策略保留文档等未提交改动，本地提交也**尚未 push**；提交说明与历史见 [dev 提交验收记录](../5_history/dev_submission_20260914.md) 与 `git log`。远端 `git@github.com:RedContritio/gicg_sim.git` 仍是 `dev`=`1e12d97` / `main`=`22c7345` / tag `v0.3.0`。接手时先 `git status`，不假定工作区干净。

**每台设备只允许一个项目根**（change `remote-host-decoupling` 不变量 #25）：56 上只保留 `D:/gicg_dev`，解释器在其 `.venv` 下；实验之间靠 cfg 参数与 per-run 目录隔离，**不靠另开根目录** —— 每个根各持一套 `artifacts/` 索引与 NNN 计数器，多根会让 `show <NNN>` 不再唯一。

**远端连接信息不再写死在 cfg 与本页**：change `remote-host-decoupling` 已把 `[remote]` 的 `ssh`/`os`/`hostname`/`root` 四字段从 14 个 cfg 外置到 gitignored 的 `configs/hosts/hosts.toml`，cfg 侧只留 `profile`；注册表已建立，本机测试、pre-commit、源码指纹中性验证、文档记录核对和本机端到端链路验证均通过。真实 56 的远端首次同步与训练派发全链路验收已获授权，当前等待 56 可用；设备上线且确认无活动训练后串行执行，change 在该验收通过前不得 archive。固定 56 的 `socket.gethostname()` 与注册表一致，配错会让 56 侧 `is_local_host` 判假、ssh 到自己成环；远端操作一律走 `tools.runs._host` 封装，不手写 SSH/SCP。

模型和大部分产物在56及本地被gitignore的`artifacts/`，并非Git备份的一部分。本轮56冻结实验的核心/观测指纹：`7b4ef71f7f13fed5d148fb2df3c21f7260c6375bec99a91daf9caf4dfe104ad1`；额外工具源码hash保存在pipeline报告。**2026-09-15 实测 `training.core.artifact_io.fingerprint()` = `ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15`，与上文 `7b4ef71f…`、上一轮实测的 `d8a09342…` 及旧 `consequence_*` 的 `c2af135c…` 均不同；旧 warmup/paired 权重一律不可加载，`artifacts/pause_20260914/checkpoints/` 已清空，本轮必须从头重训初始化。`gicg_env/libgicg.dylib` 已按新源码重建；之后若再改 `fingerprint()` 覆盖内的源码，须重新走「改完 → 重建 dylib」。**

## 资料入口

- [随机变体工具与协议](../../tools/rule_validation/VARIANTS.md)
- [原生内容路线](../3_plans/cards/native_content_curriculum.md)
- [待游戏内验证的边界](../3_plans/cards/in_game_rule_verification.md)
- [PvE与研究长期规划](../3_plans/pve_assistant_and_research.md)
- [规则辅助联合训练（已归档）](../5_history/cards/rule_auxiliary_training.md)
- [旧状态页存档](../5_history/status_before_handoff_cleanup_20260914.md)
