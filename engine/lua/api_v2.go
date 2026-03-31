// lua/api_v2.go
// 新的 Lua API V2 实现

package lua

import (
	"fmt"
	
	"github.com/yuin/gopher-lua"
	"gicg_sim/core"
)

// registerAPIV2 注册新的 API
func (r *Runtime) registerAPIV2() {
	// 伤害与治疗
	r.L.Register("damage", r.damageV2)
	r.L.Register("heal", r.healV2)
	
	// 元素附着
	r.L.Register("apply_aura", r.applyAuraV2)
	r.L.Register("has_aura", r.hasAuraV2)
	r.L.Register("remove_aura", r.removeAuraV2)
	
	// 计数器
	r.L.Register("create_counter", r.createCounterV2)
	
	// Mod 系统
	r.L.Register("attach_mod", r.attachModV2)
	r.L.Register("get_damage_info", r.getDamageInfoV2)
	r.L.Register("get_current_damage", r.getDamageInfoV2)  // 别名
	r.L.Register("set_damage_amount", r.setDamageAmountV2)
	
	// 元素反应专用API（通过角色ID操作）
	r.L.Register("has_aura_on_char", r.hasAuraOnCharV2)
	r.L.Register("apply_aura_to_char", r.applyAuraToCharV2)
	r.L.Register("remove_aura_from_char", r.removeAuraFromCharV2)
	
	// 骰子
	r.L.Register("get_dice_count", r.getDiceCountV2)
	r.L.Register("consume_dice", r.consumeDiceV2)
	r.L.Register("can_afford_dice", r.canAffordDiceV2)
	
	// 目标常量
	r.L.SetGlobal("SELF", lua.LNumber(0))
	r.L.SetGlobal("ENEMY_ACTIVE", lua.LNumber(1))
	r.L.SetGlobal("ENEMY_BACK", lua.LNumber(2))
	r.L.SetGlobal("ALL_ENEMIES", lua.LNumber(3))
	r.L.SetGlobal("ALL_ALLIES", lua.LNumber(4))
	
	// 元素常量
	r.L.SetGlobal("PHYSICAL", lua.LNumber(core.Physical))
	r.L.SetGlobal("PYRO", lua.LNumber(core.Pyro))
	r.L.SetGlobal("HYDRO", lua.LNumber(core.Hydro))
	r.L.SetGlobal("CRYO", lua.LNumber(core.Cryo))
	r.L.SetGlobal("ELECTRO", lua.LNumber(core.Electro))
	r.L.SetGlobal("ANEMO", lua.LNumber(core.Anemo))
	r.L.SetGlobal("GEO", lua.LNumber(core.Geo))
	r.L.SetGlobal("DENDRO", lua.LNumber(core.Dendro))
	r.L.SetGlobal("PIERCING", lua.LNumber(core.Piercing))
	
	// 骰子常量
	r.L.SetGlobal("DICE_PYRO", lua.LNumber(core.DicePyro))
	r.L.SetGlobal("DICE_HYDRO", lua.LNumber(core.DiceHydro))
	r.L.SetGlobal("DICE_CRYO", lua.LNumber(core.DiceCryo))
	r.L.SetGlobal("DICE_ELECTRO", lua.LNumber(core.DiceElectro))
	r.L.SetGlobal("DICE_ANEMO", lua.LNumber(core.DiceAnemo))
	r.L.SetGlobal("DICE_GEO", lua.LNumber(core.DiceGeo))
	r.L.SetGlobal("DICE_DENDRO", lua.LNumber(core.DiceDendro))
	r.L.SetGlobal("DICE_OMNI", lua.LNumber(core.DiceOmni))
	r.L.SetGlobal("ANY", lua.LNumber(-1))  // 任意骰
	
	// 计数器 Scope 常量
	r.L.SetGlobal("SCOPE_SKILL", lua.LNumber(0))
	r.L.SetGlobal("SCOPE_CHARACTER", lua.LNumber(1))
	r.L.SetGlobal("SCOPE_SIDE", lua.LNumber(2))
	
	// 计数器操作函数
	r.L.Register("get_counter", r.getCounterV2)
	r.L.Register("set_counter", r.setCounterV2)
	r.L.Register("modify_counter", r.modifyCounterV2)
	
	// 角色状态查询
	r.L.Register("get_hp", r.getHPV2)
	r.L.Register("get_max_hp", r.getMaxHPV2)
	r.L.Register("get_energy", r.getEnergyV2)
	r.L.Register("get_max_energy", r.getMaxEnergyV2)
	r.L.Register("is_alive", r.isAliveV2)
	r.L.Register("get_active_char", r.getActiveCharV2)
	
	// 能量操作
	r.L.Register("add_energy", r.addEnergyV2)
	r.L.Register("consume_energy", r.consumeEnergyV2)
	
	// 切换角色
	r.L.Register("switch_character", r.switchCharacterV2)
}

// damage(amount, element=PHYSICAL, target=ENEMY_ACTIVE)
func (r *Runtime) damageV2(L *lua.LState) int {
	amount := L.CheckInt(1)
	
	element := core.Physical
	if L.GetTop() >= 2 {
		element = core.Element(L.ToInt(2))
	}
	
	targetType := 1 // ENEMY_ACTIVE
	if L.GetTop() >= 3 {
		targetType = L.ToInt(3)
	}
	
	source := r.game.GetCurrentSide().GetActiveCharacter()
	
	switch targetType {
	case 3: // ALL_ENEMIES
		enemySide := r.game.GetEnemySide()
		for _, char := range enemySide.Characters {
			if char != nil && char.IsAlive() {
				r.dealDamageToTarget(amount, element, source, char)
			}
		}
	case 4: // ALL_ALLIES
		currentSide := r.game.GetCurrentSide()
		for _, char := range currentSide.Characters {
			if char != nil && char.IsAlive() {
				r.dealDamageToTarget(amount, element, source, char)
			}
		}
	default:
		target := r.resolveTarget(targetType)
		if target != nil {
			r.dealDamageToTarget(amount, element, source, target)
		}
	}
	
	return 0
}

// dealDamageToTarget 对单个目标造成伤害并触发 mod
func (r *Runtime) dealDamageToTarget(amount int, element core.Element, source, target *core.Character) {
	dmg := core.NewDamageInfo(amount, element, source, target)
	r.currentDamage = dmg
	
	ctx := &core.ModContext{
		Game:       r.game,
		Side:       r.game.GetCurrentSide(),
		SourceChar: source,
		TargetChar: target,
		DamageInfo: dmg,
	}
	
	currentSide := r.game.GetCurrentSide()
	enemySide := r.game.GetEnemySide()
	
	currentSide.Mods.Trigger(core.EventDamageCalc, ctx)
	if !ctx.Canceled {
		enemySide.Mods.Trigger(core.EventDamageCalc, ctx)
	}
	
	r.game.DealDamage(*dmg)
	r.currentDamage = nil
}

// heal(amount, target=SELF)
func (r *Runtime) healV2(L *lua.LState) int {
	amount := L.CheckInt(1)
	
	targetType := 0 // SELF
	if L.GetTop() >= 2 {
		targetType = L.ToInt(2)
	}
	
	target := r.resolveTarget(targetType)
	if target != nil {
		target.HP += amount
		if target.HP > target.MaxHP {
			target.HP = target.MaxHP
		}
	}
	
	return 0
}

// resolveTarget 根据类型解析目标
func (r *Runtime) resolveTarget(targetType int) *core.Character {
	currentSide := r.game.GetCurrentSide()
	enemySide := r.game.GetEnemySide()
	
	switch targetType {
	case 0: // SELF
		return currentSide.GetActiveCharacter()
	case 1: // ENEMY_ACTIVE
		return enemySide.GetActiveCharacter()
	case 2: // ENEMY_BACK
		// 返回第一个后台敌人
		for i, char := range enemySide.Characters {
			if i != enemySide.ActiveIdx && char != nil && char.IsAlive() {
				return char
			}
		}
		return nil
	case 3: // ALL_ENEMIES - 返回前台作为代表（实际逻辑需要特殊处理）
		return enemySide.GetActiveCharacter()
	case 4: // ALL_ALLIES
		return currentSide.GetActiveCharacter()
	default:
		return enemySide.GetActiveCharacter()
	}
}

// apply_aura(element, duration=2, target=ENEMY_ACTIVE)
func (r *Runtime) applyAuraV2(L *lua.LState) int {
	element := core.Element(L.CheckInt(1))
	
	duration := 2
	if L.GetTop() >= 2 {
		duration = L.ToInt(2)
	}
	
	targetType := 1 // ENEMY_ACTIVE
	if L.GetTop() >= 3 {
		targetType = L.ToInt(3)
	}
	
	target := r.resolveTarget(targetType)
	if target != nil {
		target.AddAura(element, duration)
	}
	
	return 0
}

// has_aura(element, target=ENEMY_ACTIVE) -> bool
func (r *Runtime) hasAuraV2(L *lua.LState) int {
	element := core.Element(L.CheckInt(1))
	
	targetType := 1 // ENEMY_ACTIVE
	if L.GetTop() >= 2 {
		targetType = L.ToInt(2)
	}
	
	target := r.resolveTarget(targetType)
	if target == nil {
		L.Push(lua.LBool(false))
		return 1
	}
	
	L.Push(lua.LBool(target.HasAura(element)))
	return 1
}

// remove_aura(element, target=ENEMY_ACTIVE)
func (r *Runtime) removeAuraV2(L *lua.LState) int {
	element := core.Element(L.CheckInt(1))
	
	targetType := 1 // ENEMY_ACTIVE
	if L.GetTop() >= 2 {
		targetType = L.ToInt(2)
	}
	
	target := r.resolveTarget(targetType)
	if target != nil {
		target.RemoveAura(element)
	}
	
	return 0
}

// create_counter(name, initial=0, scope=SCOPE_SKILL)
func (r *Runtime) createCounterV2(L *lua.LState) int {
	name := L.CheckString(1)
	
	initial := 0
	if L.GetTop() >= 2 {
		initial = L.ToInt(2)
	}
	
	// 默认使用 SKILL scope
	scopeIdx := 0
	if L.GetTop() >= 3 {
		scopeIdx = L.ToInt(3)
	}
	
	// 将数字转换为 scope 字符串
	var scopeStr string
	switch scopeIdx {
	case 0:
		scopeStr = "SKILL"
	case 1:
		scopeStr = "CHARACTER"
	case 2:
		scopeStr = "SIDE"
	default:
		scopeStr = "SKILL"
	}
	
	scope := core.CounterScope(scopeStr)
	
	// 获取当前上下文信息
	currentSide := r.game.GetCurrentSide()
	sideIdx := currentSide.Index
	
	var charIdx int
	if activeChar := currentSide.GetActiveCharacter(); activeChar != nil {
		charIdx = activeChar.CharIndex
	}
	
	// 获取脚本名称（优先使用当前执行的脚本名）
	scriptName := r.currentScriptName
	if scriptName == "" {
		scriptName = name
	}
	
	// 获取或创建计数器
	counter, err := currentSide.ScopedCounters.GetOrCreate(scope, sideIdx, charIdx, scriptName, name, initial)
	if err != nil {
		// 报错但继续执行，返回 nil
		fmt.Printf("Error creating counter: %v\n", err)
		L.Push(lua.LNil)
		return 1
	}
	
	// 创建 UserData
	ud := L.NewUserData()
	ud.Value = counter
	L.SetMetatable(ud, L.GetTypeMetatable("Counter"))
	
	L.Push(ud)
	return 1
}

// attach_mod(event, func_name)
func (r *Runtime) attachModV2(L *lua.LState) int {
	eventName := L.CheckString(1)
	funcName := L.CheckString(2)
	
	side := r.game.GetCurrentSide()
	
	fn := r.L.GetGlobal(funcName)
	if fn == lua.LNil {
		fmt.Printf("Warning: function %s not found\n", funcName)
		return 0
	}
	
	// 获取 Registry 表
	registry := r.L.Get(lua.RegistryIndex).(*lua.LTable)
	
	// 生成唯一引用 ID
	refID := r.nextRefID
	r.nextRefID++
	
	// 保存函数到 registry
	registry.RawSetInt(refID, fn)
	
	sideIdx := r.currentSide
	
	// 创建 Mod
	mod := &core.Mod{
		ID:     fmt.Sprintf("%s_%s", eventName, funcName),
		Source: "system",
		Event:  core.EventType(eventName),
		Handler: func(ctx *core.ModContext) {
			oldSide := r.currentSide
			r.currentSide = sideIdx
			
			L := r.L
			reg := L.Get(lua.RegistryIndex).(*lua.LTable)
			fn := reg.RawGetInt(refID)
			
			if fn == lua.LNil {
				r.currentSide = oldSide
				return
			}
			
			L.Push(fn)
			if err := L.PCall(0, 0, nil); err != nil {
				fmt.Printf("Mod handler error: %v\n", err)
			}
			
			r.currentSide = oldSide
		},
	}
	
	side.Mods.Attach(mod)
	return 0
}

// get_damage_info() -> table
func (r *Runtime) getDamageInfoV2(L *lua.LState) int {
	if r.currentDamage == nil {
		L.Push(lua.LNil)
		return 1
	}
	
	tbl := L.NewTable()
	tbl.RawSetString("amount", lua.LNumber(r.currentDamage.Amount))
	tbl.RawSetString("final_amount", lua.LNumber(r.currentDamage.FinalAmount))
	tbl.RawSetString("element", lua.LNumber(r.currentDamage.Element))
	
	if r.currentDamage.Target != nil {
		tbl.RawSetString("target_id", lua.LString(r.currentDamage.Target.ID))
	}
	if r.currentDamage.Source != nil {
		tbl.RawSetString("source_id", lua.LString(r.currentDamage.Source.ID))
	}
	
	L.Push(tbl)
	return 1
}

// set_damage_amount(amount)
func (r *Runtime) setDamageAmountV2(L *lua.LState) int {
	if r.currentDamage == nil {
		return 0
	}
	
	amount := L.CheckInt(1)
	r.currentDamage.FinalAmount = amount
	return 0
}

// get_dice_count(element=ANY) -> int
func (r *Runtime) getDiceCountV2(L *lua.LState) int {
	element := -1 // ANY
	if L.GetTop() >= 1 && L.Get(1) != lua.LNil {
		element = L.ToInt(1)
	}
	
	side := r.game.GetCurrentSide()
	
	var count int
	if element == -1 {
		count = side.Dices.GetTotal()
	} else {
		count = side.Dices.GetCount(core.DiceType(element))
	}
	
	L.Push(lua.LNumber(count))
	return 1
}

// consume_dice(amount, element=ANY) -> bool
func (r *Runtime) consumeDiceV2(L *lua.LState) int {
	amount := L.CheckInt(1)
	
	element := -1 // ANY
	if L.GetTop() >= 2 {
		element = L.ToInt(2)
	}
	
	side := r.game.GetCurrentSide()
	
	// 检查是否有足够的骰子
	var available int
	if element == -1 {
		available = side.Dices.GetTotal()
	} else {
		available = side.Dices.GetCount(core.DiceType(element))
	}
	
	if available < amount {
		L.Push(lua.LBool(false))
		return 1
	}
	
	// 移除指定元素的骰子
	removed := 0
	newDices := make([]*core.Dice, 0, len(side.Dices.Dices))
	for _, dice := range side.Dices.Dices {
		if removed < amount && (element == -1 || int(dice.Type) == element) {
			removed++
			continue
		}
		newDices = append(newDices, dice)
	}
	side.Dices.Dices = newDices
	
	L.Push(lua.LBool(true))
	return 1
}

// can_afford_dice(amount, element=ANY) -> bool
func (r *Runtime) canAffordDiceV2(L *lua.LState) int {
	amount := L.CheckInt(1)
	
	element := -1 // ANY
	if L.GetTop() >= 2 {
		element = L.ToInt(2)
	}
	
	side := r.game.GetCurrentSide()
	
	var available int
	if element == -1 {
		available = side.Dices.GetTotal()
	} else {
		available = side.Dices.GetCount(core.DiceType(element))
	}
	
	L.Push(lua.LBool(available >= amount))
	return 1
}

// get_counter(counter_ud) -> int
func (r *Runtime) getCounterV2(L *lua.LState) int {
	ud := L.CheckUserData(1)
	counter, ok := ud.Value.(*core.Counter)
	if !ok {
		L.Push(lua.LNumber(0))
		return 1
	}
	
	L.Push(lua.LNumber(counter.Get()))
	return 1
}

// set_counter(counter_ud, value)
func (r *Runtime) setCounterV2(L *lua.LState) int {
	ud := L.CheckUserData(1)
	value := L.CheckInt(2)
	
	counter, ok := ud.Value.(*core.Counter)
	if !ok {
		return 0
	}
	
	counter.Set(value)
	return 0
}

// modify_counter(counter_ud, delta) -> new_value
func (r *Runtime) modifyCounterV2(L *lua.LState) int {
	ud := L.CheckUserData(1)
	delta := L.CheckInt(2)
	
	counter, ok := ud.Value.(*core.Counter)
	if !ok {
		L.Push(lua.LNumber(0))
		return 1
	}
	
	counter.Inc(delta)
	L.Push(lua.LNumber(counter.Get()))
	return 1
}


// has_aura_on_char(char_id, element) -> bool
func (r *Runtime) hasAuraOnCharV2(L *lua.LState) int {
	charID := L.CheckString(1)
	element := core.Element(L.CheckInt(2))
	
	// 查找角色
	var target *core.Character
	for _, side := range []*core.Side{r.game.P0, r.game.P1} {
		for _, char := range side.Characters {
			if char != nil && char.ID == charID {
				target = char
				break
			}
		}
		if target != nil {
			break
		}
	}
	
	if target == nil {
		L.Push(lua.LBool(false))
		return 1
	}
	
	L.Push(lua.LBool(target.HasAura(element)))
	return 1
}

// apply_aura_to_char(char_id, element, duration)
func (r *Runtime) applyAuraToCharV2(L *lua.LState) int {
	charID := L.CheckString(1)
	element := core.Element(L.CheckInt(2))
	duration := L.CheckInt(3)
	
	// 查找角色
	var target *core.Character
	for _, side := range []*core.Side{r.game.P0, r.game.P1} {
		for _, char := range side.Characters {
			if char != nil && char.ID == charID {
				target = char
				break
			}
		}
		if target != nil {
			break
		}
	}
	
	if target != nil {
		target.AddAura(element, duration)
	}
	
	return 0
}

// remove_aura_from_char(char_id, element)
func (r *Runtime) removeAuraFromCharV2(L *lua.LState) int {
	charID := L.CheckString(1)
	element := core.Element(L.CheckInt(2))
	
	// 查找角色
	var target *core.Character
	for _, side := range []*core.Side{r.game.P0, r.game.P1} {
		for _, char := range side.Characters {
			if char != nil && char.ID == charID {
				target = char
				break
			}
		}
		if target != nil {
			break
		}
	}
	
	if target != nil {
		target.RemoveAura(element)
	}
	
	return 0
}

// get_hp(target=ENEMY_ACTIVE) -> int
func (r *Runtime) getHPV2(L *lua.LState) int {
	targetType := 1
	if L.GetTop() >= 1 {
		targetType = L.ToInt(1)
	}
	target := r.resolveTarget(targetType)
	if target == nil {
		L.Push(lua.LNumber(0))
		return 1
	}
	L.Push(lua.LNumber(target.HP))
	return 1
}

// get_max_hp(target=ENEMY_ACTIVE) -> int
func (r *Runtime) getMaxHPV2(L *lua.LState) int {
	targetType := 1
	if L.GetTop() >= 1 {
		targetType = L.ToInt(1)
	}
	target := r.resolveTarget(targetType)
	if target == nil {
		L.Push(lua.LNumber(0))
		return 1
	}
	L.Push(lua.LNumber(target.MaxHP))
	return 1
}

// get_energy(target=ENEMY_ACTIVE) -> int
func (r *Runtime) getEnergyV2(L *lua.LState) int {
	targetType := 1
	if L.GetTop() >= 1 {
		targetType = L.ToInt(1)
	}
	target := r.resolveTarget(targetType)
	if target == nil {
		L.Push(lua.LNumber(0))
		return 1
	}
	L.Push(lua.LNumber(target.Energy))
	return 1
}

// get_max_energy(target=ENEMY_ACTIVE) -> int
func (r *Runtime) getMaxEnergyV2(L *lua.LState) int {
	targetType := 1
	if L.GetTop() >= 1 {
		targetType = L.ToInt(1)
	}
	target := r.resolveTarget(targetType)
	if target == nil {
		L.Push(lua.LNumber(0))
		return 1
	}
	L.Push(lua.LNumber(target.MaxEnergy))
	return 1
}

// is_alive(target=ENEMY_ACTIVE) -> bool
func (r *Runtime) isAliveV2(L *lua.LState) int {
	targetType := 1
	if L.GetTop() >= 1 {
		targetType = L.ToInt(1)
	}
	target := r.resolveTarget(targetType)
	if target == nil {
		L.Push(lua.LBool(false))
		return 1
	}
	L.Push(lua.LBool(target.IsAlive()))
	return 1
}

// get_active_char(side=SELF) -> string
func (r *Runtime) getActiveCharV2(L *lua.LState) int {
	sideIdx := 0 // SELF
	if L.GetTop() >= 1 {
		sideIdx = L.ToInt(1)
	}
	var side *core.Side
	if sideIdx == 0 {
		side = r.game.GetCurrentSide()
	} else {
		side = r.game.GetEnemySide()
	}
	activeChar := side.GetActiveCharacter()
	if activeChar == nil {
		L.Push(lua.LNil)
		return 1
	}
	L.Push(lua.LString(activeChar.ID))
	return 1
}

// add_energy(amount, target=SELF)
func (r *Runtime) addEnergyV2(L *lua.LState) int {
	amount := L.CheckInt(1)
	targetType := 0
	if L.GetTop() >= 2 {
		targetType = L.ToInt(2)
	}
	target := r.resolveTarget(targetType)
	if target != nil {
		target.Energy += amount
		if target.Energy > target.MaxEnergy {
			target.Energy = target.MaxEnergy
		}
	}
	return 0
}

// consume_energy(amount, target=SELF) -> bool
func (r *Runtime) consumeEnergyV2(L *lua.LState) int {
	amount := L.CheckInt(1)
	targetType := 0
	if L.GetTop() >= 2 {
		targetType = L.ToInt(2)
	}
	target := r.resolveTarget(targetType)
	if target == nil || target.Energy < amount {
		L.Push(lua.LBool(false))
		return 1
	}
	target.Energy -= amount
	L.Push(lua.LBool(true))
	return 1
}

// switch_character(char_idx) -> bool
func (r *Runtime) switchCharacterV2(L *lua.LState) int {
	charIdx := L.CheckInt(1)
	side := r.game.GetCurrentSide()
	result := side.SwitchCharacter(charIdx)
	L.Push(lua.LBool(result))
	return 1
}
