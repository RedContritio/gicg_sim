# Engine bug fixes (D10-D14) — mirror match unblock

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0003-engine_bugs_d10_d13.md` at P1-T1)
**Original date:** Stage A (phase0a 训练阻塞期)
**Original status:** Accepted (全部 shipped 含回归测试)
**Supersedes:** —
**Superseded by:** —

## Why

Mirror match 训练阻塞期间发现 4 个 engine bug(D10-D13)+ 1 个 NvN 死锁 bug(D14)。共同特征:都
被既有非镜像测试套掩盖,只在 phase0a / phase0c 实际训练 / 评估时触发。每个 bug 都让 train pipeline
完全无法 work,必须修。

## What

- **D10 回合翻转 bug** — `BattleAction` 无条件翻 `g.Turn`,导致已宣告结束方仍被轮询并消耗对手有效
  行动配额。修复:`flipTurn()` helper 检查 `Players[next].DeclaredEnd`,已结束则保持当前方独占。
  3 处翻转点(`executeSkill` / `executeCard` / `executeSwitch`)统一调 `flipTurn()`。
- **D11 per-name CharEntry 别名 bug** — `declare_char(name)` 总创新 entry 覆 `ByName[name]`,镜像
  匹配下 P0 entry 被孤立,技能注册全归 P1。修复:CharEntry 拆"模板"(`ByName`,共享)+ "per-slot"
  (`BySlot`,各绑定独立)。`declare_char` 幂等;`bind_char` 克隆模板;`declare_skill` 注册到模板 +
  当前 owner slot;`registerSkillHooks` 加 (player, char) filter 防 cross-slot 触发;新加载入口
  `LoadCharFilesPerBinding(paths, playerIdx, charIdx)`。
- **D12 修复验证基线** — 修复 D10+D11 后随机 vs 随机 1v1 镜像每个角色 50 局:赤蝶 27:23 / 墨客
  26:24 / 猫咪 37:13 / 刻师傅 29:21 / 天星 45:5。猫咪/天星 残余先手优势属于角色机制方差不属 bug。
  phase0a smoke 修复后 30 iter 内打到 100%(修复前 500 iter 最好 55%)。
- **D13 Replay role state 缺 HP/能量字段** — D11 后 `ByName` 全是 template entry(HPCounterID=-1),
  `buildRoleMap` 遍历 `ByName` 收不到 counter ID,replay 输出孤立逗号。修复:改遍历 `BySlot`。
- **D14 非主动角色死亡时强制切换死锁** — `registerDeathCheck` 对**每个**死亡 enqueue 强制切换,
  不论是否主动角色。多目标清场(scripted skill 击杀非主动角色 + 主动仍存活)→ enqueue
  `PendingAction.Switch` 但没活的非主动角色可切 → 引擎 `PhaseAction` 死锁。修复:`DeferAction`
  条件加 `g.Players[playerIdx].ActiveChar == charIdx`,非主动死亡静默减少切换目标,不入队。

## Affected specs

- `engine-action-flow` (待建,P1-T2/T6 抽 action / turn-flip / death-check SHALL 时 backfill)
- `engine-loading` (D11 per-binding load 路径)
- `engine-record` (D13 replay format)
