// lua/runtime.go
package lua

import (
	"fmt"
	
	"github.com/yuin/gopher-lua"
	"gicg_sim/core"
)

// Runtime Lua 运行时
type Runtime struct {
	L           *lua.LState
	game       *core.GameState
	currentSide int
	counterUD   map[string]*lua.LUserData // Counter ID -> UserData 缓存
	nextRefID   int                       // 下一个 registry ref ID
}

// NewRuntime 创建运行时
func NewRuntime() *Runtime {
	r := &Runtime{
		L:         lua.NewState(),
		counterUD: make(map[string]*lua.LUserData),
		nextRefID: 1000, // 从1000开始避免冲突
	}
	r.registerMetatables()
	r.registerAPI()
	return r
}

// Close 关闭
func (r *Runtime) Close() {
	r.L.Close()
}

// SetGame 设置世界
func (r *Runtime) SetGame(game *core.GameState, sideIdx int) {
	r.game = game
	r.currentSide = sideIdx
}

// registerMetatables 注册元表
func (r *Runtime) registerMetatables() {
	// Counter 元表
	mt := r.L.NewTypeMetatable("Counter")
	r.L.SetField(mt, "__index", r.L.SetFuncs(r.L.NewTable(), counterMethods))
}

// counterMethods Counter 方法
var counterMethods = map[string]lua.LGFunction{
	"get":   counterGet,
	"set":   counterSet,
	"inc":   counterInc,
	"dec":   counterDec,
	"clear": counterClear,
}

func checkCounter(L *lua.LState) *core.Counter {
	ud := L.CheckUserData(1)
	if c, ok := ud.Value.(*core.Counter); ok {
		return c
	}
	L.ArgError(1, "Counter expected")
	return nil
}

func counterGet(L *lua.LState) int {
	c := checkCounter(L)
	L.Push(lua.LNumber(c.Get()))
	return 1
}

func counterSet(L *lua.LState) int {
	c := checkCounter(L)
	value := L.CheckInt(2)
	c.Set(value)
	return 0
}

func counterInc(L *lua.LState) int {
	c := checkCounter(L)
	delta := L.CheckInt(2)
	c.Inc(delta)
	return 0
}

func counterDec(L *lua.LState) int {
	c := checkCounter(L)
	delta := L.CheckInt(2)
	c.Dec(delta)
	return 0
}

func counterClear(L *lua.LState) int {
	c := checkCounter(L)
	c.Clear()
	return 0
}

// CounterScope 计数器作用域类型
type CounterScope int

const (
	ScopeSkillUnique CounterScope = iota // 技能特有（默认）
	ScopeCharShared                      // 角色级共享
	ScopeSideShared                      // 阵营级共享
)

// registerAPI 注册 API
func (r *Runtime) registerAPI() {
	// Counter API
	r.L.Register("create_counter", r.createCounter)
	
	// Damage API
	r.L.Register("damage", r.damage)
	r.L.Register("heal", r.heal)
	
	// Mod API
	r.L.Register("attach_mod", r.attachMod)
	
	// Dice API
	r.L.Register("consume_dice", r.consumeDice)
	r.L.Register("get_dice_count", r.getDiceCount)
	r.L.Register("can_afford", r.canAfford)
	
	// Target constants
	r.L.SetGlobal("SELF", lua.LNumber(0))
	r.L.SetGlobal("TARGET", lua.LNumber(1))
	r.L.SetGlobal("ACTIVE_ENEMY", lua.LNumber(2))
	r.L.SetGlobal("ALL_ENEMIES", lua.LNumber(3))
	r.L.SetGlobal("BACK_ENEMIES", lua.LNumber(4))
	r.L.SetGlobal("ALL_ALLIES", lua.LNumber(5))
	
	// Element constants
	r.L.SetGlobal("PYRO", lua.LNumber(core.Pyro))
	r.L.SetGlobal("HYDRO", lua.LNumber(core.Hydro))
	r.L.SetGlobal("CRYO", lua.LNumber(core.Cryo))
	r.L.SetGlobal("ELECTRO", lua.LNumber(core.Electro))
	r.L.SetGlobal("ANEMO", lua.LNumber(core.Anemo))
	r.L.SetGlobal("GEO", lua.LNumber(core.Geo))
	r.L.SetGlobal("DENDRO", lua.LNumber(core.Dendro))
	r.L.SetGlobal("PHYSICAL", lua.LNumber(core.Physical))
	r.L.SetGlobal("PIERCING", lua.LNumber(core.Piercing))
	
	// Dice type constants
	r.L.SetGlobal("DICE_PYRO", lua.LNumber(core.DicePyro))
	r.L.SetGlobal("DICE_HYDRO", lua.LNumber(core.DiceHydro))
	r.L.SetGlobal("DICE_CRYO", lua.LNumber(core.DiceCryo))
	r.L.SetGlobal("DICE_ELECTRO", lua.LNumber(core.DiceElectro))
	r.L.SetGlobal("DICE_ANEMO", lua.LNumber(core.DiceAnemo))
	r.L.SetGlobal("DICE_GEO", lua.LNumber(core.DiceGeo))
	r.L.SetGlobal("DICE_DENDRO", lua.LNumber(core.DiceDendro))
	r.L.SetGlobal("DICE_OMNI", lua.LNumber(core.DiceOmni))
	
	// Counter scope constants
	r.L.SetGlobal("SCOPE_SKILL_UNIQUE", lua.LNumber(0))
	r.L.SetGlobal("SCOPE_CHAR_SHARED", lua.LNumber(1))
	r.L.SetGlobal("SCOPE_SIDE_SHARED", lua.LNumber(2))
	
	// Aura API
	r.L.Register("has_aura", r.hasAura)
	r.L.Register("apply_aura", r.applyAura)
}

// create_counter(name, default, max, scope) -> Counter
// name: 计数器名称（字符串）
// default: 默认值（可选，默认0）
// max: 最大值（可选，默认999）
// scope: 作用域（可选，默认SCOPE_SKILL_UNIQUE）
func (r *Runtime) createCounter(L *lua.LState) int {
	// 参数解析
	name := ""
	if L.GetTop() >= 1 {
		name = L.ToString(1)
	}
	
	defaultVal := 0
	if L.GetTop() >= 2 {
		defaultVal = L.ToInt(2)
	}
	
	maxVal := 999
	if L.GetTop() >= 3 {
		maxVal = L.ToInt(3)
	}
	
	scope := ScopeSkillUnique
	if L.GetTop() >= 4 {
		scope = CounterScope(L.ToInt(4))
	}
	
	side := r.game.GetCurrentSide()
	activeChar := side.GetActiveCharacter()
	
	// 根据作用域生成计数器ID
	var counterID string
	switch scope {
	case ScopeCharShared:
		// 角色级共享：角色ID_计数器名
		counterID = fmt.Sprintf("char_%s_%s", activeChar.ID, name)
	case ScopeSideShared:
		// 阵营级共享：side_索引_计数器名
		counterID = fmt.Sprintf("side_%d_%s", side.Index, name)
	default:
		// 技能特有：角色ID_技能脚本名_计数器名
		// 注意：这里使用调用栈信息来推断技能名，简化处理使用计数器名本身
		counterID = fmt.Sprintf("skill_%s_%s_%s", activeChar.ID, name, name)
	}
	
	// 检查是否已存在（用于共享作用域）
	if existing, err := side.Counters.Get(counterID); err == nil && existing != nil {
		// 返回已存在的计数器
		if ud, ok := r.counterUD[counterID]; ok {
			L.Push(ud)
			return 1
		}
	}
	
	counter := side.Counters.Create(counterID, defaultVal, maxVal)
	
	// 创建 UserData
	ud := L.NewUserData()
	ud.Value = counter
	L.SetMetatable(ud, L.GetTypeMetatable("Counter"))
	
	// 缓存
	r.counterUD[counterID] = ud
	
	L.Push(ud)
	return 1
}

// damage(target_type, amount, element)
func (r *Runtime) damage(L *lua.LState) int {
	targetType := L.ToInt(1)
	amount := L.ToInt(2)
	element := core.Element(L.ToInt(3))
	
	currentSide := r.game.GetCurrentSide()
	enemySide := r.game.GetEnemySide()
	
	var target *core.Character
	
	switch targetType {
	case 0: // SELF
		target = currentSide.GetActiveCharacter()
	case 1: // TARGET (假设是敌方前台)
		target = enemySide.GetActiveCharacter()
	case 2: // ACTIVE_ENEMY
		target = enemySide.GetActiveCharacter()
	default:
		target = enemySide.GetActiveCharacter()
	}
	
	if target == nil {
		return 0
	}
	
	source := currentSide.GetActiveCharacter()
	
	// 处理元素反应
	finalAmount, finalElement := r.applyElementalReaction(target, amount, element)
	
	dmg := core.NewDamageInfo(finalAmount, finalElement, source, target)
	
	r.game.DealDamage(*dmg)
	
	return 0
}

// applyElementalReaction 应用元素反应
// 返回最终伤害值和元素类型
func (r *Runtime) applyElementalReaction(target *core.Character, amount int, element core.Element) (int, core.Element) {
	// 物理伤害不参与元素反应
	if element == core.Physical || element == core.Piercing {
		return amount, element
	}
	
	finalAmount := amount
	
	// 检查目标身上的元素附着，触发反应
	// 蒸发：火+水 或 水+火，伤害*2
	if element == core.Pyro && target.HasAura(core.Hydro) {
		// 火打水（蒸发）
		finalAmount = amount * 2
		target.RemoveAura(core.Hydro) // 消耗水附着
		fmt.Printf("💧🔥 蒸发！伤害 %d -> %d\n", amount, finalAmount)
	} else if element == core.Hydro && target.HasAura(core.Pyro) {
		// 水打火（蒸发）
		finalAmount = amount * 2
		target.RemoveAura(core.Pyro) // 消耗火附着
		fmt.Printf("🔥💧 蒸发！伤害 %d -> %d\n", amount, finalAmount)
	}
	
	// 融化：火+冰 或 冰+火
	if element == core.Pyro && target.HasAura(core.Cryo) {
		// 火打冰（融化），伤害*2
		finalAmount = amount * 2
		target.RemoveAura(core.Cryo)
		fmt.Printf("❄️🔥 融化！伤害 %d -> %d\n", amount, finalAmount)
	} else if element == core.Cryo && target.HasAura(core.Pyro) {
		// 冰打火（融化），伤害*1.5
		finalAmount = amount * 3 / 2
		target.RemoveAura(core.Pyro)
		fmt.Printf("🔥❄️ 融化！伤害 %d -> %d\n", amount, finalAmount)
	}
	
	// 超导：冰+雷，伤害+1，附加物理伤害
	if (element == core.Cryo && target.HasAura(core.Electro)) ||
	   (element == core.Electro && target.HasAura(core.Cryo)) {
		finalAmount = amount + 1
		if element == core.Cryo {
			target.RemoveAura(core.Electro)
		} else {
			target.RemoveAura(core.Cryo)
		}
		fmt.Printf("⚡❄️ 超导！伤害 %d -> %d\n", amount, finalAmount)
		// TODO: 附加1点物理穿透伤害给所有敌人
	}
	
	// 超载：火+雷，伤害+2
	if (element == core.Pyro && target.HasAura(core.Electro)) ||
	   (element == core.Electro && target.HasAura(core.Pyro)) {
		finalAmount = amount + 2
		if element == core.Pyro {
			target.RemoveAura(core.Electro)
		} else {
			target.RemoveAura(core.Pyro)
		}
		fmt.Printf("⚡🔥 超载！伤害 %d -> %d\n", amount, finalAmount)
		// TODO: 强制切换目标角色
	}
	
	// 感电：水+雷，伤害+1，附加穿透伤害
	if (element == core.Hydro && target.HasAura(core.Electro)) ||
	   (element == core.Electro && target.HasAura(core.Hydro)) {
		finalAmount = amount + 1
		if element == core.Hydro {
			target.RemoveAura(core.Electro)
		} else {
			target.RemoveAura(core.Hydro)
		}
		fmt.Printf("⚡💧 感电！伤害 %d -> %d\n", amount, finalAmount)
		// TODO: 对后台敌人造成1点穿透伤害
	}
	
	// 冻结：水+冰
	if (element == core.Hydro && target.HasAura(core.Cryo)) ||
	   (element == core.Cryo && target.HasAura(core.Hydro)) {
		target.RemoveAura(core.Hydro)
		target.RemoveAura(core.Cryo)
		// 添加冻元素附着
		target.AddAura(core.Cryo, 1) // 冻元素持续1回合
		fmt.Printf("❄️💧 冻结！\n")
		// TODO: 冻结状态下无法行动，碎冰造成额外伤害
	}
	
	// 如果没有发生反应，给目标添加元素附着
	if finalAmount == amount {
		target.AddAura(element, 2) // 元素附着持续2回合
	}
	
	return finalAmount, element
}

// heal(target_type, amount)
func (r *Runtime) heal(L *lua.LState) int {
	targetType := L.ToInt(1)
	amount := L.ToInt(2)
	
	currentSide := r.game.GetCurrentSide()
	
	var target *core.Character
	
	switch targetType {
	case 0: // SELF
		target = currentSide.GetActiveCharacter()
	case 2: // ACTIVE_ENEMY
		target = r.game.GetEnemySide().GetActiveCharacter()
	default:
		target = currentSide.GetActiveCharacter()
	}
	
	if target != nil {
		target.HP += amount
		if target.HP > target.MaxHP {
			target.HP = target.MaxHP
		}
	}
	
	return 0
}

// attach_mod(event_name, func_name)
func (r *Runtime) attachMod(L *lua.LState) int {
	eventName := L.ToString(1)
	funcName := L.ToString(2)
	
	side := r.game.GetCurrentSide()
	
	// 获取 Lua 函数
	fn := L.GetGlobal(funcName)
	if fn == lua.LNil {
		fmt.Printf("Warning: function %s not found\n", funcName)
		return 0
	}
	
	// 获取 Registry 表
	registry := L.Get(lua.RegistryIndex).(*lua.LTable)
	
	// 生成唯一引用 ID
	refID := r.nextRefID
	r.nextRefID++
	
	// 保存函数到 registry
	registry.RawSetInt(refID, fn)
	
	// 记住当前 side 索引
	sideIdx := r.currentSide
	
	// 创建 Mod
	mod := &core.Mod{
		ID:     fmt.Sprintf("%s_%s", eventName, funcName),
		Source: side.Characters[0].ID,
		Event:  core.EventType(eventName),
		Handler: func(ctx *core.ModContext) {
			// 设置正确的 currentSide
			oldSide := r.currentSide
			r.currentSide = sideIdx
			
			// 从 registry 获取函数
			L := r.L
			reg := L.Get(lua.RegistryIndex).(*lua.LTable)
			fn := reg.RawGetInt(refID)
			
			if fn == lua.LNil {
				r.currentSide = oldSide
				return
			}
			
			// 调用 Lua 函数
			L.Push(fn)
			if err := L.PCall(0, 0, nil); err != nil {
				fmt.Printf("Mod handler error: %v\n", err)
			}
			
			// 恢复 currentSide
			r.currentSide = oldSide
		},
	}
	
	side.Mods.Attach(mod)
	
	return 0
}

// consume_dice({element=count, ...}) -> bool
// 消耗指定元素和数量的骰子
// 例如: consume_dice({[ELECTRO]=3, [PYRO]=2})
func (r *Runtime) consumeDice(L *lua.LState) int {
	if L.GetTop() < 1 {
		L.Push(lua.LBool(false))
		return 1
	}
	
	// 解析费用表
	cost := make(map[core.Element]int)
	table := L.ToTable(1)
	if table != nil {
		table.ForEach(func(key, value lua.LValue) {
			elem := core.Element(lua.LVAsNumber(key))
			count := lua.LVAsNumber(value)
			cost[elem] = int(count)
		})
	}
	
	side := r.game.GetCurrentSide()
	result := side.Dices.ConsumeElementCost(cost)
	
	L.Push(lua.LBool(result))
	return 1
}

// get_dice_count(element) -> count
// 获取指定元素的骰子数量
func (r *Runtime) getDiceCount(L *lua.LState) int {
	if L.GetTop() < 1 {
		L.Push(lua.LNumber(0))
		return 1
	}
	
	element := core.Element(L.ToInt(1))
	side := r.game.GetCurrentSide()
	
	var count int
	if element < 0 {
		// 获取所有骰子数量
		count = side.Dices.GetTotal()
	} else {
		// 获取指定元素骰子数量
		count = side.Dices.GetCount(core.ElementToDice(element))
	}
	
	L.Push(lua.LNumber(count))
	return 1
}

// can_afford({element=count, ...}) -> bool
// 检查是否有足够的骰子
func (r *Runtime) canAfford(L *lua.LState) int {
	if L.GetTop() < 1 {
		L.Push(lua.LBool(true))
		return 1
	}
	
	// 解析费用表
	cost := make(map[core.Element]int)
	table := L.ToTable(1)
	if table != nil {
		table.ForEach(func(key, value lua.LValue) {
			elem := core.Element(lua.LVAsNumber(key))
			count := lua.LVAsNumber(value)
			cost[elem] = int(count)
		})
	}
	
	side := r.game.GetCurrentSide()
	result := side.Dices.CanAfford(cost)
	
	L.Push(lua.LBool(result))
	return 1
}

// has_aura(target_type, element) -> bool
func (r *Runtime) hasAura(L *lua.LState) int {
	targetType := L.ToInt(1)
	element := core.Element(L.ToInt(2))
	
	currentSide := r.game.GetCurrentSide()
	enemySide := r.game.GetEnemySide()
	
	var target *core.Character
	switch targetType {
	case 0: // SELF
		target = currentSide.GetActiveCharacter()
	case 2: // ACTIVE_ENEMY
		target = enemySide.GetActiveCharacter()
	default:
		target = enemySide.GetActiveCharacter()
	}
	
	if target == nil {
		L.Push(lua.LBool(false))
		return 1
	}
	
	L.Push(lua.LBool(target.HasAura(element)))
	return 1
}

// apply_aura(target_type, element, duration)
func (r *Runtime) applyAura(L *lua.LState) int {
	targetType := L.ToInt(1)
	element := core.Element(L.ToInt(2))
	duration := L.ToInt(3)
	
	currentSide := r.game.GetCurrentSide()
	enemySide := r.game.GetEnemySide()
	
	var target *core.Character
	switch targetType {
	case 0: // SELF
		target = currentSide.GetActiveCharacter()
	case 2: // ACTIVE_ENEMY
		target = enemySide.GetActiveCharacter()
	default:
		target = enemySide.GetActiveCharacter()
	}
	
	if target != nil {
		target.AddAura(element, duration)
	}
	
	return 0
}

// ExecuteScript 执行脚本
func (r *Runtime) ExecuteScript(script string) error {
	return r.L.DoString(script)
}

// ExecuteCharacterScript 预执行角色脚本
// 在角色加载时调用，创建 Counter 和 Mod
func (r *Runtime) ExecuteCharacterScript(script string) error {
	return r.L.DoString(script)
}

// ExecuteSkillScript 执行技能脚本
// 在技能使用时调用，定义技能效果函数
func (r *Runtime) ExecuteSkillScript(script string) error {
	return r.L.DoString(script)
}

// CallSkillFunction 调用技能函数
func (r *Runtime) CallSkillFunction(name string) error {
	fn := r.L.GetGlobal(name)
	if fn == lua.LNil {
		return fmt.Errorf("function %s not found", name)
	}
	
	r.L.Push(fn)
	return r.L.PCall(0, 0, nil)
}

// CallFunction 调用函数（通用方法，供测试使用）
func (r *Runtime) CallFunction(name string) error {
	fn := r.L.GetGlobal(name)
	if fn == lua.LNil {
		return fmt.Errorf("function %s not found", name)
	}
	
	r.L.Push(fn)
	return r.L.PCall(0, 0, nil)
}

// ExecuteCardScript 执行卡牌脚本
func (r *Runtime) ExecuteCardScript(script string) error {
	return r.L.DoString(script)
}

// CallCardFunction 调用卡牌函数
func (r *Runtime) CallCardFunction(name string) error {
	fn := r.L.GetGlobal(name)
	if fn == lua.LNil {
		// 函数不存在也返回 nil（比如碌碌无为没有 on_play）
		return nil
	}
	
	r.L.Push(fn)
	return r.L.PCall(0, 0, nil)
}
