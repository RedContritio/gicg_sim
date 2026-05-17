> **ARCHIVED 2026-05-16(P1-T7)**
>
> Status: **IMPLEMENTED 2026-05-15**
> - 实施 commit 链:56a4c61(plan)→ 62d641f(SlotSupport state)→ f8a8529(hooks + builtins)→ 840b9c5(派蒙 spike + 6 支援区生命周期 test)→ 62f37ee(merge RemoveSupport/CountSupport)→ 82ad456(player.go 拆分)
> - 全部 e2e test pass(`training/tests/` + `gicg_engine/tests/`)
>
> Engine support 行为现描述在 `openspec/specs/engine-actions/`(P1-T4)+ DSL hook reference `openspec/specs/engine-dsl/hook.md`。

---

# 支援区生命周期实现计划

> 2026-05-15 落盘。
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 或 superpowers:executing-plans。Step 用 `- [ ]` checkbox。
>
> 上下文:派蒙 lua header 自认 "deferred:支援槽 slot 系统 / 弃置机制(本 lua 简化:一次性触发 2 回合 +2 万能元素)"。现在补完整生命周期 — engine first-class Supports 区 + 容量上限 + 退槽 + future-friendly hook event + DSL 查询 builtin。

**Goal:** 让 `Slot.Support` 卡入场后真占槽(`engine.PlayerState.Supports`),可用次数耗尽时调 `remove_support(p, ref)` 从槽位移除 + push 进 `Discard`;实装 GICG canonical 4 槽位上限(on_action_check 满则拒);新增 `HookSupportRemove` event hook(future 卡可 `on_support_remove` 监听)和 `count_support(player)` builtin(future "我方支援区有 N" 类条件)。

**Architecture:**
- **engine 层**:`PlayerState.Supports []SupportInst` + `MaxSupportSlots = 4` + `HookSupportRemove` enum + clone 透传
- **interp 层**:`registerCardHooks` 加 `entry.Slot == SlotSupport` 分支(`on_action_check` 容量 reject + `on_card_play` priority 2000 push)+ 新 `builtins_support.go`(`remove_support / count_support`)+ DSL hook map 加 `on_support_remove`
- **DSL 层**:派蒙 lua round_start counter 减到 0 时调 `remove_support(p, ref)`

**Tech Stack:** Go 1.23 / Lua DSL (Go-native interp) / Go testing

---

## 审计已确认(动手前不需再 grep)

- `engine/game.go:36-44` 是 `PlayerState` 定义(不是 `Player`)。字段:Chars / ActiveChar / Hand / Deck / Discard / InitDeck / DeclaredEnd
- `engine/game.go:25-27` 已有 `CardInst{Ref, DrawnAtRound}`,可复用
- `game_clone.go:75-90` clone PlayerState 用 `append([]CardInst(nil), src.Xxx...)` pattern;`Supports` 加 1 行同样模式
- `engine/types.go:100-152` `HookType` 枚举末尾追加 `HookSupportRemove`
- `engine/hook.go:51-117` `HookTypeName` 加 case `return "on_support_remove"`
- `interp/builtins_card.go:175-201` 是 `SlotSpecialty` 处理参考范例(on_action_check + priority 2000 on_card_play)— 镜像加 `SlotSupport` 分支
- `interp/builtins_hook.go:142-160` DSL hook map — 加 1 行 `"on_support_remove": engine.HookSupportRemove`
- `interp/builtins_adr0012.go` 是 `add_dice / draw_card` 参考范例 — 新 `builtins_support.go` 同模式
- 派蒙 lua 当前 21 行,改动 3 行(在 `on_round_start` 末尾加 `if left <= 0 then remove_support(...) end`)
- 现有 `v_phase2_cards_field_lock_test.go` 不改(派蒙的 cost/slot 不变,只是 round_start 行为变了)
- 新 spike test 独立文件 `support_lifecycle_test.go`
- mock helper:已有 `tests/NewGameWithDeck(...)`(看 v_phase2 spike 用法)
- `Game.FireEventHooks(HookType, *EventContext)` in `game_counter.go:184` — `remove_support` 用此 fire HookSupportRemove

---

## File Structure

```
gicg_engine/
├── game.go               # MODIFY — 加 SupportInst struct + MaxSupportSlots const + PlayerState.Supports
├── game_clone.go         # MODIFY — 加 Supports 深拷贝 (1 行)
├── types.go              # MODIFY — HookType enum 末尾加 HookSupportRemove
├── hook.go               # MODIFY — HookTypeName 加 case
└── interp/
    ├── builtins_card.go      # MODIFY — registerCardHooks 加 SlotSupport 分支(on_action_check + priority 2000 hook)
    ├── builtins_hook.go      # MODIFY — DSL hook map 加 "on_support_remove" 一行
    └── builtins_support.go   # CREATE — remove_support / count_support builtin (~60 LOC)

data/pools/v_phase2/cards/支援/
└── 派蒙.lua              # MODIFY — round_start 末尾加 if left <= 0 then remove_support 分支

gicg_engine/tests/
└── support_lifecycle_test.go  # CREATE — 5 个 spike(~140 LOC)
```

---

## Task 1: engine state + HookSupportRemove enum

**Files:** `engine/game.go` + `engine/game_clone.go` + `engine/types.go` + `engine/hook.go`

### Step 1: 加 `SupportInst` struct + `MaxSupportSlots` const

Edit `engine/game.go`。在 `CardInst` struct 之后(line 27 之后)、`PendingCard` 之前 insert:

```go
// SupportInst tracks one card occupying a player's support zone.
// Set on card_play (priority 2000 hook, see interp/builtins_card.go).
// Removed via DSL builtin remove_support(p, ref) which also pushes the
// card_ref into Discard and fires HookSupportRemove.
type SupportInst struct {
	Ref         int // card_ref
	ActivatedAt int // game.Round when entered
}

// MaxSupportSlots — GICG canonical 4-slot support zone cap. Enforced at
// on_action_check (interp/builtins_card.go); 5th support → Playable=false.
const MaxSupportSlots = 4
```

### Step 2: `PlayerState` 加 `Supports` 字段

Edit `engine/game.go:36-44`。`PlayerState` struct 在 `Discard` 之后、`InitDeck` 之前加一行:

```go
type PlayerState struct {
	Chars       []CharInfo
	ActiveChar  int
	Hand        []CardInst
	Deck        []CardInst
	Discard     []CardInst
	Supports    []SupportInst // NEW — support zone (max MaxSupportSlots)
	InitDeck    []CardInst
	DeclaredEnd bool
}
```

### Step 3: `game_clone.go` 加深拷贝

Edit `engine/game_clone.go:85-89` 附近,在 `dst.Discard = append(...)` 之后加:

```go
dst.Supports = append([]SupportInst(nil), src.Supports...)
```

### Step 4: `types.go` 加 `HookSupportRemove` enum

Edit `engine/types.go:146-152`(`HookAction // 任意动作兜底` 之前)插入:

```go
// 支援区生命周期
HookSupportRemove // 支援卡从支援区移除时;ctx.ActorPlayer + ctx.CardRef
```

### Step 5: `hook.go` 加 `HookTypeName` case

Edit `engine/hook.go:113-114`(`case HookAction: return "on_action"` 之前)插入:

```go
case HookSupportRemove:
	return "on_support_remove"
```

### Step 6: 构建 + 现有 tests 跑通(NO 新功能 yet)

```bash
go build ./...
go test ./gicg_engine/tests/ -run TestVPhase2CardFieldLocks -v -count=1
```

Expected: build OK, 现 spike test 全 pass(`Supports` 字段空 slice,clone 透传,enum 加值不影响现有 hook)。

### Step 7: Commit

```bash
git add gicg_engine/game.go gicg_engine/game_clone.go gicg_engine/types.go gicg_engine/hook.go
git commit -m "engine: support zone state — PlayerState.Supports + MaxSupportSlots=4 + HookSupportRemove enum"
```

---

## Task 2: interp hooks + builtins(remove_support / count_support / on_support_remove)

**Files:** `interp/builtins_card.go` + `interp/builtins_hook.go` + `interp/builtins_support.go`(new)

### Step 1: `builtins_card.go` 加 `SlotSupport` 分支

Edit `gicg_engine/interp/builtins_card.go`。当前 `registerCardHooks` 函数(line 145+)末尾、`registerCardHooks` 闭合大括号之前,插入两个 hook 注册(镜像现有 SlotSpecialty 模式 line 175-201):

```go
// on_action_check: support 区满 → reject(GICG canonical 4 槽位上限)
if entry.Slot == SlotSupport {
	rt.registerHook(engine.Hook{
		Type: engine.HookActionCheck,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActionKind != engine.ActionCard || ctx.CardRef != entry.Ref {
				return
			}
			if len(g.Players[ctx.ActorPlayer].Supports) >= engine.MaxSupportSlots {
				ctx.Playable = false
			}
		},
	})
	// on_card_play priority 2000:push 到 Supports。在 canonical(1000)+ DSL(default 0)前
	// 运行,所以 DSL on_card_play 可读到 Supports 已含新卡。
	rt.registerHook(engine.Hook{
		Type:     engine.HookCardPlay,
		Priority: 2000,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.CardRef != entry.Ref {
				return
			}
			g.Players[ctx.ActorPlayer].Supports = append(
				g.Players[ctx.ActorPlayer].Supports,
				engine.SupportInst{Ref: entry.Ref, ActivatedAt: g.Round},
			)
		},
	})
}
```

### Step 2: 创建 `interp/builtins_support.go`

完整文件:

```go
package interp

import (
	engine "gicg_mono/gicg_engine"
)

// Support-zone builtins: remove_support / count_support.
// Counterpart engine state: PlayerState.Supports + MaxSupportSlots.
// HookSupportRemove fired after Discard push so on_support_remove
// hooks see the canonical post-state (card no longer in Supports,
// already in Discard).
func (rt *Runtime) registerSupportBuiltins() {
	g := rt.Globals

	// remove_support(player, card_ref) — 从指定玩家支援区移除 card_ref。
	// 找到则 splice out + push 进 Discard + fire HookSupportRemove。
	// 找不到 → no-op(允许 DSL 幂等调用,例如双 round_start 重复触发)。
	g.SetLocal("remove_support", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		var cardRef int
		switch v := args[1].(type) {
		case *CardRef:
			cardRef = v.Ref
		case int:
			cardRef = v
		}
		rp := rt.ResolvePlayer(p)
		if rp < 0 || rp > 1 {
			return nil, nil
		}
		sup := rt.Game.Players[rp].Supports
		for i, s := range sup {
			if s.Ref == cardRef {
				rt.Game.Players[rp].Supports = append(sup[:i], sup[i+1:]...)
				rt.Game.Players[rp].Discard = append(
					rt.Game.Players[rp].Discard,
					engine.CardInst{Ref: cardRef, DrawnAtRound: rt.Game.Round},
				)
				ctx := &engine.EventContext{ActorPlayer: rp, CardRef: cardRef}
				rt.Game.FireEventHooks(engine.HookSupportRemove, ctx)
				return nil, nil
			}
		}
		return nil, nil // 不在场,幂等
	}))

	// count_support(player) — 返回指定玩家支援区张数。用于 future 卡的
	// "我方支援区有 N 张时 ..."类条件。
	g.SetLocal("count_support", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		rp := rt.ResolvePlayer(p)
		if rp < 0 || rp > 1 {
			return 0, nil
		}
		return len(rt.Game.Players[rp].Supports), nil
	}))
}
```

注:`registerSupportBuiltins` 需要在 `Runtime` 构造时调用。看 `interp/builtins.go` / `runtime.go` 找现有 `register*Builtins` 串。如果有 `RegisterBuiltins` 类入口,加一行 `rt.registerSupportBuiltins()` 即可。如果模式不一样,STOP + 报告。

### Step 3: `builtins_hook.go` 加 `on_support_remove` map 入口

Edit `gicg_engine/interp/builtins_hook.go`。找到 hook map(line 142+),在 `"on_action": engine.HookAction` 之前(或合适位置)加一行:

```go
"on_support_remove": engine.HookSupportRemove,
```

### Step 4: 构建 + 现有 tests 跑通

```bash
go build ./...
go test ./gicg_engine/tests/ -run TestVPhase2CardFieldLocks -v -count=1
```

Expected: build OK,spike 全 pass(派蒙仍是 counter 软关闭路径,所以 Supports 入了但没退;test 不测退槽,只测 cost/slot 字段)。

### Step 5: 跑全 engine test no regression

```bash
go test ./gicg_engine/tests/ -count=1 2>&1 | tail -10
```

Expected: 全 pass(pre-existing 失败若有,匹配 BASE 前的失败列表)。

### Step 6: Commit

```bash
git add gicg_engine/interp/builtins_card.go gicg_engine/interp/builtins_support.go gicg_engine/interp/builtins_hook.go
git commit -m "interp: SlotSupport occupancy hooks + remove_support/count_support builtins + on_support_remove DSL hook"
```

---

## Task 3: 派蒙 DSL 改造 + 5 个 spike test

**Files:** `data/pools/v_phase2/cards/支援/派蒙.lua` + `gicg_engine/tests/support_lifecycle_test.go`(new)

### Step 1: 派蒙 lua 改造

Edit `data/pools/v_phase2/cards/支援/派蒙.lua`。当前 `on_round_start` 是:

```lua
on_round_start(function(ctx)
  local p = context_player()
  if active:get_at(p) <= 0 then return end
  add_dice(p, DiceColor.Omni, 2)
  active:set_at(p, active:get_at(p) - 1)
end)
```

改为(在 set_at 后判断 left=0 退槽):

```lua
on_round_start(function(ctx)
  local p = context_player()
  if active:get_at(p) <= 0 then return end
  add_dice(p, DiceColor.Omni, 2)
  local left = active:get_at(p) - 1
  active:set_at(p, left)
  if left <= 0 then
    remove_support(p, ref)
  end
end)
```

同时 header comment 删 "deferred:支援槽 slot 系统 / 弃置机制" 一行,新加:"用尽 2 次后调 remove_support 真退槽 + 进 Discard(engine PlayerState.Supports + MaxSupportSlots=4)"。

### Step 2: 创建 `gicg_engine/tests/support_lifecycle_test.go`

完整文件骨架(5 个 sub-test):

```go
package tests

// Support zone lifecycle spike — 锁定 PlayerState.Supports 行为 +
// remove_support 幂等 + count_support 读取 + on_support_remove fire。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestSupportEntryOccupiesSlot — 出派蒙后 Supports 长度+1
func TestSupportEntryOccupiesSlot(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	playerIdx := 0
	// 凯亚 vs 克洛琳德,出派蒙到 P0 的 Supports
	// (具体出牌 helper 见 v_phase2_cards_field_lock_test.go 用法)
	// ... 出派蒙 ...
	if got := len(env.G.Players[playerIdx].Supports); got != 1 {
		t.Errorf("Supports len = %d, want 1", got)
	}
	if env.G.Players[playerIdx].Supports[0].Ref != env.RT.Cards.ByName["派蒙"].Ref {
		t.Errorf("Supports[0].Ref = %d, want 派蒙", env.G.Players[playerIdx].Supports[0].Ref)
	}
}

// TestSupportCapacityCap — 4 张支援区满了,第 5 张 Playable=false
func TestSupportCapacityCap(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	// 直接 mock PlayerState.Supports 塞 4 个 SupportInst(用任意 ref,
	// 比如派蒙 ref × 4),再 enumerate actions 看派蒙能否出。
	// 看 v_phase2 spike 是否有现成 mock helper;如果没有,直接 G.Players[0].Supports = make([]SupportInst, 4)
	paimon := env.RT.Cards.ByName["派蒙"]
	env.G.Players[0].Supports = make([]engine.SupportInst, engine.MaxSupportSlots)
	for i := range env.G.Players[0].Supports {
		env.G.Players[0].Supports[i] = engine.SupportInst{Ref: paimon.Ref, ActivatedAt: 1}
	}
	// (具体 enumerate 派蒙的 PlayCard action 看 Playable;
	// 看 v_phase2 spike 有无现成 helper,如 env.IsPlayable("派蒙"))
	// ... assert Playable=false ...
}

// TestSupportRemoveOnZero — 派蒙 round_start 触发 2 次后,Supports 空 + Discard 含 ref
func TestSupportRemoveOnZero(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	// 出派蒙 → 推进 2 个 round → assert
	// ... 出派蒙到 P0 ...
	// ... 推进 round 直到 active:get_at(0) == 0 ...
	paimon := env.RT.Cards.ByName["派蒙"]
	if got := len(env.G.Players[0].Supports); got != 0 {
		t.Errorf("after 2 triggers Supports = %d, want 0", got)
	}
	// Discard 应含派蒙 ref
	found := false
	for _, c := range env.G.Players[0].Discard {
		if c.Ref == paimon.Ref {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("派蒙 ref %d not in Discard after expiry", paimon.Ref)
	}
}

// TestRemoveSupportIdempotent — 同卡重复 remove_support 不崩
func TestRemoveSupportIdempotent(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]
	// 先 push 一个 SupportInst,然后通过 DSL 调用 remove_support 两次
	env.G.Players[0].Supports = []engine.SupportInst{{Ref: paimon.Ref, ActivatedAt: 1}}
	// 调用 remove_support builtin 两次(用 Runtime.Call 或 invoke helper)
	// 第一次:Supports 应空,Discard 应+1
	// 第二次:no-op(不报 error,不重复 push Discard)
	// ... assert ...
}

// TestCountSupport — 0/1/2 张时 count_support 返回正确值
func TestCountSupport(t *testing.T) {
	env := NewGameWithDeck(t, []string{"凯亚"}, []string{"克洛琳德"})
	paimon := env.RT.Cards.ByName["派蒙"]
	for n := 0; n <= 2; n++ {
		env.G.Players[0].Supports = make([]engine.SupportInst, n)
		for i := range env.G.Players[0].Supports {
			env.G.Players[0].Supports[i] = engine.SupportInst{Ref: paimon.Ref}
		}
		// call count_support(0) via Runtime; assert == n
		// ... assert ...
	}
}

// TestOnSupportRemoveHook — DSL on_support_remove ctx.ActorPlayer + ctx.CardRef 正确
func TestOnSupportRemoveHook(t *testing.T) {
	// 注册一个临时 hook,记录 fired 的 ctx;调 remove_support 后验证 ctx 字段
	// 注:可能需要 在测试 lua / Go 端注册一个临时 hook 收集 ctx,
	// 看现有 hook spike 测试有无 helper(如 g.Hooks.Register(...))
}
```

> **实现注:** 具体测试实现细节 — 测试体的 `// ...` 部分需在 Task 3 实施时填充。Test 5 个的 setup 共享 NewGameWithDeck + 派蒙出牌 helper。如果没有现成 helper 出牌(action enumerate + execute card),Test 1/3 可能复杂,**fallback 路径**:直接 mock `env.G.Players[0].Supports` + 直接调 `remove_support` builtin(via `Runtime.Call` 或暴露的 invoke helper)。优先用现有 helper,fallback 在每个 test 注释里说明。

### Step 3: 跑新 spike

```bash
go test ./gicg_engine/tests/ -run "TestSupport|TestRemoveSupport|TestCountSupport|TestOnSupportRemoveHook" -v -count=1
```

Expected: 5 sub-test 全 pass。

### Step 4: 跑全 engine + 全 Python tests no regression

```bash
go test ./gicg_engine/tests/ -count=1 2>&1 | tail -10
.venv/bin/python -m pytest -n 4 training/tests/test_dmc_*.py gicg_env/tests/ -q
```

Expected: 全 pass(pre-existing 失败若有,匹配 BASE 前的失败列表)。

### Step 5: Mac CPU smoke 跑 dmc_train(确认 lua 加载 + train pipeline 不崩)

```bash
.venv/bin/python -m tools.dmc_train configs/dmc_stage3_smoke.toml 2>&1 | tail -5
```

Expected: smoke 5000 frames 完整跑通(~5 min),打印 `[done] summary: ...`。

### Step 6: Commit

```bash
git add data/pools/v_phase2/cards/支援/派蒙.lua gicg_engine/tests/support_lifecycle_test.go
git commit -m "dsl + tests: 派蒙退槽改造 + 5 个支援区生命周期 spike (entry/cap/expiry/idempotent/count/on_support_remove)"
```

---

## Self-review checklist(写完 plan 自审)

- **Spec coverage:** 4 个 user 选项 A2(容量上限)/ B1(进 Discard)/ C2(HookSupportRemove)/ D2(count_support)— 都在 Task 1-3 中实现。✓
- **Types consistency:**
  - `SupportInst{Ref int, ActivatedAt int}` 定义 Task 1 Step 1;Task 2 Step 1 push 用同字段;Task 3 Step 2 mock 也用同字段 ✓
  - `MaxSupportSlots = 4` 定义 Task 1 Step 1;Task 2 Step 1 reject 用此常量;Task 3 Step 2 capacity test 用 `engine.MaxSupportSlots` ✓
  - `HookSupportRemove` enum 加在 Task 1 Step 4;hook map 在 Task 2 Step 3;test 在 Task 3 Step 2 ✓
  - `remove_support(player, card_ref)` 接受 `*CardRef` 或 `int`;派蒙 lua Task 3 Step 1 传 `ref`(*CardRef);test idempotent 直接调可能要看 Runtime.Call 怎么 wrap arg ✓
- **Hook fire 顺序:** `remove_support` 内 push Discard **之后** fire HookSupportRemove — DSL 监听看到 canonical 已退槽 + 已 discard 的 post-state。这个语义在 Task 2 Step 2 docstring 明示 ✓
- **Audit 准:** 所有 line number / 字段名 / 函数签名 均在前序 grep 确认 ✓
- **Placeholder 扫:** Task 3 Step 2 测试体的 `// ...` 是 acknowledged TBD,在 Step 2 注里说"fallback 路径";其他无 TBD/TODO ⚠️(测试 5 个的实际填充需 Task 3 时根据现有 helper 选 path,但 spec contract 明确)

## 不在 scope

- 支援区"过载替换"(GICG canonical:第 5 张可指定替换某槽位)→ 本期 reject,future
- 其他支援卡(鸣神大社 / 凯瑟琳 / 蒂玛乌斯 ...)retrofit 调 remove_support → 本期只改派蒙
- DSL `list_support(player)` 返回卡列表 → 本期仅 count(标量足够 reactive 条件用)
- Python obs encoder 暴露 Supports → future,RL 需要时再加
- Replay/yaml export 显式 supports 区 → future
