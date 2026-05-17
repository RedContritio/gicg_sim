# DMC 子系统评审 — 2026-05-14

> 范围:`training/dmc/` Phase 3.1-3.4 落盘 + `training/dmc/PLAN.md` Phase 3.5+ 计划 +
> `configs/dmc_stage3{,_smoke}.toml`。
>
> **只讨论缺点**(user 指定)。覆盖 paradigm 选择、架构 / 复用决策、shipped 代码 bug、
> eval 协议、算力账目、计划完备性。共 41 项,按 A-F 分组。
>
> 评审基于的 commit 状态:`feature/dsl-v4-prototype`,`training/paradigms/dmc/notes.md` 标 Phase 3.4
> DONE 2026-05-14 03:44。Stage 3 GPU train 未开始。

---

## 0. 总评

工程上能跑起来的 demo,但**没有正面回答"DMC 能在 GICG 上 work"这个核心问题**。

- A(6)paradigm 与 GICG task structure 错配,DouZero 成功条件几乎不成立
- B(4)"复用 AZ ActorCritic" 的代价被低估,ADR-0006 layout 实质被破坏
- C(14)shipped 代码至少 4 个 hard bug + 多项静默 correctness 问题
- D(5)eval 协议自身 noise dominated,Phase 3.4 PASS 是过度乐观解读
- E(5)Stage 3 cfg 算力账目至少差 1-2 个数量级,GPU 资源会大量浪费
- F(7)fallback / ablation / 诊断预算不存在,closure 决策未引用

最危险的是 A.3:PASS 标准 ≥0.50 vs 同 setup 实测 RL 上限 0.271 ± 0.078。Stage 3 立项即
要求 paradigm-agnostic ceiling 之上 +0.23。Plan 没解释"为什么 DMC 能跨这个 gap"。
即使 bug 全修、性能优化全生效,**先验失败概率仍高**。

---

## A. Paradigm 层:DouZero 成功条件在 GICG 上几乎不成立

### A.1 Task structure 同构性被高估

`README.md:13-19` 把 "imperfect-info / sparse terminal / 大 action space / asymmetric"
列为 GICG 与 DouDizhu 同构,但 DouZero 能 work 的关键前提**全部不成立**:开局后无随机性、
card combo 有强组合先验、episode ≤100 step。GICG 每回合摇 8 骰子、双方各抽牌、
episode ~340 step(`memory/project_episode_step_bound.md`)。这是把"看上去同类"等同于
"算法可迁移"。

### A.2 MC return 在长 episode + 强随机下方差爆炸

γ=1 让一个 episode 内**所有** acting 状态共享同一个 G(`replay.py:50-55`、
`loss.py:42-44`),早 vs 晚的状态拿到完全相同的 ±1 信号。DouDizhu 50-100 step + 无 in-game
随机性可吸收;GICG 一次摇骰子可能直接逆转胜负,相当于把"骰子运气"backprop 到 300 个无关
状态上。这是 DMC paradigm 在长 episode + stochastic transition 任务上的已知 failure mode。

### A.3 PASS 标准与已实测 RL 上限矛盾(最严重)

`docs/4_runs/registry.md:215`:s068(同 setup 下最好 AZ asymmetric)= 0.271 ± 0.078;
F1-D2 vs F1-D2 control = 0.54(先手优势 ~+8%)。Registry 明文 "Stage 3 stricter (≥0.40)
物理不可达,PPO 0.344 / AZ pure 0.104 / AZ+BC 0.167"(`registry.md:287`)。

把 DMC PASS 设为 ≥0.50 等于要求 paradigm-agnostic ceiling 之上 +0.23,plan 完全没论证
DMC 能跨这个 gap。这是把 DouZero 在 Doudizhu 上的 0.5236 当通用基准移植,忽略了 0.5236 是
Landlord 角色优势驱动的 game-specific 数字。

### A.4 Closure 决策未引用

`memory/project_rl_routes_closure_2026_05_12.md` 列出 RL 路线 closure 全图,但
`notes.md:21-32` 的 decision changelog 只记 DMC-internal 决策,**没有论证 DMC 不在 closure
集合内**,也没有论证 DMC 解决了 closure 给出的 root cause(per-step 骰子方差、
multi-char emergence、F1-D2 局部最优陷阱)。属于绕过 closure 直接开新 paradigm。

### A.5 Imperfect-info 评估标准不对

Imperfect-info 的金标准是 exploitability(对手 best response),不是 vs 一个固定 baseline。
即使 DMC vs F1-D2 = 0.50,被 CFR best-response 测可能仍是高 exploitable。`README.md` 的
PASS criteria 只看 vs F1-D2 / F1-D4,完全不测 exploitability,也没和已有 CFR 栈做对照。

### A.6 GICG 缺乏 DouZero 的"组合先验"

DouZero 在 Doudizhu 上 work 一部分依赖 "single / pair / sequence" 等强组合规则,MC 平均
能在结构相似状态间共享信号。GICG action 是骰子 payment + skill / card index,**单 step
状态相似性低**。MC 平均效率远不如 DouZero,这是为什么 DouZero per-step 1k fps 能收敛而
GICG 不可预期。

---

## B. "复用 AZ ActorCritic" 的代价被低估(Decision #1)

### B.1 Logit-as-Q 是把 softmax policy 头当回归头训

`ActorCritic` 的 logit 是 AZ 用 softmax + KL 训出来的,只关心**相对大小**;DMC 改成
MSE on raw logit(`loss.py:43-44`),要求**绝对值**对齐到 ±1。两者归纳偏置完全不同:
网络初始化 / norm / dropout 都是为前者设计的。"50 LOC vs 300 LOC"(`notes.md:23`)
是把实现成本而非算法适配性作为决策依据,这是反过来的。

### B.2 value 头 + delta_pred 头每步算了但全丢

`agent.py:127`、`forward_batch:177` 都返回 `(logits, value, delta_pred)` 三件套,但 DMC
只用 logits(`loss.py:43`、`agent.py:144`)。GPU forward 算力 1/3 浪费。Stage 3 cfg
单进程 + GPU + 100M frames(`configs/dmc_stage3.toml:13`)本就 GPU 利用率极低,叠这个
waste 是双重成本。

### B.3 Logit 头无 per-action 标识 → Q 表达力差

AZ 的 logit 借 hook_emb gather 得到,设计目的是相对排序,**没有 per-action absolute
scale**。当 Q 值需要在不同 action 间区分"赢面 +0.8 vs 输面 -0.3"时,这种共享 backbone +
gather 表达力受限。`PLAN.md` Risk #1 自承 "Logit-as-Q bilinear 表达力不足",但没给 fallback
触发条件。

### B.4 ADR-0006 layout 实质被破坏

`README.md:2` 自承 "AZ⟷CFR 零互 import";但:

| 文件 | 引用位置 | 来源 |
|---|---|---|
| `config.py:14` | `ScenarioConfig` | `training.az.config` |
| `config.py:15` | `AgentConfig` | `training.az.network.agent` |
| `agent.py:21` | `ActorCritic` | `training.az.network.actor_critic` |
| `agent.py:22` | `AgentConfig` | `training.az.network.agent` |

az 子树里的 `network/` 和 `ScenarioConfig` 实质上变成了**隐式 framework**,但没迁到
`training/framework/`。AZ 改网络结构会破 DMC,反之亦然。与 ADR-0006 立约时的隔离意图相反。

---

## C. 当前已写代码里的具体 bug

### C.1 Resume 路径必崩 — UnboundLocalError(P0)

`train_loop.py:375` 在 `if resume_ckpt_path is not None:` 块内调用
`_restore_rng_states(ckpt['rng'], agent, opp_pool, buffer, rng_action, rng_side)`,
但 `rng_action` / `rng_side` 在 line 385-386 才定义(if 块外)。Python local-scope 规则会
把这两个名字识别为 local,read-before-assign 直接抛 `UnboundLocalError`。
**任何 `--resume_from` 调用立刻挂**。

### C.2 Historical opponent pool 完全未接通,30/30/10/30 mix 实质是 60/30/10/0(P0)

`train_loop.py:345`:`opp_pool = OpponentPool(cfg.opponent_pool, dmc_agent_factory=None)`,
`opponent_pool.py:67-72` 在 factory=None 时 fallback 到 `RandomPlayer`。Decision #4 文档说的
30% historical **没有任何代码实现**,实际 mix 是 60% random / 30% F1-D2 / 10% F1-D4,
完全没有 self-play 成分。`notes.md:200-203` 的 smoke 结论 "76 W / 52 L / 8 D" 正是基于
这个被破坏的 mix。

### C.3 Eval 污染 training 的 static cache

`periodic_eval.py:93` 在 eval scenario 上调 `agent.game_start(env.static_obs)`,**用的就是
training agent 实例**(`train_loop.py:512` `evaluator.run_once(agent)`)。`AgentBase.game_start`
覆写 `_hook_emb / _counter_sids / _char_skill_refs / _hook_mask` 等 static cache。eval 跑完
返回时 training agent 的 static cache 是 eval 最后一个 scenario 的状态。Stage 3 fixed teams
不易暴露,Stage 4 char_pool 抽样后 → 训练 batch forward 时 `_hook_emb` 是上次 eval 的。
`notes.md:225` 标为 Phase 3.5 known limitation,但这是 silent correctness bug。

### C.4 Eval 同步阻塞 training

`train_loop.py:511-513` 同步调用 `evaluator.run_once`。Stage 3 cfg n_scenarios=128 × 2 sides ×
2 baselines = 512 局/eval。F1-D4 单决策 1-2 sec(`notes.md:221`),F1-D4 那 256 局至少
6-12 分钟,blocking。每小时一次 eval 占训练 wall time 10-20%+。`periodic_eval.py:9-11`
自承 "TODO Phase 3.5 fork",但 Stage 3 cfg 已经把 n_scenarios 拉满。

### C.5 Truncated episode 给出错误 G=0

`train_loop.py:170-178` `_terminal_z`:`if winner < 0: return 0.0`,把 truncated 当 draw,
G=0 push 到 buffer(`replay.py:50-55`)。网络学到"长 episode 状态 → Q ≈ 0",但实际可能
是赢面状态被切了。F1-D2 是 search baseline,episode 普遍更长 → 更容易 truncate → 更容易
污染对 F1-D2 局的 Q 估计。这正是 DMC 在长 episode 任务上的已知 failure mode。

### C.6 ε-greedy 探索几乎不存在

`exp_epsilon = 0.01`(`config.py:78`),episode ~340 步 → 期望 3.4 个随机动作。在 ~100-300
size legal action space 上是"基本 deterministic argmax"。off-policy correction、Q 值估计
覆盖度、early-game 状态多样性都依赖 explore,0.01 不够。

### C.7 PHASE_SELECT_ACTIVE 永远选 action 0

`train_loop.py:199-200` + `periodic_eval.py:87-88` 都 `env.step(0)` 跳过选 active char。
Stage 3 single char OK;Stage 4+ multi-char asymmetric 时 agent **完全不学初始角色选择
策略**,这本身是 GICG 一个有意义的决策点。Stage 4 cfg 没改这段。

### C.8 每个 transition 复制全套 static obs → 内存炸

`train_loop.py:147-167` `_capture_obs` 把 `counter_sids / active_slot_mask /
char_skill_refs / hook_types / hook_values / hook_mask` 全 numpy 复制塞进 transition。
Stage 3 cfg `buffer_cap = 100_000` + hook_types 维度 `n_hooks=900 × max_tokens=120` ≈
0.86 MB / transition。100k × 0.86 MB ≈ **86 GB**,5070 Ti box 不可能 fit。`notes.md:223`
自承 "memory 浪费",Stage 3 cfg 没修。

### C.9 `max_grad_norm = 40.0` 等于不裁

`config.py:79`。MSE 在 ±1 target 上典型 grad norm < 1.0,40.0 是事实上的"无裁剪"。
AZ / DouZero 都用 0.5-5.0。无经验依据。

### C.10 update-to-data ratio 不可控

`train_loop.py:467` `n_train_steps_this_ep = max(1, len(transitions) // 4)` ——
一个 episode 训 ~5-50 步,每步用 buffer 里随机 batch_size=32。同一新 transition 可能 0 次
也可能 N 次入 batch,update-to-data ratio 不可控。DouZero 是 actor-learner 解耦 + learner
独立 step rate,这里把训练频次绑到 episode 长度上是单进程 demo 的快路。

### C.11 `OpponentPool._rng` 默认无 seed

`opponent_pool.py:37` `self._rng = random.Random()`(无种子),`train_loop.py:346` 才覆盖。
未来路径若忘 seed,opponent 抽样不可复现,且 `_capture_rng_states` 拿不到一致的 seed
状态。应在 __init__ 强制 seed。

### C.12 `saved_eps` 临时改 agent.epsilon 不线程安全

`periodic_eval.py:104-109` 通过 try/finally 在 eval 内部把 agent.epsilon 临时设 0。
Sync 单进程 OK,但 Phase 3.5 改成 fork eval process 时,如 eval 与 train 并发,共享 agent
实例的 epsilon 会被串改。代码风格鼓励了未来 race。

### C.13 Optimizer state 跨 device 没处理

`train_loop.py:356, 364`:`torch.load(..., map_location=cfg.device)` +
`agent.optimizer.load_state_dict(ckpt['optimizer'])`。optimizer state 里的
`exp_avg / exp_avg_sq` 不会被 map_location 自动迁移设备。Mac CPU ckpt → Windows CUDA
resume 必报 device mismatch,plan 没提迁移路径。

### C.14 Episode 训练有效率仅 50%

`train_loop.py:230, 425-426` `state.frames += n_steps`(全部 env step),但 `transitions`
只记 acting agent 那半边(line 217-223)。`frames` 计数器虚报 2x。100M frames 实际只有
50M training transition。算力账目须按 50% 重算。

---

## D. Eval 协议层

### D.1 n=8 上的 0.125 被算作 PASS

`notes.md:188-217` 把 4 round × n=8 看到 1 次胜(WP=0.125, 95% CI [0.02, 0.47])算
"directional signal exists / Phase 3.4 PASS"。1/8 在均匀随机下也有
P(=1 win | p=0.5) ≈ 0.031。**和 random play 完全不可区分**,但被记为 PASS,留给 Phase 3.5
一个虚假 baseline。

### D.2 swap_sides 不能解决 turn-order bias

`periodic_eval.py:165-180` 把 agent 放 p0 跑一轮、放 p1 跑一轮平均。但 *teams* 也跟着
swap(`_play_one_scenario:70-72` 把 team_0/team_1 互换),所以"agent on p0"是
"agent 拿赤蝶",p1 是"agent 拿墨客"。把"先后手优势"和"角色优势"耦合,平均不能消去
*角色不平衡* 的 bias。`notes.md:197` smoke 看到 0.25 vs 0.00 偏差就是这个未解开的耦合。

### D.3 缺 floor / Elo 对照

Smoke 只跑 vs F1-D2,Stage 3 cfg vs F1-D2 + F1-D4。无 random baseline 当 floor sanity,
也无 vs 历史 ckpt 的 Elo 进度量。如 F1-D2 ceiling = 0.54,DMC 训到 0.50 后无任何梯度信号
衡量"还能不能更强"。

### D.4 每 scenario 新建 GicgEnv

`periodic_eval.py:74-84` 每 scenario 一个新 `GicgEnv(...)`。`notes.md:224` 自承
"0.8 sec/eval round × 4 scenarios"。Stage 3 n=128 × 2 × 2 = 512 次 env 构造 ≈ 410 sec /
eval round 仅 env 构造开销。应 cache 同 team 的 env,只 reset(seed=)。

### D.5 Eval scenario 多样性单一

`gen_eval_scenarios.py:30-66` 只随机 teams + env_seed。但 deck shuffle seed、initial dice
seq、hand draw seed 全部由单一 env_seed 决定 → eval 无法独立控制 "同 team 不同手牌" 的
方差。`PLAN.md:181-188` 提到 dice_seq_seed / deck_seed_p0 / deck_seed_p1 三 seed 分离,
实现没做。

---

## E. 性能与算力账目自相矛盾

### E.1 Stage 3 cfg 数字根本算不通(P0)

`configs/dmc_stage3.toml:13-21`:`total_frames=100_000_000`、`device='cuda'`、cfg comment
自承 "single-process @ ~10-30 fps,2e9 frames 不现实"。但 100M @ 30 fps = **926 hours**,
@ 17 fps(`notes.md:158`)= **1635 hours**。README/Plan 说 "16-25h on 5070 Ti"。
**差两个数量级**。这个 cfg 不能用,但已经 commit 了。

### E.2 GPU 大部分时间空转

Single-process actor + ctypes engine step + GPU forward → actor 是 CPU bound,GPU 等 NN
forward call 之间空。5070 Ti 16GB 在这种单进程下大概 < 5% util。Plan Phase 3.5 默认 cfg
写 cuda 直接对应不上单进程实现。

### E.3 CCD0 / JIT trace / shared memory 是没必要的预优化

`PLAN.md:296-396` 用 ~100 行篇幅讨论 X3D affinity + JIT + shared mem,但前提是
multi-process actor-learner 已 ship,实际 Phase 3.4 是 single-process。前置都没有,后置的
perf 优化是在不确定 paradigm 是否 work 之前 over-engineering。Stage 3 PASS 失败(基于
A.3 大概率)→ 全部 perf 工作浪费。

### E.4 Smoke 17 fps 与 Plan 30k+ fps 预估差 1800x

Plan 借 DouZero 的 EPYC 9K84 数据外推 X3D 单 actor 1500 fps、24 actor 36000 fps
(`PLAN.md:391-395`),但 GICG env step 比 rlcard 复杂得多(ctypes engine call + DSL hook
派发)。实测 17 fps 与外推差 90x/single,V-Cache + JIT 不可能补回来。Plan 没给"如果 X3D
不到 30k fps 怎么办"的 fallback。

### E.5 Episode 训练有效率算力虚报(见 C.14)

`state.frames` 计 env step 而非 transition,实际训练数据是 50%。Stage 3 cfg "100M frames"
实际只有 50M training step,plan 与 cfg 口径不一致。

---

## F. 计划 / 验证不充分

### F.1 零单元测试(P1)

`training/dmc/` 下没有 tests/ 目录。全 repo grep 不到任何 `test_dmc*` / `dmc_test*`。
`CLAUDE.md` 明文 "每个契约配测试 / 新加的 raise 必须配 pytest.raises / 数值不变量必须
配数值测试"。当前所有 `raise ValueError`(`replay.py:60-64`、`opponent_pool.py:73`、
`loss.py:36-41`、`config.py:36-41`)、`OpponentPool._weighted_choice` 概率正确性、
`dmc_mse_loss` 数值正确性、`_terminal_z` 边界、`_capture_obs` shape consistency 都没测。

### F.2 Stage 4 / Stage 5 写在 Stage 3 之前

`PLAN.md:444-468` 详写 Stage 4/5 cfg 和 prerequisite。但 Stage 3 (Phase 3.5) 还没 GPU
train。Stage 3 失败(per A.3 大概率)→ Stage 4/5 文档全部废纸。`CLAUDE.md` "范围扩张前
先问"反过来——这里没等结果先扩范围。

### F.3 "Lazy periodic eval" 与 "early stop" 冲突

`PLAN.md:430-433` Stage 3 早停 = "vs F1-D2 WP **持续 3 次 eval > 0.50**",但 eval 间隔
60 min → 早停判定窗口 ≥ 3 小时;`save_interval_minutes = 30` → ckpt 节奏比 eval 还快 →
早停信号到来时已多存 5-6 个 ckpt,disk 浪费 + 无法及时停。eval 频次和早停规则没耦合。

### F.4 没有"hparam sweep / ablation 怎么做"的预算

`PLAN.md` Risk #1 给 "fallback A2 独立 Q-MLP" 但没设触发阈值或预留时间。Risk #2
"30% historical 太弱拖整体" 也没有 ablation 通道。Stage 3 拿到 0.30-0.45 中间值,
ablation 怎么走、走多少 GPU-h 全没说。Compute budget 表(`PLAN.md:472-481`)只列各
Stage 主路线时间,不留诊断 budget。

### F.5 Decision #1 fallback 路径没准备

Risk #1 提 "fallback 到 A2 独立 Q-MLP 路径",但 A2 没设计文档、没接口约定、没 LOC 估算。
一旦真要 fallback,等于重做。

### F.6 Cross-platform (Phase 3.2) 风险被低估

`notes.md:11` Phase 3.2 status=pending(Windows side);`PLAN.md:127` 写 "TCP localhost
replace Unix socket 50 LOC"——50 LOC 但还得 verify Mac+Windows 全测试 PASS,而 socket 改造
往往会牵连 framework/inference 整套(`memory/project_v_phase2_eval_schema_gaps.md` 已经
标了 silent fail)。这块 risk 被低估为半天。

### F.7 Decision changelog 只记结论不记否定

`notes.md:21-32` 全是 "采纳 X 因为 Y",没有 "否决 Z 因为 W"。缺少决策档案使得后续看
commit 历史的人无法判断为什么不用 PPO bootstrap / TD-λ / NFSP / Deep CFR(这些都是
imperfect-info + GICG 现有栈支持的 paradigm)。

---

## 建议优先级(实施视角)

如果坚持继续 DMC 路线,**P0 必修后才有资格上 GPU**:

| 项 | 类别 | 描述 |
|---|---|---|
| C.1 | bug | Resume `rng_action`/`rng_side` UnboundLocalError 修掉 |
| C.2 | bug | 接通 `dmc_agent_factory`,30/30/10/30 mix 真正生效 |
| C.8 | mem | static obs dedup(类比 framework `StaticDedupBufferBase`),否则 Stage 3 cfg OOM |
| E.1 | cfg | `total_frames` / wall time 估算重做,Stage 3 cfg 当前不可用 |

**P1**(否则 Stage 3 结果不可信):

| 项 | 类别 | 描述 |
|---|---|---|
| C.3 | correctness | eval 用独立 agent 实例,不污染 training cache |
| C.4 | perf | eval fork 独立 process,否则 wall time 失真 |
| C.5 | correctness | truncated episode 不入 buffer 或单独标记,不当 G=0 |
| D.2 | eval | 解开 swap-sides 与 team-swap 的耦合 |
| F.1 | test | 至少补 `loss.py` / `replay.py` / `opponent_pool.py` 的契约测试 |

**根本问题**(P0 修完仍未解决):
A.3(PASS 标准 vs 实测上限)+ A.4(closure 未引用)+ B.1(logit-as-Q paradigm 错配)。
建议在 P0 修完后,**先用 fix 后的 smoke 跑 100k frame 看 vs F1-D2 趋势**,如趋势仍不能在
n=64 eval 上做到 ≥ 0.30(vs F1-D2 vs F1-D2 control 0.54 的一半),即可不上 Stage 3 GPU,
转而审视 paradigm 选择本身。

---

## 不变更的前提

本评审基于以下事实,如有变化需重看:

- `feature/dsl-v4-prototype` branch 当前 head
- `training/paradigms/dmc/notes.md` 标 Phase 3.4 DONE 2026-05-14 03:44(单进程 5035 frames smoke)
- Stage 3 GPU train **未开始**,本评审不评价 GPU 实测结果
- s068 baseline 数据来自 `docs/4_runs/registry.md` 2026-04-28 的 3-seed 结果

> 后续进展不改本文,在 `1_specs/` 或 `3_plans/` 写新文,顶部加
> `> Superseded by: ...`(per `docs/5_history/README.md` 编辑规则)。
