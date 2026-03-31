// lua/runtime.go
package lua

import (
	"fmt"
	"os"
	
	"github.com/yuin/gopher-lua"
	"gicg_sim/core"
)

// Runtime Lua 运行时
type Runtime struct {
	L             *lua.LState
	game          *core.GameState
	currentSide   int
	counterUD     map[string]*lua.LUserData // Counter ID -> UserData 缓存
	nextRefID     int                       // 下一个 registry ref ID
	currentDamage *core.DamageInfo          // 当前处理中的伤害信息（用于 damage_calc mod）
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

// loadSystemScripts 加载系统级脚本
func (r *Runtime) loadSystemScripts() {
	// 加载元素反应系统脚本
	scriptPath := "/home/redcontritio/gicg_sim/data/system/elemental_reaction.lua"
	script, err := os.ReadFile(scriptPath)
	if err != nil {
		fmt.Printf("Warning: failed to load system script %s: %v\n", scriptPath, err)
		return
	}
	
	if err := r.L.DoString(string(script)); err != nil {
		fmt.Printf("Warning: failed to execute system script %s: %v\n", scriptPath, err)
	}
}

// Close 关闭
func (r *Runtime) Close() {
	r.L.Close()
}

// SetGame 设置世界
func (r *Runtime) SetGame(game *core.GameState, sideIdx int) {
	r.game = game
	r.currentSide = sideIdx
	
	// 加载系统级脚本（现在 game 已经设置好了）
	r.loadSystemScripts()
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
	// 使用新的 API V2
	r.registerAPIV2()
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
	
	// 创建伤害信息
	dmg := core.NewDamageInfo(amount, element, source, target)
	
	// 设置当前伤害（供 damage_calc mod 使用）
	r.currentDamage = dmg
	
	// 触发 damage_calc mod（元素反应系统在这里处理）
	ctx := &core.ModContext{
		Game:       r.game,
		Side:       currentSide,
		SourceChar: source,
		TargetChar: target,
		DamageInfo: dmg,
	}
	
	// 触发双方的 damage_calc mod
	currentSide.Mods.Trigger(core.EventDamageCalc, ctx)
	if !ctx.Canceled {
		enemySide.Mods.Trigger(core.EventDamageCalc, ctx)
	}
	
	// 使用可能被 mod 修改后的伤害值
	r.game.DealDamage(*dmg)
	
	// 清除当前伤害
	r.currentDamage = nil
	
	return 0
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
	
	// 获取 source（用于系统mod时可能为空）
	source := "system"
	if activeChar := side.GetActiveCharacter(); activeChar != nil {
		source = activeChar.ID
	}
	
	// 创建 Mod
	mod := &core.Mod{
		ID:     fmt.Sprintf("%s_%s", eventName, funcName),
		Source: source,
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

// get_current_damage() -> table
func (r *Runtime) getCurrentDamage(L *lua.LState) int {
	if r.currentDamage == nil {
		L.Push(lua.LNil)
		return 1
	}
	
	// 创建 Lua table 表示伤害信息
	tbl := L.NewTable()
	tbl.RawSetString("amount", lua.LNumber(r.currentDamage.Amount))
	tbl.RawSetString("final_amount", lua.LNumber(r.currentDamage.FinalAmount))
	tbl.RawSetString("element", lua.LNumber(r.currentDamage.Element))
	
	// target 和 source 用 userdata 或者简单的标识
	if r.currentDamage.Target != nil {
		tbl.RawSetString("target", lua.LString(r.currentDamage.Target.ID))
	}
	if r.currentDamage.Source != nil {
		tbl.RawSetString("source", lua.LString(r.currentDamage.Source.ID))
	}
	
	L.Push(tbl)
	return 1
}

// set_damage_amount(amount)
func (r *Runtime) setDamageAmount(L *lua.LState) int {
	if r.currentDamage == nil {
		return 0
	}
	
	amount := L.ToInt(1)
	r.currentDamage.FinalAmount = amount
	return 0
}

// has_aura_on_char(char_id, element) -> bool
func (r *Runtime) hasAuraOnChar(L *lua.LState) int {
	charID := L.ToString(1)
	element := core.Element(L.ToInt(2))
	
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
func (r *Runtime) applyAuraToChar(L *lua.LState) int {
	charID := L.ToString(1)
	element := core.Element(L.ToInt(2))
	duration := L.ToInt(3)
	
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
func (r *Runtime) removeAuraFromChar(L *lua.LState) int {
	charID := L.ToString(1)
	element := core.Element(L.ToInt(2))
	
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
