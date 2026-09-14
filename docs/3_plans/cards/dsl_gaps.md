---
plan: dsl_gaps
status: HISTORICAL
last_updated: 2026-09-14
based_on: 全 706 raw cleansed yaml(518 action + 138 char + 61 monster) + grep gicg_engine/interp 全 builtin
supersedes: 2026-04-28 PM 版(基于 sqrt(N)=52 张样本,4 个 ★★★ 已被 ADR-0012 closed 但未更新)
---

# DSL 覆盖力缺失分析(re-audit 2026-04-30)

> **历史快照**：本文保留 2026-04-30 的全量审计结论。当前 DSL 契约
> 以 `openspec/specs/engine-dsl/` 和 `openspec/specs/engine-runtime/`
> 为准；文中的 ACTIVE/CLOSED 是当时状态。

对照当时的 DSL API 文档（现已迁入 `openspec/specs/engine-dsl/`）和
`CLAUDE.md` API 块,
basis 已从 sqrt(N) 升级为全 706 张 cleansed + 全 builtin grep 实证。

按优先级 ★ 排序。

**re-audit 主要变化(2026-04-30)**:

- ADR-0012 落地后 4 个原 ★★★ 已 **CLOSED** — 准备技能 / 特技 slot / 抓牌 / 生成骰
- ctx.element setter ★★ → **CLOSED**(`proxies_ctx.go:84` SetField 已支持,只缺文档)
- add_aura / add_shield builtin ★★ → **NOT NEEDED**(counter-based 是 idiomatic 表达)
- 装备槽唯一性 ★★ → **CLOSED**(builtins_card.go:170-188 enforce + Tag.Equip)

**新发现真 ★★★**: `ctx.is_specialty` 字段未启用(IsSpecialty 字段定义存在,
但 `invoke_skill_silent` 没赋值,DSL 无法判别特技伤害)。详见 §C.

参考: 全量句频次见 [`effect_pattern_frequency.md`](./effect_pattern_frequency.md)、
DSL 现状汇总见 [`dsl_capabilities_audit.md`](./dsl_capabilities_audit.md)。

---

## A. 资源 / 数值系统

### A1. 夜魂值(Nightroul) ✅ NO ENGINE CHANGE NEEDED

**Evidence**: 希诺宁(`character/505321`)、刃轮装束 / 高速腾跃(术语) / 驰轮车·疾驰(`action/505460`)。

**机制**: 角色装备特定状态(如刃轮装束)后获得「夜魂加持」,可累积**最多 2 点**夜魂值。
技能 / 特技消耗夜魂;为 0 时弃装备 + 结束加持。

**当前 DSL 表达**: `declare_counter("夜魂", Scope.Self, 0, {min=0, max=2})` + buff DSL ownership
+ `on_after_write` 监听归零弃装 + `on_card_play` filter 装备牌 — 全 counter+hook 表达,无 engine 改。

**剩余工作**: 纯 DSL 写,无 builtin 缺失。**user 自治 priority**(玛薇卡时代角色集中爆发后再写)。

---

### A2. 始基力 / 形态(arche) ★★★

**Evidence**: 克洛琳德(`character/503960` 标 "始基力:荒性")、攻坚特化型机关·荒(500549)、
陆行岩本真蕈(6628)、失能形态(术语)、陆地优势(术语)。

**全量频次** (effect_pattern_frequency.md):
- `受到具有「TERM」的角色造成的伤害后：此角色转换为「TERM」失能形态：...` × 6
- `「TERM」处于「TERM」时无法使用原本的技能,只能使用「TERM」的技能` × 6
- `「TERM」下的技能不会造成元素伤害,只能造成物理伤害` × 6
- `角色受到火元素伤害后,转换为枯焦状态` × 4
- `角色受到雷元素伤害后,转换为活化状态` × 4

**当前 DSL 表达**: 形态 counter ✓ + `on_after_damage` 切形态 ✓ + 反应判定 ✗

**Gap**: 始基力反应(荒+芒湮灭等)不在现有 reactions/ 清单。

**🔑 设计原则(2026-04-30 user 指示)**: **始基力反应按需启用,不入全局 system/reactions/**。
当前 `data/system/reactions/{冻结,超导,蒸发,感电,融化,结晶,解冻,超载}.lua` 是 pool-agnostic
全局加载,任何卡都可触发。**始基反应不应这样**:

- ✅ 方案 A(buff-style ownership):始基反应 hook 写在涉及该机制的 character 文件里
  (攻坚机关·荒 / 克洛琳德 / 陆行岩本真蕈),declare 自己的 `on_reaction_damage` /
  `on_after_damage` filter,跟 [`feedback_buff_owns_effects`](../../) 一致。
- 若 N 角色重复,后续抽 shared module(`local arche = require("arche/失能形态")` 风格的
  lazy import),仍由 character 文件触发 require — 不入 `data/system/`。

**实现路径**: 参考现有 `data/system/reactions/结晶.lua` 写法(counter+hook 模式),
但 owner 是 character 文件而非 system/。

**结论**: 不需要 engine 改;需要 DSL 文件 + 设计 owner 边界(角色端 require 模式)。

---

## B. 准备技能(Prepare Skill) ✅ CLOSED — ADR-0012

**Evidence**: 高频旋击 → 超速旋击(术语,`character/501447 歼灭特化型机关` 用)、
准备技能(总术语,3 张引用)、镀金旅团·沙中净水(`monster/500595`)。

**已落地 builtin** (gicg_engine/interp/builtins.go):
- `set_preparing(player, skill_id)` — 把 skill 入队,turn flip 时自动 invoke
- `get_preparing(player)` — 查 player 准备中的 skill_id
- `clear_preparing(player)` — 清空(冻结等打断时用)
- `invoke_skill_silent(skill_id)` — 跑 skill effect 但不触发 `on_skill_use` 后续

**spike test**: `gicg_engine/tests/prepare_skill_spike_test.go` ✓

**剩余工作**: DSL 文件实现具体卡的 prepare 逻辑(机关怪 / boss 卡)。无 engine 改。

---

## C. 特技(Specialty)系统

### C.1 slot 约束 ✅ CLOSED — ADR-0012

`builtins_card.go:170-188` 实现:
- `Slot.Specialty` 卡 declare 时记录 slot
- `on_action_check` reject 重复 specialty 装备(per-char,1 件)
- `on_card_play` 记录 slot 占用

`Tag.Specialty=8` + `Slot.Specialty=3` 在 enum 中可用。

### C.2 invoke_skill_silent ✅ CLOSED — ADR-0012

特技调用走 `invoke_skill_silent` 即不触发 `on_skill_use` 后续。

### C.3 ctx.is_specialty 未启用 ★★★ **真 gap**

**evidence**: `gicg_engine/context.go:79-83` 定义了 `IsSpecialty bool` 字段(注释说"下游 hook
可 if ctx.IsSpecialty then return end 跳过"),**但 grep 全 engine 无任何赋值点**:

```
$ grep -rn "IsSpecialty\b" gicg_engine/
context.go:79-83:    定义 + 注释
(无其他)
```

且 `proxies_ctx.go` 的 `GetField` switch case **没列 "is_specialty"** — DSL 通过
`ctx.is_specialty` 读会返回 nil。

**影响**: 特技伤害 "不视为角色造成的伤害" 这条规则,DSL 当前无法判别。
玛薇卡时代 ~30 张相关卡受影响。

**修复**:
- engine: `invoke_skill_silent` 设 `ctx.IsSpecialty=true`(或对应 EventContext 字段)
- DSL: `proxies_ctx.go` GetField 加 `case "is_specialty": return ctx.IsSpecialty`

**工作量**: 2 行 engine 改 + 1 行 proxy 改 + 1 个 spike test。**优先级 ★★★**。

### C.4 disable 条件(冻结/石化/眩晕)

`on_action_check` 已可扩,无 engine 改。结合现有 frozen.lua 模式即可。

---

## D. 操作牌堆 / 资源生成

### D1. 抓 N 张牌 ✅ CLOSED — ADR-0012

`draw_card(player, n?)` 在 `builtins.go:218-229` 已有,默认 n=1。

### D2. 生成元素骰 ✅ CLOSED — ADR-0012

`add_dice(player, color_idx, n)` 在 `builtins.go:119-132` 已有。
color_idx 用 `DiceColor.{Fire,...,Omni}` enum。

evidence(全量):
- `生成N个ELEM元素骰` 直接 `add_dice(player, DiceColor.<X>, N)`
- `生成N个万能元素骰` → `add_dice(player, DiceColor.Omni, N)`
- `投掷阶段:总是投出N个ELEM元素骰和N个ELEM元素骰` × 12 — 这是 fix_dice 配置非 effect

### D3. 调和(Tune)hook ★

**Evidence**: 桓那兰那(`6603` 应在效果里有"调和此牌时")、`5488_换班时间`。

**全量频次**: ~3-5 张涉及。

**当前 DSL**: 无 `on_tune` hook。

**结论**: 用例少,可推迟。需新 hook,小工作量。

---

## E. 反应附加效果

### E1. 结晶 → 护盾 ✅ NO BUILTIN NEEDED

**误判修正**: 旧 dsl_gaps 标 "需 add_shield builtin"。实际 `data/system/reactions/结晶.lua` 已有完整实现(counter-based + on_damage_reduce hook):

```lua
local 结晶护盾 = declare_counter("结晶护盾", Scope.PerPlayer, 0, { min = 0, max = 10, tag = Tag.Shield })
on_reaction_damage(function(ctx)
  ...
  defer_fn(function() 结晶护盾:add_at(actor, 1) end)
end)
on_damage_reduce(function(ctx)
  local shield = 结晶护盾:get_at(ctx.target_player)
  ...
end)
```

shield 是 counter+Tag.Shield+hook 模式,不是 builtin。**当前 DSL 已表达**。

### E2. 扩散反应 ✅ COVERED

`reactions/` 已实现(memory `project_e2e_test_scenario` 提到蝶舞用例)。

---

## F. 元素改造 / 伤害类型转换 ✅ CLOSED — 已支持

**误判修正**: 旧 dsl_gaps 假设 ctx 可能 read-only。实际 `proxies_ctx.go:84` SetField 已实现:

```go
case "element":
    v, _ := ToInt(val)
    ctx.Element = engine.Element(v)
```

DSL 可在 `on_damage_boost` 内 `ctx.element = Element.Geo`。

**剩余工作**: API 文档 list `ctx.element` 是可写字段。无 engine 改。

evidence: 刃轮装束(`物理伤害变为岩元素`)、万众瞩目(`物理变水`)— 直接 set 即可。

---

## G. 状态形态机

### G1. 元素生命(总附着 + 免疫) ✅ NO BUILTIN NEEDED

**误判修正**: 旧 dsl_gaps 假设 `add_aura` builtin。实际 `data/system/element.lua` 已用 counter:

```lua
local attached_fire = declare_counter("火元素附着", Scope.PerChar, 0, { min = 0, max = 1 })
```

总附着 → `on_round_start` 内 `attached_water:set_at(p, c, 1)` 即可。
免疫 → `on_damage_reduce` filter `ctx.element` + `ctx.value = 0` cancel。

shield-style counter+hook 已是 idiomatic。**当前 DSL 已表达**。

### G2. 出战状态 vs 角色状态 ✅ COVERED

`Scope.ActiveStatus` ✓ vs `Scope.Self` ✓。

---

## H. 目标选择 / 智能 Target ★★

**Evidence**:
- 万众瞩目("受伤最少的我方角色")
- 追踪爆弹("切换到的角色")
- 部分召唤物("敌方场上随机一名")

**当前 Target enum** (builtins_enums.go:67-70): `EnemyActive / EnemyAll / OwnAll /
EnemyNonActive / OwnActive / CardTarget` — **仅 6 个**。

**缺**:
- `Target.OwnLowestHp` / `Target.EnemyLowestHp`(选最低血,治疗 / 召唤物)
- `Target.OwnLeastDamaged`(万众瞩目 — 受伤最少)
- `Target.EnemyRandomNonActive`(随机后台,部分召唤物)
- `Target.PreviousActive`(切换 trigger,追踪爆弹)

**或者** `find_char(predicate)` 通用 builtin(更灵活,DSL 可写谓词)。

**Verdict**: ★★ — 多张召唤物 / 治疗卡受影响。preferred:**find_char(predicate)** 一次到位,
而非给每个 case 加 enum。

---

## I. 触发频次 / 资源重置

### I1. 每回合 N 次 ★ DX

**全量频次**: `（每回合N次）` 后缀 × 176(top-2 高频),`（每回合至多N次）` × 6,`(每回合N次)` × 5 等。

**当前 DSL**: counter + `on_round_start` 手动 reset,**已可表达**。

**Idea**: `declare_card(name, dices, {per_round_uses=N})` 自动注入 reset hook。

**结论**: 纯 DX 改进。手写不阻塞。优先级低。

### I2. 料理:每回合每角色 1 次 ✅ COVERED

`Tag.Food` counter 群 + `get_counter_group(Tag.Food)` 已支持。

---

## J. HP 上限 / 多召唤物 ✅ COVERED

`declare_char(name, {hp=12, ...})` 参数化 hp ✓。`Tag.Summon` 无数量限制 ✓。

---

## K. 跨卡引用 / 装备槽 ✅ CLOSED

### K1. 装备唯一性(武器 / 圣遗物 / 天赋)

`Tag.Equip` + DSL filter 已 enforce("最多装备 1 件武器/圣遗物/天赋")。

### K2. 特技槽(每角色 1 张) ✅ CLOSED — ADR-0012

见 §C.1。

---

## 总结:必修(★★★)清单(2026-04-30)

| Gap | 工作量 | 阻塞性 | 责任方 |
|---|---|---|---|
| **C.3 ctx.is_specialty 启用** | 极小(2 engine + 1 proxy + 1 spike) | 玛薇卡时代 ~30 张特技伤害卡 | engine + proxy |
| **A2 始基力反应**(buff-owned,不入 system/) | 中(每角色 1 个 lua 文件 + 共享 arche util) | 6 张攻坚机关 / 克洛琳德 / 陆行岩本真蕈类 | DSL only |

## 重要(★★)清单

| Gap | 责任方 |
|---|---|
| **H Target 扩展 / find_char(predicate)** | engine builtin |
| (per_round_uses 封装) | DSL DX,可推迟 |

## 可推迟(★)清单

| Gap | 责任方 |
|---|---|
| D3 调和 hook | engine + DSL |

## 已 CLOSED(2026-04-30 audit 修订)

| 原标记 | 实际 |
|---|---|
| B 准备技能 ★★★ | ADR-0012 ✅ |
| C.1 特技 slot ★★★ | ADR-0012 ✅ |
| C.2 invoke_skill_silent ★★★ | ADR-0012 ✅ |
| D1 抓牌 ★★★ | ADR-0012 ✅ |
| D2 生成骰 ★★★ | ADR-0012 ✅ |
| A1 夜魂值 ★★★ | counter+hook 已可表达,无 engine 改 |
| F 元素改造 ctx.element setter ★★ | proxies_ctx.go:84 已支持 |
| E1 结晶 → 护盾(add_shield 误判) | counter+hook 是 idiomatic,无 builtin 缺 |
| G1 元素生命(add_aura 误判) | counter+hook 是 idiomatic,无 builtin 缺 |
| K1 装备槽唯一性 | Tag.Equip + DSL filter 已 enforce |

## 后续

1. **C.3 IsSpecialty 启用**(0.5 day):写 spike test 验证,然后 1 行 engine + 1 行 proxy 改即可
2. **H Target 扩展 / find_char**(1 day):design + impl
3. **A2 始基力反应**(1-2 day per 角色):按 character 文件 owner,N 个角色后再抽 shared util
4. 自动化 parser 实跑(`docs/3_plans/cards/dsl_capabilities_audit.md` §G)校准前述 ★★★ 实际优先级
