package interp

// ADR-0019 §B.4 — declare_shield builtin (DSL macro 等价)。
//
// 默认场景 (无元素特异 / 无条件 / 单一消耗逻辑) 用 builtin 一行替代:
//   declare_counter + Tag.Shield + on_damage_reduce hook + dispose 逻辑。
//
// closure spike (2026-05-04) 证伪 lua 不支持 closure return value, 所以
// builtin 不接 lambda;特殊场景 (护体岩铠物理半伤 / 岩石大盾岩元素 2 倍 /
// 计数特殊消耗) 展开成手写 hook 不用 macro, 保留 v1 自由度。
//
// 用法:
//   declare_shield("结晶护盾", Scope.PerPlayer, 0, { max = 10 })
//   declare_shield("猫爪护盾", Scope.PerChar, 1)  -- max 默认 = init
//
// 等价展开:
//   local c = declare_counter(name, scope, count, { tag = Tag.Shield, max = max })
//   on_damage_reduce(function(ctx)
//     if ctx.element == Element.Piercing then return end  -- §B.1 跳过
//     local s = c:get_at(ctx.target_player)  -- or c:get() for Self/Global
//     if s <= 0 then return end
//     local absorb = min(s, ctx.value)
//     c:sub_at(ctx.target_player, absorb)
//     ctx.value = ctx.value - absorb
//   end)

import (
	engine "gicg_mono/gicg_engine"
)

func (rt *Runtime) builtinDeclareShield(args []Value) (Value, error) {
	// Args: name, scope, count, opts?
	// 走 builtinDeclareCounter 复用所有 declare 逻辑(min/max/display/scope 处理),
	// 然后再 register hook。

	// 准备 opts 表 — 强制设 tag = Tag.Shield(若 caller 没显式 tag)
	var optsTable *Table
	if len(args) > 3 && args[3] != nil {
		optsTable, _ = args[3].(*Table)
	}
	if optsTable == nil {
		optsTable = &Table{Fields: map[string]Value{}}
	}
	// 强制注入 Tag.Shield (Tag 值在 builtins_enums.go 注册;Shield = 6)
	optsTable.Fields["tag"] = 6
	// 若 max 未指定,默认 = init count
	if _, hasMax := optsTable.Fields["max"]; !hasMax {
		if cnt, ok := ToInt(args[2]); ok {
			optsTable.Fields["max"] = cnt
		}
	}

	declareArgs := []Value{args[0], args[1], args[2], optsTable}
	counterRef, err := rt.builtinDeclareCounter(declareArgs)
	if err != nil {
		return nil, err
	}

	// 注册 on_damage_reduce hook 实施 piercing skip + min consume 逻辑;
	// counter proxy 类型通过 type switch 选 read/write 路径。
	rt.registerShieldReduceHook(counterRef)

	return counterRef, nil
}

// registerShieldReduceHook — 注册 on_damage_reduce hook,实施护盾消耗逻辑。
// 跟 reactions/结晶.lua line 30-36 等价(Piercing skip + min consume + delta)。
// counterRef 可以是 *CounterProxy (Self/Global) 或 *PerPlayerProxy / *SelfSlotProxy
// (PerPlayer / PerChar);hook 内部根据类型选 get/set 或 get_at/set_at 路径。
func (rt *Runtime) registerShieldReduceHook(counterRef Value) int {
	hookFn := func(g *engine.Game, ctx *engine.EventContext) {
		// Piercing skip — ADR-0019 §B.1
		if ctx.Element.IsPiercing() {
			return
		}
		if ctx.Value <= 0 {
			return
		}
		// 根据 counterRef 类型查 shield value + decrement
		shield := readShieldValue(g, counterRef, ctx.TargetPlayer, ctx.TargetChar)
		if shield <= 0 {
			return
		}
		absorb := shield
		if ctx.Value < absorb {
			absorb = ctx.Value
		}
		writeShieldValue(g, counterRef, ctx.TargetPlayer, ctx.TargetChar, -absorb)
		ctx.Value -= absorb
	}
	return rt.registerHook(engine.Hook{
		Type: engine.HookShieldAbsorb, // ADR-0019 §B.5: strict 路径下走 ShieldAbsorb 而非 DamageReduce
		Fn:   hookFn,
	})
}

// readShieldValue — 根据 counter proxy 类型选 read 路径。
func readShieldValue(g *engine.Game, ref Value, player, char int) int {
	switch p := ref.(type) {
	case *CounterProxy:
		if p.ID < 0 {
			return 0
		}
		return g.Counters[p.ID].Value
	case *PerPlayerProxy:
		if player < 0 || player > 1 {
			return 0
		}
		id := p.IDs[player]
		if id < 0 {
			return 0
		}
		return g.Counters[id].Value
	case *SelfSlotProxy:
		if player < 0 || char < 0 || char >= MaxChars {
			return 0
		}
		id := p.SlotIDs[player*MaxChars+char]
		if id < 0 {
			return 0
		}
		return g.Counters[id].Value
	}
	return 0
}

// writeShieldValue — 根据 counter proxy 类型选 write 路径(delta 加法)。
func writeShieldValue(g *engine.Game, ref Value, player, char int, delta int) {
	switch p := ref.(type) {
	case *CounterProxy:
		if p.ID < 0 {
			return
		}
		g.WriteCounter(p.ID, engine.OpAdd, delta)
	case *PerPlayerProxy:
		if player < 0 || player > 1 {
			return
		}
		id := p.IDs[player]
		if id < 0 {
			return
		}
		g.WriteCounter(id, engine.OpAdd, delta)
	case *SelfSlotProxy:
		if player < 0 || char < 0 || char >= MaxChars {
			return
		}
		id := p.SlotIDs[player*MaxChars+char]
		if id < 0 {
			return
		}
		g.WriteCounter(id, engine.OpAdd, delta)
	}
}
