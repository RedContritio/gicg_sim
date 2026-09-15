# Backlog

跨项目(training / engine / infrastructure)待办清单。按类别组织,不按时间
排序——优先级在表格里标。更新随代码一起 commit,正常 git workflow。

**更新规范**:
- 完成的项目**不要**从表格删,移到文末 "Completed" 区,保留历史决策脉络
- 新 idea 直接插到相应类别,状态字段标 `idea` / `scoped` / `in-flight` / `blocked`
- 优先级(`P`)字段:1=now / 2=after current run / 3=nice-to-have / 4=research
- 一行一事,避免嵌套。若事需要拆,就拆成多行

## 训练 runs

| ID | run label | Config | 目的 | P | 状态 |
|---|---|---|---|---|---|
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
| I2 | /loop 显式起动流程 | 让 ScheduleWakeup 在 runtime 下可靠 fire;无代码改动,改工作流 | 2 | idea |
| I4 | ScheduleWakeup fire telemetry | 写 `artifacts/wakeup_log.jsonl`,记录预期 vs 实际 fire 时间,积累丢 fire 模式 | 4 | idea |
| I8 | Cost icon OCR + 直方图自动判定 | 增量 raw 录入时(新版本卡引入新 cost icon hash),自动判 cost type 不依赖人工。机制:OCR 中心数字(template match 0-5,字体大易识别)+ 扣中心区取环形主色直方图(白浅描边=same,深灰实心=any,7 元素色=specific)。当前 38 hash 已人工判定(2026-04-28 PM),保存在 `data/cost_icons/_judgement.yaml`,可作 ground truth 校准 OCR 模型。等出现新 hash 再做。 | 4 | idea |
| I9 | `tools.runs.sync` 跨机重名冲突安全 (类 2 H4) | rsync `--update` 跨机重名 silently clobber by mtime,无冲突报告。两个 dev 同时 register `r013`,后 push 的覆盖先的(且不报)。修法:sync 前 fetch 远端 metadata,mtime tie + content diff 时 fail;或按 host namespace metadata 路径(`artifacts/runs/<host>/<id>.toml`)。需要先决策 namespace 策略 | 3 | idea (audit `tools/runs/` 2026-05-18) |
| I10 | `tools.runs.sync` 前向兼容 host namespace | 当前 register/list/schema hardcoded `runs_dir/<id>.toml` flat 顶层,无 nested 路径风险。若 I9(跨机冲突 host namespace)落地为 `artifacts/runs/<host>/<id>.toml`,sync include `*.toml` 会漏 subdir。Pre-decision:I9 决策后,sync include 同步加 `**/*.toml`,或保持 flat 用 host hash 后缀 | 4 | idea (contingent on I9, 2026-05-18) |
| I29-D1 | I29 Win box gate (post-R7 follow-up) | Mac fair bench 1.54x MET,Win box (`dev@192.0.2.10`) production fair bench 仍未跑。user 接受 Mac-only ACCEPT,但 audit reviewer R4 flag silent 范围降级,留 follow-up verify Win Go/Py ratio | 3 | idea (audit I1 deferred,2026-05-25) |
| I29-D2 | I29 production no-cap fair bench | bench cfg `minimax_node_budget=4000` 双侧 capped to ~D2.7,production stage3 cfg 不设 cap 跑 full D4。Python cgo crossings (~28K snapshot/step per turn) dominant scenario 下 Go subprocess native interp 应 >> 1.54x。跑 `tools.runs.train configs/dmc/stage3_b_v_legacy_go.toml` vs `stage3_b_v_legacy.toml` × 多 seed (~30 min/run × 6 runs = 3h wall)。验证 I29 real production motivation | 2 | idea (post-R7 follow-up,2026-05-25) |
| I29-D3 | I29 AZ/PPO/CFR/BC paradigm Go subprocess port | R7 仅 ship DMC paradigm。各 paradigm port 走 R7 N-subprocess pattern (Go obs encoder + opp baseline + paradigm.Run + Python collector adapter + tests,~500-800 LOC each)。CFR/BC 是否值得 port 看 paradigm tier (CFR=frozen,BC=first-class)。Phase 2 follow-up,各 paradigm 单独 OpenSpec change | 3 | idea (post-R7 follow-up,2026-05-25) |
| I29-D4 | I29 test coverage gap (N>2 e2e + partial-spawn cleanup + inference path) | 5ep_e2e tests N=2 only,production 跑 N=4-16,N=4+ parametrize 缺。partial-spawn failure cleanup (`go_subprocess_pipeline.py` try/except block) 无 dedicated test (只 implicit cover)。~150 LOC 加 `parametrize(N=[2,4])` + 加 `test_partial_spawn_cleanup` killing one subprocess mid-spawn | 4 | idea (post-R7 follow-up,2026-05-25) |
| I29-D5 | I29 Linux GPU box re-verify | Mac M4 scheduler CV 30-67%,Linux box (GPU 可选) 应给 tighter std bounds + 真 production GPU pipeline。现 Linux GPU box 不在 infra,follow-up if 新机器 available | 4 | idea (post-R7 follow-up,2026-05-25) |

## 测试 / 文档

| ID | 项目 | 说明 | P | 状态 |
|---|---|---|---|---|
| D4 | 更新 `docs/2_decisions/adr-0005-az_decisions_d1_d14.md` | 反映 K=3 移除决策和根因 | 3 | idea |
| D5 | Ablation 总结 doc | 沉淀 r001-r006 对比矩阵 + 三层缺陷分析 | 3 | idea |

## 研究 / scoping

| ID | 问题 | 需要的基础 | P | 状态 |
|---|---|---|---|---|
| R1 | Engine API: `card_requires_char(ref)` 元数据 | 支持 PerOpponentPool 精确过滤 talent;Python / DSL 都能 query | 3 | scoped |
| R3 | Determinization 质量定量评估 | 写 test:某固定局面下 1000 个 det 和 "地面真实" 对手 state 的 earth-mover 距离 | 4 | idea |
| R4 | Game tree 公共信息 vs 隐藏信息 完整审计 | DSL + engine + obs 三层,梳理哪些字段应对对手隐藏(目前基于 ad-hoc 决定) | 4 | idea |

---

## Completed

_完成的工作保留此处,供未来回溯决策脉络。已由后续重构删除/失效的条目合并成行。_

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
| 2026-04-21 | D3 | Bayesian dice posterior tests | `ede252a` — 8 tests 覆盖 uniform(非 chi² 而用均值偏差)+ sum/non-neg/zero + paid 偏斜 + paid/tuned_out 等价性 |
| 2026-04-22 | T1 | r006 消融 char_skill_refs obs region | 定 r001(0.55) vs r005A(0.45) 的 0.10 gap 来源;mcts_200=0.40 |
| 2026-04-22 | T2 | r007 long-scaling run | killed(I5 deadlock);arena collapse g1000=0.05,ckpt_g01200 gauntlet vs_mcts_200=0.05;长程训练暴露 collapse 模式,驱动 r008 paradigm change(AZ→CFR) |
| 2026-04-22 | T3 | r008 CFR prototype | failed — iter 199 40% vs random + 0/10 vs 一切基线;比 iter 20 初始化还差;strat_loss 下降与 policy 质量脱钩。详见 `5_history/runs_pre_redesign_2026_05_17.md` 与 memory `project_rl_routes_closure_2026_05_12` |
| 2026-04-22 | I1 | CronCreate durable backup watcher | durable cron 事实上落地;本 session 每 ~1h fire "Watchdog" prompt 兜底 |
| 2026-04-22 | I5 | train_az worker 死亡死锁 | `fb0c267` heartbeat + PoolDeadlock + SIGKILL/SIGSTOP 回归 |
| 2026-04-22 | I7 | MCTS event log 累积 | `b125ef6` env.log_suspend/resume;r007 replay 1M→438 行 |
| 2026-04-23 | I6 | OS-MCCFR 非收敛 | `e05b713` + `54f6c35` 两步 fix;Kuhn OS Nash 收敛验证 |
| 2026-04-23 | — | eval_service schema-driven 协议 + send_matchup CLI | `34fcc73` JSON Schema authoritative,送 send_gauntlet 告别;CLI dotted path |
| 2026-04-23 | D4 | decisions.md K=3 移除决策 | 新增 D14:ExpandUnionK 废弃决策 + 根因(只变 dice 不变 hand/deck,D1 覆盖 <20%,净负 0.05) |
| 2026-04-23 | D5 | r001-r006 ablation 总结 | `docs/5_history/ablations/r001_r006_ablation.md` — 三层缺陷分析:fast anneal / K=3 / char_skill_refs 的独立净效应 |
| 2026-04-23 | D6 | 拆 gicg_env/tests/test_env.py | `7fed8df` — 539 → 299 + test_env_inspect.py 244 |
| 2026-04-23 | D7 | 全 repo line-limit 违反清零 | `6917f74` training/ 三层 + `7fed8df` 剩 py 4 文件 + `3c194e8` Go 24 文件 |
| 2026-05-17 | I3 | `tools.register_run.py` 自动 append registry | `core-network-generic-promotion` 起由 `tools/runs/{register,complete,list,show,sync}` CLI 取代 |
| 2026-05-20 | I24 | DMC mp actor 移除 torch 依赖 | `faf5005`。actor RSS 1.5 GB → 547 MB;Total mem 37 → 8 GB(N=8);N=8 fps 29.5 → 33.1 |
| 2026-05-20 | I25 | InfServer 返 numpy bytes 响应 | `e9d7133`。Opt-in by decoder-path(non-DMC paradigms 保 legacy);Mem 没赚(I24 已把 torch lazy load 干净),perf +11% |
| 2026-05-20 | I27 | `tools.runs._remote_sync` Win path scp 失败 | `da983fe`。`REMOTE_ROOT_POSIX = 'D:/gicg_dev'`(原 `/d/gicg_dev`);`ssh_run` 不受影响 |
| 2026-05-21 | I26 | DMC N=24 actor 不可用根因 | **REVERSED**:I30 ship 后复跑 N=24 得 fps 32.4(N=16 的 88%),oversub 退化未复现。当前 baseline 推荐 N=16,N=24 可用于 scaling 测试 |
| 2026-05-25 | I29 | Go-native actor pool | R7 重构(N 独立 Go subprocess + 删 SHM inference bridge);Mac N=4 fair-budget Go/Py = **1.54x** (5-seed)。详 memory `project_i29_r7_acceptance_ship` + spec `training-architecture/actor-backend.md` |
| 2026-05-26 | I29-D6 | Go N=8 scaling degradation | 根因 GOMAXPROCS oversub;default 0 → 1 后 N=8 ratio 0.66x → **1.21x**;H1 InfServer GIL 假设排除 |
| 2026-05-29 | I28 | `tools.runs` 完整 workflow — 消除手动 ssh/scp | `kill`/`tail` + `pull --dir/--files` + `status.py` 走 `RemoteCfg` + `build_engine` probe gcc;verify 767 PASS + 1 skipped |
| 2026-06-01 | I31 | AZ/CFR/PPO mp actor pool 统一 | squash merge main (`b3d0922`);净 +6903/-4705 LOC;33 commits;1177 PASS + 5 smoke。PPO 暂缓 |
| 2026-06-02 | I11,I13–I23 | `tools.runs` 旧模块遗留项审计 | 合并关闭:相关模块(complete/`tools.run --run-id`)已在 2026-05-18 clean-slate 重写中删除,或缺陷已在新实现中修复。I12 单独落地 |
| 2026-06-02 | I12 | `tools.runs.sync` 从 subdir 调用 silent zero-transfer | `sync.py` `_verify_repo_root` guard 检查 `.git/` 存在 + test |
| 2026-05-29 | I32 | W3 engine ignorance 重构 | **won't fix (cost ROI)** — ~1450 LOC 跨 Go engine + DSL + obs schema + tokenizer,全套 break ckpt;仅当 RL pipeline 稳定收敛且有专职 4-6 周窗口再评估 |
