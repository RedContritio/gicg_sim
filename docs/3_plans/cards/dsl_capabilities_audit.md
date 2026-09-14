---
plan: dsl_capabilities_audit
status: HISTORICAL
last_updated: 2026-09-14
based_on: 全 706 张 raw cleansed yaml(518 action + 138 character + 61 monster) + tools.audit_effect_patterns 全量 normalize
---

# DSL 能力 audit + effect 自动化可行性评估

> **历史审计快照**：统计与路径记录 2026-04-30 的 706 条来源。当前
> DSL 契约见 `openspec/specs/engine-dsl/`；最新官方内容流程见
> [`native_content_curriculum.md`](native_content_curriculum.md)。

精化 [`dsl_gaps.md`](./dsl_gaps.md) 的 ★★★ 清单。dsl_gaps 基于 sqrt(N)=52 张样本估算,
本 audit 基于全量 717 cleansed yaml 实证 + 当前 builtin 现状对照。

新发现:**dsl_gaps 标 ★★★ 必修的 5 个 gap 中,4 个已被 ADR-0012 实际落地**(spike PASS
后 builtin 入仓但 dsl_gaps.md 未更新)。本文给出现状清单 + 真正剩余 gap。

---

## A. 当前 DSL builtin 完整清单(2026-04-30)

来源:`gicg_engine/interp/builtins.go` + `builtins_*.go` + `registry.go`。

### A.1 Counter / declare API

| builtin | 签名 | 备注 |
|---|---|---|
| `declare_counter(name, scope, init?, opts?)` | core | 创建命名 counter; min/max/tag/display 等 opts |
| `create_counter(...)` | alias of declare_counter | |
| `get_counter(name, scope?)` | | 命名 lookup,跨文件复用 |
| `get_counter_group(tag)` | | tag 群批量返回 |
| `register_on_tag_write(tag, fn)` | | tag 群通配 write hook |

### A.2 Char / Skill / Card API

| builtin | 备注 |
|---|---|
| `declare_char(name, opts?)` | hp / energy_cap 参数化 |
| `bind_char(name, player, char_idx)` | 把命名 char 绑到 slot |
| `get_char(name)` | |
| `declare_skill(name, opts?)` | cost / energy_delta / type 等 |
| `get_skill(name)` | |
| `invoke_skill(skill_id)` | 触发完整 hook 链 |
| `invoke_skill_silent(skill_id)` | **ADR-0012**: 不触发 on_skill_use |
| `set_preparing(player, skill_id)` | **ADR-0012**: 准备技能 |
| `get_preparing(player)` | **ADR-0012** |
| `clear_preparing(player)` | **ADR-0012** |
| `declare_card(name, dices, opts?)` | opts 含 `slot=Slot.Specialty/Equip/Support` (ADR-0012) |
| `get_card(name)` | |
| `add_card(ref, zone)` | 加卡到 hand/deck |
| `draw_card(player, n?)` | **ADR-0012**: 抽牌 N 张 |
| `add_dice(player, color_idx, n)` | **ADR-0012**: 生成元素骰 |

### A.3 Action / Combat API

| builtin | 备注 |
|---|---|
| `deal_damage(target, element, value)` | 进伤害 pipeline |
| `heal(target, value)` | |
| `defer_fn(fn)` | 延后 hook 链结束后执行 |
| `get_active_char()` / `set_active_char(...)` / `get_next_char()` | |
| `context_player()` | 当前 hook 触发 player |
| `force_switch_next()` | 强制切下个角色 |
| `cancel()` | 中断当前 action |
| `gain_energy(proxy, n)` / `consume_energy(proxy, n)` | |
| `set_alive(p, c, alive)` | |
| `request_switch(player)` | 排队 switch action |
| `set_winner(w)` | 强制结算 |
| `has_card_in_own_hand(card_ref)` | **限当前 context player 自己 hand**,跨方查询禁止 |

### A.4 Dice / Cost API

| builtin | 备注 |
|---|---|
| `roll_dice(player, n)` | |
| `clear_dice_pool(player)` | |
| `get_dice_count(player, color)` | |
| `cost_mod(ctx, slot, delta)` | mutate ctx.Cost(自动登记 hook id) |
| `cost_total(ctx)` | gate consume-aware discount |
| `was_applied(ctx, hook_id)` | 判 cost_mod 是否触发,用于 charge consumption |

### A.5 Hook 注册(24 个 hook 类型)

| hook | 触发时机 |
|---|---|
| `on_damage_boost(prio?, fn)` | 伤害管道:加伤前 |
| `on_reaction_damage` | 反应触发时 |
| `on_damage_reduce` | 伤害管道:减伤(护盾) |
| `on_after_damage` | 伤害结算后 |
| `on_before_heal` / `on_after_heal` | |
| `on_before_energy_gain` / `on_after_energy_gain` | |
| `on_before_energy_consume` / `on_after_energy_consume` | |
| `on_action_check` | action 合法性 gate |
| `on_action_prepare` | action 进入准备阶段 |
| `on_skill_use` | 技能使用后 |
| `on_card_play` | 卡牌打出后 |
| `on_switch` | 角色切换 |
| `on_before_turn_flip` | turn 翻面前 |
| `on_round_start` / `on_round_end` | 回合首/末 |
| `on_round_end_post_summon` / `on_round_end_decay` / `on_round_end_final` | 末阶细分 3 段 |
| `on_death` / `on_revive` | |
| `on_before_write` / `on_after_write` | counter write hooks |

### A.6 Enum

| enum | 值 |
|---|---|
| `Element` | None / Fire / Ice / Water / Electro / Geo / Anemo / Dendro / Physical |
| `Scope` | Self / ActiveStatus / PerChar / PerPlayer / Global |
| `Tag` | Summon / Element / Equip / Food / Support / Shield / Dice / **Specialty(8)** |
| `DiceColor` | Fire-Dendro + Omni |
| `CostSlot` | Fire-Dendro + Match / Any / All |
| `Target` | EnemyActive / EnemyAll / OwnAll / EnemyNonActive / OwnActive / CardTarget(**仅 6**) |
| `Source` | Skill / Card / Status / Summon / Support / Reaction |
| `Slot` | None / Equip / Support / **Specialty(ADR-0012)** |
| `Weapon` | None / Sword / Polearm / Bow / Claymore / Catalyst |

### A.7 system/ 目录

`data/system/{alive,dice,draw,element,equip,food,frozen,reaction,round,timeout}.lua` +
`data/system/reactions/{冻结,超导,蒸发,感电,融化,结晶,解冻,超载}.lua`(8 个反应)。

---

## B. effect 全量 pattern frequency(evidence)

详见 [`effect_pattern_frequency.md`](./effect_pattern_frequency.md)(自动生成,
script: `tools/audit_effect_patterns.py`)。

**关键统计**:

- effect_text blocks: 1348(action.main + char.skills/.summons/.talent + monster.skills/.summons)
- 句子总数(中文。/换行/分号 split): 3245
- 去重 normalized pattern: 1469

**top-10 pattern 覆盖 32.9% 句子,但**:

- 4 条是 **metadata**(`战斗行动:...装备此牌` / `（每回合N次）` / `（牌组中包含...才能加入牌组）` / `可用次数:N`),不需要 effect 实现
- 3 条是 **核心 deal_damage / heal**(物理 137 / 元素 122 / 结束阶段元素 45),已有 builtin
- 1 条是 **HTML 残留 bug**(`" class="wiki-note-text">` 52 句,见 §E)
- 1 条是 **slot meta**(`角色最多装备N件「TERM」` 40),已有 enforce 机制
- 1 条是 **武器 restrict**(`「TERM」角色才能装备` 39),已有 `requires_weapon`

**真正可严格 white-list 自动化的 effect-level pattern**(第一波最小集):

| 句式 | 频次 | DSL emit |
|---|---|---|
| `造成N点物理伤害` | 137 | `deal_damage(target, Element.Physical, N)` |
| `造成N点ELEM元素伤害` | 122 | `deal_damage(target, Element.<X>, N)` |
| `结束阶段：造成N点ELEM元素伤害` | 45 | `on_round_end(...) deal_damage(...)` |
| `角色造成的伤害+N` | 24 | `on_damage_boost(...) ctx.value += N` |
| `结束阶段：造成N点ELEM元素伤害，治疗我方出战角色N点` | 5 | combo |
| `治疗目标角色N点` | 3 | `heal(Target.CardTarget, N)` |
| `结束阶段：治疗所有我方角色N点` | 3 | on_round_end + heal_all |

合计 ~340 句(占 3245 的 ~10.5%)。

**metadata-level 自动化覆盖**(declare_card opts 一次到位):

| 句式 | 频次 | declare_card opt |
|---|---|---|
| `战斗行动：我方出战角色为CHAR时...` | 191 | `requires_char=CHAR + battle_action=true` |
| `（每回合N次）` | 176 | `per_round_uses=N`(需新增) |
| `（牌组中包含CHAR，才能加入牌组）` | 145 | `deck_constraint=CHAR` |
| `可用次数：N` | 119 | `uses_counter=N`(已有 pattern,统一封装) |
| `（角色最多装备N件「TERM」）` | 40 | slot meta(已 enforce) |
| `（「TERM」角色才能装备` | 39 | `requires_weapon=X` |
| `快速行动：装备给我方的CHAR` | 14 | `fast_action + requires_char` |
| `投掷阶段：总是投出N个ELEM元素骰...` | 12 | `fix_dice=[...]` |
| `投掷阶段：N个元素骰初始总是投出ELEM元素` | 7 | partial fix dice |
| `持续回合：N` | 10 | `duration_rounds=N` |

合计 ~750 句 metadata。**几乎所有装备/天赋/支援卡有这一类 prefix/suffix**,
declare_card opts 全自动覆盖。

---

## C. dsl_gaps re-evaluation(2026-04-30)

dsl_gaps.md ★★★ 必修清单 5 项,实际状态:

| dsl_gaps 标记 | 实际现状(grep builtins.go) | 状态 |
|---|---|---|
| **B. 准备技能** `skip_turn / invoke_skill_silent` | `set_preparing / get_preparing / clear_preparing / invoke_skill_silent` 全有(ADR-0012) | ✅ **CLOSED** |
| **C. 特技系统** slot 约束 + silent invoke + 特技伤害 flag | `Slot.Specialty=3` + `Tag.Specialty=8` + `invoke_skill_silent` 全有(ADR-0012);`is_specialty` 伤害 flag 待 audit | 🟡 **70% CLOSED**(伤害 flag 未确认) |
| **D1. 抓牌** `draw_card(player, n)` | `draw_card(player, n?)` 已有 | ✅ **CLOSED** |
| **D2. 生成骰** `add_dice(player, element, n)` | `add_dice(player, color_idx, n)` 已有 | ✅ **CLOSED** |
| **A1. 夜魂值** | 纯 DSL counter(无 engine 改),已可表达 | ✅ **CLOSED** (待人写) |

**真正剩余 ★★★ gap**(从 effect 全量数据看):

### C.1 始基力反应(adr-0016 ?) — 监管中

`data/system/reactions/` 含 8 个标准反应(冻结/超导/蒸发/感电/融化/结晶/解冻/超载),
**不含**始基力相关反应(荒+芒湮灭 → 物理化等)。

evidence:
- `（角色受到火元素伤害后，转换为枯焦状态）` × 4
- `（角色受到雷元素伤害后，转换为活化状态）` × 4
- `「失能形态」下的技能不会造成元素伤害，只能造成物理伤害` × 6
- `受到具有「TERM」的角色造成的伤害后：此角色转换为「TERM」失能形态：...` × 6

涉及 character: 攻坚特化型机关·荒(500549)、克洛琳德、陆行岩本真蕈(6628)等。

**需:** `data/system/reactions/失能形态.lua` + 形态切换的 `on_damage_boost`。

### C.2 Target 扩展 — ★★ 提至 ★★★

dsl_gaps H 节标 ★★。effect 全量数据看实际频次相对低(<10 句),但**召唤物 / 治疗大量**用:

- `治疗我方出战角色`(已有 OwnActive 覆盖)
- `对所有敌方后台角色造成N点穿透伤害`(EnemyNonActive 已有)
- `受伤最少的我方角色`(万众瞩目)— **缺 LowestHp / LeastDamaged**
- `随机一名敌方后台角色`(部分召唤物)— **缺 EnemyRandomNonActive**

**需:** `Target.OwnLowestHp` / `Target.EnemyLowestHp` / `Target.OwnLeastDamaged` /
`Target.EnemyRandomNonActive`。或者 `find_char(predicate)` 通用 builtin。

### C.3 元素改造(伤害类型转换)— ★★

dsl_gaps F 节。effect 数据:`物理伤害变为ELEM元素`(刃轮装束 / 万众瞩目)。
当前 `on_damage_boost` 内 `ctx.element = X` 是否 setter — **需 audit ctx proxy 写权限**。
若已支持,只是文档缺;若 read-only,需扩 ctx_proxy。

### C.4 cost_mod 多对手 / 跨技能场景 — ★

`对角色打出「TERM」或角色使用技能时：少花费N个ELEM元素` × 14,
现 `cost_mod / cost_total / was_applied` 三件套覆盖,但**多卡协同 charge consumption**
模式还需 audit DSL 实例(月桂的宝冠 / 天空之卷等天赋)。

### C.5 食物轮换 — DX

`（每回合每个角色最多食用N次「TERM」）` × 14。`Tag.Food` 已有,需统一封装
`per_round_per_char` 重置 hook。纯 DX,不阻塞。

---

## D. 自动化可行性 — 卡牌级覆盖率预估

按 effect_text 是否能由白名单 pattern 完全覆盖,把卡分桶:

### D.1 假设白名单(初版)

emit DSL 的句式集合(strict regex / PEG):

- vanilla(空 effect / 仅 metadata)
- `造成N点{物理|ELEM元素}伤害`
- `结束阶段：造成N点ELEM元素伤害`
- `结束阶段：治疗{我方出战角色|所有我方角色}N点`
- `治疗{目标角色|我方出战角色}N点`
- `角色{使用「TERM」}?造成的伤害+N`(限 element-agnostic / element-specific 分两条)
- `召唤CARD`(仅 zero-arg summon ref)
- `生成N个ELEM元素骰` / `生成N个万能元素骰`
- `抓N张牌`
- `获得N点充能`

加上**所有 metadata 句**(战斗行动 / 装备 / 牌组约束 / 可用次数 / 持续回合 / 快速行动 / 投掷阶段 fix dice / 角色最多装备 / 才能装备)。

### D.2 卡级覆盖率(预估,需跑实际 parser 后再校准)

| 卡类型 | 估算 auto / total | 备注 |
|---|---|---|
| **天赋牌**(metadata-heavy) | ~60% / ~190 张 | restriction + battle_action + 1 句简单 boost |
| **元素共鸣**(标准 cost + draw/add_dice) | ~80% / ~14 张 | 简单 DSL 一致 |
| **武器**(damage boost 或 charge consumption) | ~30% / ~50 张 | 简单的 +N damage 可,charge consumption 需手 |
| **圣遗物**(cost discount / per-round) | ~25% / ~30 张 | cost_mod 模式手写更安全 |
| **简单事件牌**(治疗 / 抓牌 / 生成骰) | ~40% / ~80 张 | 单句基础动词 |
| **复杂事件 / 食物 / 支援**(状态附加 / 跨卡引用) | ~10% / ~150 张 | 多数 manual |
| **召唤物**(每回合伤害 / 减伤) | ~50% / ~200 张 | `结束阶段:造成N点ELEM伤害` 模板高频 |
| **角色普攻 / 战技**(标准 cost + 标准 damage) | ~70% / ~410 张 | cost 已 templated;effect 多数是 deal_damage 单句 |
| **角色爆发**(复杂多段效果) | ~20% / ~138 张 | 多句 / 召唤 / 状态附加 |
| **monster 技能** | ~30% / ~180 张 | 形态切换 / 始基反应需 manual |

**整体粗估**: 30-40% 卡可由 strict white-list 完全自动转 + emit 完整 Lua;剩 60-70% 必须 manual。

合理执行序:

1. **白名单 parser 实现**(1 周) → 实际跑出 auto/manual 分布,校准上表估算
2. **手写 manual 卡时,聚合 fail pattern**(每 10-20 张 audit 一次)→ 反向扩 white-list
3. 闭环到 60-70% auto / 30-40% manual

---

## E. HTML strip bug(发现于 audit 中,**需修**)

**症状**: 31 张 cleansed yaml 的 `effect_text` 含 `" class="wiki-note-text">` 残留,
共 52 个出现位置(top-7 pattern)。

例:
```
data/cleaned/action/6323_荒泷第一.yaml:
  装备有此牌的荒泷一斗每回合第2次及以后使用喧哗屋传说时：如果触发乱神之怪力所附属角色进行重击时：造成的伤害+1物理伤害。" class="wiki-note-text">。
```

raw HTML pattern:`<u>X</u><sup class="wiki-sup">[详情]</sup></span>...` 嵌套时
data-name 属性的尾 `"` + `class="wiki-note-text">` 进了 text content。

**根因**: lxml `text_content()` 在某些 wiki 嵌套(`<span data-type="详情" data-name="...">[详情]</span>` 紧随 `<u>` 块)下,把 `data-name` 属性 quote 误归为文本。

**影响**:
- effect_text 不可读,自动化 parser 必 fail
- 但 **effect_html / term_refs / terms 字典** 不受影响(用 lxml attribute 解析)
- 不阻塞 metadata 自动化(metadata 字段都不依赖 effect_text)

**修复方向**(下次 cleansing patch 时修):
- `tools.cards.html_utils.html_to_multiline_text` 在 lxml `text_content()` 前先 strip `<sup>` 元素(避免 detail-tooltip 周围 attribute leak)
- 或 escape 处理 `<u>...[详情]</u>` 整块

**31 张待修清单**: `grep -l "wiki-note-text" data/cleaned/*/*.yaml`

不本 audit 阻塞,可作单独 patch session 处理。

---

## F. 落地建议(优先级)

### F.1 立即可做

1. **修 dsl_gaps.md**:把 ★★★ 准备技能 / 特技 / 抓牌 / 生成骰 / 夜魂值标 ✅ CLOSED
2. **跑 strict-pattern parser 第一版**(1-2 day):覆盖 §D.1 白名单,出 `data/pools/v3.3/cards/<NAME>/main.lua` 的 metadata 部分 + 简单 effect 部分
3. **flag HTML strip bug**(本文 §E 已 flag,留下次 cleansing patch)

### F.2 短期 ADR(支撑 50%+ 自动化)

| ADR | 内容 | 依赖 effect 频次 |
|---|---|---|
| ADR-0013(草稿)使用特技 | `is_specialty=true` 伤害 flag(C 节余项) | ~30 张玛薇卡时代相关 |
| ADR-0014 Target 扩展 | `Target.OwnLowestHp / EnemyLowestHp / OwnLeastDamaged / EnemyRandomNonActive` 或 `find_char(pred)` | 召唤物 + 万众瞩目类 |
| ADR-0015 元素改造 setter | `ctx.element = X` 在 `on_damage_boost` 内可写 | ~10 张刃轮装束 / 万众瞩目 |
| ADR-0016 始基力反应 | `data/system/reactions/失能形态.lua` + 形态切换 hook | ~6 张攻坚机关 / 克洛琳德 |

### F.3 长期 / 锦上添花

- per-round / per-round-per-char 频次 builtin 封装(纯 DX,~14+176 句受益但已可手写)
- food rotation 标准模式(已可表达,缺 sugar)

---

## G. 接下来执行序(建议)

1. 跑 strict-pattern parser 原型 → 校准 D.2 的卡级覆盖率估算(避免做 ADR-0013/14/15/16 前过度投入)
2. 选 1-2 张全 metadata 卡(如「悠古的磐岩」)走通 `data/pools/v3.3/{cards,characters}/...` 录入 → 验证 cfg `pool="v3.3"` 训练 load
3. 根据 parser 实际产出排 ADR-0013/14/15/16 优先级 + 修 dsl_gaps.md

不再依赖 sqrt(N) 估算,本 audit 与 effect_pattern_frequency.md 是 evidence base。
