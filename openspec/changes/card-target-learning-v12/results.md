# v12：卡牌目标可见性与条件学习

## 修复及其证据

发现相同状态下，美味烧鸡指向受伤和满血角色时，旧 action_refs 都为同一个
`[Card, hook, -1]`，付款也相同。共享动作头只看这两部分，因此任何权重都不能
区分两个动作；不是增加训练预算能够解决的问题。

现在第三列包含相对执行者的目标槽，Python C API / Go actor 共用引擎映射；
共享网络加入卡牌目标 embedding。回归验证实际治疗量不同、分数可不同、梯度
到达目标 embedding；抹除目标字段后分数严格相同。参数量增加 384。

广泛回归还暴露超载调用 `force_switch`，解释器只注册 `force_switch_next`，
tokenizer 和静态审计白名单却沿用旧名。四处现统一为已有正式名字与同一 opcode，
不更改切换行为。固定 action RNG 29、环境 seed 123 的三角色对局在第 75 次输入
稳定复现原错误；修复后可走到终局。原始输入见 overload-failure.json。

## 固定预算条件目标实验

双方与目标角色/出战角色全部 8 种组合均衡；训练 8 个布局种子×8=64 状态，
测试 4 个新布局种子×8=32 状态。通过合法普攻、切换与结束产生伤情，无手改 HP。
只在美味烧鸡两个合法目标间选择：伤者实际治疗 1、满血者实际治疗 0。
同一局面两个候选付款相同，顺序打乱；固定目标或只选出战角色均只有 50%。

每种子完整 32 维 DMC 网络随机初始化，200 次更新、批量 8。实验固定预算和阈值
见 protocol.md；结果以 learning-results.json 中最终源码复跑记录为准。
首次架构验证运行在超载命名修复前；之后固定同一协议复跑，不调参或挑选种子。

最终源码复跑结果（共 277,056 参数）：

| 初始化种子 | 训练前命中 | 训练后命中 | 抹除目标字段 |
| --- | --- | --- | --- |
| 41 | 53.1% | 100% | 50% |
| 42 | 50% | 100% | 50% |
| 43 | 50% | 100% | 50% |

三个种子均达到预登记的 90% 门槛，双方、受伤槽与出战槽的分层结果也均为 100%。
最终检查点来源与当前生产源码指纹一致，报告的训练父权重列表为空。

这是 8 个受控模板在新布局编号下的验证，不是 32 个独立复杂场景、完整对局胜率、
新规则迁移或长程规划。阶段 3 的目标选择子任务可以单独验收，整个阶段仍未通过。

## 验证与兼容性

- 最终 Go 引擎、解释器、DSL 审计、搜索、actor 全部通过。
- 最终广泛 Python 回归：1330 passed、6 skipped、22 个既有 JIT 弃用警告，54.97s。
- 五范式完整 smoke：10 passed，493.36s，覆盖共享网络改动的训练、保存、恢复；
  此后仅统一超载函数名并同步审计白名单，最终规则由上述 Go/Python 回归覆盖。
- 最终 readiness_base/tactics 预检：32 局、1610 次输入，未做梯度更新。
- 继续排除旧的无上限 minimax 用例 `test_budget_uncapped_equals_old_const`。

旧 v11 权重/数据及超载修复前的本轮临时权重/数据共 16 文件已删除，清单见
removed-artifacts.json；仅留诊断报告，不用于训练。最终产物独立保存在
artifacts/card_target_v12_final，artifact 指纹拒绝旧输入语义。
预留牌以逸待劳、速速茶点未参与。

## 下一步与待确认项

1. **短程 RL 前继续补动作语义**：实测调和美味烧鸡/测试卡_碎片时，两个动作的
   native identities 区分手牌，但 refs 都为 `[4,-1,-1]`、付款全零。
   需要暴露被弃牌的规则引用和所转换骰色，并审计其他联合动作，不能现在宣称动作
   表达已经完整。此问题不影响本轮仅含两治疗目标的条件实验。
2. 补费用触发、目标资格与包含对手应答/终局的短程学习；随后才进入更大 RL 预算。
3. 强制切换是否触发“切换角色时”效果：规范写应触发，实现直接改变出战位，
   已单独向用户确认，函数名修复不擅自改变这项行为。

复现命令（输出目录必须不存在）：

```sh
.venv/bin/python -m tools.experiments.target_learning --output artifacts/NEW_target_probe
.venv/bin/python -m pytest training/tests/test_card_target_actions.py tools/experiments/tests/test_target_data.py gicg_env/tests/test_overload_replay.py -q
GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_engine/tests -run TestOverloadBuiltin -count=1
.venv/bin/python -m tools.cards.rule_baseline
```
