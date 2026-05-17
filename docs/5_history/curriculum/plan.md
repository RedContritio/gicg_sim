> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **CLOSED** by ADR-0009 / ADR-0010(`openspec/changes/archive/0009-rl-paradigm-pivot-terminus/` + `archive/0010-rl-research-reopen/`)
> - Stage 0-2 PASS(s055-063,multi-seed)
> - Stage 3 dual verdict:PPO ceiling 0.344 / AZ pure 0.104 / AZ+BC 0.167(stricter ≥0.40 FAIL)
> - Stage 4-5 ABANDONED(per ADR-0009 closure)
>
> 数据点见 `docs/4_runs/registry.md` s055-066 + r010-012。
> Production fallback:r009 BC ckpt epoch_3 vs F1-D2=0.75。

---

# RL Curriculum Plan — 从第一性原理让游戏变得可学

**日期:** 2026-04-24
**前置:** `../../2_decisions/adr-0008-rl_paradigm_pivot.md`(为什么 pure end-to-end 失败)
**性质:** 多周执行计划,不是单 run 规划。目标让 RL 栈验证可学,然后逐步逼近 full 2v2 游戏。

---

## 目的

r001-r008 直接训 full 2v2 GICG 全部失败(详见 `memory project_rl_paradigm_pivot`)。
原因不是算法选错,是**游戏结构违反 RL 可学性的 5/5 条件**(长 episode + 稀疏奖励 +
隐藏信息 + 大动作空间 + 复杂随机性)。

文献一致做法:**先缩到 RL 能打穿的最小可学 kernel,验证 pipeline,再递增复杂度**。
AlphaZero → 9×9 Go 先验证;AlphaStar → minigame;OpenAI Five → 1v1 mirror。

本 curriculum 以 5 个 stage 执行这条路线。**核心判据:每个 stage 有明确 go/no-go,
不达标不进下一 stage。**

---

## 核心原则

1. **简化先于优化。** 任何 stage 的失败,优先问"这个 stage 是否该更简单",
   而不是"算法是否该更强"。
2. **验证优先于推进。** 每 stage 的目的是**排除栈本身的 bug**,不是训出 SOTA agent。
3. **独立改动并行做。** Factored action / handcrafted features / dense reward
   是三条正交改进,不依赖 curriculum 进度。
4. **保留退出点。** 若某 stage 反复失败,退回上一 stage 做更久训练/调参,
   而不是硬推。

---

## Infrastructure 前置改动(T-A / T-B / T-C / T-D)

与 curriculum 正交,先做好再开 Stage 0。

**重排原因:** 2026-04-24 审计发现 T-A/T-B/T-C 原估算多处与现状不符 ——
action space 早已分解、handcrafted feature 大部分已在固定 sid、反应/可观
测/定骰/回合上限四个 env flag 全部缺失。以下各节已按审计结果重写。

### T-A: Factored (identity, payment) 双头 policy

**语义前提(纠正 2026-04-24 早版的错误分析):** GICG 本质是骰子管理游戏,
付 dice 的颜色选择**有跨回合战略意义**:
- **有色 cost** (`3 fire`) 只能用 fire+omni 付, **omni 稀缺**
- **无色 cost** (`2 any`) 必须同色,选烧哪色 = 决定下轮保留什么
- **Tune** 动作本身就是 dice 管理 action
- **反应 setup** (Stage 4+): 故意留 water 骰为下轮蒸发
- **Energy** 充能: 付 dice 附带充能,颜色间接影响充能节奏

所以引擎枚举"同 identity 不同 payment"为独立 legal action **不是冗余**,
是暴露真实策略决策点。**用规则(greedy_dice)代替学习的 payment 选择**
会丢失这一维度的策略表达力,不是等价变换。

**2026-04-24 量化结果(`tools/profile_action_variants.py`,30 局随机自博):**

| 配置 | avg legal | avg unique-id | "dice 决策密度" | legal p50/p90/p99 |
|---|---|---|---|---|
| Full 2v2(全卡池) | 23.85 | 7.97 | 66.6% | 9 / 70 / 143 |
| Stage 0 (1v1 mirror 无卡) | 20.71 | 4.74 | 77.1% | 17 / 48 / 75 |

("dice 决策密度" = `1 - unique_id / legal`,之前误称"浪费率",其实它量化
的是**一次决策里付 dice 选择的比重**,越高 = dice 管理决策越多。)

**关键观察:** 29%-44% 的 identity 有 2+ payment variants,这正是 agent
需要学 dice 管理的决策点。单头 policy 扁平输出到 n_legal 是在这些点上
浪费参数容量,但不丢信息;用规则 payment 则是**丢信息换容量**,在 Stage 1+
(骰子随机回归) 开始就有损上限。

**正确方案:双头 policy,学 payment 而非规则选**

```
obs → trunk
       ├─ identity_head  → P(id | s)       masked to n_unique_id
       └─ payment_head   → P(pay | id, s)  masked per-id
```

训练 target:
- identity head: MCTS visit 在 identity 聚合,`π̂(id) = Σ_{pay} N(id,pay) / N_total`
- payment head: 条件于 identity,`π̂(pay | id) = N(id, pay) / N(id)`

MCTS 树:
- 两层 children: 先按 identity 分, 选中 identity 下再按 payment 分
- 或扁平保留原叶子,prior 按 `P(id) × P(pay|id)` 合成后归一化

**分阶段应用:**

| Stage | 骰子来源 | dice 管理策略性 | T-A 做法 |
|---|---|---|---|
| 0 | `fix_dice` 定骰 | ≈0(每回合固定,无跨回合保留决策) | **可跳过**,或 env 预 filter(L1)无损简化 |
| 1 | 随机 roll | 初现(omni 节省等) | **需要**学 payment |
| 2 | 同上 + partial obs | 同上 | 同上 |
| 3 | 加卡 → 卡成本多样 | 加剧 | 同上 |
| 4 | 反应 → 颜色 setup | 顶峰 | 双头 + payment head 必做 |

**Stage 0 的 MVP**(因为 fix_dice 使 dice 管理退化):
- env 层加 `factored_actions: bool` — 开启则 `get_legal_actions` 用
  greedy_dice 预 filter,每 identity 留一条,step(filtered_idx) 映射回
  raw_idx。MCTS / network / selfplay 零改动
- **Stage 0 专属**,不能带到 Stage 1+。文档里要 HARD FLAG 这个限制

**Stage 1+ 正式 T-A**(~2-3 天):
- `training/az/network/actor_critic.py`: 加 payment_head,条件于 selected
  identity embedding
- `training/az/mcts/node.py`: children 两层结构 (id → Dict[pay_key, Node])
  或 prior 合成方案
- `training/az/selfplay.py`: 记录 (id_pi, pay_pi | id) 作 target
- `training/framework/matchup/greedy_dice.py::filter_logical_actions` 只
  作 bootstrap prior / fallback,**不作最终决策**

**验证:**
- Stage 0 L1 env filter: F1-D2 predicted ≈ 0.50(fix_dice 下等价成立)
- Stage 1+ 双头: 对比"规则 payment" vs "学 payment" 两版 agent,后者
  应显著胜出(预期 ≥ 0.60),若没差说明 dice 管理在当前 reward 下未成
  bottleneck,可延后再上

### T-B: Char 元素 ID(obs 侧 ✅ 完成 2026-04-24;network 侧延后)

**设计修正(2026-04-24 user pushback):** 原方案 one-hot 96 维被否决。
理由:obs 里其它元素 reference(dice 每色 pinned sid、attach counter
每色、hook tokens 里的 Element enum)表示都不一致 — 再引 one-hot 是
第三种独立编码,加剧不一致。改用 **ID + 共享 embedding**:每 char 存一
个 int (Element enum 0..8,-1 for phantom),**12 ints 而不是 96 floats**。
后续 network 侧加共享 embedding table,让 char element、dice color、
skill damage、card element 都走同一个表,"fire" 在任何位置 → 同一向量。

**已实施(obs 侧):**
- `gicg_engine/observation.go` 加 `ObsCharElementSlots = 12` 常量 +
  `StaticObsSize()` 含入 + `BuildStaticObs()` 在 hook tokens 之后追加
  per-char element ID block,iteration order (P0 c0..c5, P1 c0..c5)
- `training/framework/obs_constants.py` 导出 `OBS_CHAR_ELEMENT_SLOTS`
- `training/framework/network/agent_base.py` + `training/cfr/traversal/
  encoding.py` 的 static-obs slice 加上界(原本 `static[meta+refs:]`
  展开到末尾,现在必须 bound 到 `meta+refs+hook_size` 否则 reshape 把
  element block 当 hook tokens 崩)
- Go 测试 `gicg_engine/tests/obs_char_element_test.go` 4 cases pass

**后续工作(network 侧,延后到 Stage 4+ 反应 matchup 显著化时):**
- 在 actor_critic / advantage_net 里加 element embedding table
  `element_embed: [10, d]`(9 个 Element 值 + 1 个 phantom slot)
- 读 static obs 的 element block,per-char 索引 embedding,拼到 char
  feature 里
- **同时** 把 dice color sid 和 attach counter 也改成用元素 ID 查同一
  个 embedding(深工作,需要改 dice/attach 的 sid emit),这才是"共享
  embedding"的完整形态
- 验证:F1-D2 baseline + element embedding 与 baseline 的 head-to-head,
  Stage 4 场景下预期有可测差距

**为什么 obs 侧先行:** engine 改动小、零 network 风险(slice 加上界即可),
给后续 network 实验留好接口。Stage 0-3 下 element 差异未成 bottleneck,
不跑 network 侧就没损失。

### T-C: Dense reward wiring(✅ 已完成 2026-04-24)

**状态:** done.

**实施:**
- `gicg_env/env.py::GicgEnv.__init__` 加 `reward_shaping: dict | RewardShaping | None`
- `gicg_env/env_reward.py` 定义 `RewardShaping` dataclass + `compute_shaped_reward`
- `step()` 现在返回标准 RL 4-tuple `(obs, reward, done, info)`,所有 40+ 现有
  callers 已 migrate
- 测试:`gicg_env/tests/test_env_reward_shaping.py`(16 cases,450/450 全套回归通过)

**当前支持字段:** `hp_delta` / `hp_taken_penalty` / `kill_bonus` / `death_penalty`
/ `terminal_win` / `terminal_loss`。未启用的字段(如 shield_absorbed,
reactions_*)可在 curriculum 进入 Stage 3-4 需要时增补。

### T-D: Stage 0 env flag(新增,预估 1-2 天)

**现状:** `fix_dice` / `fully_observable` / `disable_reactions` / `max_rounds`
**全部不存在**。原计划把它们写在 Stage 0 game spec 里,假设现成,是错的。

**方案:** 分两层。

**Go 侧** (`gicg_engine/capi/capi_init.go::GameConfig`):
- `FixDice []int` — 若非空,每回合 roll 输出强制为此(长度 8,对应 8 色)
- `FullyObservable bool` — dynamic obs emit 时包含对手 hand/deck/dice
- `DisableReactions bool` — 加载 DSL 时跳过 `data/system/reaction.lua` +
  `data/system/reactions/` 目录(需确认 data_dir 加载器是否支持黑名单,可能
  需新加 "skip list")
- `MaxRounds int` — 达上限时 game 进入 GAME_OVER,winner = 2 (draw)

**Python 侧** (`gicg_env/env.py::GicgEnv.__init__`):
- 同名参数,透传至 Go config JSON
- 无 override 则保持现有行为

**验证:**
- `test_env_fix_dice.py` — reset(seed)×10 后 dice 恒等于 fix_dice
- `test_env_fully_observable.py` — obs 长度变大,敌手 hand/deck/dice 区非零
- `test_env_disable_reactions.py` — 火 + 水 互攻 hp delta 仅算基础伤,无蒸发倍率
- `test_env_max_rounds.py` — round_num 达 max 时 done=True 且 winner=2

---

## Stage 0 — Minimum Viable Learnable Kernel

**目标:** 验证 RL 栈(env + network + training loop)能学到任何东西。

**这不是训强 agent,是排查 pipeline bug。** r001-r008 累积的疑问 ——"是算法问题
还是 pipeline 问题" —— Stage 0 能在 2 小时内 yes/no 回答。

### 前置:T-D 完成后才能开 Stage 0

下表的 4 个 env flag(`fix_dice` / `fully_observable` / `disable_reactions` /
`max_rounds`)**当前都不存在** —— 2026-04-24 前原计划误以为现成。T-D 实现它们
之后,本节配置才能直接写入 config。

### Game spec

| 维度 | 配置 | 依赖 |
|---|---|---|
| Team | **1v1,单角色**(无切换,无 Switch fixation pathology) | — |
| Char | `data/characters/测试角色/` (2-3 个简单伤害技能,无 buff,无元素反应) | 新建 DSL |
| Cards | **无**(`card_pool=[]`) | 已支持 |
| Elemental reactions | **关闭**(`disable_reactions=True`,或 char 用同元素绕过) | T-D |
| Dice | **固定**(`fix_dice=[2,2,2,2,0,0,0,0]`,无 roll 随机) | T-D |
| Visibility | **完全可观测**(`fully_observable=True`,obs 含对手手牌 + 骰子) | T-D |
| Max rounds | **3**(`max_rounds=3`) | T-D |
| Reward | **稠密** HP delta + 击杀 + 终局(`reward_shaping={...}`) | T-C ✓ |

### Action space

Factored(T-A 完成后):
- logical action ∈ {skill_0, skill_1, skill_2, end_turn} — 4 选项
- dice payment 用 dice_greedy 规则自动选

**有效动作空间 = 4 每决策。** episode ~20-30 步。

**注:** 若 T-A 量化结果显示 payment variant 分布很窄(多数 identity 只有 1-2 个
payment 可选),则 Stage 0 可跳过 T-A 改造,直接用现有 `(kinds, indices)`
接口训练,让网络隐式学会payment。Stage 0 的 4 个 skill × 简单 dice cost
场景下,per-identity variant 很可能就是 1。

### Network

**最小:** 双线性层 + 两头(policy + value):
```
obs (~100 维) → MLP[256, 128] → (policy_logits[4], value[1])
```
d_model 原 128 换成 ~256 的简单 MLP,不用 attention。目的是排查 attention 栈是否
是问题源之一。

### RL algo

**首选 PPO**(简单、已知鲁棒)。
- 现有 `training/az/` 栈是 AZ-based,`training/cfr/` 是 CFR,**均无 PPO 实现**
- 写新 PPO 是主路线:独立 `training/ppo/` 目录,~300-500 LOC,自含训练循环
- Fallback:用 AZ 栈 `n_rollouts=1` 近似 policy gradient,但不等价
  (MCTS-visit-as-prior ≠ PG),诊断力打折 — 不推荐 Stage 0 用

**推荐:PPO from scratch**。这让 "stack 是否 OK" 的验证不受 AZ / MCTS 特有
bug 影响。参考实现结构: rollout 收集 → GAE returns → clip-ratio loss + value
MSE + entropy bonus → minibatch SGD。

### Baselines

- vs random: **期望 ≥ 0.95**
- vs greedy F1-D1 dice_greedy: **期望 ≥ 0.40**(teacher 级别是上限)

### Go / No-go

| 指标 | 结果 | 动作 |
|---|---|---|
| vs random ≥ 0.95 within 2h | ✓ stack OK,进 Stage 1 | |
| vs random 0.70-0.95 within 2h | 部分 | 加大网络 / 训练更久,若稳定在 0.90+ 可进 |
| vs random ≤ 0.65 within 4h | ✗ | **栈有 bug**。诊断顺序:(a) env.step reward 是否符合预期?打印 10 步 reward 看;(b) 网络能不能 fit F1-D1 的 behavior cloning?不能 → 网络/obs 问题;(c) RL loss 是否在降?不降 → 算法实现问题 |

---

## Stage 1 — 加回骰子随机性

**变动:** 移除 `fix_dice`,骰子每回合随机 roll。其他同 Stage 0。

**期望:** 同算法 2-4h 训到 ≥ 0.90 vs random。随机性引入方差但不改变问题结构。

**Go/No-go:** < 0.80 → 回 Stage 0 排查 RL 对 stochastic env 的鲁棒性。

---

## Stage 2 — 加回 partial observability

**变动:** `fully_observable=False`。对手骰子 / 手牌(尚无)隐藏。

**验证点:** 这是 hidden info 的第一次引入。若用 AZ,IS-MCTS determinization
开始发挥作用。应测:
- PPO partial obs 能否训到 ≥ 0.75
- AZ IS-MCTS 相对 AZ 无 determinization(直接看"当前 obs 代表真 state")是否明显更优

**Go/No-go:** < 0.65 vs random → hidden info 处理有问题,检查 obs 构造 /
IS-MCTS 采样。

---

## Stage 3 — 加回卡牌

**变动:** 
- 加小卡池(5-10 张简单 card,单次出伤害加成 / 治疗 / 换骰)
- 加 hand(隐藏)、deck(隐藏)
- 其他同 Stage 2

**期望:** 需要更多 training compute。卡组合开始产生策略复杂度。

**Go/No-go:** ≥ 0.65 vs random → 进 Stage 4;≤ 0.50 → 需 reward shaping 强化
(若之前没加)或减卡池到 2-3 张试。

**2026-04-26 Stage 3 closure (s021-s054, 29 ablation, n=3 multi-seed
per cell):** F1-D2 ≥ 0.40 stricter 在当前 BC→PPO pipeline 下物理不可
达。multi-card masked 0.073 / fullobs 0.104;1-card best-of-each
combined 也仅 0.281(NOT additive)。4 个 factors 量化:BC warm-start
+0.24 dominant(s054 scratch peak ~0.11);partial obs +0.13;F1-D3
teacher +0.10(masked-only,与 fullobs 互替);PPO oscillation 区间
~±0.10-0.15(s053 wr 在 [0.18, 0.42] 抖)。Falsified:soft target
collapse / PPO undertraining。**决策:不推 Stage 4,pivot 回 AZ
路线。** AZ 路线本身有自己的 risk(`project_r008_postmortem` r007
collapse 等),pivot 是 "PPO 路线已结构性证否,AZ 继续投入" 而非 "AZ
已解决"。详见 `../../4_runs/registry.md` Stage 3 closure 段 + memory
`project_stage3_full_diagnosis`。aggregate.json 在每组第一个 ckpt
parent dir。

---

## Stage 4 — 加回元素反应

**变动:**
- char pool 放开到多元素(赤蝶火 + 墨客水 + 刻师傅岩 等)
- 开启元素反应(火 + 水 = 蒸发,+ 冰 = 融化 etc)
- 仍 1v1

**期望:** 状态转移变复杂(反应非局部),MCTS 搜索有用性上升。RL 需稠密 reward
+ 大 compute。

**Go/No-go:** ≥ 0.60 vs random。这里开始逼近原 game 复杂度。

---

## Stage 5 — 扩到 2v2(full game)

**变动:**
- team_size=2,多角色切换
- full card pool
- 全规则游戏

**期望:** 若 Stage 0-4 都过,这里是规模问题,不是结构问题。加大 compute + 可能
warm-start from Stage 4 ckpt。

**Go/No-go:** ≥ 0.50 vs mcts_200。此时可对比 r009 BC / r010 混合的结果,
确认 curriculum 方向是否收敛到更强 agent。

---

## 实施路径(2026-04-24 重排)

### Week 1 — Infra + Stage 0

- ✅ Day 1(~1h 实际): T-C dense reward wiring — done 2026-04-24
- ✅ Day 1(~1h): T-D env flags (max_rounds + fix_dice only, 2026-04-24)
- ✅ Day 1: T-A 量化(跳过 factoring for Stage 0,结果见 T-A 章节)
- Day 1-2: T-B element one-hot(96 维 static obs 末尾)
- Day 2-3: 写测试 char DSL(`data/characters/测试角色/`)
- Day 3-6: 写 PPO from scratch(`training/ppo/`)
- Day 6-7: Stage 0 训练 + gauntlet 验证

**原估 3-5 天,Day-1 快速收敛后 ≈ 4-5 天**(T-A 跳过 + T-D 缩到 2 flag
缩短了前 3 天;PPO from scratch 仍是 3 天主力工作)。

### Week 2-3 — Stages 1-3

每 stage 1-4 天,取决于收敛速度。

### Week 4-6 — Stages 4-5

复杂度上升,单 stage 可能 1 周。

### 总时长

3-5 周到完整 5 stage。若任一 stage 失败,停下重排,不硬推。

---

## 与现有资产的关系

### 复用(已验证存在)
- `gicg_env/` 基础(只扩参数,不重写)
  - HP/Energy/Alive/Active/Dice/alive_count **已在 pinned sid 0..65** (不 shuffle + 归一化)
  - `reward_shaping` 已接入(T-C ✓)
- `gicg_engine/capi` C-API 层(扩 GameConfig 字段接 T-D flags)
- `training/framework/matchup/greedy_dice.py::filter_logical_actions` — T-A dice 规则复用
- `training/framework/matchup/` 的 gauntlet + `tools/eval_service.py`(已验证存在)
- `tools/register_run.py` + `../../4_runs/registry.md`(已验证存在)
- `training/az/network/` 作为 Stage 4+ 的 AZ baseline
- `training/framework/network/agent_base.py::AgentBase`(PPO agent 可继承)

### 新建
- Go 侧 `GameConfig` 扩 `FixDice` / `FullyObservable` / `DisableReactions` / `MaxRounds` 字段(T-D)
- `data/characters/测试角色/*` — Stage 0 测试 char DSL
- `gicg_engine/observation.go` 加 element one-hot 块(T-B)
- `training/ppo/` — 新目录,PPO 实现(Stage 0-3 主力 RL 栈)
- `configs/curriculum_stage_N.toml` — 每 stage 一个 config
- `../../3_plans/curriculum/stage{N}.md` — 每 stage 的 LIVE status doc(本目录)

### 不动
- `training/cfr/` — r008 已证 CFR 在此不 work,curriculum 不走这条
- `training/az/mcts/` — 保留到 Stage 4 再用
- 现 r001-r008 artifacts — 历史数据,不清理

---

## 新 session 启动 checklist

若在新 session 重开,按此顺序:

1. 读 `../../2_decisions/adr-0008-rl_paradigm_pivot.md` —— 理解为什么不继续 r001-r008 路线
2. 读本文 —— 理解 curriculum 架构
3. 读 memory:
   - `project_rl_paradigm_pivot` — 决策指引
   - `project_greedy_baseline` — F1-D2 = 0.90 基线(Stage 0+ 对比用)
   - `project_r008_postmortem` — CFR 失败归档
   - `project_training_layout` — framework/az/cfr 三层结构
4. 现状 check:
   - `git log --oneline | head -20` 看最近 commit
   - `../../4_runs/registry.md` 看 run history
   - `.venv/bin/python -m tools._meta.check_line_limits` 确保 repo clean
5. **T-C dense reward wiring ✅ 已完成**(2026-04-24)
   - 实施文件:`gicg_env/env.py` + `gicg_env/env_reward.py`
   - 测试:`gicg_env/tests/test_env_reward_shaping.py`
6. **开始 T-D env flags**(当前阻挡项):
   - `gicg_engine/capi/capi_init.go::GameConfig` 扩字段
   - `gicg_env/env.py::GicgEnv.__init__` 加参数透传
   - 分别加 4 个独立测试(fix_dice / fully_observable / disable_reactions / max_rounds)
7. **T-B element one-hot** + **T-A 量化 → 决定改不改**
8. **Stage 0 setup**:写测试 char DSL + PPO 栈 + config
9. 每 stage 结果登记 registry + 写 stage result doc

---

## 风险和 mitigation

| 风险 | Mitigation |
|---|---|
| T-D `disable_reactions` 需改 DSL 加载器 | Fallback:同元素双方(双火)避免 reaction 触发,不改加载器;留 flag 到真的需要时再做 |
| T-D `fully_observable` 改 obs 尺寸,影响 static obs layout | Stage 0 下 dynamic obs 增量小(对手 1 char × 1 slot + 8 dice),先加到 dynamic obs 末尾,不动 structural sid pinning |
| T-A 量化表明 factoring 收益不大 | 直接跳过,Stage 0 用现 `(kinds, indices)` 接口 — 节约 0.5-1 天 |
| 测试 char DSL 仍触发 reaction / buff | 用同元素双方(如双火)避免 reaction;若 DSL 有隐藏 buff,写纯简 Lua(仅 skill + damage,无 counter) |
| PPO from scratch 3-5 天写不完 | Fallback 用现 AZ 栈降 MCTS budget=1 —— 但要记这不等价 PG,诊断力打折 |
| Stage 0 通过但 Stage 1 失败 | 说明随机性引入了问题。回 Stage 0 验证同一训练循环在 deterministic 版本的 stability |
| Stage 0 失败(stack bug) | 最坏也最信息量大 — 值得花 1-2 天真诊断,而不是试更多 hyperparam |

---

## 与 r009/r010 incremental 路线的关系

r009/r010(BC warm-start + greedy MCTS + dense reward,`../../4_runs/_individual/r009_plan.md`)
是**与本 curriculum 正交的另一条路**:
- r009/r010 = "直接上 full 2v2 game,用 F1-D2 做 teacher"
- curriculum = "先 1v1 单 char 最简,验证 RL 栈能学"

**两者不冲突,可并行:**
- curriculum 的 T-A/T-B/T-C 前置也能加速 r009(factored action + dense reward 都是 r009 需要的)
- r009 成功 → 证明 BC-warm-start 在 full game 可行,curriculum 作为后备 / 学术路径
- r009 失败 → curriculum 提供独立验证("是 pipeline bug 还是 game-too-complex")

**若资源只够一条,先做 curriculum Stage 0-1(5-7 天)**,因为它同时回答:
- pipeline 是否 OK(r009 依赖此信息)
- 游戏结构简化后是否 RL-learnable(r010 假设此)

Stage 0-1 通过后,可选回 r009/r010 快速 demo,或继续 curriculum 追求 SOTA。

---

## 成功的最终定义

本 curriculum 成功不是"Stage 5 达 0.95 vs mcts_200"。成功是:

**每个 stage 的 go/no-go 都走通,我们能回答:**
1. 这个 RL 栈在哪个复杂度水平工作
2. 加入隐藏信息的影响量化
3. 加入卡牌的影响量化
4. 加入元素反应的影响量化
5. 扩到 2v2 的 compute 需求估计

**这些答案是 r001-r008 无法给出的**(因为 r001-r008 只有"全都失败"这一个数据点),
也是未来任何训练决策的先决信息。
