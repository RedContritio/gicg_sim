---
plan: spike_review
status: HISTORICAL
last_updated: 2026-09-14
based_on: ADR-0012 spike (prepare-skill + specialty)
---

# ADR-0012 Spike Review

> **历史审查记录**：本文保留 ADR-0012 spike 当时的结论与待办；当前
> DSL/API 契约以 OpenSpec LIVE spec 为准。

## 验证结果

| 项 | 状态 | 测试 |
|---|---|---|
| 准备技能(歼灭机关 → 高频旋击 → 超速旋击) | ✅ 端到端 PASS | `tests/prepare_skill_spike_test.go` |
| 特技装备(玛薇卡 + 驰轮车·疾驰) | ✅ 端到端 PASS | `tests/specialty_spike_test.go` |
| 槽位 1-card cap(已装备时第 2 张拒绝) | ✅ PASS | 同上 |
| add_dice / draw_card builtin | ✅ work | 同上 |
| invoke_skill_silent + ctx.SkipSkillHooks | ✅ work | prepare 自动触发的超速旋击 |
| 全套 Go 测试零回归 | ✅ PASS | `go test ./gicg_engine/...` |

## 实际 engine 改动量

`git diff --stat HEAD -- gicg_engine/` 净增约 150 行(不含测试):

- `context.go` +9(SkipSkillHooks / IsSpecialty 字段)
- `game.go` +9(Preparing[2] 字段 + 注释)
- `action_execute_other.go` +35(ResolvePreparing 实现 + flipTurn 钩入)
- `interp/builtins_skill.go` +20(invoke_skill_silent + 公共逻辑提取)
- `interp/builtins.go` +60(5 个新 builtin)
- `interp/builtins_card.go` +25(declare_card.slot + 槽位约束 hooks)
- `interp/registry.go` +25(CharSlot enum + CharEntry.SpecialtyCardRef)
- `interp/builtins_char.go` +2(field init)
- `tokenizer_tokens.go` / `tokenizer_maps.go` +20(enum tokens)
- `interp/builtins_enums.go` +5(Slot enum + Weapon Claymore/Catalyst + Tag.Specialty)
- `dsl/audit_test.go` +4(audit allowlist for 新 builtin)

**ADR-0012 工作量估算"中(engine + DSL)"准确**;实际数字与设计文档预期接近。

## 关键发现(写入 ADR followup)

1. **CardRef.Ref 从 0 开始** — `SpecialtyCardRef` 不能用 0 作 sentinel,改用 -1。这跟其他 -1 sentinel(HPCounterID / EnergyCounterID 等)一致。
2. **silent invoke 仍 fire engine canonical hook** — 能量增减 / dice 等核心管道在 silent invoke 时也跑(因为 canonical 不查 SkipSkillHooks)。DSL 写"使用技能后" buff 必须 `if ctx.SkipSkillHooks then return end` 自行 filter,canonical 行为跟真实 GI TCG "不视为使用技能" 不完全一致(canonical 行为是 +能量,真实是 不+能量)。
   - **决策**:此差距属于 ★★ 级,留 followup。当前 silent invoke 的 +1 能量在多数实战场景影响小;真实游戏的"不视为技能"主要影响"使用技能后"buff 触发,后者 DSL 已可 filter。
3. **char-skill 文件不能 `get_card("X")`** — topo 静态扫描把 src 含 `get_card("X")` 的文件标记依赖 `card:X`;X 在 sharedFiles(后载)→ 依赖未满足 → 文件被 silent excluded(无错误)。**约定**:char-skill 文件只引用 char-scope 实体(其他 skill / counter),需要 card 时通过 sharedFiles(talent / event)反向 ref char。
   - **决策**:这是当前 loader 设计的 architectural constraint,玛薇卡的"产手牌选择"机制需要在 sharedFiles 一侧实现(产手牌 buff 卡监听玛薇卡战技 → add_card)。设计 OK。
4. **槽位约束语义** — 真实 GI TCG 的特技装备**不能替换**(已装就不能再装新的);spike 实现按此处理。如未来发现可替换的特技存在,ADR followup 需扩展。
5. **Element.Omni 不应作伤害元素** — 万能元素是 dice color 概念,不是 damage element;spike 用 DiceColor.Omni 给 add_dice,正确。

## 未实现(留 future ADR / 下个 sprint)

- **"使用特技"作为 ActionKind 子类** — spike 仅验证装备 + 槽位约束;真实卡需要 GetLegalActions 把已装备特技列为 BattleAction 候选。需要新 ActionKind 或 declare_skill 加 `is_specialty` 标记。
- **玛薇卡战意系统** — 可变伤害(伤害 = 消耗资源量)+ 自定义充能资源(战意,不获 energy);需要 DSL builtin `consume_all(counter)` 返回值并支持 `deal_damage(target, elem, value=consumed_amount)`。
- **始基力 / 元素改造** — 克洛琳德/失能形态;需要 reactions/ 扩展。
- **选择牌**(玛薇卡战技产 3 张驰轮车选 1) — 需要 engine action `ChooseCard` + GetLegalActions 候选拓展。
- **跨角色资源消耗**(玛薇卡焚曜之环) — 出战状态 hook 已可表达,无需新 primitive,纯 DSL 工作。

## 关于全量(task #12)

**verdict:跳过全量**。理由:
- sqrt(N)=52 张 + 玛薇卡 53 张已暴露 ADR-0012 之外的 ★★★ gap(战意 / 选择牌 / 始基力)— 这些是各自独立机制,需要独立 ADR
- 全量 628 张大概率不会发现新的 ★★★ engine primitive gap,只会增加各 ★★★ 已知机制的实例数(更多带战意角色 / 更多准备技能 / 等)
- 录入主流 4.x-5.x 卡池只需基于已知 gap 写新 ADR(战意 / 选择牌 / 始基力 / 使用特技 action),不依赖更多样本
- 全量 cleansing 成本 ~5h sonnet,投入产出低

## 下一步建议

按 ★★★ 优先级开新 ADR:
1. **ADR-0013:使用特技 action**(GetLegalActions + ActionKind 扩展) — ~小,完成 ADR-0012 闭环
2. **ADR-0014:战意系统**(可变伤害 + 自定义充能资源) — 中
3. **ADR-0015:选择牌机制**(产手牌 + 玩家选择) — 中
4. **ADR-0016:始基力反应**(reactions/ 扩展 + Element 第二维度) — 大

完成上述 ADR 后开始按真实游戏版本(v3.3 → v4.5 → v5.x)分批录入正式 pool。
