# 验证与后续入口

从仓库根目录运行，依赖及远程约定遵循 CLAUDE.md。

```sh
GOCACHE=/private/tmp/gicg-review-go-cache go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/
GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_engine/... ./gicg_mcts/... ./gicg_actor/...
.venv/bin/python -m pytest -n 4 training/tests gicg_env/tests tools/experiments/tests tools/eval/tests tools/cards/tests -k 'not test_budget_uncapped_equals_old_const' -q
.venv/bin/python -m tools.experiments.prepare_training --output /private/tmp/gicg-readiness.json
.venv/bin/python -m pytest -m smoke_full training/tests/test_dmc_smoke_full.py -q
GOCACHE=/private/tmp/gicg-review-go-cache go test -race ./gicg_engine/tests -run 'TestPublicCause|TestPublicRound|TestContinuation_|TestTargetFrame' -count=1
```

集成测试需要临时本机端口和共享内存权限。完整 smoke 使用临时工作区的新检查点；期间
保持生产源码不变，避免进程级来源指纹缓存与续训不一致。本次没有改变网络尺寸/类别
词表，广泛回归覆盖五范式默认 smoke，额外完整 smoke 聚焦改动的 DMC 采样/标签入口。
仍显式排除旧的无上限 minimax 用例；22 个 JIT 弃用 warning 沿用既有环境。

失败重现：读取 `<output>.failure.json` 中 config、seed、policy 和 inputs，使用同一
源码/共享库，在 prepare_training 中用 `--configs <config> --seeds <seed>` 重跑；每个种子
依次执行 balanced/aggressive。动作前缀用于进一步缩减反例。失败时主报告不是 passed。

## 下一阶段命令（本轮未执行正式实验）

先进入路线阶段 3 的规则辅助任务和短局面验证；通过后再使用下列小范围 RL 入口。
这些配置各预算 3000 帧，当前模型 276672 参数，默认 seed=41。用 `--override meta.seed=42`
和 `43` 做另外两个独立种子，均从头训练，不能 resume 旧污染权重。

```sh
.venv/bin/python -m tools.runs.train configs/dmc/readiness_base.toml
.venv/bin/python -m tools.runs.train configs/dmc/readiness_tactics.toml
.venv/bin/python -m tools.experiments.evaluate_clean configs/dmc/readiness_base.toml <新检查点> <输出.json> --scenarios 32
```

学习验证配置中禁用了训练内部周期评估，使用上方明确处理平局、步数超限和显式牌组的
独立入口。固定评估种子 91000，32 个场景逐一换边，每个随机/F1-D2 对手各 64 场，
报告胜负平、score、逐场结果和按场景配对的区间。不能把真实平局当失败，也不能把
安全步数截断当平局。记录随机策略本身作为对照，但预检随机对局不用于策略评分。

`readiness_holdout.toml` 留出以逸待劳、速速茶点，两者不在基础/战术训练 card_pool 中。
只做过规则加载/依赖验证，不用该配置采样训练或挑选基础模型。随后先零样本，再比较
分档微调和同适应预算从零训练，并回测旧环境。

5070 Ti 的连接信息、吞吐、显存和远程 actor 仍是后续步骤，未在本轮配置或启动。
