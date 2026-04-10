package lua

/*
#include <lua.h>
#include <lualib.h>
#include <lauxlib.h>
#include <stdlib.h>

static int get_counter_id_from(lua_State *L, int idx) {
	int *ud = (int*)luaL_checkudata(L, idx, "Counter");
	return *ud;
}

static void wrap3_lua_pop(lua_State *L, int n) {
	lua_pop(L, n);
}
static void wrap3_lua_getfield(lua_State *L, int idx, const char *name) {
	lua_getfield(L, idx, name);
}
static void wrap3_lua_pushvalue(lua_State *L, int idx) {
	lua_pushvalue(L, idx);
}
static void wrap3_lua_setglobal(lua_State *L, const char *name) {
	lua_setglobal(L, name);
}
*/
import "C"

import (
	"gicg_mono/gicg_engine"
	"unsafe"
)

// readOwnerContext 从 Lua 全局变量读取当前 hook owner
func readOwnerContext(L *C.lua_State) (int, int) {
	ownerPlayer := engine.FilterAny
	ownerChar := engine.FilterAny

	cn1 := C.CString("_current_owner_player")
	defer C.free(unsafe.Pointer(cn1))
	C.wrap3_lua_getfield(L, -10002, cn1)
	if C.lua_type(L, -1) == C.LUA_TNUMBER {
		v := int(C.lua_tointeger(L, -1))
		if v >= 0 {
			ownerPlayer = v
		}
	}
	C.wrap3_lua_pop(L, 1)

	cn2 := C.CString("_current_owner_char")
	defer C.free(unsafe.Pointer(cn2))
	C.wrap3_lua_getfield(L, -10002, cn2)
	if C.lua_type(L, -1) == C.LUA_TNUMBER {
		v := int(C.lua_tointeger(L, -1))
		if v >= 0 {
			ownerChar = v
		}
	}
	C.wrap3_lua_pop(L, 1)

	return ownerPlayer, ownerChar
}

// luaFuncRef 存储 Lua 函数引用，用于 hook 回调
type luaFuncRef struct {
	L   *C.lua_State
	Ref C.int // luaL_ref 返回的引用
}

// callLuaHook 调用 Lua 函数引用，传入 ctx table 并读回修改。
// 栈操作：set context player → push ctx → push fn → push ctx copy → pcall → readback → pop ctx
func callLuaHook(g *engine.Game, ctx *engine.EventContext, ref luaFuncRef) {
	L := ref.L
	// 设置 _current_context_player 供 PerPlayer counter 自动 resolve
	C.lua_pushinteger(L, C.lua_Integer(ctx.ActorPlayer))
	cn := C.CString("_current_context_player")
	defer C.free(unsafe.Pointer(cn))
	C.wrap3_lua_setglobal(L, cn)
	pushContext(L, ctx)                              // stack: [ctx]
	ctxIdx := C.lua_gettop(L)                        // 记住 ctx 位置
	C.lua_rawgeti(L, C.LUA_REGISTRYINDEX, ref.Ref)  // stack: [ctx, fn]
	C.wrap3_lua_pushvalue(L, ctxIdx)                 // stack: [ctx, fn, ctx_copy]
	if C.lua_pcall(L, 1, 0, 0) != 0 {               // stack: [ctx, err] or [ctx]
		_ = C.lua_tolstring(L, -1, nil)
		C.wrap3_lua_pop(L, 1) // pop error           // stack: [ctx]
	}
	// Lua 函数修改的是同一个 table 对象，ctx 仍在 ctxIdx 位置
	readbackContext(L, ctxIdx, ctx)
	C.wrap3_lua_pop(L, 1) // pop ctx
}

// registerEventHook: (fn) 或 (priority_int, fn)
func registerEventHook(L *C.lua_State, hookType engine.HookType) C.int {
	g := getGame(L)
	if g == nil {
		return 0
	}

	nargs := int(C.lua_gettop(L))
	var fnIdx C.int
	var priority int

	if nargs >= 2 && C.lua_type(L, 1) == C.LUA_TNUMBER {
		priority = int(C.lua_tointeger(L, 1))
		fnIdx = 2
	} else {
		fnIdx = 1
	}

	if C.lua_type(L, fnIdx) != C.LUA_TFUNCTION {
		return 0
	}

	C.wrap3_lua_pushvalue(L, fnIdx)
	ref := C.luaL_ref(L, C.LUA_REGISTRYINDEX)
	funcRef := luaFuncRef{L: L, Ref: ref}

	ownerPlayer, ownerChar := readOwnerContext(L)

	h := engine.Hook{
		Type:        hookType,
		CounterID:   engine.FilterAny,
		Priority:    priority,
		OwnerPlayer: ownerPlayer,
		OwnerChar:   ownerChar,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			callLuaHook(g, ctx, funcRef)
		},
	}

	hookID := g.Hooks.Register(h)
	C.lua_pushinteger(L, C.lua_Integer(hookID))
	return 1
}

// registerWriteHook 注册写入 hook (counter, op, fn)
func registerWriteHook(L *C.lua_State, hookType engine.HookType) C.int {
	g := getGame(L)
	if g == nil {
		return 0
	}

	counterID := int(C.get_counter_id_from(L, 1))
	op := engine.Op(C.luaL_checkinteger(L, 2))

	if C.lua_type(L, 3) != C.LUA_TFUNCTION {
		return 0
	}
	C.wrap3_lua_pushvalue(L, 3)
	ref := C.luaL_ref(L, C.LUA_REGISTRYINDEX)
	funcRef := luaFuncRef{L: L, Ref: ref}

	ownerPlayer, ownerChar := readOwnerContext(L)

	h := engine.Hook{
		Type:        hookType,
		CounterID:   counterID,
		Op:          op,
		OwnerPlayer: ownerPlayer,
		OwnerChar:   ownerChar,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			callLuaHook(g, ctx, funcRef)
		},
	}

	hookID := g.Hooks.Register(h)
	C.lua_pushinteger(L, C.lua_Integer(hookID))
	return 1
}

// parseFilter 从 Lua table 解析 HookFilter

// --- Hook registration exports ---

//export go_on_before_write
func go_on_before_write(L *C.lua_State) C.int {
	return registerWriteHook(L, engine.HookBeforeWrite)
}

//export go_on_after_write
func go_on_after_write(L *C.lua_State) C.int {
	return registerWriteHook(L, engine.HookAfterWrite)
}

//export go_on_damage_boost
func go_on_damage_boost(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookDamageBoost)
}

//export go_on_reaction_damage
func go_on_reaction_damage(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookReactionDamage)
}

//export go_on_damage_reduce
func go_on_damage_reduce(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookDamageReduce)
}

//export go_on_after_damage
func go_on_after_damage(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookAfterDamage)
}

//export go_on_before_heal
func go_on_before_heal(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookBeforeHeal)
}

//export go_on_after_heal
func go_on_after_heal(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookAfterHeal)
}

//export go_on_before_energy_gain
func go_on_before_energy_gain(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookBeforeEnergyGain)
}

//export go_on_after_energy_gain
func go_on_after_energy_gain(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookAfterEnergyGain)
}

//export go_on_before_energy_consume
func go_on_before_energy_consume(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookBeforeEnergyConsume)
}

//export go_on_after_energy_consume
func go_on_after_energy_consume(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookAfterEnergyConsume)
}

//export go_on_action_check
func go_on_action_check(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookActionCheck)
}

//export go_on_action_prepare
func go_on_action_prepare(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookActionPrepare)
}

//export go_on_skill_use
func go_on_skill_use(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookSkillUse)
}

//export go_on_card_play
func go_on_card_play(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookCardPlay)
}

//export go_on_switch
func go_on_switch(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookSwitch)
}

//export go_on_before_turn_flip
func go_on_before_turn_flip(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookBeforeTurnFlip)
}

//export go_on_round_start
func go_on_round_start(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookRoundStart)
}

//export go_on_round_end
func go_on_round_end(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookRoundEnd)
}

//export go_on_round_end_post_summon
func go_on_round_end_post_summon(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookRoundEndPostSummon)
}

//export go_on_round_end_decay
func go_on_round_end_decay(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookRoundEndDecay)
}

//export go_on_round_end_final
func go_on_round_end_final(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookRoundEndFinal)
}

//export go_on_action
func go_on_action(L *C.lua_State) C.int {
	return registerEventHook(L, engine.HookAction)
}
