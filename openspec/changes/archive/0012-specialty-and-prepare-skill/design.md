# Design (retrospective)

## Consequences

### DSL 改动汇总

| 字段 / builtin | 类型 | 说明 |
|---|---|---|
| `Slot.Specialty` | enum | declare_card 的 slot 选项 |
| `Tag.Specialty` | counter tag | 槽位 counter group |
| `invoke_skill_silent(id)` | builtin | 不触发 on_skill_use 后续 |
| `set_preparing(p, id)` | builtin | 设置准备状态 |
| `get_preparing(p)` | builtin | 查询 |
| `clear_preparing(p)` | builtin | 清准备 |
| `skip_turn(p)` | builtin | 跳过下次 turn |
| `on_prepare_resolve(fn)` | hook | 准备完成时触发 |
| `draw_card(p, n)` | builtin | 抽 n 张 |
| `add_dice(p, element, n)` | builtin | 生成骰 |
| `ctx.IsSpecialty` | ctx field | hook 内可 filter |

### Engine 改动汇总

| 文件 | 改动 |
|---|---|
| `engine/event.go`(或 game.go) | `EventContext` 加 IsSpecialty / SkipSkillHooks;`Game` 加 Preparing[2] |
| `interp/builtins_skill.go` | invoke_skill_silent;set/get/clear_preparing;skip_turn;HookPrepareResolve fire |
| `interp/builtins.go` | 注册新 builtin |
| `interp/builtins_action.go` | turn-flip 拦截 preparing |
| `interp/builtins_card.go` | declare_card 的 slot 字段处理;Slot.Specialty 槽强制 |
| `interp/builtins_dice.go`(新) | add_dice |
| `engine/hooks.go` | HookPrepareResolve 类型 |

### 实际 ship 文件

- `gicg_engine/interp/builtins_adr0012.go` — 集中实现 set_preparing / draw_card / add_dice / invoke_skill_silent
- `gicg_engine/tests/prepare_skill_spike_test.go` + `specialty_spike_test.go` — PASS

## Tradeoffs revisited

- ADR-0019 §A 依赖前置任务 C.1(本 ADR Status 已显式 ACCEPTED,ADR-0019 ACCEPTED 前置)
- spike 通过判据 PASS;失败判据(engine 改动 > 500 行 / DSL 新增 >5 builtin / 端到端与 wiki 不一致)
  均未触发
- silent invoke 粒度选 `SkipSkillHooks`(全跳)而非 `SkipDSLSkillHooks`(仅 DSL);engine canonical
  仍跑(消能量等)
- A22 `ctx.is_specialty` 启用见 ADR-0019 §A.1(P0-5 防御性提示:`invoke_skill_silent` 当前仅 specialty
  路径用,prepare-resolve 走 ResolvePreparing 不经 invokeSkillCommon,实施正确但脆弱;后续若引入新
  silent 路径需改 `invokeSkillCommon` signature 加 `kind SilentKind` 枚举)

### Out of scope(留作后续)

- A2 始基力反应(reactions/ 扩展)
- E1 结晶 → 护盾(reactions DSL)
- F ctx.element setter 文档
- H Target 扩展
- 其他 ★★ / ★ gap

## References

- `docs/2_decisions/adr-0012-specialty_and_prepare_skill.md` (mirror)
- `docs/3_plans/cards/dsl_gaps.md` — 全 gap 列表
- `docs/3_plans/cards/cleansing_schema.md` 领域笔记 § 特技槽
- `data/cleaned/character/505321_希诺宁.yaml` — 特技拥有者样本
- `data/cleaned/action/505460_驰轮车_疾驰.yaml` — 特技装备牌样本
- `data/cleaned/monster/501447_歼灭特化型机关.yaml` — 准备技能样本
- `data/cleaned/_glossary.yaml` 术语 `特技` / `准备技能` 完整解释
- memory `project_adr_0012_specialty_prepare` — 2026-04-28 PM spike PASS summary
