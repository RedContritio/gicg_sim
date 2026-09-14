# v13：强制切换事件与最终验证

用户确认：强制切换也触发“切换角色时”的效果。

## 实现

规则自动切换（force_switch_next / set_active_char）现在复用既有切换执行路径，
使用 ActForcedReaction 派发 HookSwitch；死亡换人继续使用原来的 ActForcedDeath，
不叠加第二次事件。无实际位置变化不触发。强制切换不扣骰，不额外翻转行动权，
不消费只针对主动付费切换的效果；有主动限定的规则仍自行过滤上下文。

事件中再造成死亡时，managed boundary 保存暂停点；选人后继续执行外层剩余效果。
新增回归检查自动切换事件、死亡换人事件、外层后续效果各恰好一次，并验证运行时克隆
和快照多次恢复。同步用例检查延迟效果执行、同位设置不重复触发和骰子/行动权不变。

## 验证

- 最终 Go 引擎、解释器、DSL、记录、搜索、actor 全部通过。
- 最终广泛 Python 回归：1330 passed、6 skipped、22 个既有 JIT 警告，48.38s。
- 初训环境 gate：readiness_base/tactics 各 16 局，共 1610 次输入，均通过。
- 网络架构与 v12 相同，沿用 v12 五范式完整 smoke 的 10 passed；本轮改规则事件，
  以最终 Go/Python 回归和环境 gate 验证。仍排除旧无上限 minimax 测试。

治疗目标条件实验按 v12 同一预登记协议从零复跑，最终记录见 learning-results.json。
三个种子 41/42/43 的最终目标命中率均为 100%，抹除目标字段均为 50%；
各 200 次更新、64 训练状态、32 测试状态，仍仅代表受控治疗目标子任务。
三个检查点均能严格加载到最终网络，来源指纹匹配，未加载父权重训练。
新增切换/死亡暂停/克隆恢复/超载用例同时通过 Go race 检查（3.173s）。
旧规则指纹的 v12 最终检查点及数据共 4 文件已删除，仅留历史报告，详 removed-artifacts.json。
最新可用产物位于 artifacts/card_target_v13_final。预留牌以逸待劳、速速茶点未参与。

统计更正：v12 verification.json 的 parameter_count 误将 state_dict 的 buffer 一并
计入，得到 341,056；实际模型参数为 277,056，与 v12 正文一致。这不影响训练或指标。
v12 冻结文件保持原样，v13 verification.json 改用 model.parameters() 统计。

## 新 session 下一步

当前已通过治疗目标子任务，但阶段 3 尚未整体完成。首先修复调和动作语义：
不同弃牌/转换骰色目前仍可映射为相同 NN 动作输入，见 v12 复现说明。
随后补费用触发、目标资格、含对手应答或终局的短程 RL；不直接启动 5070 Ti 长训。
强制切换规则已确认，不必再次询问。

```sh
.venv/bin/python -m tools.cards.rule_baseline
GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_engine/tests -run 'TestOverloadBuiltin|TestSetActiveCharDispatches|TestForceSwitchEffect' -count=1
.venv/bin/python -m tools.experiments.target_learning --output artifacts/NEW_target_probe
```
