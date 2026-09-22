# 新 session 接手清单

**56 已授权使用。** 授权持续有效，直到用户明确取消；包含训练、评估和其他高性能操作。当前没有活动远端任务。

当前状态以 [实时状态](0_status/README.md) 为入口；实验细节见 [暂停交接](HANDOFF_PAUSED.md) 和 [ExIt 报告](5_history/exit_pilot_20260918.md)。

## 当前结论

1. 当前目标仍是「在保持零样本/少样本泛化能力的基础上，稳定战胜 F1-D2」，**尚未完成**。
2. 当前最好已确认的语义策略是 executed warmup + RL16：原生约 42–45%，heldout 变体约 40–43%，正式 CI 下界仍低于 50%。
3. 数据扩容、容量、DAgger、追加 RL、推理时搜索、从零 ExIt 和无锚 ExIt 热启动均未突破目标。
4. 锚定 ExIt 的 beta=0.3 没有建立正向证据：argmax 75/220，对基线 83/220；MCTS16 66/220，对基线 64/220。
5. beta=1.0 的 run `202609200935_000084_exit_ws_anchor_b1` 只有 12 局、797 条 transition、32 次训练更新，不能作算法判读；产物已拉取，远端任务已停止。
6. RL16→AZ 只是参数移植，不是行为等价转换。4 局 823 个同状态决策中，普通决策 argmax 一致率 71%，最大概率误差 0.608。由此暂停端到端 ExIt 主线。
7. 第二轮 GPT-6 审查已完成。当前只批准有硬预算上限的冻结策略 value 诊断；若 V 在预算内没有通过，唯一备选是从原 SemanticQNet 出发的 native DMC。反事实教师不再是 native DMC 的前置条件，R 作为独立投入方向暂停。
8. 32 根修正隐藏信息评估的平均配对收益在 signed-outcome 尺度为 -0.0104，换算为 expected-score 为 -0.0052（-0.521pp），根聚类正态 95% 区间为 [-0.0467, +0.0362]。后续 4 根 exhaustive 中只有 2 个根产生非 current raw leader；aligned/unaligned 各做 64 次独立 paired validation，均无 qualified root。opening teacher 未取得资格，但这不足以全局否定方法；未训练 reroll adapter。
9. 终局 PG 在 seed 932000/932100/932200/932300 上相对 acceptance 基线分别为 +3.636/-1.818/-0.455/+3.182pp，均值 +1.136pp，但 two-level CI 跨零。等权 soup 在 seed 935000 为 38.636%，RL16 基线 41.364%，paired delta -2.727pp，paired 95% 区间 [-6.818,+0.909]pp。
10. generic pair 的 256×4 结果为开发分数 30.0%（基线 31.818%）；逐色 reroll 原语与 RNG 错位使该标签构造无效。ordinary-only 128×8 仍为 30.0%，仅 31 rows，其中 17 条权重 0.25、14 条 discordance，终局动作偏好仍过于稀疏。原语/观察正确，当前问题是教师标签构造与方差，不能判定教师思想失效；已暂停扩训。
11. value 工具曾混用 signed outcome（-1/0/+1）与 expected score（0/0.5/1；存在平局时不等于纯胜率）。纯终局续局实验不受该尺度问题影响；使用 value/search 的历史判断必须在显式编码修复后重新确认。当前工作区已加入 checkpoint `value_encoding`、加载时统一转为 signed、搜索边界转回 expected score，以及完整 macro-reroll 后继状态的 value 诊断，但尚未完成正式校准实验。
12. 第二轮 GPT-6 独立审查已完成，原始回复保存在 [`review/gpt6_d2_training/002_reply.md`](../review/gpt6_d2_training/002_reply.md)。结论是先做 V 诊断，失败后转 native DMC；不恢复当前 ExIt/MCTS，也不继续无上限扩大反事实教师。

## 工作区

- 分支 `dev`，本地提交尚未 push。
- `v0.3.2` 收录每回合正常重掷、任意可加载 checkpoint 的 Web 推理、完整网页对局日志，以及棋盘内的目标、支付、调和和重掷交互。
- 每回合重掷是环境行为变化：旧 checkpoint 仍可加载，但训练时未见过该决策；旧评估结果只代表无正常重掷的旧环境，需要在当前规则下重新评估。
- 2026-09-22 已通过 Go 引擎测试、训练测试、环境与 Web 后端测试、前端 lint/生产构建和 diff 检查。`ref/genius-invokation` 是独立参考包，未安装其 `gitcg` 绑定，不计入项目测试。
- `remote-host-decoupling` 已实现并归档；远端操作仍只允许走 `tools.runs.*`，不得手写 SSH/SCP。
- `artifacts/` 已从约 84 GB 清理到约 116 MB。当前顶层只保留 `d2_training`、`exit_az`、`semantic_rl`、`web_live` 四个系列 tag；旧实验、重复权重、临时评估和空运行已按用户授权永久删除。`exit_az` 本地 run 的 243 个滚动 checkpoint 已裁为单一 `latest.pt`。
- 运行系统的 tag 布局改造位于未提交工作区：新增显式 `meta.experiment_tag`，新运行目标格式为 `artifacts/<experiment_tag>/<timestamp>_<NNNNNN>/`，`run_label` 只描述单次运行；未配置时暂时回退到 `run_label`。allocator、list、show、recover、resume 和 sync 已适配，相关测试 248 项通过，ruff、line-limit 和 `git diff --check` 通过。仍需在提交前复核旧夹具假设，并给同系列活动配置补齐统一 `experiment_tag`。
- Web 发布模型现位于 `artifacts/exit_az/release/az_exit/`，RL16 位于 `artifacts/semantic_rl/runs/202609172344_000055_semantic_rl/`，Web 对局日志位于 `artifacts/web_live/sessions/`。路径迁移后的 Web 后端测试为 34 passed、1 skipped。
- 当前 `.venv/bin/pytest` 的 shebang 仍指向旧工作区；本机验证使用 `PYTHONPATH=.venv/lib/python3.14/site-packages python3 -m pytest ...`。不要因该入口损坏重建或覆盖用户环境。

## 恢复顺序

1. 读本页、[实时状态](0_status/README.md)、[暂停交接](HANDOFF_PAUSED.md)、`AGENTS.md` 和 `openspec/project.md`。
2. 运行 `git status --short --branch`；保留所有现有改动。
3. 执行 S0 契约与重算：确认 value 编码、视角、训练 target、搜索边界和 rollout `old_value` 一致；从原始 winner/draw 重算统计；确认完整 macro-reroll 协议。任一关键契约失败即停止后续实验。
4. S0 通过后执行限额 S1：优先复用合格轨迹，最多 64 个独立来源组，按来源拆为 48 训练、16 开发；比较冻结表示的 linear、MLP 和 observation probe，每个最多两个初始化、约 1000 次小批更新。若没有可靠 value 信号，不进入 S2。
5. S1 通过后才执行 S2：使用 24 个未参与拟合和选模的新先手根，每根 current 加两个预固定合法候选；每候选先做 8 次真实终局续局，无明显失败时按预定计划补到 16 次。本轮新增采集累计上限为约 150,000 环境步或 75,000 次学习方前向，任一先到即停。
6. V 若在预算内失败，转向 native DMC：保持原生 Q 终局回报回归、新环境数据、完整重掷宏动作、无 PER，先做两个训练 seed、各 64 局的有限恢复实验。不得混入 policy-gradient、参数 soup 或 AZ 转换模型。
7. R 继续暂停；教师资格只约束是否蒸馏该教师，不约束 native DMC。当前 ExIt/MCTS、reroll adapter 和 generic pair 扩训均不恢复。
8. 复核运行系统的 tag 布局改造；活动配置必须显式设置共同的 `experiment_tag`，同系列 seed/retry/eval 不得再次成为顶层目录。工作区变化后重跑与改动相称的测试和门禁。

## 评测纪律

- 正式 F1-D2 面板：opponent depth 2，55 scenarios × 2 layouts × 2 sides = 220 局。
- 已用于选模的 seed 不得再当独立证据；正式晋级用新 seed，报告配对场景聚类 95%CI。
- 最终目标要求多种子下 CI 下界 >50%，并保留 heldout 规则变体表现。
- 最终预留训练 seed 971000/981000/991000、测试 seed 971900/981900/991900 尚未使用。

## 最小接手提示词

> 阅读 AGENTS.md、openspec/project.md、docs/0_status/README.md、docs/HANDOFF.md、docs/HANDOFF_PAUSED.md、docs/3_plans/cards/d2_counterfactual_recovery.md 和 review/gpt6_d2_training/002_reply.md，在 dev 的脏工作区接手，不 reset/clean。56 已授权使用且持续到用户明确取消，当前无活动远端任务。RL16→AZ 非行为等价；现有 opening teacher、终局 PG、soup 和 generic pair 均未取得稳定收益。第二轮审查决定先做有硬预算上限的冻结策略 V 诊断；V 失败后唯一备选是原 SemanticQNet 的 native DMC，R 独立扩训与当前 ExIt/MCTS 暂停。value 的 signed/expected-score 编码修复与正式诊断尚未完成。artifacts 已按系列 tag 清理，运行系统的 experiment_tag 布局仍需集成复核。

## 历史资料

- [ExIt / AZ 战役记录](5_history/exit_pilot_20260918.md)
- [D2 反事实恢复路线](3_plans/cards/d2_counterfactual_recovery.md)
- [GPT-6 第二轮审查问题](../review/gpt6_d2_training/002_prompt.md)
- [GPT-6 第二轮审查回复](../review/gpt6_d2_training/002_reply.md)
- [D2 训练方法审计](../review/gpt6_d2_training/audit.md)
- [F1-D2 战役总结](5_history/d2_campaign_20260917.md)
- [暂停期旧会话](5_history/pause_sessions_20260914_0915.md)
- [历史交接 1](5_history/handoff_20260914_part1.md)
- [历史交接 2](5_history/handoff_20260914_part2.md)
- [历史交接 3](5_history/handoff_20260914_part3.md)
