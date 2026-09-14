# 验收方法

所有命令从仓库根目录运行。引擎共享库在 Python 验收前重新构建。完整 smoke 期间不修改生产源文件，以免其进程级来源指纹缓存与续训子进程不一致。

```sh
GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_engine/... ./gicg_mcts/...
GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_actor/...
GOCACHE=/private/tmp/gicg-review-go-cache go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/
.venv/bin/python -m pytest -n 4 training/tests gicg_env/tests -k 'not test_budget_uncapped_equals_old_const' -q
.venv/bin/python -m pytest -m smoke_full training/tests -q
GOCACHE=/private/tmp/gicg-review-go-cache go test -race ./gicg_engine/tests -run 'TestTargetFrame|TestLegacyTarget|TestCounterPerspectiveForced' -count=1
.venv/bin/python -m pytest tools/cards/tests/test_rule_baseline.py -q
.venv/bin/python -m tools._meta.check_openspec_indices
```

Go actor 及 Python 集成测试需要临时本机端口、共享内存和进程指标访问。初次沙箱运行被这些系统接口权限阻止，停止了该次完整 smoke；在允许这些接口的本地环境重新验收。不得将权限失败计为测试通过。

沿用 v8 的显式排除：`TestMinimaxBudget::test_budget_uncapped_equals_old_const` 比较两个实际上无上限的深度 4 搜索，运行时间不可控；该未修改用例不在本轮验收结论内。完整 smoke 的临时数据/检查点均重新生成，未载入旧训练结果。

专项覆盖：实际支付后暂停、非法输入无副作用、消费后不可重复调用、快照/导入 map 独立性、独立运行时恢复、卡牌/程序/参数可见、对手私有条件不可见、未知 native 规则降为不完整、损坏和旧版检查点原子拒绝、真实致死伤害保持重放路径标记、规则引用重编号与绑定重排不改变 NN 语义、梯度到规则及类别编码。

通过只说明这些路径和训练链路的回归结果；不能证明完整规则正确、完整程序可见、或零样本策略能力。完整暂停解释器迁移仍在 tasks 的未完成项中。
