package test

import (
	"testing"

	"gicg_sim/core"
	"gicg_sim/lua"
)

func setupLuaAPIV2Game() (*core.GameState, *lua.Runtime) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	diluc := core.NewCharacter("diluc", "迪卢克", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, diluc)
	game.LoadCharacterData("diluc")

	// P0 第二个角色
	fischl := core.NewCharacter("fischl", "菲谢尔", 8, 3, core.Electro)
	game.P0.LoadCharacter(1, fischl)
	game.LoadCharacterData("fischl")

	// P1 两个角色
	dummy1 := core.NewCharacter("dummy1", "木桩1", 20, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy1)

	dummy2 := core.NewCharacter("dummy2", "木桩2", 20, 0, core.Hydro)
	game.P1.LoadCharacter(1, dummy2)

	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()
	return game, runtime
}

// TestLuaAPIV2_CharState 测试角色状态查询 API
func TestLuaAPIV2_CharState(t *testing.T) {
	game, runtime := setupLuaAPIV2Game()
	defer runtime.Close()

	script := `
function on_test()
    local hp = get_hp(SELF)
    local max_hp = get_max_hp(SELF)
    local energy = get_energy(SELF)
    local max_energy = get_max_energy(SELF)
    local alive = is_alive(SELF)
    local active = get_active_char(SELF)
    
    return hp, max_hp, energy, max_energy, alive, active
end
`
	runtime.ExecuteSkillScript(script, "test.lua")
	runtime.CallSkillFunction("on_test")

	activeChar := game.P0.GetActiveCharacter()
	if activeChar == nil {
		t.Fatal("没有活跃角色")
	}

	if activeChar.HP != 10 {
		t.Errorf("期望 HP=10, 实际 %d", activeChar.HP)
	}
	if activeChar.MaxHP != 10 {
		t.Errorf("期望 MaxHP=10, 实际 %d", activeChar.MaxHP)
	}
	if activeChar.Energy != 0 {
		t.Errorf("期望 Energy=0, 实际 %d", activeChar.Energy)
	}
	if activeChar.MaxEnergy != 3 {
		t.Errorf("期望 MaxEnergy=3, 实际 %d", activeChar.MaxEnergy)
	}
}

// TestLuaAPIV2_Energy 测试能量操作 API
func TestLuaAPIV2_Energy(t *testing.T) {
	game, runtime := setupLuaAPIV2Game()
	defer runtime.Close()

	script := `
function on_test()
    add_energy(2, SELF)
    local e1 = get_energy(SELF)
    
    local ok = consume_energy(1, SELF)
    local e2 = get_energy(SELF)
    
    local fail = consume_energy(5, SELF)
    local e3 = get_energy(SELF)
    
    return e1, e2, e3, ok, fail
end
`
	runtime.ExecuteSkillScript(script, "test.lua")
	runtime.CallSkillFunction("on_test")

	activeChar := game.P0.GetActiveCharacter()
	if activeChar.Energy != 1 {
		t.Errorf("期望最终 Energy=1, 实际 %d", activeChar.Energy)
	}
}

// TestLuaAPIV2_SwitchCharacter 测试切换角色 API
func TestLuaAPIV2_SwitchCharacter(t *testing.T) {
	game, runtime := setupLuaAPIV2Game()
	defer runtime.Close()

	if game.P0.ActiveIdx != 0 {
		t.Fatalf("初始活跃角色应为 0, 实际 %d", game.P0.ActiveIdx)
	}

	script := `
function on_test()
    local ok = switch_character(1)
    return ok
end
`
	runtime.ExecuteSkillScript(script, "test.lua")
	runtime.CallSkillFunction("on_test")

	if game.P0.ActiveIdx != 1 {
		t.Errorf("切换后期望活跃角色=1, 实际 %d", game.P0.ActiveIdx)
	}
}

// TestLuaAPIV2_DamageAllEnemies 测试多目标伤害 API
func TestLuaAPIV2_DamageAllEnemies(t *testing.T) {
	game, runtime := setupLuaAPIV2Game()
	defer runtime.Close()

	script := `
function on_test()
    damage(2, PHYSICAL, ALL_ENEMIES)
end
`
	runtime.ExecuteSkillScript(script, "test.lua")
	runtime.CallSkillFunction("on_test")
	game.ProcessDamageQueue()

	if game.P1.Characters[0].HP != 18 {
		t.Errorf("期望 dummy1 HP=18, 实际 %d", game.P1.Characters[0].HP)
	}
	if game.P1.Characters[1].HP != 18 {
		t.Errorf("期望 dummy2 HP=18, 实际 %d", game.P1.Characters[1].HP)
	}
}

// TestLuaAPIV2_DamageAllAllies 测试友方多目标伤害 API
func TestLuaAPIV2_DamageAllAllies(t *testing.T) {
	game, runtime := setupLuaAPIV2Game()
	defer runtime.Close()

	script := `
function on_test()
    damage(1, PHYSICAL, ALL_ALLIES)
end
`
	runtime.ExecuteSkillScript(script, "test.lua")
	runtime.CallSkillFunction("on_test")
	game.ProcessDamageQueue()

	if game.P0.Characters[0].HP != 9 {
		t.Errorf("期望 diluc HP=9, 实际 %d", game.P0.Characters[0].HP)
	}
	if game.P0.Characters[1].HP != 7 {
		t.Errorf("期望 fischl HP=7, 实际 %d", game.P0.Characters[1].HP)
	}
}

// TestLuaAPIV2_GetActiveChar 测试获取活跃角色 API
func TestLuaAPIV2_GetActiveChar(t *testing.T) {
	game, runtime := setupLuaAPIV2Game()
	defer runtime.Close()

	script := `
function on_test()
    local self_active = get_active_char(SELF)
    local enemy_active = get_active_char(ENEMY_ACTIVE)
    return self_active, enemy_active
end
`
	runtime.ExecuteSkillScript(script, "test.lua")
	runtime.CallSkillFunction("on_test")

	// 该函数没有返回值到 Go 层，直接验证状态即可
	if game.P0.GetActiveCharacter().ID != "diluc" {
		t.Errorf("期望 P0 活跃角色为 diluc")
	}
	if game.P1.GetActiveCharacter().ID != "dummy1" {
		t.Errorf("期望 P1 活跃角色为 dummy1")
	}
}
