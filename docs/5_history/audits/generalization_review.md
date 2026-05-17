# 泛化能力审查:DSL Token 化是否真的让网络学到了元规则

> 2026-04-17 审查。起因:讨论"DSL 编码 → 网络通过 token 学习元规则"
> 这条设计假设是否在当前实现里成立。审查发现实现存在,但若干必要前提条件
> 缺失,导致**当前训练几乎不可能验证元规则学习**。

## 设计假设(待验证)

游戏会持续引入新卡和数值平衡,所以希望网络从 DSL 内容(而非卡牌 ID)学习规则,
新卡上线零样本 / 少样本即可应对。

为此实现了:
- `gicg_engine/hook.go:22` — `Hook.Tokens []TokenPair`,DSL hook body 的 token 序列
- `gicg_engine/observation.go:21-25` — `StaticObs.HookTokens [900×120×2]` 输出
- `training/network.py:69-106` — `HookEncoder`(Transformer,vocab=256,
  `token_dim=d_model`,c1 配置下 d=128),消费 token 序列
- `training/network.py:167-217` — `CrossAttentionBlock`,hook ↔ counter 双向融合

理论上,网络应该可以从 hook token 序列**结构化地**理解卡牌,而不是把 token
当作伪 ID 索引。

## 已确认的正向项(代码精读后)

以下设计点经直接读源码确认存在且实现正确,**不再是验证 gap**:

### P1:控制流 token 完整保留

`gicg_engine/tokenizer.go:14-19` 的 vocab 包含 `TokIf, TokThen, TokEnd,
TokReturn, TokElseif, TokElse, TokAnd, TokOr, TokNot`。`TokenizeLua`
(行 437-442)把它们当普通关键字 token 输出,不做 flatten 或控制流消除。
`ExtractHookBodies`(行 462-499)用 depth counter 提取 `function(ctx)...end`
对的整段 body,if/elseif 嵌套结构在 token 序列里**完整保留**。

意味着:HookEncoder 输入足以表达"在 ctx.actor_player == ... 时返回,
否则 deal_damage" 这种条件逻辑,不是被压扁的动作集合。

### P2:数值 token 走标量投影,不是 vocab 查表

我前一轮误判了。重读 `training/network.py:73, 96`:

```python
self.value_proj = nn.Linear(1, token_dim)
...
tok_emb = self.token_embed(types_flat.clamp(0, 255))
        + self.value_proj(values_flat)        # ← 数值走 1D 线性投影
        + self.pos_embed(pos)
```

数值 token(`TokLitNumber=240`)的 Value 字段(int16 实际数值)经
`value_proj` 线性投影后**加到** type embedding 上。这给了 `damage 2` 和
`damage 3` 一个**线性相关的 embedding 邻近性先验** — 至少在数值方向上
有序关系。

意味着:数值微调扰动(2→3→4→5)在 embedding 层面就有平滑性,网络不需要
从零学序关系。这是**正确的归纳偏置**。

## 现有的反位置耦合机制

为防止"位置 = ID"作弊,已实现 per-episode shuffle:

| 维度 | shuffle | 实现位置 |
|---|---|---|
| Hook 槽位(900) | ✓ | `gicg_engine/game.go:588` |
| Counter 槽位 | ✓ | `gicg_engine/game.go:585` |
| Card 槽位 | ✓ | `gicg_engine/game.go:590` |
| **Char 槽位** | ✗ | `gicg_engine/observation.go:335-341` 固定写入 |

Char 不 shuffle 是**有意为之**(`ActionSwitch.char_idx` 必须有稳定语义,
否则动作头解码崩),不是 bug。但这条仅在"训练阵容随机"的前提下不构成
泛化障碍。

## 已发现的实现-设计 Gap

### G1:阵容随机化 — 框架已实现,默认入口未启用(中,2026-04-17 修正)

**初版描述错误**:本节最初写的是"框架不支持随机阵容,需要把
`ScenarioConfig.team_0/team_1` 改成 Optional"。第二轮调查后**修正**。

**实际现状**:

- `ScenarioConfig` 已含 `char_pool: Optional[list[str]]`、`team_size: int`、
  `allow_mirror: bool` 字段(`training/config.py:44-46`)
- `c1_random_config` 已存在并使用上述字段(`training/config.py:311-315`):
  `char_pool=["赤蝶","墨客","猫咪","刻师傅","天星"], allow_mirror=False`
- 但 `c1_config`(主训练入口)仍是固定 `team_0=team_1=["赤蝶"]`,
  未启用随机化
- `gicg_env/env.py:7` 的 `ALL_CHARS` 与 `c1_random_config.char_pool` 一致,
  说明 5 个角色都已实装

**影响(降级)**:

1. **不是"框架阻塞",是"入口选择"**:把训练入口切到 `c1_random_config`
   即可获得阵容随机化
2. C1 系列结果都是固定单角色 mirror 跑出来的,与"元规则学习"假设
   验证无关 — 这部分原判断仍成立
3. `c1_random_config` 本身**也可能有 bug**(配置存在 ≠ 跑通过),
   切换前需先做 smoke 验证

**建议**:

- 切换主训练入口到 `c1_random_config`(或新建 `c2_*` 配置),
  下一次长训用随机阵容
- 跑前先 smoke 5-10 局验证 obs 维度足够、`n_counter_slots=1832`
  对多角色组合不溢出
- 留个 G1-followup:**`c1_random_config` 是 1v1 随机角色,但 team_size=1**。
  3v3 随机阵容仍是未实现状态 — 如果未来要做完整 3v3,需扩展
  `team_size` 采样和 obs slot 计算

### G2:value_proj 在 Type 间共享,语义混叠(低-中)

**现状**(代码精读后修正):

P2 已经说明 `value_proj(Value)` 给数值 token 提供了线性序关系。但
`value_proj` 是**所有 token 共用一个 1D 线性层**,而 Value 字段在不同 Type
下语义完全不同:

| Token Type | Value 字段语义 | 范围 |
|---|---|---|
| `TokLitNumber=240` | 实际数值 | 通常 0-50 |
| `TokLitString=241` | 字符串内容 hash | int16 全程([-32768, 32767]) |
| `TokVarRef=250` | 变量名 hash | int16 全程 |
| 其他 ~250 个 type | 0(填充) | 0 |

`tokenizer.go:418-422, 450-454` 显示字符串/变量名都用 `h = h*31 + c` 哈希成
int16,没有截断到小范围。

**影响**:

1. **数值与 hash 共用 value_proj**:`(TokLitNumber, 5)` 和
   `(TokLitString, hash=5)` 加进去的 `value_proj(5)` 完全相同。网络要靠
   Type embedding 的 gating 区分两者用途 — 理论可以学到,但增加了不必要的
   学习负担
2. **大数值 hash 主导 embedding**:hash 可以达到 ±30000,而 `value_proj` 是
   线性的,意味着大 hash token 的 value 项会**几个数量级压过** type embedding
   和 pos embedding。如果 LayerNorm 没在前面挡住,实际上变成"hash 主导
   embedding 方向" — 这反而强化了"内容指纹"作弊
3. **变量名 hash 碰撞**:int16 空间小,DSL 里大量自定义变量名(buff 名、
   counter 名),collision 概率不可忽略。两个不同变量碰撞后 token 完全相同

**验证方法**(可立即跑,不需训练):

1. 把训练好的 model 拿出来,打印一批 token 的 embedding norm,看 `TokLitString`
   / `TokVarRef` 的 norm 是不是远大于其他
2. 检查 `HookEncoder` 输入是否有 LayerNorm 在 transformer 前(看了源码:
   `network.py:88-100` **没有** input LayerNorm,只有 transformer 内部的)

**建议修复**(按 ROI 排序):

1. **最低成本**:数值 hash 在 tokenizer 端就用 `% small_vocab`(比如 1024)
   截断,改成查表式 categorical embedding。1 小时工作量
2. **中成本**:Type-specific value handling — 对 `TokLitNumber` 走 scalar,
   对 hash 类走 categorical embedding。半天工作量
3. **不推荐**:全面重做 token schema。投入产出比差

**优先级**:**等 G3 实验 1 跑完再决定**。如果扰动实验显示网络对数值变化
确实有响应,说明 value_proj 实际工作得不错,G2 可以延后。

### G3:零样本泛化从未被验证(严重)

**现状**:

- `feedback_no_ids.md` 记忆和 `gicg_env/env.py` 注释都强调"反 ID 设计"
- 但 `gicg_env/tests/`、`training/tests/` 没有任何"训练时见过卡集 A,
  测试时引入卡集 B,胜率 > 随机"的实验
- 现有的 gauntlet(`vs mcts_50/200/random`)只能证明绝对强度,
  **无法区分"学到规则" vs "学到指纹"**

**影响**:

设计假设(DSL token → 元规则)目前是**未证伪**而非"已验证"。
如果将来上 L5/L6 新卡发现网络完全不会处理,会很被动。

**建议实验**(按成本递增):

1. **冻结网络 + 单 token 扰动**(几小时):同一状态喂两次,第二次改一个 hook
   的数值 token,看 value/policy 输出是否按规则方向移动
2. **卡池 holdout**(1-2 天):训练时屏蔽某些卡(比如 L4 全部),测试时引入,
   看胜率是否高于随机基线
3. **角色 holdout**(依赖 G1 修复后):训练用 4 个角色,测试用第 5 个,
   看胜率是否非 trivial

实验 1 是 ROI 最高的。即使 G1 没修也能跑。

## 待决策的设计选择

### D-Curriculum:顺序课程 vs Domain Randomization

如果决定做"通过数值扰动逼出元规则学习",有两种实现路径:

| 选项 | 描述 | 优缺点 |
|---|---|---|
| 顺序课程 | 先训稳 v1.0 → 切到 v1.1(改数值)→ ... | 简单。但 catastrophic forgetting 风险高,网络可能为每个版本各学一套指纹 |
| Domain Randomization | 训练时每局从数值分布采样(类比 sim2real) | 从一开始网络看不到稳定指纹,被迫学结构。工程更复杂 |

**判定:DR**。

**论证(2026-04-17 第一性原理推导补充)**:

顺序课程下,早期训练阶段网络只见到 hook token 子空间 H₀。HookEncoder
输出的 ruleset 嵌入 R 会锚在 H₀ 的统计分布上,value head 对 R 的响应
模式同样锚在该分布。引入新卡(扩展 H₀ → H₁)时:

1. 新 hook 的 R 嵌入分布与 H₀ 不同 → value 输出漂移
2. 漂移幅度由 value head 的 Lipschitz 常数 × R 分布距离决定
3. 漂移 ⇒ 短期 self-play 强度回归 ⇒ 需要 unlearning + 再训练

DR 下从训练第 1 局起 R 就在完整 H 空间分布上,value head 学到的是
**对完整分布的 marginal**,不会在引入"已在 H 内但样本少"的新卡时漂移。

**反对顺序课程的关键**:课程 = "从 H₀ 到 H 的 distribution shift",
DR = "从一开始就在 H 上"。在持续演化的游戏里,distribution shift
是常态而非例外,把 shift 提前到训练时(DR)比留到部署后(课程)正确。

**唯一让步**:训练前 1% 步可允许较小卡池(8-12)做 warmup,让 search
信号 dense;之后立刻全随机。这是 warmup,不是课程。

**前置条件**:这条决策只在 G1 + G3 都解决后才有真正落地意义。
当前阵容固定 + 零样本未验证,讨论扰动课程是空中楼阁。

---

## 待评估的设计增强项(2026-04-17 第一性原理推导新增)

以下 4 项由独立第一性原理推导提出,**不是惯例**,而是从 D2(元规则学习
硬约束)、G3(不完全信息不退化)、M3(零和自洽性)演绎得到。当前实现
没有,需要决定是否纳入 roadmap。

### B-1:Belief head — 显式预测对手手牌 marginal

**论证**:不完全信息 ⇒ 真 value 依赖隐藏状态分布。当前 value head 只输出
标量 v_self,没有显式机制让网络从 observable(hand bucket、counter 历史、
对手出牌序列)推断 hidden(对手手牌)。隐式学习"会发生但不可控制"。

**形式**:增加 v_belief(s_t) → 80 维 sigmoid,目标"对手当前手牌中是否含
卡 c"。训练时拿真值监督(self-play 时双方信息都可获取),推理时只用
v_self。

**Loss**:`L_belief = BCE(对手手牌 one-hot, v_belief)`,权重 0.5。

**ROI**:中。要求训练 buffer 多存一个"对手当前手牌"字段,中等改动。
**触发条件**:G3 实验在不完全信息退化(对手手牌 mask 后 value 估计崩)
时才必要。

### B-2:Symmetry loss — 利用零和自洽性

**论证**:零和确定胜负 ⇒ v(s) + v(swap_player(s)) = 0 数学严格成立。
当前网络没有显式约束这件事,只能通过数据隐式学到(每局 P0/P1 视角各
出现一次)。

**形式**:`L_symm = MSE(v(s) + v(swap(s)), 0)`,权重 0.1。
mirror 对局时 swap(s)=s ⇒ 强制 v=0,治标 mirror 偏差。

**ROI**:低(改动小但提升幅度未知)。半天工作量。
**触发条件**:任何时候都能加,但收益有限,优先级低于 B-1/B-3。

### B-3:Frozen sinusoidal hash encoding — 替代 value_proj 处理 hash 类 token

**论证**:这是 G2 的**上位修复方案**。当前 G2 描述"value_proj 共享导致
混叠";第一性原理推导更尖锐:**任何 hash payload 的参数化 embedding 都
违反 D2**(元规则学习禁用 ID embedding,而 hash → 参数 = 学到的指纹)。

**形式**:对 `TokLitString` 和 `TokVarRef` 的 Value 字段,**不**走
`value_proj`,改走 frozen sinusoidal positional-style encoding(参数训练前
随机初始化后**冻结**,不参与梯度更新)。这样 hash 只能用于"两处出现的
同一 hash 在 attention 中可以注意彼此"(等同性测试),不能记忆"hash=X ⇒
某卡"。

`TokLitNumber` 仍走 `value_proj`(数值有真实序关系,需要参数化学习)。

**ROI**:中。涉及 HookEncoder 重构,但工作量集中(1-2 天)。
**触发条件**:**G3 实验阴性时这是首要嫌疑修复**。

### B-4:训练时 TokLitNumber ±1 扰动 — token 级数据增强

**论证**:与 B-3 配套。即使数值走参数化 value_proj 学到序关系,网络仍
可能记忆"伤害=2 的特定 token = 某卡"。训练时以 p=0.1 概率对 TokLitNumber
扰动 ±1,**不影响游戏行为**(该扰动不传到引擎,只在 obs 端做),迫使
网络学"伤害值的相对大小关系"而非"具体常量 = 某卡"。

**ROI**:高(1 小时实现,效果潜在显著)。
**触发条件**:G3 实验阴性时与 B-3 配套实施。

---

## B-1~B-4 优先级

| 项 | 优先级 | 触发条件 | 工作量 |
|---|---|---|---|
| B-4 | 高 | G3 阴性时立即做 | 1 小时 |
| B-3 | 中-高 | G3 阴性时主修复 | 1-2 天 |
| B-1 | 中 | G3 阴性 + 不完全信息退化具体证据 | 中等 |
| B-2 | 低 | 任何时候,聊胜于无 | 半天 |

## 优先级建议(2026-04-17 更新)

1. **G1**:切训练入口到 `c1_random_config`(框架已实现,只是 default 没用)。
   先 5-10 局 smoke 验证维度。半天
2. **G2 验证**(打印 embedding norm):零成本,先确认 hash 主导问题是否真的存在
3. **G3 实验 1**(冻结网络扰动):成本几小时,即使 G1 没切也能跑。
   是回答"现在到底学到了什么"成本最低的实验
4. **G3 实验 2/3**(holdout):依赖 G1 切换 + G3 实验 1 阴性结果
5. **B-4**(数值扰动):G3 阴性时立即做,1 小时
6. **B-3**(frozen hash encoding):G3 阴性时的主修复,1-2 天
7. **B-1**(belief head):仅在 G3 显示不完全信息退化具体证据时
8. **B-2 / D-Curriculum 落地**:最低优先级,前置实验全做完再说

不要在 G1 没切换前讨论"网络是否学到了元规则" — 当前训练场景退化到
**单角色 mirror**,结论无论正反都没有泛化层面的意义。

## 仍未确定 / 需实验验证

以下问题**必须跑实验才能定**,审查无法靠读代码下结论:

1. **G3 本体**:网络是否真的从 token 内容学到规则,还是退化为指纹查表 —
   靠扰动实验和 holdout 实验(G3 实验 1/2/3)
2. **D-Curriculum 的实证选择**:DR 是否真的优于顺序课程 —
   只有在 G1+G3 解决后做 A/B 才能定
3. **HookEncoder 的 attention 模式**:网络对哪些 token 关注最强 —
   可视化作为 G3 实验的补充诊断,无法独立得出结论

## 附录:本审查未深入的工程项

- 跨版本继续训练的 checkpoint 兼容性 — 当前无版本号字段,obs schema 一改
  老 checkpoint 直接 shape mismatch。**仅当真的开始做版本演化时再处理**
- `n_counter_slots = 2*6*128 + 2*140 + 16 = 1832`(`config.py:105`):
  6 是 `OBS_MAX_CHARS`,128 是 per-char counter 上限。G1 修复后阵容随机化
  下,需要确认这个上限对所有角色组合都够用
- `gicg_engine/interp/builtins.go` 的"卡牌注册时自动生成规范 token"逻辑
  本次未读 — 这是另一条 token 生成路径(非 DSL 源码 tokenize 而是合成),
  和 hand-written DSL 的 token 分布是否一致是个潜在的 distribution shift
  来源
