# 新 session 接手清单

**训练保持暂停。56 当前禁止使用。** 禁止状态持续有效，直到用户明确重新授权；重新授权后持续有效，直到用户再次取消。禁止期间不得对 56 做只读探查、同步、训练、评估或进程操作。

当前状态以 [实时状态](0_status/README.md) 为入口；实验细节见 [暂停交接](HANDOFF_PAUSED.md) 和 [ExIt 报告](5_history/exit_pilot_20260918.md)。

## 当前结论

1. 当前目标仍是「在保持零样本/少样本泛化能力的基础上，稳定战胜 F1-D2」，**尚未完成**。
2. 当前最好已确认的语义策略是 executed warmup + RL16：原生约 42–45%，heldout 变体约 40–43%，正式 CI 下界仍低于 50%。
3. 数据扩容、容量、DAgger、追加 RL、推理时搜索、从零 ExIt 和无锚 ExIt 热启动均未突破目标。
4. 锚定 ExIt 的 beta=0.3 没有建立正向证据：argmax 75/220，对基线 83/220；MCTS16 66/220，对基线 64/220。
5. beta=1.0 只完成一个短训练切片。56 上 run `202609200935_000084_exit_ws_anchor_b1` 产出 `ckpt_2431.pt`，但尚未评估；其 metadata 仍错误标记为 `running`。取消授权前最后一次核对未发现活动 Python 进程，此后不得再探查。

## 工作区

- 分支 `dev`，本地提交尚未 push。
- `v0.3.2` 收录每回合正常重掷、任意可加载 checkpoint 的 Web 推理、完整网页对局日志，以及棋盘内的目标、支付、调和和重掷交互。
- 每回合重掷是环境行为变化：旧 checkpoint 仍可加载，但训练时未见过该决策；旧评估结果只代表无正常重掷的旧环境，需要在当前规则下重新评估。
- 2026-09-22 已通过 Go 引擎测试、训练测试、环境与 Web 后端测试、前端 lint/生产构建和 diff 检查。`ref/genius-invokation` 是独立参考包，未安装其 `gitcg` 绑定，不计入项目测试。
- 当前本地源码指纹：`ffcd19e36cc81e7730bf7a390989055db5f22869ddc15f6624c41d2f7b8ab0bf`。
- 本次结构拆分触及指纹覆盖内源码。beta=1.0 checkpoint 生成于拆分前；未来若重新授权使用 56，**先决定如何评估该 checkpoint，不要先同步本地源码覆盖远端现场**。
- `remote-host-decoupling` 已实现并归档；远端操作仍只允许走 `tools.runs.*`，不得手写 SSH/SCP。

## 恢复顺序

1. 读本页、[实时状态](0_status/README.md)、[暂停交接](HANDOFF_PAUSED.md)、`CLAUDE.md` 和 `openspec/project.md`。
2. 运行 `git status --short --branch`；保留所有现有改动。
3. 只做本地检查与整理，直到用户明确重新授权 56。
4. 若工作区继续变化，重跑与改动相称的本地测试和门禁；否则沿用 `v0.3.2` 的验收结果。
5. 重新授权后，先处理 run 000084 的陈旧 metadata 和 `ckpt_2431.pt` 评估方案，再决定是否同步或继续实验。
6. 新训练、续训和大规模评估均需用户明确要求；设备授权不等于自动授权启动训练。

## 评测纪律

- 正式 F1-D2 面板：opponent depth 2，55 scenarios × 2 layouts × 2 sides = 220 局。
- 已用于选模的 seed 不得再当独立证据；正式晋级用新 seed，报告配对场景聚类 95%CI。
- 最终目标要求多种子下 CI 下界 >50%，并保留 heldout 规则变体表现。
- 最终预留训练 seed 971000/981000/991000、测试 seed 971900/981900/991900 尚未使用。

## 最小接手提示词

> 阅读 CLAUDE.md、openspec/project.md、docs/0_status/README.md、docs/HANDOFF.md 和 docs/HANDOFF_PAUSED.md，在 dev 的脏工作区接手，不 reset/clean。56 当前禁止使用，且该状态持续到用户明确重新授权。当前断点是锚定 ExIt beta=1.0 的 ckpt_2431 尚未评估；先完成本地验收与文档收口，不自动训练。

## 历史资料

- [ExIt / AZ 战役记录](5_history/exit_pilot_20260918.md)
- [F1-D2 战役总结](5_history/d2_campaign_20260917.md)
- [暂停期旧会话](5_history/pause_sessions_20260914_0915.md)
- [历史交接 1](5_history/handoff_20260914_part1.md)
- [历史交接 2](5_history/handoff_20260914_part2.md)
- [历史交接 3](5_history/handoff_20260914_part3.md)
