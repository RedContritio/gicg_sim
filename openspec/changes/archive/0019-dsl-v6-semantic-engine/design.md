# Design (retrospective)

## Consequences

### §A.1 IsSpecialty 启用(已完成)

- `interp/builtins_skill.go:163`:`invokeSkillCommon` 当 silent=true 设 `ctx.IsSpecialty=true`
- `interp/proxies_ctx.go:73`:GetField 加 `case "is_specialty"`
- `tests/specialty_ctx_spike_test.go`:spike PASS,全 suite 无 regression

**P0-5 防御性**:`invoke_skill_silent` 当前仅 specialty 路径用(prepare-resolve 走 ResolvePreparing
不经 invokeSkillCommon),实施正确但脆弱。后续若引入新 silent 路径,改 `invokeSkillCommon` signature
`silent bool, kind SilentKind` 枚举(Specialty / PrepareResolve / Other),IsSpecialty 仅 Specialty
kind 时 set。

### §B.1 Element.Piercing vs Element.None 语义关系(避免误改)

- `Element.None` = 反应触发后,引擎/反应 handler 把 incoming element 消耗后设的 sentinel(代码侧),
  **反应消耗后状态**,不进 attacker-side cost
- `Element.Piercing` = attacker 主动声明的伤害类型,attacker-side 属性,跳过反应/护盾/减伤
- 二者**不互转**

### §B.2 DamageModifierLog 作用域

- **per `DealDamage` call 一个 DamageModifierLog**(DealDamage 入口分配,栈上)
- **嵌套 damage call**(反击 / 反应 sub damage / 扩散子伤害)各自一个独立 log,不合并
- **engine push 到 obs ring 在 fire AfterDamage 之后**(`damage.go:155 fireAfterDamage` 之后)
- **DSL read 路径**:`proxies_ctx.go` 加 `case "modifiers"`,从 `rt.Game.currentDamageLog` 读;ctx 字段
  不直接挂 ModifierLog(避免 union 污染)
- **monotonic 部分 view**:`ctx.modifiers` 在任意 hook 时机可读(已 fire 部分总和,未 fire 不在);
  HookAfterDamage 读 = 完整
- **以逸待劳类 priority bracket idiom 改写**:旧 priority -100 在 reduce 末尾读 absorbed → 改
  `HookAfterDamage` 内遍历 `ctx.modifiers` 找 `Kind=ModShieldAbsorb` 的 sum

### §B.3 prepare-skill obs 编码

- storage 不动:`Game.Preparing [2]int` 仍存 skillID
- engine 启动 + skill 加载完后 build `Game.skillIdentityMap map[int]SkillIdentity` 反查表:
  `{CharIdx, SkillSlot}`(SkillSlot ∈ {0=普攻, 1=战技, 2=爆发, 3=被动})
- obs encoder 直接 O(1) 查 `skillIdentityMap[Preparing[player]]` → typed pair
- 每方一对 (-1, -1) 表无 prepare;Clone 时 skillIdentityMap 共享只读

### §B.3 typed ReactionID enum(DSL declare)

- 不 hardcode 在 engine,DSL `declare_reaction("Vaporize")` 注册得到 ID
- engine 加 `Game.ReactionRegistry map[string]int`(类似 CounterRegistry)
- DSL `set_reaction_kind(R_VAPORIZE)` 写 `EventContext.ReactionKind` 字段(每 DealDamage 入口 reset)
- obs encoder 编 fixed slot N=32 上界
- **支持新增反应**:始基/烈绽放/未来反应 — 任何 DSL 文件 declare 即可,**engine 0 改**

### §B.3 obs schema 变更影响

增加 8 × (1+1+1+1+1+1+12+typed_fields) ≈ 数百维新 obs feature → **现有 BC checkpoint 全部失效**。
Migration 必须含 "obs schema 变更 → BC dataset 重生成" 步。参考 memory `project_typed_obs_ckpt_break`
2026-05-08 TypedDamageEncoder 加进 ActorCritic,§B.3a 前所有 ckpt 不兼容(BREAKING by design)。

### §B.4 护盾 macro 设计

macro **完全可展开为 v1 现有写法**,不引入新引擎机制。macro **只覆盖默认场景**(无元素特异 / 无条
件 / 单一消耗逻辑)— 结晶护盾 / 简单装备护盾等。**特殊场景**(护体岩铠物理半伤 / 岩石大盾岩元素 2
倍 / 计数特殊消耗)**展开成 v1 现有手写 hook,不用 macro** — 保留 DSL 自由度。

**P0-3 Shield 顺序问题**:v1 当前 hook 注册顺序 = DSL 加载时刻**全局静态**,跟 GI TCG 实际"出战护盾
vs 团队护盾 + runtime 获得顺序"**有偏差**。reference impl `entity.ts:528` entity 创建时 register hook,
顺序是 **runtime stack**(后获得后注册先消耗)。本 ADR §B-4 macro 实施时:若 macro 在 entity declare
时 register hook → 顺序对齐 reference impl runtime stack;若 macro 在 DSL 文件加载时 register hook →
偏差仍存在。**B.4 spike 必带护盾顺序对照测试**。

### §B.5 旧 hook 删除路径

| 新时机 | 含义 | DSL 迁移路径 |
|---|---|---|
| `HookDamageType` | 元素修改(物理→火附魔等) | `ctx.element = X` |
| `HookDamageAdd` | 加法增伤 | `ctx.value += N` |
| `HookDamageMul` | 乘法增伤 | `ctx.value *= N` |
| `HookReactionDamage` | 反应判定(保留)+ set_reaction_kind | 反应 lua 加 1 行 declare + 1 行 set_reaction_kind |
| `HookDamageReduceBuff` | 减伤 buff(物理半伤等) | 元素特异减伤迁此 |
| `HookShieldAbsorb` | 护盾消耗 | 所有 Tag.Shield counter 消耗 hook 迁此 |
| `HookDamageImmunity` | 免疫(kill all) | `ctx.value = 0` 全免用法迁此 |

**旧 `HookDamageBoost` / `HookDamageReduce` 删除**(strict 路线下不保留兜底)。

### Migration 实施顺序

工作量总计 ~1060-2660 LOC(对比 v4 prototype 重写 3400 LOC,~31-78%;strict 路线 LOC 上界接近重写,
但价值在长期一致性 + RL obs 信号区分)。

LOC 不确定性主要来自 §A.3 始基反应(克洛琳德实证后才能定准)和 §B-5 DSL 迁移(audit 完整 lua 集后
定准)。

注:LOC 不含 BC dataset 重生成 + §C.1 ADR-0012 PR(docs-only)。

## Tradeoffs revisited

### 收益
- 工作量从 "重写 ~3400 LOC" 降至 ~1080-2050 LOC 增量
- 生产 v1 不动核心,无 regression 风险
- v1 现有 DSL 自由度全保留
- §B-1 简化:删 Penetrate flag,Element 类目化
- §B-2/B-3 修 P0-3 RL 黑盒(reaction kind / shield absorbed / modifier source / element transition /
  preparing_skill 进 obs)
- §B-4 macro 简化护盾 DSL 写法
- §B-5 加新 hook 时机给 obs 区分 modifier kind 的依据

### 代价
- §B-2/B-3 加 obs 维度,fixed-shape 上界 (K=8 / K_mod=12) 需 effect_pattern_frequency 实证统计微调
- §A.3 始基反应 LOC 大(400-600),N=6 张需多迭代
- v4 prototype 30 axiom 设计工作"白做",但负面知识保留

### 不做
- 不重写 v1
- 不引入引擎自动消耗 Tag.Shield(reference impl 反实证)
- 不删任何现有 hook 时机(保留 v1 自由度;§B.5 删的是 v1 的旧 hook 而非"现有",strict 后新 hook 替换)
- 不强制迁移现有 lua(strict 后必须;但仅 §B.5 范围)
- 不改 EventContext union(问题 4 推迟,FC-2)
- 不上线 v4 prototype

### Future Considerations (FC)

- **FC-1 乘算反应支持**:本 ADR 保持反应在 Add/Mul 之后,反应内仅 Flat Add(对齐 GI TCG 现状);乘算
  反应出现时再决策
- **FC-2 EventContext union 重构**(问题 4):未来若新加 hook 时机超过 union 容量,或 BC dataset 反复
  schema 变,再评估拆 sum-type per HookType

### Open Questions

1. §A.3 始基反应实施模式 + acceptance criteria(P1-E)
2. §B-3 K_mod 上限实证统计(B.0 是新写工具 `tools/scan_modifier_frequency.py`)
3. ~~§A.3 find_char(predicate) closure 支持~~ — ✅ 已证伪并解决(2026-05-04)
4. §B-4 declare_shield 是否纳入 v1 stdlib — 倾向 DSL lib
5. ~~§B-5 是否实施~~ — strict 路线下必须实施
6. P0-3 Shield 顺序与 GI TCG 实际规则差异审计

## P1 Status update (2026-05-15)

memory `project_adr_0019_strict` 显示 2026-05-07 v1 增量改造 17 commits ship,strict 8 hook 流水线
落地。§A.3 始基反应 Phase 2 留下次。本 ADR P1-T1 时正式从 PROPOSED 改 Accepted(de-facto since
2026-05-07 strict ship)。

## References

- `docs/2_decisions/adr-0019-dsl_v6_semantic_engine.md` (mirror)
- `docs/3_plans/cards/dsl_gaps.md` — 706 张 cleansed 实证审计
- `ref/genius-invokation/`(`Guyutongxue/genius-invokation` clone, AGPLv3.0)— 对照 + 反实证
- `docs/5_history/v4-experience.md` — 待写 v4 prototype 经验摘要(supersede 正式化前置)
- [`../0017-dsl-v4/`](../0017-dsl-v4/) — supersede-on-implementation
- [`../0018-dsl-v5-event-sourcing/`](../0018-dsl-v5-event-sourcing/) — supersede-on-implementation
- [`../0012-specialty-and-prepare-skill/`](../0012-specialty-and-prepare-skill/) — §A 依赖
- memory `project_adr_0019_strict` — 2026-05-07 v1 增量 17 commits ship
- memory `project_typed_obs_ckpt_break` — §B.3 obs schema 变更 ckpt 作废
- memory `feedback_lua_dsl_constraints` — closure spike 证伪
- memory `project_v1_is_production` — v1 是生产引擎
