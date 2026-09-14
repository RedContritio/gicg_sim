# v2 验证记录（2026-09-11）

三项用户裁定已落实到 [规则清单](rules.md)：乘胜计数起点确认不需改码；
佛跳墙增加技能来源门槛及回合末清除；蝶印扩大到带印后台角色。

新增 current_rules_clarified_test.go，覆盖真卡牌伤害不消费佛跳墙、
其他非技能来源不消费、技能恰好消费一次、后台未用食物过期、后台印
仅命中带印者且下回合不重复、多个印致死后的克隆恢复和参数错误。
新增 IR 用例确认目标筛选计数绑定没有从模型可见规则中丢失。

## 已运行

- 卡牌/组合专项：`go test ./gicg_engine/tests -run '^TestCurrent(Rules|Cards)_' -json -count=1`，
  36 个顶层测试、141 个子用例通过，无失败。日志 `/private/tmp/gicg-rules-v2-cases.jsonl`。
- `go test -race ./gicg_engine/... ./gicg_mcts/...` 通过，日志
  `/private/tmp/gicg-rules-v2-race.log`。
- `go test -race ./gicg_actor/...` 通过，日志 `/private/tmp/gicg-rules-v2-actor.log`。
- 重建 `gicg_env/libgicg.dylib` 后，环境与四个 MCTS 集成模块 177 通过，
  日志 `/private/tmp/gicg-rules-v2-python.log`。
- 版本工具 5 项测试通过；`go build ./...`、gofmt、ruff、OpenSpec 索引、
  diff 空白检查通过。
- `current-cards-2026-09-11-v2` 冻结 499 个文件，默认命令
  `.venv/bin/python -m tools.cards.rule_baseline` 校验 MATCH。

Go 使用 `GOCACHE=/private/tmp/gicg-review-go-cache`。Python 集成命令：

```bash
.venv/bin/python -m pytest -n 4 gicg_env/tests/ \
  training/tests/test_mcts.py training/tests/test_mcts_go.py \
  training/tests/test_az_mcts_go_phase2_path.py \
  training/tests/test_az_mcts_phase2_path.py -q
```

v1 的规则文档及指纹未覆盖；切换默认校验至 v2。对旧 v1 执行校验会
报告已知代码变化，这是版本漂移提示，不应刷新旧清单来隐藏差异。
没有启动训练；没有提交代码。剩余语义与已知归因问题见 rules.md Q 表。
