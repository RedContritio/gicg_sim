# 验证记录（2026-09-11）

## 交付结果

- [规则清单](rules.md)：21 张实际用牌、赤蝶/墨客及扩展机制，包含费用、
  目标、触发、消费、持续与重置；用户确认 U、项目工作规则 P、疑问 Q
  分开。用户再次确认仅验证当前训练配置，并要求歧义单独确认。
- [交互矩阵](interactions.md)：全部 21 张牌都有证据和缺口映射；新增
  I01–I12 共 12 类、28 个双席位子用例，全通过。
- 新增代码：current_rules_combinations_test.go、current_rules_lifecycle_test.go、
  current_rules_targets_test.go。本批没有修改游戏执行代码或 DSL 行为。
- [源码清单](source-manifest.json)：496 个文件冻结为
  `current-cards-2026-09-11-v1`；包含工作区未提交修改，因此 HEAD 本身
  不足以复现。SHA-256 文件集校验通过；这是依赖超集，不是全池认证。

## 实际执行

| 检查 | 结果 |
| --- | --- |
| `go test ./gicg_engine/tests -run '^TestCurrent(Rules\|Cards)_' -count=1 -json` | 31 个顶层测试、133 个子用例通过，无失败 |
| `go test -race ./gicg_engine/... ./gicg_mcts/...` | 所有包通过；未变化包使用 Go 测试缓存，新增测试所在包本次运行 |
| `go build ./...` | 通过 |
| `.venv/bin/python -m pytest tools/cards/tests/test_rule_baseline.py -q` | 5 通过；覆盖不变、拒绝覆盖、内容变化、新增、删除（含文档删除） |
| `.venv/bin/python -m tools.cards.rule_baseline` | MATCH，496 文件 |
| OpenSpec 索引、gofmt、ruff check/format、git diff --check | 通过 |

Go 命令使用 `GOCACHE=/private/tmp/gicg-review-go-cache`。
本地原始日志：`/private/tmp/gicg-baseline-cases.jsonl`、
`/private/tmp/gicg-baseline-race.log`。日志可能随临时目录清理，仓库内测试
和手工预期保留，可通过上述命令重新执行。

本批只改文档、测试及版本校验工具，没有重新构建 Python 引擎库，也未
重跑训练集成；上批 177 项 Python 结果不表述为本批重新执行。

## 使用版本校验

从仓库根目录运行：

```bash
.venv/bin/python -m tools.cards.rule_baseline
```

任何覆盖范围内的文件变动、增删都会返回非零并列出差异。工具只读校验，
不会自动更新指纹。规则裁定导致变化时，应在新版本目录准备 rules.md
和 interactions.md，再指定新的清单路径及版本创建：

```bash
.venv/bin/python -m tools.cards.rule_baseline --freeze \
  --manifest openspec/changes/<new-version>/source-manifest.json \
  --version <new-version>
```

已有清单拒绝覆盖。不要用更新哈希的方式跳过规则/测试复核。

## 尚未闭合

本批工作完成的是可追踪规则基线与关键交互验收，尚未完成所有规则裁定。
已单独询问乘胜计数起点、佛跳墙来源/期限、后台蝶印。剩余优先级/目标
边界见 Q01–Q05；以逸待劳归因是已知缺陷，仅 HP 结果测试通过不能掩盖。
本批没有进行随机对局验证，没有启动训练，没有提交或发布代码。

2026-09-11 补充：[D01](decisions.md) 已确认乘胜计数起点；现有执行无需改动。
重新运行该牌第四次付费操作专项，10 个双席位/操作类型子用例通过；
v1 源码指纹仍匹配。佛跳墙及后台蝶印仍等待答复。
