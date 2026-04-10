package lua

/*
#include <lua.h>
#include <lualib.h>
#include <lauxlib.h>
#include <stdlib.h>

// Forward declarations for Go exports used in this file
extern int go_counter_get(lua_State *L);
extern int go_counter_min(lua_State *L);
extern int go_counter_max(lua_State *L);
extern int go_counter_set(lua_State *L);
extern int go_counter_add(lua_State *L);
extern int go_counter_sub(lua_State *L);

static void wrap_lua_pushcfunction(lua_State *L, lua_CFunction fn) {
	lua_pushcfunction(L, fn);
}

static void wrap_lua_setfield(lua_State *L, int idx, const char *name) {
	lua_setfield(L, idx, name);
}

static void wrap_lua_getfield(lua_State *L, int idx, const char *name) {
	lua_getfield(L, idx, name);
}

static void wrap_lua_rawseti(lua_State *L, int idx, int n) {
	lua_rawseti(L, idx, n);
}

static void wrap2_lua_pop(lua_State *L, int n) {
	lua_pop(L, n);
}

// Wrapper to push counter userdata with metatable
static void push_counter(lua_State *L, int id) {
	int *ud = (int*)lua_newuserdata(L, sizeof(int));
	*ud = id;
	luaL_getmetatable(L, "Counter");
	lua_setmetatable(L, -2);
}

static int get_counter_id(lua_State *L, int idx) {
	int *ud = (int*)luaL_checkudata(L, idx, "Counter");
	return *ud;
}

// Wrapper for lua_setglobal/getglobal (macros)
static void wrap2_lua_setglobal(lua_State *L, const char *name) {
	lua_setglobal(L, name);
}
*/
import "C"

import (
	"gicg_mono/gicg_engine"
	"unsafe"
)

func InitCounterMetatable(s *State) {
	L := s.L
	cname := C.CString("Counter")
	defer C.free(unsafe.Pointer(cname))
	C.luaL_newmetatable(L, cname)

	C.lua_pushvalue(L, -1)
	cindex := C.CString("__index")
	defer C.free(unsafe.Pointer(cindex))
	C.wrap_lua_setfield(L, -2, cindex)

	registerMethod := func(name string, fn C.lua_CFunction) {
		cn := C.CString(name)
		defer C.free(unsafe.Pointer(cn))
		C.wrap_lua_pushcfunction(L, fn)
		C.wrap_lua_setfield(L, -2, cn)
	}

	registerMethod("get", C.lua_CFunction(C.go_counter_get))
	registerMethod("cmin", C.lua_CFunction(C.go_counter_min))
	registerMethod("cmax", C.lua_CFunction(C.go_counter_max))
	registerMethod("set", C.lua_CFunction(C.go_counter_set))
	registerMethod("add", C.lua_CFunction(C.go_counter_add))
	registerMethod("sub", C.lua_CFunction(C.go_counter_sub))

	C.wrap2_lua_pop(L, 1)
}

//export go_create_counter
func go_create_counter(L *C.lua_State) C.int {
	g := getGame(L)
	if g == nil {
		return 0
	}

	value := int(C.luaL_checkinteger(L, 1))
	min := int(C.luaL_checkinteger(L, 2))
	max := int(C.luaL_checkinteger(L, 3))

	id := g.CreateCounter(value, min, max)
	C.push_counter(L, C.int(id))
	return 1
}

//export go_counter_get
func go_counter_get(L *C.lua_State) C.int {
	g := getGame(L)
	id := int(C.get_counter_id(L, 1))
	val := g.ReadCounter(id)
	C.lua_pushinteger(L, C.lua_Integer(val))
	return 1
}

//export go_counter_min
func go_counter_min(L *C.lua_State) C.int {
	g := getGame(L)
	id := int(C.get_counter_id(L, 1))
	val := g.ReadCounterMin(id)
	C.lua_pushinteger(L, C.lua_Integer(val))
	return 1
}

//export go_counter_max
func go_counter_max(L *C.lua_State) C.int {
	g := getGame(L)
	id := int(C.get_counter_id(L, 1))
	val := g.ReadCounterMax(id)
	C.lua_pushinteger(L, C.lua_Integer(val))
	return 1
}

//export go_counter_set
func go_counter_set(L *C.lua_State) C.int {
	g := getGame(L)
	id := int(C.get_counter_id(L, 1))
	val := int(C.luaL_checkinteger(L, 2))
	g.WriteCounter(id, engine.OpSet, val)
	return 0
}

//export go_counter_add
func go_counter_add(L *C.lua_State) C.int {
	g := getGame(L)
	id := int(C.get_counter_id(L, 1))
	val := int(C.luaL_checkinteger(L, 2))
	g.WriteCounter(id, engine.OpAdd, val)
	return 0
}

//export go_counter_sub
func go_counter_sub(L *C.lua_State) C.int {
	g := getGame(L)
	id := int(C.get_counter_id(L, 1))
	val := int(C.luaL_checkinteger(L, 2))
	g.WriteCounter(id, engine.OpSub, val)
	return 0
}

//export go_deal_damage
func go_deal_damage(L *C.lua_State) C.int {
	g := getGame(L)
	targetHP := int(C.get_counter_id(L, 1))
	elem := engine.Element(C.luaL_checkinteger(L, 2))
	value := int(C.luaL_checkinteger(L, 3))

	opts := engine.DamageOpts{ActorPlayer: -1, ActorChar: -1}
	if C.lua_gettop(L) >= 4 && C.lua_type(L, 4) == C.LUA_TTABLE {
		csrc := C.CString("source")
		defer C.free(unsafe.Pointer(csrc))
		C.wrap_lua_getfield(L, 4, csrc)
		if C.lua_type(L, -1) == C.LUA_TNUMBER {
			opts.Source = engine.Source(C.lua_tointeger(L, -1))
		}
		C.wrap2_lua_pop(L, 1)

		cpen := C.CString("penetrate")
		defer C.free(unsafe.Pointer(cpen))
		C.wrap_lua_getfield(L, 4, cpen)
		if C.lua_type(L, -1) == C.LUA_TBOOLEAN {
			opts.Penetrate = C.lua_toboolean(L, -1) != 0
		}
		C.wrap2_lua_pop(L, 1)
	}

	g.DealDamage(targetHP, elem, value, opts)
	return 0
}

//export go_heal
func go_heal(L *C.lua_State) C.int {
	g := getGame(L)
	targetHP := int(C.get_counter_id(L, 1))
	value := int(C.luaL_checkinteger(L, 2))
	g.Heal(targetHP, value)
	return 0
}

//export go_set_winner
func go_set_winner(L *C.lua_State) C.int {
	g := getGame(L)
	player := int(C.luaL_checkinteger(L, 1))
	g.SetWinner(player)
	return 0
}

//export go_set_alive
func go_set_alive(L *C.lua_State) C.int {
	g := getGame(L)
	player := int(C.luaL_checkinteger(L, 1))
	char := int(C.luaL_checkinteger(L, 2))
	alive := C.lua_toboolean(L, 3) != 0
	g.SetAlive(player, char, alive)
	return 0
}

//export go_draw_card
func go_draw_card(L *C.lua_State) C.int {
	g := getGame(L)
	player := int(C.luaL_checkinteger(L, 1))
	count := int(C.luaL_checkinteger(L, 2))
	for i := 0; i < count; i++ {
		g.DrawCard(player)
	}
	return 0
}

//export go_cancel
func go_cancel(L *C.lua_State) C.int {
	// TODO: 实现 cancel 机制
	return 0
}

//export go_request_switch
func go_request_switch(L *C.lua_State) C.int {
	g := getGame(L)
	player := int(C.luaL_checkinteger(L, 1))

	p := &g.Players[player]
	var survivors []int
	for k, ch := range p.Chars {
		if k != p.ActiveChar && ch.Alive {
			survivors = append(survivors, k)
		}
	}

	switch len(survivors) {
	case 0:
	case 1:
		g.Players[player].ActiveChar = survivors[0]
	default:
		g.PendingAction = &engine.Action{
			Kind:      engine.ActionSwitch,
			PlayerIdx: player,
			Forced:    true,
		}
	}
	return 0
}

//export go_get_next_char
func go_get_next_char(L *C.lua_State) C.int {
	g := getGame(L)
	playerIdx := int(C.luaL_checkinteger(L, 1))
	current := int(C.luaL_checkinteger(L, 2))
	p := &g.Players[playerIdx]
	n := len(p.Chars)
	for i := 1; i < n; i++ {
		idx := (current + i) % n
		if p.Chars[idx].Alive {
			C.lua_pushinteger(L, C.lua_Integer(idx))
			return 1
		}
	}
	C.lua_pushinteger(L, C.lua_Integer(current))
	return 1
}

//export go_force_switch_next
func go_force_switch_next(L *C.lua_State) C.int {
	g := getGame(L)
	player := int(C.luaL_checkinteger(L, 1))

	// 从当前出战角色的下一个开始，找第一个存活的
	p := &g.Players[player]
	n := len(p.Chars)
	for i := 1; i < n; i++ {
		idx := (p.ActiveChar + i) % n
		if p.Chars[idx].Alive {
			p.ActiveChar = idx
			return 0
		}
	}
	// 没有存活角色（不应该到这里，超载前角色应该存活）
	return 0
}

//export go_get_actor_player
func go_get_actor_player(L *C.lua_State) C.int {
	g := getGame(L)
	cur := g.CurrentEvent()
	C.lua_pushinteger(L, C.lua_Integer(cur.Player))
	return 1
}

//export go_get_active_char
func go_get_active_char(L *C.lua_State) C.int {
	g := getGame(L)
	player := int(C.luaL_checkinteger(L, 1))
	C.lua_pushinteger(L, C.lua_Integer(g.Players[player].ActiveChar))
	return 1
}

//export go_get_round
func go_get_round(L *C.lua_State) C.int {
	g := getGame(L)
	C.lua_pushinteger(L, C.lua_Integer(g.Round))
	return 1
}

//export go_get_turn
func go_get_turn(L *C.lua_State) C.int {
	g := getGame(L)
	C.lua_pushinteger(L, C.lua_Integer(g.Turn))
	return 1
}

//export go_get_first_end
func go_get_first_end(L *C.lua_State) C.int {
	g := getGame(L)
	C.lua_pushinteger(L, C.lua_Integer(g.FirstEnd))
	return 1
}

//export go_get_enemy_alive
func go_get_enemy_alive(L *C.lua_State) C.int {
	g := getGame(L)
	// 读取 _current_context_player
	cn := C.CString("_current_context_player")
	defer C.free(unsafe.Pointer(cn))
	C.wrap_lua_getfield(L, C.LUA_GLOBALSINDEX, cn)
	player := int(C.lua_tointeger(L, -1))
	C.wrap2_lua_pop(L, 1)

	enemy := 1 - player
	return pushAliveList(L, g, enemy)
}

//export go_get_own_alive
func go_get_own_alive(L *C.lua_State) C.int {
	g := getGame(L)
	cn := C.CString("_current_context_player")
	defer C.free(unsafe.Pointer(cn))
	C.wrap_lua_getfield(L, C.LUA_GLOBALSINDEX, cn)
	player := int(C.lua_tointeger(L, -1))
	C.wrap2_lua_pop(L, 1)

	return pushAliveList(L, g, player)
}

// pushAliveList 将指定玩家的存活角色索引列表推入 Lua 栈
func pushAliveList(L *C.lua_State, g *engine.Game, playerIdx int) C.int {
	if playerIdx < 0 || playerIdx > 1 {
		C.lua_createtable(L, 0, 0)
		return 1
	}
	p := &g.Players[playerIdx]
	C.lua_createtable(L, C.int(len(p.Chars)), 0)
	idx := 1
	for k, ch := range p.Chars {
		if ch.Alive {
			C.lua_pushinteger(L, C.lua_Integer(k))
			C.wrap_lua_rawseti(L, -2, C.int(idx))
			idx++
		}
	}
	return 1
}

//export go_count_alive
func go_count_alive(L *C.lua_State) C.int {
	g := getGame(L)
	playerIdx := int(C.luaL_checkinteger(L, 1))
	if playerIdx < 0 || playerIdx > 1 {
		C.lua_pushinteger(L, 0)
		return 1
	}
	count := 0
	for _, ch := range g.Players[playerIdx].Chars {
		if ch.Alive {
			count++
		}
	}
	C.lua_pushinteger(L, C.lua_Integer(count))
	return 1
}

//export go_defer_fn
func go_defer_fn(L *C.lua_State) C.int {
	g := getGame(L)
	if C.lua_type(L, 1) != C.LUA_TFUNCTION {
		return 0
	}
	C.lua_pushvalue(L, 1)
	ref := C.luaL_ref(L, C.LUA_REGISTRYINDEX)

	// 捕获当前 context player
	cn := C.CString("_current_context_player")
	C.wrap_lua_getfield(L, C.LUA_GLOBALSINDEX, cn)
	capturedPlayer := int(C.lua_tointeger(L, -1))
	C.wrap2_lua_pop(L, 1)
	C.free(unsafe.Pointer(cn))

	g.Defer(func(g *engine.Game) {
		// 恢复 context player
		cn2 := C.CString("_current_context_player")
		C.lua_pushinteger(L, C.lua_Integer(capturedPlayer))
		C.wrap2_lua_setglobal(L, cn2)
		C.free(unsafe.Pointer(cn2))

		// 调用 Lua 函数
		C.lua_rawgeti(L, C.LUA_REGISTRYINDEX, ref)
		if C.lua_pcall(L, 0, 0, 0) != 0 {
			C.wrap2_lua_pop(L, 1)
		}
		C.luaL_unref(L, C.LUA_REGISTRYINDEX, ref)
	})
	return 0
}

//export go_add_skill
func go_add_skill(L *C.lua_State) C.int {
	g := getGame(L)
	playerIdx := int(C.luaL_checkinteger(L, 1))
	charIdx := int(C.luaL_checkinteger(L, 2))
	skillID := int(C.luaL_checkinteger(L, 3))
	g.AddSkill(playerIdx, charIdx, skillID)
	return 0
}

//export go_register_counter_char
func go_register_counter_char(L *C.lua_State) C.int {
	g := getGame(L)
	counterID := int(C.get_counter_id(L, 1))
	playerIdx := int(C.luaL_checkinteger(L, 2))
	charIdx := int(C.luaL_checkinteger(L, 3))
	g.RegisterCounterChar(counterID, playerIdx, charIdx)
	return 0
}

//export go_remove_hook
func go_remove_hook(L *C.lua_State) C.int {
	g := getGame(L)
	hookID := int(C.luaL_checkinteger(L, 1))
	g.Hooks.Remove(hookID)
	return 0
}

//export go_add_card
func go_add_card(L *C.lua_State) C.int {
	g := getGame(L)
	cardRef := int(C.luaL_checkinteger(L, 1))
	zone := int(C.luaL_checkinteger(L, 2))
	player := int(C.luaL_checkinteger(L, 3))

	// resolve Player constants
	if player < 0 {
		cn := C.CString("_current_context_player")
		defer C.free(unsafe.Pointer(cn))
		C.wrap_lua_getfield(L, C.LUA_GLOBALSINDEX, cn)
		ctx := int(C.lua_tointeger(L, -1))
		C.wrap2_lua_pop(L, 1)
		if player == -10 { // Player.Own
			player = ctx
		} else if player == -11 { // Player.Enemy
			player = 1 - ctx
		}
	}

	p := &g.Players[player]
	card := engine.CardInst{Ref: cardRef}
	if zone == 1 { // Zone.Hand
		if len(p.Hand) < 10 {
			p.Hand = append(p.Hand, card)
		}
	} else { // Zone.Deck
		p.Deck = append(p.Deck, card)
	}
	return 0
}

//export go_gain_energy
func go_gain_energy(L *C.lua_State) C.int {
	g := getGame(L)
	targetEnergy := int(C.get_counter_id(L, 1))
	value := int(C.luaL_checkinteger(L, 2))
	g.GainEnergy(targetEnergy, value)
	return 0
}

//export go_consume_energy
func go_consume_energy(L *C.lua_State) C.int {
	g := getGame(L)
	targetEnergy := int(C.get_counter_id(L, 1))
	value := int(C.luaL_checkinteger(L, 2))
	g.ConsumeEnergy(targetEnergy, value)
	return 0
}

//export go_set_active_char
func go_set_active_char(L *C.lua_State) C.int {
	g := getGame(L)
	player := int(C.luaL_checkinteger(L, 1))
	charIdx := int(C.luaL_checkinteger(L, 2))
	g.Players[player].ActiveChar = charIdx
	return 0
}

//export go_invoke_skill
func go_invoke_skill(L *C.lua_State) C.int {
	g := getGame(L)
	skillID := int(C.luaL_checkinteger(L, 1))

	// read _current_context_player
	cn := C.CString("_current_context_player")
	defer C.free(unsafe.Pointer(cn))
	C.wrap_lua_getfield(L, C.LUA_GLOBALSINDEX, cn)
	pi := int(C.lua_tointeger(L, -1))
	C.wrap2_lua_pop(L, 1)

	p := &g.Players[pi]

	g.PushEvent(engine.EventFrame{
		ActionCtx: engine.ActUseSkill,
		Source:    engine.SrcSkill,
		Player:    pi,
		Char:      p.ActiveChar,
	})

	ctx := &engine.EventContext{
		ActionCtx:   engine.ActUseSkill,
		Source:      engine.SrcSkill,
		ActorPlayer: pi,
		ActorChar:   p.ActiveChar,
		SkillIndex:  skillID,
		Paid:        true,
	}
	g.FireEventHooks(engine.HookSkillUse, ctx)

	g.PopEvent()

	return 0
}
