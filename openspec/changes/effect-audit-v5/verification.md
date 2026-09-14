# v5 验证记录（2026-09-11）

- 六份继承解析后的训练配置：692 个按槽位展开的效果定义，0 个审计错误。
- 默认 Go 审计与负向测试：删除 order、IR、定义引用，或注入未注册修正都会失败。
- 随机整局：12 种子、656 次输入、95 回合、6 个角色死亡、21 种出现过的效果；五类动作均覆盖。
  原局/克隆/池化快照/checkpoint（支持的节点）和完整回放一致。
- 随机独立层：24 种子×160 操作，共 3840 次；与独立参考模型一致。
- `go test -race ./gicg_engine/... ./gicg_mcts/... ./gicg_actor/...`：通过。
- 重建 C shared 库后，环境、训练与 cards 工具 Python 套件：1245 passed、6 skipped。
  继续显式排除含无界 minimax 的 `training/tests/test_greedy_player.py`，未把它记为通过。
- 五范式完整烟雾：10 passed，711.90 秒；CFR 沿用既有测试桩，不能据此声称完成真实 CFR 策略训练。
- 未启动正式 RL、远程实验、零样本胜率或微调泛化对照。

## 可复现命令

```sh
.venv/bin/python -m tools.cards.effect_audit --output /tmp/effect-audit.json
GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_engine/tests -run 'TestRandomEffectSequences|TestRandomIndependentLayersAgainstReference' -count=1 -v
GICG_AUDIT_SEED=3 GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_engine/tests -run TestRandomEffectSequences -count=1 -v
```

整局随机测试失败时保存种子、完整 factory 配置和输入索引序列，默认目录为系统临时目录下的
`gicg-audit-failures`；可用 `GICG_AUDIT_FAILURE_DIR` 指定持久目录。
固定种子重跑依赖同一规则/引擎基线，不能把动作索引用于其他版本。

## 结论边界

实际修复了玄冰/武器漏绑、实例所属方读取错误、公开决策状态缺失和 counter 观测截断。
绑定覆盖不等于穷尽语义分支；复杂暂停程序和旧式引用语义的可观测性限制已保留在审计报告。
新增实现与测试文件符合行数限制；全仓仍有既存超限文件，没有以此阻断本轮验收。

OpenSpec 索引、相关格式/F821、`git diff --check` 通过。
新基线 `current-training-custom-v5` 冻结 852 个文件，校验 MATCH；旧版 manifest 未修改。
