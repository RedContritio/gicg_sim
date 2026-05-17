# Specialty + prepare-skill — DSL / engine extension

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0012-specialty_and_prepare_skill.md` at P1-T1)
**Original date:** 2026-04-28 PM (accepted 2026-05-07)
**Original status:** Accepted (spike PASS + builtin shipped in `interp/builtins_adr0012.go`)
**Supersedes:** —
**Superseded by:** —

## Why

sqrt(N)=52 张样本扫描发现 5 个 ★★★ DSL gap。本 ADR 聚焦两个最阻塞的:

1. **特技(Specialty)**:玛薇卡时代核心机制(4.x 后半起),装备牌附带子技能,角色级 1 槽,使用算
   战斗行动但不算技能
2. **准备技能(Prepare Skill)**:歼灭机关 / boss 怪类机制,跨多个行动轮触发,跳过 turn,不触发
   on_skill_use 后续

剩余 ★★★ 中 D1(`draw_card`) / D2(`add_dice`) 都是 builtin export,顺路一起做。A1(夜魂)是 DSL
复杂度,无 engine 改,留 DSL 编写阶段。

## What

- **D1 EventContext 扩展** — `engine.EventContext` 加 `IsSpecialty bool`(frame 是特技调用,hook 可
  filter)+ `SkipSkillHooks bool`(silent invoke / prepare resolve 设置,FireEventHooks 检查跳过
  on_skill_use 但仍跑 skill effect 本身)
- **D2 特技槽 — counter group** — 新增 `Tag.Specialty` + `Slot.Specialty`;`declare_card(... { slot
  = Slot.Specialty, requires_char = ... })`;引擎层强制 1-card 上限
- **D3 Silent invoke** — 新 builtin `invoke_skill_silent(skill_id)`:与 `invoke_skill` 同入口,push
  frame 时 `SkipSkillHooks=true`;FireEventHooks(HookSkillUse) 检查 flag → 不 dispatch DSL on_skill_use,
  仍跑 engine canonical(消能量 / 加 dice)。Spike 验证粒度(`SkipDSLSkillHooks` vs `SkipAllSkillHooks`)
- **D4 准备技能 — Game 字段 + builtin** — `Game.Preparing [2]int`(0 = 无);新 builtin
  `set_preparing(player, skill_id)` / `get_preparing(player) -> int` / `clear_preparing(player)` /
  `skip_turn(player)`;Turn-flip 拦截 `Game.Step` 在 `before_turn_flip` hook 后检查 — 若该方
  `Preparing[p] != 0`:silent invoke skill + 清 Preparing[p] + **不**翻转给该方;新 hook
  `HookPrepareResolve`(silent invoke 之前 fire,可 cancel — 例冻结时不准备)
- **D5 资源 builtin** — `draw_card(player, n)`(包装 `Game.DrawCard`,卡组空 graceful)+
  `add_dice(player, element, n)`(`Game.Players[p].Dice` 添加,考虑 `FixDice` 交互)

### Spike 计划(3 张代表卡)

1. **希诺宁**(`character/505321`)— 特技拥有者,夜魂值
2. **驰轮车·疾驰**(`action/505460`)— 特技装备牌
3. **歼灭特化型机关**(`monster/501447`)— 准备技能

**Spike 通过判据**:Lua declare 不报错 + Game init 含 char/card + Mock match invoke 状态正确 + 单测/e2e PASS。

## Affected specs

- `engine-dsl` (declare_card slot 字段,Slot.Specialty / Tag.Specialty enum)
- `engine-event` (EventContext.IsSpecialty / SkipSkillHooks)
- `engine-hooks` (HookPrepareResolve, HookSkillUse skip 语义)
- `engine-action-flow` (turn-flip 拦截 prepare)
