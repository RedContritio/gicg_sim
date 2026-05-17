# v1 增量改造 — DSL gap 闭合 + damage/obs 语义增强(保留 v1 自由度)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0019-dsl_v6_semantic_engine.md` at P1-T1)
**Original date:** 2026-05-01
**Original status:** Accepted (de-facto since 2026-05-07 strict ship,P1 时正式标 Accepted)
**Supersedes:** supersede-on-implementation [`../0017-dsl-v4/`](../0017-dsl-v4/)(v4 prototype 30 axiom
重写路线被反思)+ [`../0018-dsl-v5-event-sourcing/`](../0018-dsl-v5-event-sourcing/)(基于 v4 prototype
的局部修补)
**Superseded by:** —

## Why

基于 `dsl_gaps.md` 706 张 cleansed yaml 实证审计 + v1 实测 damage/obs 设计问题 + opus subagent 三轮
评审修订 + `Guyutongxue/genius-invokation` 开源对照实证 + closure spike 证伪 + user 对 strict / engine
ignorance 边界确认。

### 1. v1 是生产引擎,实测覆盖 95%+ 卡池

`gicg_engine/` 主目录是生产 v1(`damage.go` 268 LOC 完整管线 + lua DSL + counter+hook idiom)。`v2/`
是旁路 prototype,从未上线。`dsl_gaps.md`(2026-04-30 706 张 cleansed yaml 审计)实测剩余 gap:★★★
× 2 / ★★ × 1 / ★ × 1。绝大多数原 ★★★ gap 已被 ADR-0012 关闭。

### 2. v1 实测设计问题(本 ADR §B 修正)

- **问题 1**:护盾是 generic counter + `Tag.Shield` 协议;消耗顺序 / 上限 / 穿透绕过全 DSL 自己写
- **问题 2**:`HookDamageReduce` 单一时机混 3 种语义(护盾消耗 / 减伤 buff / 免疫),priority 协商
- **问题 3**:obs 完全不暴露 typed damage 信号(P0-3 漏洞)— RL 看 final dmg 但不知 raw / absorbed / reaction kind
- **问题 4**:`EventContext` 30+ 字段 union over-loaded(本 ADR 不修,FC-2 future)
- **问题 5**:damage 管线 4 阶段不区分 modifier 类型(flat / multiplier / replace / cap)

### 3. 穿透是基础 element 类型,不是 modifier flag

GI 规则:穿透是无视护盾和减伤的物理伤害,不附着不反应。当前 v1 用 `Element + Penetrate bool` 双字段
(冗余)。grep 实测 v1 中 `penetrate=true` 仅 4 处使用点。

### 4. v1 ↔ v6 reference impl 关键对照

`ref/genius-invokation/`(AGPLv3.0,完整官方卡池)对照发现:

- **反应表设计**:`base/reaction.ts:174 LOC` typed 静态映射 `Aura × DamageType → [Aura, Reaction|null]`,
  `DamageType` 含 `Physical / Piercing / Heal` ✅ 验证 §B-1 路线
- **护盾设计**:`builder/entity.ts:528-549` 每护盾 entity 自己注册 `on("decreaseDamaged")` hook;
  builder pattern `shield(N)` 一行打包 = declare counter + 注册 hook + dispose 逻辑;**不是引擎自动
  遍历消耗**。reference impl 反实证 §B-4 早期"引擎自动消耗"路线
- **DSL macro / builder shortcut** 是简化声明的方式,**不替代 hook 自定义路径**

## What

### 核心原则
1. **DSL 表达力自由度保留** — 任意 counter / 任意 hook 时机 / 任意 priority / 任意 modifier 表达力
2. **damage 管线 strict 拆 4+3 阶段**:旧 `HookDamageBoost` / `HookDamageReduce` 删除,DSL 必须 audit
   + 迁移分类(对齐 ref impl modifyDamage0/1/2/3 + 减伤端 strict 拆)
3. **支持 DSL 新增反应** — 反应 typed enum 由 DSL `declare_reaction("X")` 注册得到 ID,engine 0
   hardcode 反应名
4. **引擎不引入"自动消耗"等强规范** — 护盾消耗等行为仍 DSL hook
5. **No-IDs 原则保留** — typed enum 常量由 DSL declare 后 engine 维护反查表

### 完整 strict 流水线(8 hook 时机)

```
HookDamageType         — 元素修改(物理→火附魔等)
  → HookDamageAdd      — 加法增伤
  → HookDamageMul      — 乘法增伤
  → HookReactionDamage — 反应判定 + DSL set_reaction_kind
  → HookDamageReduceBuff — 减伤 buff
  → HookShieldAbsorb   — 护盾消耗
  → HookDamageImmunity — 免疫
  → 扣血
  → HookAfterDamage    — 后置
```

无旧 Boost / 旧 Reduce 兜底。DSL 全部 audit 分类。

### §A — DSL 表达力 gap 闭合

- **A1** `ctx.is_specialty` 启用 — ✅ 已完成
- **A2** `find_char_by_kind(player, KindEnum)` builtin(★★;closure spike 已证伪 2026-05-04 → enum-based)
- **A3** 始基力反应(★★★,DSL only;克洛琳德 ≥ 150 LOC,6 张总 ~400-600 LOC)
- **A4** 调和 hook(★,推迟)

### §B — damage/obs 语义增强(全 strict)

- **B1** `Element.Piercing` 替代 `Penetrate` flag(★★★ 必做;~15 + 6 lua + record format compat ~30)
- **B2** typed Modifier list 带 element 维度(★★★ 必做;per-DealDamage 独立 log + currentDamageLog
  栈;~80 + ~20 subkind)
- **B3** obs 暴露 typed damage event + prepare-skill(★★★ 必做;`recent_damage[K=8]` ring + reaction
  enum DSL declare + prepare-skill skillIdentityMap 反查表;~180 + BC dataset 重生成)
- **B4** 护盾 declare macro(★★ 可选;静态 opts 不接 lambda;~30 + 顺序对照 spike + Tag.Shield 兼容 spike)
- **B5** strict 拆 Boost(4 时机)+ Reduce(3 时机)— 旧 hook 删(★★★;~150 engine + ~200-450 DSL)

### §C — 防御性 / 兼容修订

- **C.1** ADR-0012 status 同步 ACCEPTED(P1-5,docs-only,本 ADR ACCEPTED 前置)
- **C.2** supersedes 关系澄清:用 `supersedes-on-implementation`,本 ADR ACCEPTED 不自动 supersede
  ADR-0017/0018;实施完成 + v4 prototype `gicg_engine/v2/` 删除 + 经验摘要落 `docs/5_history/v4-experience.md`
  后才正式 supersede

## Affected specs

- `engine-dsl` (Element.Piercing / find_char_by_kind / declare_shield macro / declare_reaction registry)
- `engine-damage` (8 hook 时机 strict 拆;旧 Boost / Reduce 删)
- `engine-obs` (recent_damage ring K=8 + typed reaction + Modifier log + prepare-skill 反查表)
- `engine-event` (set_reaction_kind builtin)
