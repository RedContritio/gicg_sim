// lua/runtime.go
package lua

import (
	"fmt"
	"os"
	"path/filepath"
	
	"github.com/yuin/gopher-lua"
	"gicg_sim/core"
)

// Runtime Lua 运行时
type Runtime struct {
	L                 *lua.LState
	game              *core.GameState
	currentSide       int
	counterUD         map[string]*lua.LUserData // Counter ID -> UserData 缓存
	nextRefID         int                       // 下一个 registry ref ID
	currentDamage     *core.DamageInfo          // 当前处理中的伤害信息（用于 damage_calc mod）
	currentScriptName string                    // 当前执行的脚本名称
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
	scriptPath := filepath.Join(core.GetDataDir(), "system", "elemental_reaction.lua")
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
func (r *Runtime) ExecuteSkillScript(script string, scriptName string) error {
	r.currentScriptName = scriptName
	defer func() { r.currentScriptName = "" }()
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
