package lua

/*
#include <lua.h>
#include <lualib.h>
#include <lauxlib.h>
#include <stdlib.h>

static void wrap_ctx_setfield(lua_State *L, int idx, const char *name) {
	lua_setfield(L, idx, name);
}
static void wrap_ctx_getfield(lua_State *L, int idx, const char *name) {
	lua_getfield(L, idx, name);
}
static void wrap_ctx_pop(lua_State *L, int n) {
	lua_pop(L, n);
}
*/
import "C"

import (
	"gicg_mono/gicg_engine"
	"unsafe"
)

// pushContext 将 EventContext 推送到 Lua 栈上作为 table
func pushContext(L *C.lua_State, ctx *engine.EventContext) {
	C.lua_createtable(L, 0, 16)
	idx := C.lua_gettop(L)

	setInt := func(name string, val int) {
		cn := C.CString(name)
		defer C.free(unsafe.Pointer(cn))
		C.lua_pushinteger(L, C.lua_Integer(val))
		C.wrap_ctx_setfield(L, idx, cn)
	}
	setBool := func(name string, val bool) {
		cn := C.CString(name)
		defer C.free(unsafe.Pointer(cn))
		if val {
			C.lua_pushboolean(L, 1)
		} else {
			C.lua_pushboolean(L, 0)
		}
		C.wrap_ctx_setfield(L, idx, cn)
	}

	setInt("value", ctx.Value)
	setInt("element", int(ctx.Element))
	setInt("source", int(ctx.Source))
	setInt("action_context", int(ctx.ActionCtx))
	setInt("actor_player", ctx.ActorPlayer)
	setInt("actor_char", ctx.ActorChar)
	setInt("skill_index", ctx.SkillIndex)
	setInt("card_ref", ctx.CardRef)
	setInt("target_player", ctx.TargetPlayer)
	setInt("target_char", ctx.TargetChar)
	setInt("counter_id", ctx.CounterID)
	setInt("op", int(ctx.Op))
	setInt("action_kind", int(ctx.ActionKind))
	setInt("ap_cost", ctx.APCost)
	setInt("energy_cost", ctx.EnergyCost)
	setInt("hand_index", ctx.HandIndex)
	setInt("switch_char", ctx.SwitchChar)

	setInt("target_mode", ctx.TargetMode)

	setBool("penetrate", ctx.Penetrate)
	setBool("playable", ctx.Playable)
	setBool("cancelled", ctx.Cancelled)
	setBool("skip_reaction", ctx.SkipReaction)
	setBool("hit", ctx.Hit)
	setBool("battle_action", ctx.BattleAction)
	setBool("need_target", ctx.NeedTarget)
	setBool("paid", ctx.Paid)
}

// readbackContext 从 Lua 栈上 table 读回可修改的字段到 EventContext
func readbackContext(L *C.lua_State, idx C.int, ctx *engine.EventContext) {
	getInt := func(name string) (int, bool) {
		cn := C.CString(name)
		defer C.free(unsafe.Pointer(cn))
		C.wrap_ctx_getfield(L, idx, cn)
		if C.lua_type(L, -1) == C.LUA_TNUMBER {
			val := int(C.lua_tointeger(L, -1))
			C.wrap_ctx_pop(L, 1)
			return val, true
		}
		C.wrap_ctx_pop(L, 1)
		return 0, false
	}
	getBool := func(name string) (bool, bool) {
		cn := C.CString(name)
		defer C.free(unsafe.Pointer(cn))
		C.wrap_ctx_getfield(L, idx, cn)
		if C.lua_type(L, -1) == C.LUA_TBOOLEAN {
			val := C.lua_toboolean(L, -1) != 0
			C.wrap_ctx_pop(L, 1)
			return val, true
		}
		C.wrap_ctx_pop(L, 1)
		return false, false
	}

	if v, ok := getInt("value"); ok {
		ctx.Value = v
	}
	if v, ok := getInt("element"); ok {
		ctx.Element = engine.Element(v)
	}
	if v, ok := getInt("ap_cost"); ok {
		ctx.APCost = v
	}
	if v, ok := getInt("energy_cost"); ok {
		ctx.EnergyCost = v
	}
	if v, ok := getBool("playable"); ok {
		ctx.Playable = v
	}
	if v, ok := getBool("cancelled"); ok {
		ctx.Cancelled = v
	}
	if v, ok := getBool("skip_reaction"); ok {
		ctx.SkipReaction = v
	}
	if v, ok := getBool("battle_action"); ok {
		ctx.BattleAction = v
	}
	if v, ok := getBool("need_target"); ok {
		ctx.NeedTarget = v
	}
	if v, ok := getInt("target_mode"); ok {
		ctx.TargetMode = v
	}
}
