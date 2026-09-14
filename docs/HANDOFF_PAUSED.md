# 暂停交接：2026-09-14

用户因额度要求停止任务，之后再开发。当前目标未达成；不要自动启动新训练或继续审计。当前分支 dev，本次代码、网页和文档整理为 v0.3.0 开发快照；恢复时以 git status 核对后续修改，不 reset/clean。

## 最新结论

原生五角色凯亚、迪卢克、芭芭拉、砂糖、菲谢尔，随机3v3、30张合法牌组。变体覆盖伤害、治疗、指定骰费；D2是目标标准。随机变体下稳定胜过D2仍未证明。

校准残差RL已完成：每臂4×512局、16 workers、lr=0.001。独立96400/110场景×两席位×两布局：初始19.09%，带后果预测候选第2轮21.36%，零后果特征对照第4轮24.09%。后果预测的额外收益没有统计证据；仅对照相对初始提升的配对区间略高于0。

**关键新证据：同面板监督预热模型34.55%，配对规则训练后19.09%，差值-15.45个百分点，95%区间[-22.73,-7.73]。** 规则预测学好并不代表策略保留；下一次优先研究如何隔离规则监督对基础策略的破坏。不能宣称所有规则监督必然有害。

所选两模型的凯亚探针均为预测16/16、技能排名16/16、完整行动选择伤害领先技能0/16。此有限探针不能替代五角色规则响应或全局最优决策证据。

## 执行状态

- 校准RL等待器34391正常退出，remote_exit=0。
- 补充评估等待器21252正常退出，remote_exit=0，结果全部回传；停止检查未发现该模块仍运行。
- documentation_audit 已通过 interrupt_agent 中断；先读覆盖清单再恢复，不重复已审文件。
- 没有启动下一轮训练。网页预览若仍有本地服务，仅是预览，不是训练；恢复时按需检查。

## 必要文件

| 内容 | 本机路径 |
|---|---|
| 详细实验与置信区间 | docs/5_history/consequence_rl_20260914.md |
| 校准RL原始面板、探针、训练曲线 | artifacts/consequence_calibrated_rl_20260914/ |
| 监督预热对比与所选模型探针 | artifacts/consequence_followup_20260914/ |
| 初始化与第一轮残差结果 | artifacts/consequence_bootstrap_20260914/、artifacts/consequence_rl_20260914/ |
| 六份关键模型备份及来源/SHA | artifacts/pause_20260914/checkpoints/manifest.json |
| 兼容训练源码快照 | artifacts/consequence_snapshot_20260914/source_manifest.json、source.tar.gz、supplement.tar.gz |
| 文档审计逐文件覆盖与行为疑点 | artifacts/documentation_audit_20260914/ |
| 网页改动与未完成视觉验收 | docs/5_history/gameplay_ui_20260914.md |
| 周/月计划与最终验收协议 | docs/3_plans/rule_learning_roadmap.md |

artifacts 被 Git 忽略，不能仅靠提交备份。暂停目录另保存工作区 diff、文件清单和修改文件归档；不包含全部历史经验池。

56根 `D:/gicg_consequence_20260914`，Python `D:/gicg_native/venv/Scripts/python.exe`；远端来源指纹 `c2af135cd2ac2223ed9ece10cd08e3182b6c2f441ec054aee5663e66d1e2f4ec`。配置 `configs/dmc/native_consequence.toml`。所有远程操作使用 tools.runs._host；不要直接同步整个当前工作区覆盖兼容快照，也不要重标旧模型指纹。

## 恢复顺序

1. 阅读本页、CLAUDE.md，检查 Git 工作区；核对暂停备份清单。没有自动续训任务。
2. 从 warmup.pt 出发研究策略保留：冻结/复制策略与规则预测编码器，或加入固定策略约束；先用受控阶段对照验证预测提升同时不损害对局策略。不要直接把34.55%称为达标。
3. 有明确收益再扩大RL预算；评估须区分开发选模与独立复核。最终三组训练seed971000/981000/991000、测试seed971900/981900/991900仍保留未用；目标需多种子置信下界超过50%及规则响应证据。
4. 文档审计未完成全仓人工审阅，以 coverage.tsv 为准；已发现的运行契约问题仅记录，未修改行为。SHM no-op 不影响当前 semantic RL 链路。
5. 网页UI已实现但尚缺浏览器视觉验收；本快照仅有已记录的专项验证，未完成全仓统一验收。不要把局部检查当全仓通过。
