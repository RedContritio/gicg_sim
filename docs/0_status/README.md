---
last_updated: 2026-09-14
status: LIVE
---

# 当前状态：新 session 第一站

本页是当前工作入口。旧实验中的“当前/正在运行/下一步”只具有历史意义。规约读 [项目目的](../../openspec/project.md) 和 [开发约定](../../CLAUDE.md)，具体接手读 [HANDOFF](../HANDOFF.md)。

## 全局位置

长期产品目标：最新正式版七圣召唤 PvE 决策辅助工具，并积累可复现研究证据。当前阶段是**模拟环境、规则表达和训练方法验证**，还不是可交付的正式 PvE 助手。

当前活动目标：**解决学习不到规则的问题，在随机变体下稳定胜过 D2**。未达成。

| 领域 | 已完成 | 尚未证明或未完成 |
|---|---|---|
| 模拟环境 | 引擎、Lua DSL、快照恢复、强制切换/反应等规则修复；原生五角色与23张行动牌可运行 | 游戏内边界逐项实测；全官方卡池完整规则覆盖 |
| 当前训练环境 | 凯亚、迪卢克、芭芭拉、砂糖、菲谢尔；3v3；固定30张随机合法牌组；观测布局shuffle | 其他正式角色扩展与PvE关卡接入 |
| NN表达 | 类型化IR、操作数角色、数值编码、技能/卡牌到效果关联；兼容性指纹 | 模型稳定利用规则变化做出更好选择 |
| 训练与评估 | 56远端CUDA、采样/恢复、BC/RL、D2评估、场景聚类置信区间、配对比较 | 当前原生变体环境下稳定超过D2 |
| 产品与研究 | 长期规划、实验记录、已有网页接口 | 网页体验后续优化；真实PvE验证、概率校准、论文结论 |

## 当前证据

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

## 当前运行：配对监督联合RL

56已启动`artifacts/native_paired_rl_20260914`，辅助/普通RL各4×512局、16 workers，master seed95100。从同一配对预训练模型出发；首个run为`202609141059_000032_semantic_rl`，启动确认时辅助第1轮39/512局。后续自动选模及独立D2评估。执行等待器session80476；只依据completion判断完成。[固定协议、来源与恢复边界](../3_plans/cards/paired_joint_rl.md)。

## 下一步

1. 三项修复已通过集成验收，工程阻塞解除；用户已授权将dev压缩合入main，按Git实际状态确认提交结果。56冻结训练不受影响。
2. 配对监督已证明受控数值预测可学习（原凯亚探针16/16），但策略仍8/16。持续联合RL已启动，完成后用自然对局、规则响应和独立D2结果共同验证；不要直接把即时伤害排序当策略目标。
3. 有可靠收益再扩展训练与多种子验证。既有最终预留训练seed971000/981000/991000，最终变体seed971900/981900/991900；当前实验未使用。最终各模型场景聚类95%胜率下界须超过50%，并有规则响应证据。
4. 规则边界待用户游戏内实测；不阻止已授权的方法实验，但不能宣称全部官方规则已获实测认证。

## 工作区与恢复边界

分支`dev`。2026-09-14用户要求将累积实现提交为开发快照；提交说明与5项未通过回归见[提交验收记录](../5_history/dev_submission_20260914.md)。原5项回归阻塞已处理并通过集成验收，本轮按用户授权将dev压缩合入main，再同步合并基线回dev；最终提交与工作区以Git状态为准。接手时仍先检查git status，不能假定工作区永远干净。

模型和大部分产物在56及本地被gitignore的`artifacts/`，并非Git备份的一部分。本轮56冻结实验的核心/观测指纹：`7b4ef71f7f13fed5d148fb2df3c21f7260c6375bec99a91daf9caf4dfe104ad1`；额外工具源码hash保存在pipeline报告。本机正在修改观测schema和网络链路，新代码不能直接视为兼容本轮旧权重。不得给旧权重重标指纹。结束聊天不等于停止远端训练，也不承诺关闭客户端后仍有自动唤醒。

## 资料入口

- [规则辅助联合训练](../3_plans/cards/rule_auxiliary_training.md)
- [随机变体工具与协议](../../tools/rule_validation/VARIANTS.md)
- [原生内容路线](../3_plans/cards/native_content_curriculum.md)
- [待游戏内验证的边界](../3_plans/cards/in_game_rule_verification.md)
- [PvE与研究长期规划](../3_plans/pve_assistant_and_research.md)
- [旧状态页存档](../5_history/status_before_handoff_cleanup_20260914.md)
