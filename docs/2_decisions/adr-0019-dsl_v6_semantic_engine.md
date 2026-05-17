---
adr: 0019
title: v1 增量改造 — DSL gap 闭合 + damage/obs 语义增强(保留 v1 自由度)
status: PROPOSED
date: 2026-05-01
supersedes-on-implementation:
  - adr-0017-dsl_v4.md (v4 prototype 30 axiom 重写路线被反思)
  - adr-0018-dsl_v5_event_sourcing.md (基于 v4 prototype 的局部修补)
---

# ADR-0019: v1 增量改造

> **MOVED to `openspec/changes/archive/0019-dsl-v6-semantic-engine/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0019-dsl-v6-semantic-engine/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0019-dsl-v6-semantic-engine/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


## Status

PROPOSED — 基于 `dsl_gaps.md` 706 张 cleansed yaml 实证审计 + v1 实测 damage/obs 设计问题 + opus subagent 三轮评审修订 + `Guyutongxue/genius-invokation` 开源对照实证 + closure spike 证伪 + user 对 strict / engine ignorance 边界确认。**核心原则**:**DSL 表达力自由度保留**;damage 管线 **strict 拆 4+3 阶段**(对齐 ref impl + reduce 端拆),旧 boost/reduce hook 删除,DSL audit + 迁移;**支持 DSL 新增反应**(declare_reaction registry,engine 0 hardcode 反应名)。

## Context

### 1. v1 是生产引擎,实测覆盖 95%+ 卡池

`gicg_engine/` 主目录是生产 v1(`damage.go` 268 LOC 完整管线 + lua DSL + counter+hook idiom)。`v2/` 是旁路 prototype,从未上线。

`dsl_gaps.md`(2026-04-30 706 张 cleansed yaml 审计)实测剩余 gap:★★★ × 2 / ★★ × 1 / ★ × 1。绝大多数原 ★★★ gap 已被 ADR-0012 关闭。

### 2. v1 实测设计问题(本 ADR §B 修正)

5 个具体问题:
- **问题 1**:护盾是 generic counter + `Tag.Shield` 协议;消耗顺序 / 上限 / 穿透绕过全 DSL 自己写
- **问题 2**:`HookDamageReduce` 单一时机混 3 种语义(护盾消耗 / 减伤 buff / 免疫),priority 协商
- **问题 3**:obs 完全不暴露 typed damage 信号(P0-3 漏洞)— RL 看 final dmg 但不知 raw / absorbed / reaction kind
- **问题 4**:`EventContext` 30+ 字段 union over-loaded(本 ADR 不修)
- **问题 5**:damage 管线 4 阶段不区分 modifier 类型(flat / multiplier / replace / cap)

### 3. 穿透是基础 element 类型,不是 modifier flag

GI 规则:穿透是无视护盾和减伤的物理伤害,不附着不反应。当前 v1 用 `Element + Penetrate bool` 双字段(冗余)。grep 实测 v1 中 `penetrate=true` 仅 4 处使用点(感电.lua / 超导.lua / damage.go / builtins_action.go)。

### 4. v1 ↔ v6 reference impl 关键对照

`ref/genius-invokation/`(`Guyutongxue/genius-invokation` clone,AGPLv3.0,完整官方卡池)对照发现:

- **反应表设计**:`base/reaction.ts:174 LOC` typed 静态映射 `Aura × DamageType → [Aura, Reaction|null]`,`DamageType` 含 `Physical / Piercing / Heal` ✅ 验证 §B-1 路线
- **护盾设计**:`builder/entity.ts:528-549` 每护盾 entity 自己注册 `on("decreaseDamaged")` hook,builder pattern 把 `shield(N)` 一行打包 = declare counter + 注册 hook + dispose 逻辑;**不是引擎自动遍历消耗**。reference impl 反实证 §B-4 早期"引擎自动消耗"路线
- **DSL macro / builder shortcut** 是简化声明的方式,**不替代 hook 自定义路径**

## Decision — strict 4+3 阶段 + DSL 自由度

### 核心原则
1. **DSL 表达力自由度保留** — 任意 counter / 任意 hook 时机 / 任意 priority / 任意 modifier 表达力
2. **damage 管线 strict 拆 4+3 阶段**:旧 `HookDamageBoost` / `HookDamageReduce` 删除,DSL 必须 audit + 迁移分类(对齐 ref impl modifyDamage0/1/2/3 + 减伤端 strict 拆)
3. **支持 DSL 新增反应** — 反应 typed enum 由 DSL `declare_reaction("X")` 注册得到 ID,engine 0 hardcode 反应名
4. **引擎不引入"自动消耗"等强规范** — 护盾消耗等行为仍 DSL hook(declare_shield macro 是 opt-in 简化语法糖,不替代手写)
5. **No-IDs 原则保留** — typed enum 常量(Reaction.Vaporize / Element.Fire 等)由 DSL declare 后 engine 维护反查表;global skillID 不进 obs

### 完整 strict 流水线(8 hook 时机)

```
HookDamageType         — 元素修改(物理→火附魔等)
  → HookDamageAdd      — 加法增伤(班尼特 +2 / 反应 +2 等 ctx.value += N)
  → HookDamageMul      — 乘法增伤(ctx.value *= N)
  → HookReactionDamage — 反应判定 + DSL set_reaction_kind
  → HookDamageReduceBuff — 减伤 buff(物理半伤等)
  → HookShieldAbsorb   — 护盾消耗
  → HookDamageImmunity — 免疫
  → 扣血
  → HookAfterDamage    — 后置(ctx.modifiers 完整 view)
```

无旧 Boost / 旧 Reduce 兜底。DSL 全部 audit 分类。

### §A — DSL 表达力 gap 闭合

#### A1:`ctx.is_specialty` 启用(★★★)— ✅ 已完成

**已实施**:
- `interp/builtins_skill.go:163`:`invokeSkillCommon` 当 silent=true 设 `ctx.IsSpecialty=true`
- `interp/proxies_ctx.go:73`:GetField 加 `case "is_specialty"`
- `tests/specialty_ctx_spike_test.go`:spike PASS,全 suite 无 regression

**P0-5 防御性**:`invoke_skill_silent` 当前仅 specialty 路径用(prepare-resolve 走 ResolvePreparing 不经 invokeSkillCommon),实施正确但**脆弱**。后续若引入新 silent 路径(非 specialty),改 `invokeSkillCommon` signature:`silent bool, kind SilentKind`(枚举 Specialty / PrepareResolve / Other),IsSpecialty 仅 Specialty kind 时 set。当前不抢做,加注释提示。

#### A2:始基力反应(★★★,DSL only)

**设计**:始基反应不入 `system/reactions/`,作 buff-owned hook 写在 character 文件;N 角色重复时抽 `data/lib/arche.lua` 共享 module。

**LOC 重估**(P1-3 修正):克洛琳德涉及多形态切换 + 元素生命检测,单角色 ≥150 LOC;6 张总计 **~400-600 LOC**(原估 180 严重低估)。

**实施序列**:先实证 1 张克洛琳德 + user 确认模式,后扩展 5 张。

#### A3:`find_char_by_kind(player, KindEnum)` builtin(★★)

**closure spike 已证伪**(2026-05-04):v1 lua DSL `ReturnStmt` 无 value 字段(`ast.go:51`)+ `errReturn struct{}` 不携带 value(`eval.go:6`)+ `callClosure` 不传返回值(`builtins_hook.go:120`)。**closure-return-value 路线不可行**,改 enum-based 路线。

**修订**:加 `find_char_by_kind(player, KindEnum) → []char_idx`,KindEnum 预定义:
- `Kind.LowestHp` / `Kind.HighestHp` — 治疗 / 召唤物随机最低
- `Kind.LeastDamaged` — 万众瞩目"受伤最少的我方角色"
- `Kind.RandomNonActive` — 部分召唤物"敌方场上随机一名"
- `Kind.PreviousActive` — 追踪爆弹"切换到的角色"

**Trade-off**:损失灵活性(新需求需加 KindEnum 改 engine,而非 DSL 写新谓词);换确定性 + 与 v1 closure 限制对齐。新 Kind 出现时改 builtin 比改 DSL 表达力更可控。

**工作量**:~50 LOC engine + 1 spike test 验证 5 种 Kind 各自正确。

#### A4:调和 hook(★,推迟)

`on_tune` hook 涉及 ~3-5 张。玛薇卡 / 后续版本再实施。

### §B — damage/obs 语义增强(全部 opt-in,不强制迁移)

#### B1:`Element.Piercing` 替代 `Penetrate` flag(★★★ 必做)

**Element.None vs Element.Piercing 语义关系**(避免误改):
- `Element.None` = 反应触发后,引擎/反应 handler 把 incoming element 消耗后设的 sentinel(代码侧),**反应消耗后状态**,不进 attacker-side cost
- `Element.Piercing` = attacker 主动声明的伤害类型,attacker-side 属性,跳过反应/护盾/减伤
- 二者**不互转**。`感电.lua:17` `ctx.element = Element.None`(反应消耗后)**保持 None,不改 Piercing**;只把 `deal_damage(..., {penetrate=true})` opts 改为 `deal_damage(..., Element.Piercing)` parameter

**修订**:
- `types.go` Element enum 加 `ElementPiercing` value
- 加 helper:`Element.IsElemental() / IsPiercing() / IsPhysical()`
- 删 `EventContext.Penetrate` + `DamageOpts.Penetrate`
- `damage.go` 判定改 `ctx.Element.IsPiercing()`(reaction + reduce 两阶段)
- **DSL lua 适配 6 处**(grep 实测,不是 2 处):`感电.lua` / `超导.lua` / `data/pools/v_legacy/cards/.../刺刺猫爪.lua` / `以攻代守.lua` / `赤蝶_蝶火.lua` / `刻师傅_雷暴.lua`,各自把 `{penetrate=true}` opts 改 `Element.Piercing` 参数
- **P1-4 record/replay format migration**:writer 输出 `element` 字段含 Piercing;reader 加 fallback `if e.Fields["penetrate"].(bool) == true && element == None: treat as ElementPiercing`,旧 replay 文件兼容

**工作量**:~15 LOC engine + **6 行 lua**(每文件 1 行 opts→param 改)+ record format compat ~30 LOC。

#### B2:typed Modifier list,带 element 维度(★★★ 必做)

**P0-1 修复**:Modifier 不只是 Value delta,要带 element 维度。**Modifier struct 不进 EventContext**(P1-6 修正,避免 union 污染),作为单独 `DamageModifierLog`,per-damage-call 独立分配:

```go
type ModifierKind int
const (
    ModBoost ModifierKind = iota   // HookDamageBoost(蝶火附魔等)
    ModReactionBonus                // HookReactionDamage(蒸发 +2)
    ModReduce                       // HookDamageReduce(护盾 + buff 等)
    ModImmunity                     // 假设新增 HookDamageImmunity(B5 加)
)

type Modifier struct {
    Source        int       // hook.ID 引用(避免 string copy 重复存)
    Kind          ModifierKind
    ValueBefore   int       // ctx.Value 修改前
    ValueAfter    int       // ctx.Value 修改后
    ElementBefore Element   // ctx.Element 修改前(蝶火附魔 / 蒸发转 None 等)
    ElementAfter  Element   // ctx.Element 修改后
}

type DamageModifierLog struct {
    Modifiers []Modifier
}
```

**作用域 / 存储语义**(P0-D 修复):
- **per `DealDamage` call 一个 DamageModifierLog**(DealDamage 入口分配,栈上)
- **嵌套 damage call**(反击 / 反应 sub damage / 扩散子伤害)各自一个独立 log,不合并;反击的 modifier 不污染父 damage 的 log
- **engine push 到 obs ring 在 fire AfterDamage 之后**(damage.go:155 `fireAfterDamage(ctx)` 之后),整 log 复制进 `recent_damage[K]` ring 当前条目
- **DSL read 路径**(P0-α 决策 b):`proxies_ctx.go` 加 `case "modifiers"`,从 `rt.Game.currentDamageLog` 读;**ctx 字段不直接挂 ModifierLog**(P1-6 union 不污染);engine 加 `Game.currentDamageLog *DamageModifierLog` 栈,DealDamage 入口 push,出口 pop,嵌套 call 各栈层独立
- **monotonic 部分 view**(P1-ε):`ctx.modifiers` 在任意 hook 时机可读(monotonic snapshot — 已 fire 部分总和,未 fire 不在);DSL 作者懂 reduce 阶段中段读 = 部分,HookAfterDamage 读 = 完整
- **以逸待劳类 priority bracket idiom 改写**(strict 后必然路径):旧 priority -100 在 reduce 末尾读 absorbed → 改 `HookAfterDamage` 内遍历 `ctx.modifiers` 找 `Kind=ModShieldAbsorb` 的 sum
- **subkind 细分**(P1-β 决策 b):hook 注册 API 加 `subkind` 字段:`on_damage_reduce_buff(priority, fn, {subkind="shield_pre_modifier"})` 或类似;Modifier kind 自然细分

**实施**:`damage.go` 在每 fire hook 前 record (ValueBefore, ElementBefore),fire 后 compare,自动 append modifier 到 currentDamageLog 栈顶。`fireAfterDamage` 后 push 到 obs ring,然后 pop 栈。

**工作量**:~80 LOC engine(含 currentDamageLog 栈 + modifier proxy)+ ~20 LOC for subkind metadata。

#### B3:obs 暴露 typed damage event + prepare-skill(★★★ 必做)

**修订**:
- `observation_dynamic.go` 加 `recent_damage[K=8]` ring(P1-1 上调,覆盖超导/感电/扩散一对多场景)
- 每条 typed:src/tgt char、element(含 Piercing)、raw / final / absorbed、reaction_kind enum、modifiers list(**K_mod=16 起步**,基于 §B.0 静态实证 P95=5/P99=14/MAX=17,加 padding;§B.2 落地后跑 replay log dynamic refine)
- **P1-8 加 prepare-skill obs 编码**(P0-γ 决策:engine 维护反查映射):
  - storage 不动:`Game.Preparing [2]int` 仍存 skillID(向后兼容)
  - engine 启动 + skill 加载完后,build `Game.skillIdentityMap map[int]SkillIdentity` 反查表:`{CharIdx, SkillSlot}`(SkillSlot ∈ {0=普攻, 1=战技, 2=爆发, 3=被动})
  - obs encoder 直接 O(1) 查 `skillIdentityMap[Preparing[player]]` → typed pair
  - 每方一对 (-1, -1) 表无 prepare;Clone 时 skillIdentityMap 共享只读
- **typed `ReactionID` enum**(P0-β 决策 a:DSL declare):
  - 不 hardcode 在 engine,DSL 通过 `declare_reaction("Vaporize")` 注册得到 ID
  - engine 加 `Game.ReactionRegistry map[string]int`(类似 CounterRegistry),`declare_reaction` 首次见 alloc 新 ID,重复见返 已 alloc ID(idempotent)
  - DSL `set_reaction_kind(R_VAPORIZE)` 写 `EventContext.ReactionKind` 字段(reset on 每 DealDamage 入口)
  - obs encoder 编 `ctx.ReactionKind` 进 fixed slot,N=32 上界(加载完成后所有反应 ID < N)
  - **支持新增反应**:始基/烈绽放/未来反应 — 任何 DSL 文件 declare 即可,**engine 0 改**
- **B.3 落地前 obs schema 变更影响**:增加 8 × (1+1+1+1+1+1+12+typed_fields) ≈ 数百维新 obs feature → **现有 BC checkpoint 全部失效**,Migration 必须含 "obs schema 变更 → BC dataset 重生成" 步;参考 memory `hook_gradient_bug` 提示 ckpt 作废处置

**工作量**:~180 LOC encoder + 30 ring buffer + reaction kind detection。

**reaction kind 不再用 transition 检测**(P0-β 决策 a 后):DSL `set_reaction_kind(R_X)` 显式写入 `ctx.ReactionKind`,engine 0 推断;旧 v1 `damage.go:84` 的 `non-None → None` transition 检测仅保留作 RewardAccum.ReactionsTriggered 计数(reward 用),**不再驱动 obs reaction_kind**。

**P0-1 / P0-β 联动**:reaction_kind 由 DSL 显式标记,Modifier list 提供"哪些 hook 各贡献多少修改"细节。两套独立信号 obs 都含。

#### B4:护盾 declare macro(★★ 可选,**保留 v1 自由度**)

**对照 reference impl**(`builder/entity.ts:528`):每护盾自己注册 `on("decreaseDamaged")` hook,builder shortcut `shield(N)` 一行打包。

**closure spike 证伪后修订**(2026-05-04):macro 不接 condition / dispose_on_empty lua function(closure return 不支持)。改"**默认场景 macro,特殊场景手写**":

**默认 macro**(覆盖无条件 / 无元素特异 / 单一消耗逻辑的常见护盾,如结晶护盾):

```lua
local c = declare_counter(name, scope, count, { tag = Tag.Shield, max = opts.max or count })
on_damage_reduce(opts.priority or 0, function(ctx)
    if ctx.element.is_piercing() then return end  -- §B-1 自动判定
    local s = c:get_at(ctx.target_player)
    if s <= 0 then return end
    local absorb = min(s, ctx.value)
    c:sub_at(ctx.target_player, absorb)
    ctx.value = ctx.value - absorb
    -- macro 不处理 dispose_on_empty,DSL 自己 on_after_write 处理
end)
```

**关键设计**:
- macro **完全可展开为 v1 现有写法**,不引入新引擎机制
- macro **只覆盖默认场景**(无元素特异 / 无条件 / 单一消耗逻辑)— 结晶护盾 / 简单装备护盾等
- **特殊场景**(护体岩铠物理半伤 / 岩石大盾岩元素 2 倍 / 计数特殊消耗)**展开成 v1 现有手写 hook,不用 macro** — 保留 DSL 自由度
- `priority` 让 DSL 在多护盾间自定 — **保留自由度**
- **不引入引擎自动遍历 Tag.Shield** — 顺序由 hook 注册顺序决定
- 现有 `结晶.lua` 可选迁移到 `declare_shield`,**不强制**

**P0-3 Shield 顺序问题正视**:v1 当前 hook 注册顺序 = DSL 加载时刻**全局静态**,跟 GI TCG 实际"出战护盾 vs 团队护盾 + runtime 获得顺序"**有偏差**。reference impl `entity.ts:528` entity 创建时 register hook,顺序是 **runtime stack**(后获得后注册先消耗)。本 ADR §B-4 macro 实施时:
- 若 macro 在 entity declare 时 register hook → 顺序对齐 reference impl runtime stack
- 若 macro 在 DSL 文件加载时 register hook → 偏差仍存在
- **B.4 spike 必带护盾顺序对照测试**:KQM TCL 给出 GI 实际顺序 vs macro 实施顺序,差异需明确

**B.4 closure 依赖已消除**(closure spike 证伪后):macro 不接 lua function 参数,只接静态 opts(priority / max / scope),无 closure 风险。

**B.4 兼容现有 `Tag.Shield` 监听者**:macro 展开内含 `tag = Tag.Shield`,若 DSL 中有任意 `register_on_tag_write(Tag.Shield, ...)` 监听者,counter 写入仍 fire。**spike 前置 audit**:grep 现有 lua 中 `Tag.Shield` 写监听者(P1-γ:三轮评审发现一轮引用的 `以攻代守.lua:9` 不是真 Tag.Shield 监听者,需重新 audit 找真正使用者;若 0 个则该 spike case 简化为兼容性证明而非真实场景)。

**工作量**:~30 LOC DSL macro(纯 lua,因不需 closure 处理简化)+ 顺序对照 spike + Tag.Shield 兼容 spike。**前置**:顺序对照 spike PASS + Tag.Shield 兼容 spike PASS(closure spike 已证伪,不需要再做)。

#### B5:strict 拆 Boost(4 时机)+ Reduce(3 时机)— 旧 hook 删

**strict 4 阶段 boost**(对齐 ref impl modifyDamage0/1/2):
| 新时机 | 含义 | DSL 迁移路径(从旧 HookDamageBoost) |
|---|---|---|
| `HookDamageType` | 元素修改(物理→火附魔等) | `ctx.element = X` 类用法迁此 |
| `HookDamageAdd` | 加法增伤 | `ctx.value += N` 类用法迁此 |
| `HookDamageMul` | 乘法增伤 | `ctx.value *= N` 类用法迁此 |
| `HookReactionDamage` | 反应判定(保留)+ DSL `set_reaction_kind` | 反应 lua 加 1 行 declare + 1 行 set_reaction_kind |

**strict 3 时机 reduce**(对齐 ref impl modifyDamage3 拆分):
| 新时机 | 含义 | DSL 迁移路径(从旧 HookDamageReduce) |
|---|---|---|
| `HookDamageReduceBuff` | 减伤 buff(物理半伤等) | 元素特异减伤 / 数值条件减伤迁此 |
| `HookShieldAbsorb` | 护盾消耗 | 所有 Tag.Shield counter 消耗 hook 迁此 |
| `HookDamageImmunity` | 免疫(kill all) | `ctx.value = 0` 全免用法迁此 |

**旧 `HookDamageBoost` / `HookDamageReduce` 删除**(strict 路线下不保留兜底)。

**以逸待劳类 priority bracket idiom 改写**(strict 后必然路径):
```lua
-- 旧 (priority -100 在 reduce 末尾读 absorbed)
on_damage_reduce(-100, function(ctx) reflect(ctx.preShieldValue - ctx.value) end)

-- 新 (HookAfterDamage 读 ctx.modifiers)
on_after_damage(function(ctx)
    local absorbed = 0
    for _, m in ipairs(ctx.modifiers) do
        if m.kind == ModifierKind.ShieldAbsorb then
            absorbed = absorbed + (m.value_before - m.value_after)
        end
    end
    if absorbed > 0 then reflect(absorbed) end
end)
```

**DSL audit + 迁移工作量估**:
- 现有 8 个 reaction lua 加 declare_reaction + set_reaction_kind:每文件 ~2 行,共 ~16 行
- 现有 N 张装备/buff 卡 audit `on_damage_boost` → 分到 Type/Add/Mul:估 N=20-30 张,每张 ~5-10 行小改,合计 ~100-300 LOC
- 现有 `on_damage_reduce` 用法 audit → 分到 ReduceBuff/ShieldAbsorb/Immunity:估 N=4-10 张,合计 ~30-100 LOC
- 以逸待劳类 priority bracket 改写:估 2-3 张,~30 LOC
- 始基反应额外 declare_reaction:~6 张,每张 +1 行

**工作量**:~150 LOC engine(7 新 hook 时机注册 + dispatch 顺序 + 删旧 hook)+ ~200-450 LOC DSL audit + 迁移。

**前置**:无 spike(不再需要 P1-A 一致性 spike,因为 strict 不允许 macro/非-macro 并存)。

### §C — 防御性 / 兼容修订(从评审引入)

#### C1:`ADR-0012` status 同步 ACCEPTED(P1-5)

ADR-0012 文档头还是 PROPOSED,但 builtin 已实现(set_preparing / draw_card / add_dice / invoke_skill_silent grep 验证)。**本 ADR ACCEPTED 前置条件**:PR `adr-0012` 改 `Status: ACCEPTED`。

#### C2:supersedes 关系澄清(P0-6)

**改 `supersedes-on-implementation`**(已在 frontmatter 调整):
- 本 ADR ACCEPTED **不**自动 supersede ADR-0017/0018
- 实施完成 + v4 prototype `gicg_engine/v2/` 删除 + 经验摘要落 `docs/5_history/v4-experience.md` 后,才正式 supersede
- 中间状态:ADR-0017/0018 仍 PROPOSED active,本 ADR PROPOSED-implementing,共存清晰

## Tradeoffs

### 收益
- 工作量从"重写 ~3400 LOC"降至 **~1080-2050 LOC 增量**(strict 路线 LOC 比 opt-in 翻 1-2 倍,主要在 §B-5 的 DSL audit + 迁移;含 spike + record format compat + 6 处 lua 适配 + B.0 工具新写 + prepare-skill 反查表 + reaction declare)
- 生产 v1 不动核心,无 regression 风险
- **v1 现有 DSL 自由度全保留**:hook 时机不删、priority bracket idiom 工作、自定义护盾消耗路径保留
- §B-1 简化:删 Penetrate flag,Element 类目化
- §B-2/B-3 修 P0-3 RL 黑盒(reaction kind / shield absorbed / modifier source / element transition / preparing_skill 进 obs)
- §B-4 macro 简化护盾 DSL 写法,N 张 lua 可选 -10 行/张
- §B-5 加新 hook 时机给 obs 区分 modifier kind 的依据

### 代价
- §B-2/B-3 加 obs 维度,fixed-shape 上界(K=8 / K_mod=12)需 effect_pattern_frequency 实证统计微调
- §A.3 始基反应 LOC 大(400-600),N=6 张需多迭代
- 旧 `HookDamageReduce` 保留导致 hook 时机数量 +3,DSL 作者要学新选择
- v4 prototype 30 axiom 设计工作"白做",但负面知识保留(哪些方向不必要)

### 不做
- 不重写 v1
- **不引入引擎自动消耗 Tag.Shield**(reference impl 反实证)
- **不删任何现有 hook 时机**(保留 v1 自由度)
- 不强制迁移现有 lua
- 不改 EventContext union(问题 4 推迟)
- 不上线 v4 prototype

## Open Questions

1. **§A.3 始基反应实施模式 + acceptance criteria**(P1-E):"1 张克洛琳德实证后扩"的模式 OK 标准 = (a) **LOC/张 上限 TBD**(克洛琳德实证完成后定,初步估 ~150-250 但**未实证**;后续 5 张实测 P75 设上限);(b) 出现 ≥ 3 次的 helper 抽到 `data/lib/arche.lua`;(c) spike test PASS 含元素生命转换 + 始基反应 + 失能形态切换 3 case
2. **§B-3 K_mod 上限实证统计**(P1-2):**B.0 是新写工具**(`tools/scan_modifier_frequency.py` 不存在,需新建,~50 LOC)— 扫 v1 训练 replay log + cleansed yaml 静态分析,统计单 damage event modifier 数分布 P95/P99;**B.3 实施前必跑**,scientific 定 K_mod。已存在的 `effect_pattern_frequency.md` 是文本 pattern,**不是** modifier 频次,不可复用
3. ~~**§A.3 find_char(predicate) closure 支持**(P1-7)~~ — ✅ **已证伪并解决**(2026-05-04):lua DSL `ReturnStmt` 无 value 字段,closure 不能返回值;A.2 改 `find_char_by_kind(KindEnum)` enum-based;B.4 macro 不接 lambda 改静态 opts
4. **§B-4 declare_shield 是否纳入 v1 stdlib** — `data/lib/shield.lua` vs `interp/builtins.go` builtin 注册;倾向 DSL lib(可改不改 engine)
5. ~~**§B-5 是否实施**~~ — strict 路线下必须实施,删旧 hook 整迁移
6. **P0-3 Shield 顺序与 GI TCG 实际规则差异审计** — KQM TCL 给的护盾消耗顺序 vs B.4 macro 实施顺序(runtime stack vs DSL load),差异列表 + 是否需要修复;若不修则在 ADR 列为 known limitation

## Future Considerations(标记将来考虑,本 ADR 不解决)

### FC-1:乘算反应支持

**背景**:GI TCG 现有 13 反应数值全部 Flat(+1/+2),没有 ×N 反应。但 ADR §B-5 strict 流水线把 `HookReactionDamage` 排在 `HookDamageAdd / HookDamageMul` **之后**,这意味着反应内 `ctx.value += 2` 是反应阶段独立 mutate(不属于 Add/Mul 阶段)。

**未来问题**:若新增反应(始基 / 烈绽放 / 玩家自定义)需要乘算(如假设"火+某始基 → ×1.5 dmg"):
- 反应内 `ctx.value *= 1.5` 时机在 Mul 之后,序列上违反"先 Type 后 Add 后 Mul"几何序
- modifier kind 推断:engine 看 (before, after) pair 应推 ModReactionMul,不与 ModBoostMul 混

**若未来真出现乘算反应**,可选方案:
- (1) HookReactionDamage 自由 mutate(+/*/任意),engine 推算术形式自动归 modifier kind
- (2) 拆 HookReactionAdd / HookReactionMul 两个时机,反应 lua 按算术形式分到不同 hook
- (3) 反应阶段重排到 Add/Mul **之前**(对齐"反应是基础附加"直觉),反应内自由 mutate
- (4) declare_reaction 携带数值,engine 自动 mutate(违反 engine ignorance)

**当前决议**:本 ADR 保持反应在 Add/Mul **之后**,反应内仅 Flat Add(对齐 GI TCG 现状);乘算反应出现时再决策。

### FC-2:EventContext union 重构(问题 4)

v1 EventContext 30+ 字段 over-loaded(各 hook 类型共享),工作量大本 ADR 不修。未来若新加 hook 时机超过 union 容量,或 BC dataset 反复 schema 变,再评估 EventContext 拆 sum-type per HookType。

## Migration

### 实施顺序(各步独立 commit + spike test PASS)

| 步 | 内容 | LOC |
|---|---|---|
| **§A 步** | | |
| ✅ A.1 | IsSpecialty 启用 + spike test | 完成(~5+80) |
| ✅ closure spike | 证伪(无需写 test;ast.go:51 + eval.go:6 + builtins_hook.go:120 实证)— A.2 / B.4 改 enum / 静态 macro 路线 | 完成(0 LOC) |
| A.2 | A3 — `find_char_by_kind(player, KindEnum)` builtin(enum-based) | ~50 + 5 Kind spike |
| A.3 | A2 — 始基反应起步 1 张克洛琳德实证(LOC ≥ 150)+ 扩展 5 张 | ~150 实证 / ~400-600 总 |
| **§B 步** | | |
| B.0 | effect_pattern_frequency 实证 modifier 数分布(B.3 前置) | ~50 工具脚本 |
| B.1 | `Element.Piercing` 替代 Penetrate + 6 lua 适配 + record format compat | ~15 + 6 lua + ~30 compat |
| B.2 | DamageModifierLog typed,带 element 维度 + 作用域定义 | ~80 |
| B.3 | obs `recent_damage[K=8]` ring + reaction kind enum(non-None→None)+ prepare-skill (active_char, skill_slot) 编码 + obs schema 变更 → BC dataset 重生成 | ~180 + BC regen |
| B.4 | `declare_shield` DSL macro(静态 opts,不接 lambda)+ 顺序对照 spike + Tag.Shield 兼容 spike;特殊场景手写 hook 不用 macro | ~30 macro + ~50 spike |
| B.5 | **strict 拆 4+3 hook 时机** — 加 `HookDamageType/Add/Mul/ReduceBuff/ShieldAbsorb/Immunity` 6 时机 + 删旧 `HookDamageBoost/Reduce` + DSL audit 全部迁移 + 以逸待劳类改写 + reaction.lua 加 declare_reaction + set_reaction_kind | ~150 engine + ~200-450 DSL |

**手算实施新增**(已完成 §A.1 = 5+80 不计):
- §A 实施新增:A.2(50)+ A.3 实证 + 扩展(150 ~ 1500 视 acceptance criteria 实证后定)= **§A 总 ~200-1550 LOC**
- §B 实施新增:
  - B.0 modifier 频次工具 = 50
  - B.1 Element.Piercing + 6 lua + record compat = 51
  - B.2 DamageModifierLog typed + currentDamageLog 栈 + subkind metadata = 100
  - B.3 obs ring + reaction declare registry + skillIdentityMap 反查表 = 230
  - B.4 declare_shield macro + 2 spike = 80
  - **B.5 strict 4+3 hook 时机 + DSL audit + 迁移 = 350-600**
  - **§B 总 ~860-1110 LOC**
- §C:C.1 docs-only,不计

**总计 ~1060-2660 LOC**(对比 v4 prototype 重写 3400 LOC,**~31-78%**;strict 路线 LOC 上界接近重写,但价值在长期一致性 + RL obs 信号区分)。

LOC 不确定性主要来自 §A.3 始基反应(克洛琳德实证后才能定准)和 §B-5 DSL 迁移(audit 完整 lua 集后定准)。

注:LOC 不含 BC dataset 重生成(独立脚本/数据 produce step,见 §B.3)+ §C.1 ADR-0012 PR(docs-only,不进 LOC 计算)。

### 步骤依赖
- ✅ closure spike 已证伪 → A.2 走 enum-based 路线 / B.4 macro 不接 lambda(2026-05-04)
- B.0 实证 modifier 频率统计是 B.3 K_mod 上界前置
- B.1 独立,可先做(简化判定)
- B.2 + B.3 依赖 B.1(modifier 编码 + obs 编码需 Element typed + reaction direction 修正)
- B.3 落地需 BC dataset 重生成(obs schema 变,现有 ckpt 失效)
- B.4 依赖自身顺序对照 spike + Tag.Shield 兼容 spike(closure spike 已不再需要),2 spike 全 PASS 才实施
- B.5 依赖 B.4 spike 结论(P1-A 一致性可调和 → 实施;不可调和 → 推迟/不做)
- §A 与 §B 完全并行(各自 spike + 实施)

## 进入实施之前(前置条件)

- **C.1**(从 Migration 表移到此处)— PR `adr-0012` 改 `Status: ACCEPTED`(docs-only,不进 LOC),作为本 ADR 实施前置任务
- ADR-0019 ACCEPTED
- §A.1 已完成
- ✅ closure spike 已证伪(2026-05-04)— A.2 / B.4 改路线
- B.0 modifier 频率实证统计完成(B.3 K_mod 前置)
- B.4 顺序对照 + Tag.Shield 兼容 spike PASS(B.4 实施前置)
- 始基反应 1 张克洛琳德实证 user 按 acceptance criteria 确认后扩

## 关系

- supersedes-on-implementation ADR-0017(v4 prototype 30 axiom 重写路线)
- supersedes-on-implementation ADR-0018(v5 event-sourcing 局部修补)
- §A 实施基于 `docs/3_plans/cards/dsl_gaps.md`(已 ACTIVE)
- §B 实施参考 `ref/genius-invokation/`(对照 + 反实证)
- ADR-0012(准备技能 / 特技 slot / 抓牌 / 生成骰 builtin)= 本 ADR §A 依赖,需先 ACCEPTED
