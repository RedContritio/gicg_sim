# Backlog

跨项目(training / engine / infrastructure)待办清单。按类别组织,不按时间
排序——优先级在表格里标。更新随代码一起 commit,正常 git workflow。

**更新规范**:
- 完成的项目**不要**从表格删,移到文末 "Completed" 区,保留历史决策脉络
- 新 idea 直接插到相应类别,状态字段标 `idea` / `scoped` / `in-flight` / `blocked`
- 优先级(`P`)字段:1=now / 2=after current run / 3=nice-to-have / 4=research
- 一行一事,避免嵌套。若事需要拆,就拆成多行

## 监控节奏(ScheduleWakeup delaySeconds)

长任务(训练 / smoke / gauntlet)的 wakeup 节奏固定如下:

| 场景 | delay | 理由 |
|---|---|---|
| 距任务结束 > 1h | **3300s (55min)** | 粗粒度,不白烧 cache TTL |
| 距任务结束 ≤ 1h | **900s (15min)** | 细粒度,衔接 phase 切换 |

**任务完成后的首次 wakeup** 必须:
1. 检查上一任务结果(final ckpt / gauntlet_results / 进程状态)
2. 记录结果(report + registry)
3. 启动下一项任务(从 backlog 按 P 值)
4. 按上表重新计算 delay

同任务内反复监控 → 每次 fire 先估算距结束时间,再选 delay。

---

## 训练 runs

| ID | run label | Config | 目的 | P | 状态 |
|---|---|---|---|---|---|
| T1 | r006 | `configs/r006_slow_noskillrefs_400g.toml` | 消融 char_skill_refs obs region,定 r001(0.55)vs r005A(0.45)的 0.10 gap 来源 | 1 | **done** (mcts_200=0.40) |
| T2 | **r007** 长程 | `configs/r007_slow_1500g.toml` slow anneal 1500g | scaling 验证:看 r001 0.55 在 1500g 能否到 0.70+ | 1 | **done** (2026-04-22, killed I5 deadlock; arena collapse g1000=0.05, ckpt_g01200 gauntlet vs_mcts_200=0.05;完整失败分析见 registry) |
| T3 | **r008** CFR prototype | `tools.run_cfr --preset r008_cfr_prototype --n-workers 4` | 跨 paradigm 验证:Deep CFR 在本游戏 fixed-team 2v2 下能否训出可用策略 | 2 | **done, failed** (2026-04-24) — iter 199 40% vs random + 0/10 vs 一切基线;比 iter 20 初始化还差;strat_loss 下降与 policy 质量脱钩。详见 memory `project_r008_postmortem` + registry r008 result |
| T4 | r001 重做 | 旧配置 + 修好的 determinize(per-opponent + Bayesian dice) | 新基线是否显著 > 0.55 | 4 | idea |

## 算法改进

| ID | 项目 | 说明 | P | 状态 |
|---|---|---|---|---|
| A1 | C 方案:D1 actions network-informed prior | addNewActionsUniform 触发时单独发 tiny eval 求 prior,替换 1/n uniform。直击 r003 反向相关根因 | 2 | scoped |
| A2 | d_model 128→256 + MPS backend | memory `feedback_default_mps`:d_model=128 下 MPS 慢 CPU 3-4×;≥256 + batch≥32 可能翻盘。需 smoke 验证 | 3 | idea |
| A3 | priority_weight ablation | 当前 3.0。做 {1.0, 2.0, 3.0, 5.0} smoke 对比。AZ 论文接近 uniform | 3 | idea |
| A7 | IS-MCTS root dirichlet_eps 调参 | 当前 0.25。扫 grid 看探索平衡 | 4 | idea |

## 基础设施 / 监控

| ID | 项目 | 说明 | P | 状态 |
|---|---|---|---|---|
| I1 | CronCreate durable=true backup watcher | 每 30min 独立于 /loop 检查 pipeline 状态,防 ScheduleWakeup 丢 fire | 1 | **done** (durable cron 已跑;每 ~1h fire "Watchdog" prompt 检查 r006/r007/活任务;ScheduleWakeup 丢 fire 时兜底触发) |
| I2 | /loop 显式起动流程 | 让 ScheduleWakeup 在 runtime 下可靠 fire;无代码改动,改工作流 | 2 | idea |
| I3 | `tools/register_run.py` 自动 append registry | ~~launch_config 时自动往 docs/4_runs/registry.md 加行~~ **DONE** by `tools/runs/{register,complete,list,show,sync}` CLI in `core-network-generic-promotion` 2026-05-17 (`tools/_meta/register_run.py` 已 deprecated banner) | 3 | **done** |
| I4 | ScheduleWakeup fire telemetry | 写 `artifacts/wakeup_log.jsonl`,记录预期 vs 实际 fire 时间,积累丢 fire 模式 | 4 | idea |
| I5 | **[BUG] train_az worker 死亡死锁** | `_train_async.py:108` `pool.next_result(timeout=None)` 无超时 + 无 worker liveness 探测。r007 现场:1 worker 静默死亡,253 局结果从未入 queue,主线程永久阻塞。修复 commit `fb0c267`:heartbeat Array + `alive_workers()` + `PoolDeadlock` 异常;SIGKILL + SIGSTOP 两场景回归测试通过(`test_parallel_pool_deadlock.py`)。验收过。 | 1 | **done** (2026-04-22) |
| I6 | **[BUG] OS-MCCFR 非收敛** | B1 review 验证在 Kuhn Poker 上 OS 不收敛。两处 bug 按 Lanctot 2013 Def.4 修复:① `reach_q_full` → per-decision `reach_q_prefix`(commit `e05b713`)② 非采样 regret 用 σ(a*) 而非 σ(a)(commit `54f6c35`)。测试:Kuhn OS 50K iter 收敛 Nash 家族(P1(J)=0.263, P2(Q)|bet=0.394 ≈ 1/3,etc)。 | 1 | **done** (2026-04-23) |
| I7 | MCTS snapshot/restore 期间 event log 累积 | r007 replay diagnostic 显示 ckpt_g01200 vs mcts_100 对局的 YAML replay 达 1M 行 / 22908 次 "round 10" 标头 — MCTSPlayer 在 rollout 时 env.step() 写到 game log,env.restore() 只恢复 state 不截日志。修复 commit `b125ef6`:`env.log_suspend()/resume()` 开关,MCTS/AZ player 的 select_action 包一层。r007 replay 1M → 438 行(正常 10 round)。副产物:长 gauntlet 加速 | 1 | **done** (2026-04-22) |
| I8 | Cost icon OCR + 直方图自动判定 | 增量 raw 录入时(新版本卡引入新 cost icon hash),自动判 cost type 不依赖人工。机制:OCR 中心数字(template match 0-5,字体大易识别)+ 扣中心区取环形主色直方图(白浅描边=same,深灰实心=any,7 元素色=specific)。当前 38 hash 已人工判定(2026-04-28 PM),保存在 `data/cost_icons/_judgement.yaml`,可作 ground truth 校准 OCR 模型。等出现新 hash 再做。 | 4 | idea |
| I9 | `tools.runs.sync` 跨机重名冲突安全 (类 2 H4) | rsync `--update` 跨机重名 silently clobber by mtime,无冲突报告。两个 dev 同时 register `r013`,后 push 的覆盖先的(且不报)。修法:sync 前 fetch 远端 metadata,mtime tie + content diff 时 fail;或按 host namespace metadata 路径(`artifacts/runs/<host>/<id>.toml`)。需要先决策 namespace 策略 | 3 | idea (audit `tools/runs/` 2026-05-18) |
| I10 | `tools.runs.sync` 前向兼容 host namespace | 当前 register/list/schema hardcoded `runs_dir/<id>.toml` flat 顶层,无 nested 路径风险。若 I9(跨机冲突 host namespace)落地为 `artifacts/runs/<host>/<id>.toml`,sync include `*.toml` 会漏 subdir。Pre-decision:I9 决策后,sync include 同步加 `**/*.toml`,或保持 flat 用 host hash 后缀 | 4 | idea (contingent on I9, 2026-05-18) |
| I11 | `tools.runs.complete` 状态机 guard (类 2 L11) | 当前 `complete --status` 允许任意转移 done→failed→done,`--final-loss` 覆写无 audit trail。修法:reject status 降级(done 后只允许加 notes,不允许改 status),或前值入 `notes.text` 追加。需决策"是否允许 re-complete" | 4 | idea (audit `tools/runs/` 2026-05-18) |

## 测试 / 文档

| ID | 项目 | 说明 | P | 状态 |
|---|---|---|---|---|
| D4 | 更新 `docs/2_decisions/adr-0005-az_decisions_d1_d14.md` | 反映 K=3 移除决策和根因 | 3 | idea |
| D5 | Ablation 总结 doc | 沉淀 r001-r006 对比矩阵 + 三层缺陷分析 | 3 | idea |
| D6 | 拆 `gicg_env/tests/test_env.py`(539) | 500 行上限遗留 | 4 | **done** (commit `7fed8df` 拆 test_env.py 539→299 + test_env_inspect.py 244) |
| D7 | 拆剩余超限文件 | 2026-04-23 training/ 三层拆分 + 剩余 py + Go 全清。最终状态:`tools/_meta/check_line_limits.py` 零违反 | 4 | **done** (commits `6917f74` + `7fed8df` + `3c194e8`:training/ 三层 + 4 个 py + 24 个 Go 全拆) |

## 研究 / scoping

| ID | 问题 | 需要的基础 | P | 状态 |
|---|---|---|---|---|
| R1 | Engine API: `card_requires_char(ref)` 元数据 | 支持 PerOpponentPool 精确过滤 talent;Python / DSL 都能 query | 3 | scoped |
| R3 | Determinization 质量定量评估 | 写 test:某固定局面下 1000 个 det 和 "地面真实" 对手 state 的 earth-mover 距离 | 4 | idea |
| R4 | Game tree 公共信息 vs 隐藏信息 完整审计 | DSL + engine + obs 三层,梳理哪些字段应对对手隐藏(目前基于 ad-hoc 决定) | 4 | idea |

---

## Completed

_完成的工作保留此处,供未来回溯决策脉络_

| 完成日 | ID | 项目 | 落地 commit |
|---|---|---|---|
| 2026-04-21 | (近期) | obs config 开关(A 方案) | `038bdef` |
| 2026-04-21 | (近期) | 删除 expand_union_k 全部代码 | `29ca0c4` |
| 2026-04-21 | (近期) | `_resolve_pool_refs` 读真实 deck(去 filler hack) | `4e434c8` |
| 2026-04-21 | (近期) | PerOpponentPool + Bayesian dice posterior | `4301786` |
| 2026-04-21 | (近期) | `tools/diag_determinize.py` + 契约审计 doc | `8f66729` |
| 2026-04-21 | A4 | Hand posterior Bayesian audit | N/A (no code)。引擎无 mulligan phase、无 redraw 机制,hand 只通过 draw(deck→hand)/ play / tune 动,所有动作在 `_subtract_public(pool, opponent_discard)` 后已反映到 `remaining`。给定当前 observables `{pool, discard, hand_size, deck_size}`,采样 = uniform-without-replacement over remaining → **即最优 Bayesian 后验,当前实现无改进空间**。A6(原"对手打过的 card_ref 从 remaining 减去")被证实和 A4 重复且已实现,一并关闭 |
| 2026-04-21 | A5 | Tune action → dice posterior | `65c2fc5` — Game.DiceTunedOut/In accumulator,tune 执行时 increment;capi GameGetDiceTunedOut/In;determinize `sample_opponent_dice(paid, tuned_out)` α = 1 + paid + tuned_out。DiceTunedIn 暴露但暂不用(硬下界 TODO) |
| 2026-04-21 | D1 | ObsConfig toggles tests | `ede252a` — 5 tests 覆盖 include_char_skill_refs + 4 shuffle toggle on/off 对照 |
| 2026-04-21 | D2 | PerOpponentPool tests | `ede252a` — 4 tests 覆盖 dispatch + copy-semantics + key validation |
| 2026-04-22 | I5 | train_az worker 死亡死锁 | `fb0c267` heartbeat + PoolDeadlock + SIGKILL/SIGSTOP 回归 |
| 2026-04-22 | I7 | MCTS event log 累积 | `b125ef6` env.log_suspend/resume;r007 replay 1M→438 行 |
| 2026-04-23 | I6 | OS-MCCFR 非收敛 | `e05b713` + `54f6c35` 两步 fix;Kuhn OS Nash 收敛验证 |
| 2026-04-23 | — | eval_service schema-driven 协议 + send_matchup CLI | `34fcc73` JSON Schema authoritative,送 send_gauntlet 告别;CLI dotted path |
| 2026-04-21 | D3 | Bayesian dice posterior tests | `ede252a` — 8 tests 覆盖 uniform(非 chi² 而用均值偏差)+ sum/non-neg/zero + paid 偏斜 + paid/tuned_out 等价性 |
| 2026-04-22 | T2 | r007 long-scaling run | killed(I5 deadlock);arena collapse g1000=0.05,ckpt_g01200 gauntlet vs_mcts_200=0.05;长程训练暴露 collapse 模式,驱动 r008 paradigm change(AZ→CFR) |
| 2026-04-22 | I1 | CronCreate durable backup watcher | durable cron 事实上落地;本 session 每 ~1h fire "Watchdog" prompt 兜底 |
| 2026-04-23 | D4 | decisions.md K=3 移除决策 | 新增 D14:ExpandUnionK 废弃决策 + 根因(只变 dice 不变 hand/deck,D1 覆盖 <20%,净负 0.05) |
| 2026-04-23 | D5 | r001-r006 ablation 总结 | `docs/5_history/ablations/r001_r006_ablation.md` — 三层缺陷分析:fast anneal / K=3 / char_skill_refs 的独立净效应 |
| 2026-04-23 | D6 | 拆 gicg_env/tests/test_env.py | `7fed8df` — 539 → 299 + test_env_inspect.py 244 |
| 2026-04-23 | D7 | 全 repo line-limit 违反清零 | `6917f74` training/ 三层 + `7fed8df` 剩 py 4 文件 + `3c194e8` Go 24 文件 |
