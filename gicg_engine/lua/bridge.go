package lua

/*
#include <lua.h>
#include <lualib.h>
#include <lauxlib.h>

// Forward declarations for Go callbacks
extern int go_create_counter(lua_State *L);
extern int go_deal_damage(lua_State *L);
extern int go_heal(lua_State *L);
extern int go_set_winner(lua_State *L);
extern int go_set_alive(lua_State *L);
extern int go_draw_card(lua_State *L);
extern int go_cancel(lua_State *L);
extern int go_get_enemy_alive(lua_State *L);
extern int go_get_own_alive(lua_State *L);
extern int go_request_switch(lua_State *L);
extern int go_get_actor_player(lua_State *L);
extern int go_get_active_char(lua_State *L);
extern int go_force_switch_next(lua_State *L);
extern int go_get_round(lua_State *L);
extern int go_get_turn(lua_State *L);
extern int go_get_first_end(lua_State *L);
extern int go_count_alive(lua_State *L);
extern int go_defer_fn(lua_State *L);
extern int go_remove_hook(lua_State *L);
extern int go_register_counter_char(lua_State *L);
extern int go_add_skill(lua_State *L);
extern int go_get_next_char(lua_State *L);
extern int go_invoke_skill(lua_State *L);
extern int go_add_card(lua_State *L);
extern int go_gain_energy(lua_State *L);
extern int go_consume_energy(lua_State *L);
extern int go_on_before_energy_gain(lua_State *L);
extern int go_on_after_energy_gain(lua_State *L);
extern int go_on_before_energy_consume(lua_State *L);
extern int go_on_after_energy_consume(lua_State *L);
extern int go_set_active_char(lua_State *L);

// Counter methods
extern int go_counter_get(lua_State *L);
extern int go_counter_min(lua_State *L);
extern int go_counter_max(lua_State *L);
extern int go_counter_set(lua_State *L);
extern int go_counter_add(lua_State *L);
extern int go_counter_sub(lua_State *L);

// Hook registration
extern int go_on_before_write(lua_State *L);
extern int go_on_after_write(lua_State *L);
extern int go_on_damage_boost(lua_State *L);
extern int go_on_reaction_damage(lua_State *L);
extern int go_on_damage_reduce(lua_State *L);
extern int go_on_after_damage(lua_State *L);
extern int go_on_before_heal(lua_State *L);
extern int go_on_after_heal(lua_State *L);
extern int go_on_action_check(lua_State *L);
extern int go_on_action_prepare(lua_State *L);
extern int go_on_skill_use(lua_State *L);
extern int go_on_card_play(lua_State *L);
extern int go_on_switch(lua_State *L);
extern int go_on_before_turn_flip(lua_State *L);
extern int go_on_round_start(lua_State *L);
extern int go_on_round_end(lua_State *L);
extern int go_on_round_end_post_summon(lua_State *L);
extern int go_on_round_end_decay(lua_State *L);
extern int go_on_round_end_final(lua_State *L);
extern int go_on_action(lua_State *L);

// Register a C function as global
static void register_func(lua_State *L, const char *name, lua_CFunction fn) {
	lua_pushcfunction(L, fn);
	lua_setglobal(L, name);
}
*/
import "C"

import (
	"fmt"
	"gicg_mono/gicg_engine"
	"sync"
	"unsafe"
)

// gameRegistry 存储 lua_State → *engine.Game 的映射
// 使 Go 回调能找到对应的 Game 实例
var (
	gameMu       sync.RWMutex
	gameRegistry = map[uintptr]*engine.Game{}
)

func registerGame(L *C.lua_State, g *engine.Game) {
	gameMu.Lock()
	gameRegistry[uintptr(unsafe.Pointer(L))] = g
	gameMu.Unlock()
}

func unregisterGame(L *C.lua_State) {
	gameMu.Lock()
	delete(gameRegistry, uintptr(unsafe.Pointer(L)))
	gameMu.Unlock()
}

func getGame(L *C.lua_State) *engine.Game {
	gameMu.RLock()
	g := gameRegistry[uintptr(unsafe.Pointer(L))]
	gameMu.RUnlock()
	return g
}

// preludeLua 定义所有枚举常量和辅助函数。
// strict_enum 创建只读 table，访问不存在的 key 报错。
var preludeLua = fmt.Sprintf(`
local function strict_enum(name, t)
  local proxy = {}
  return setmetatable(proxy, {
    __index = function(_, k)
      local v = t[k]
      if v == nil then
        error(name .. " has no member '" .. tostring(k) .. "'", 2)
      end
      return v
    end,
    __newindex = function()
      error(name .. " is read-only", 2)
    end,
  })
end

Element = strict_enum("Element", {
  None     = %d,
  Fire     = %d,
  Ice      = %d,
  Water    = %d,
  Electro  = %d,
  Geo      = %d,
  Physical = %d,
})

Op = strict_enum("Op", {
  Set = %d,
  Add = %d,
  Sub = %d,
})

Action = strict_enum("Action", {
  UseSkill        = %d,
  PlayCard        = %d,
  Switch          = %d,
  ForcedDeath     = %d,
  ForcedReaction  = %d,
})

Source = strict_enum("Source", {
  Skill    = %d,
  Card     = %d,
  Status   = %d,
  Summon   = %d,
  Support  = %d,
  Reaction = %d,
})

Scope = strict_enum("Scope", {
  Self         = 1,
  ActiveStatus = 2,
  PerChar      = 3,
  PerOwnChar   = 4,
  PerEnemyChar = 5,
  PerPlayer    = 6,
  Global       = 7,
})

Filter = strict_enum("Filter", {
  Self   = %d,
  Active = %d,
})

Target = strict_enum("Target", {
  EnemyActive    = 1,
  EnemyAll       = 2,
  OwnAll         = 3,
  EnemyNonActive = 4,
  OwnActive      = 5,
  CardTarget     = 6,
})

ActionKind = strict_enum("ActionKind", {
  Skill   = %d,
  Card    = %d,
  Switch  = %d,
  EndTurn = %d,
})

Weapon = strict_enum("Weapon", {
  None  = 0,
  Sword = 1,
  Polearm = 2,
  Bow   = 3,
})

Tag = strict_enum("Tag", {
  Summon  = 1,
  Element = 2,
  Equip   = 3,
  Food    = 4,
  Support = 5,
  Shield  = 6,
})

Player = strict_enum("Player", {
  Own   = -10,
  Enemy = -11,
  All   = -12,
})

Zone = strict_enum("Zone", {
  Hand = 1,
  Deck = 2,
})
`,
	// Element
	engine.ElemNone, engine.ElemFire, engine.ElemIce, engine.ElemWater,
	engine.ElemElectro, engine.ElemGeo, engine.ElemPhysical,
	// Op
	engine.OpSet, engine.OpAdd, engine.OpSub,
	// Action
	engine.ActUseSkill, engine.ActPlayCard, engine.ActSwitch,
	engine.ActForcedDeath, engine.ActForcedReaction,
	// Source
	engine.SrcSkill, engine.SrcCard, engine.SrcStatus,
	engine.SrcSummon, engine.SrcSupport, engine.SrcReaction,
	// Filter
	engine.FilterSelf, engine.FilterActive,
	// ActionKind
	engine.ActionSkill, engine.ActionCard, engine.ActionSwitch, engine.ActionEndTurn,
)

var preludeFiles = []string{
	"counter.lua",
	"char.lua",
	"damage.lua",
	"skill.lua",
	"card.lua",
	"sandbox.lua",
	"death.lua",
}


// RegisterPrelude 将所有 DSL 函数和常量注册到 Lua 状态
func RegisterPrelude(s *State, g *engine.Game) {
	L := s.L
	registerGame(L, g)

	// 注册 Go 回调函数（必须在 declareLua 之前，因为 declareLua 使用 _raw_create_counter 等）
	C.register_func(L, C.CString("_raw_create_counter"), C.lua_CFunction(C.go_create_counter))
	C.register_func(L, C.CString("_raw_deal_damage"), C.lua_CFunction(C.go_deal_damage))
	C.register_func(L, C.CString("_raw_heal"), C.lua_CFunction(C.go_heal))
	C.register_func(L, C.CString("set_winner"), C.lua_CFunction(C.go_set_winner))
	C.register_func(L, C.CString("set_alive"), C.lua_CFunction(C.go_set_alive))
	C.register_func(L, C.CString("draw_card"), C.lua_CFunction(C.go_draw_card))
	C.register_func(L, C.CString("cancel"), C.lua_CFunction(C.go_cancel))
	C.register_func(L, C.CString("get_enemy_alive"), C.lua_CFunction(C.go_get_enemy_alive))
	C.register_func(L, C.CString("get_own_alive"), C.lua_CFunction(C.go_get_own_alive))
	C.register_func(L, C.CString("request_switch"), C.lua_CFunction(C.go_request_switch))
	C.register_func(L, C.CString("get_actor_player"), C.lua_CFunction(C.go_get_actor_player))
	C.register_func(L, C.CString("get_active_char"), C.lua_CFunction(C.go_get_active_char))
	C.register_func(L, C.CString("force_switch_next"), C.lua_CFunction(C.go_force_switch_next))
	C.register_func(L, C.CString("get_round"), C.lua_CFunction(C.go_get_round))
	C.register_func(L, C.CString("get_turn"), C.lua_CFunction(C.go_get_turn))
	C.register_func(L, C.CString("get_first_end"), C.lua_CFunction(C.go_get_first_end))
	C.register_func(L, C.CString("count_alive"), C.lua_CFunction(C.go_count_alive))
	C.register_func(L, C.CString("defer_fn"), C.lua_CFunction(C.go_defer_fn))
	C.register_func(L, C.CString("remove_hook"), C.lua_CFunction(C.go_remove_hook))
	C.register_func(L, C.CString("_register_counter_char"), C.lua_CFunction(C.go_register_counter_char))
	C.register_func(L, C.CString("_add_skill"), C.lua_CFunction(C.go_add_skill))
	C.register_func(L, C.CString("get_next_char"), C.lua_CFunction(C.go_get_next_char))
	C.register_func(L, C.CString("_invoke_skill"), C.lua_CFunction(C.go_invoke_skill))
	C.register_func(L, C.CString("_add_card"), C.lua_CFunction(C.go_add_card))
	C.register_func(L, C.CString("_gain_energy"), C.lua_CFunction(C.go_gain_energy))
	C.register_func(L, C.CString("_consume_energy"), C.lua_CFunction(C.go_consume_energy))
	C.register_func(L, C.CString("on_before_energy_gain"), C.lua_CFunction(C.go_on_before_energy_gain))
	C.register_func(L, C.CString("on_after_energy_gain"), C.lua_CFunction(C.go_on_after_energy_gain))
	C.register_func(L, C.CString("on_before_energy_consume"), C.lua_CFunction(C.go_on_before_energy_consume))
	C.register_func(L, C.CString("on_after_energy_consume"), C.lua_CFunction(C.go_on_after_energy_consume))
	C.register_func(L, C.CString("_set_active_char"), C.lua_CFunction(C.go_set_active_char))

	C.register_func(L, C.CString("_raw_on_before_write"), C.lua_CFunction(C.go_on_before_write))
	C.register_func(L, C.CString("_raw_on_after_write"), C.lua_CFunction(C.go_on_after_write))
	C.register_func(L, C.CString("on_damage_boost"), C.lua_CFunction(C.go_on_damage_boost))
	C.register_func(L, C.CString("on_reaction_damage"), C.lua_CFunction(C.go_on_reaction_damage))
	C.register_func(L, C.CString("on_damage_reduce"), C.lua_CFunction(C.go_on_damage_reduce))
	C.register_func(L, C.CString("on_after_damage"), C.lua_CFunction(C.go_on_after_damage))
	C.register_func(L, C.CString("on_before_heal"), C.lua_CFunction(C.go_on_before_heal))
	C.register_func(L, C.CString("on_after_heal"), C.lua_CFunction(C.go_on_after_heal))
	C.register_func(L, C.CString("on_action_check"), C.lua_CFunction(C.go_on_action_check))
	C.register_func(L, C.CString("on_action_prepare"), C.lua_CFunction(C.go_on_action_prepare))
	C.register_func(L, C.CString("on_skill_use"), C.lua_CFunction(C.go_on_skill_use))
	C.register_func(L, C.CString("on_card_play"), C.lua_CFunction(C.go_on_card_play))
	C.register_func(L, C.CString("on_switch"), C.lua_CFunction(C.go_on_switch))
	C.register_func(L, C.CString("on_before_turn_flip"), C.lua_CFunction(C.go_on_before_turn_flip))
	C.register_func(L, C.CString("on_round_start"), C.lua_CFunction(C.go_on_round_start))
	C.register_func(L, C.CString("on_round_end"), C.lua_CFunction(C.go_on_round_end))
	C.register_func(L, C.CString("on_round_end_post_summon"), C.lua_CFunction(C.go_on_round_end_post_summon))
	C.register_func(L, C.CString("on_round_end_decay"), C.lua_CFunction(C.go_on_round_end_decay))
	C.register_func(L, C.CString("on_round_end_final"), C.lua_CFunction(C.go_on_round_end_final))
	C.register_func(L, C.CString("on_action"), C.lua_CFunction(C.go_on_action))

	if err := s.DoString(preludeLua); err != nil {
		panic("prelude init failed: " + err.Error())
	}

	for _, f := range preludeFiles {
		if err := s.DoFile(preludeDir + "/" + f); err != nil {
			panic("prelude " + f + ": " + err.Error())
		}
	}
}

var preludeDir = "../prelude"

func SetPreludeDir(dir string) {
	preludeDir = dir
}

// Cleanup 清理注册
func Cleanup(s *State) {
	unregisterGame(s.L)
}
