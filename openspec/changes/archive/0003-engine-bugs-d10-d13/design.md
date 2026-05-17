# Design (retrospective)

## Consequences

### D10 turn flip
- 文件:`gicg_engine/action.go::flipTurn()`,3 处 (executeSkill/executeCard/executeSwitch) call site 改造
- 回归测试:`gicg_engine/tests/turn_flip_test.go` — P0 EndTurn 后 P1 用技能,回合保持 P1
- 隐藏成因:所有 1v1 镜像评估对训练 / 随机 agent 同等影响,训练胜率与 random 同水平掩盖 bug 存在

### D11 CharEntry alias
- `declare_char` 幂等(`ByName[name]` 已存在直接返回)
- `bind_char` 克隆模板 → 独立 PlayerIdx/CharIdx/HPCounterID/EnergyCounterID/AliveCounterID/ActiveCounterID/Skills
- `get_char` 有 slot context 时返 `BySlot[p][c]`,否则 fallback `ByName` 模板
- `declare_skill` 同时注册到 template(canonical, cross-slot 共享) + 当前 owner slot entry
- `registerSkillHooks` 加 owner filter:`if ctx.ActorPlayer != slotPlayer || ctx.ActorChar != slotChar { return }`
- 新入口 `LoadCharFilesPerBinding(paths, playerIdx, charIdx)` 用固定 owner context 拓扑加载;cards/ 仍走全局 `LoadFilesWithDeps`
- helpers (`splitDSLPaths`)将 `data/characters/<name>/` 与 `data/cards/` 文件分流
- 回归测试:`TestMirrorMatchSkillsWork` — 镜像初始化后 `BySlot[0][0].SkillIDs` 与 `BySlot[1][0].SkillIDs` 均填充

### D13 replay
- `gicg_engine/record/roles.go::buildRoleMap` 改遍历 `BySlot`
- 回归测试:`TestRecord_MirrorMatchCharState`

### D14 forced switch
- `gicg_engine/interp/builtins.go::registerDeathCheck`:`DeferAction` 加 `ActiveChar == charIdx` 条件
- 非主动死亡静默减目标,不入队
- 主动死亡仍 enqueue;`checkWin` (在 `SetAlive` 内) 仍处理"全 3 死 → GameOver"
- 回归测试:`gicg_engine/tests/non_active_death_test.go::TestNonActiveDeath_NoForcedSwitch` +
  `TestActiveDeath_DoesForceSwitch`
- 与 `strict_truncation` 关系:assert 仍保留(主目的是捕配置错),死锁路径已在引擎层关

## Tradeoffs revisited

- D11 拆 template + per-slot 是最小破坏性的修复路径:接受少量 entry 重复(每方一份 char entry)换
  per-binding 隔离;`get_char` 多一层 slot-context 判断
- D14 选 "非主动死亡静默" 而非 "非主动死亡入 cleanup queue":前者最小变更,后者会牵动 `GetLegalActions`
  + `forcedSwitchActions` 重构。当时风险/收益不划算

## References

- `docs/2_decisions/adr-0003-engine_bugs_d10_d13.md` (mirror)
- `gicg_engine/action.go::flipTurn` — D10
- `gicg_engine/interp/load_char.go::LoadCharFilesPerBinding` — D11
- `gicg_engine/record/roles.go::buildRoleMap` — D13
- `gicg_engine/interp/builtins.go::registerDeathCheck` — D14
- `tools/diag_long_episode.py` — D14 诊断工具
