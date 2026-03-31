// core/counter_scope.go
package core

import (
	"fmt"
	"sync"
)

// CounterScope 计数器作用域类型
type CounterScope string

const (
	ScopeSkill      CounterScope = "SKILL"      // 技能级
	ScopeCharacter  CounterScope = "CHARACTER"  // 角色级
	ScopeSide       CounterScope = "SIDE"       // 阵营级
)

// ScopedCounterManager 带作用域的计数器管理器
type ScopedCounterManager struct {
	// 计数器存储
	// skill_counters: map[sideIdx][charIdx][scriptName][counterName]*Counter
	// char_counters: map[sideIdx][charIdx][counterName]*Counter  
	// side_counters: map[sideIdx][counterName]*Counter
	
	skillCounters map[int]map[int]map[string]map[string]*Counter
	charCounters  map[int]map[int]map[string]*Counter
	sideCounters  map[int]map[string]*Counter
	
	// 记录计数器的初始值（用于校验重复创建）
	initialValues map[string]int
	
	mu sync.RWMutex
}

// NewScopedCounterManager 创建带作用域的计数器管理器
func NewScopedCounterManager() *ScopedCounterManager {
	return &ScopedCounterManager{
		skillCounters: make(map[int]map[int]map[string]map[string]*Counter),
		charCounters:  make(map[int]map[int]map[string]*Counter),
		sideCounters:  make(map[int]map[string]*Counter),
		initialValues: make(map[string]int),
	}
}

// CounterKey 生成计数器的唯一键
func (scm *ScopedCounterManager) CounterKey(scope CounterScope, sideIdx, charIdx int, scriptName, counterName string) string {
	switch scope {
	case ScopeSkill:
		return fmt.Sprintf("skill_%d_%d_%s_%s", sideIdx, charIdx, scriptName, counterName)
	case ScopeCharacter:
		return fmt.Sprintf("char_%d_%d_%s", sideIdx, charIdx, counterName)
	case ScopeSide:
		return fmt.Sprintf("side_%d_%s", sideIdx, counterName)
	default:
		return fmt.Sprintf("unknown_%s_%s", scope, counterName)
	}
}

// GetOrCreate 获取或创建计数器
func (scm *ScopedCounterManager) GetOrCreate(
	scope CounterScope,
	sideIdx, charIdx int,
	scriptName string,
	counterName string,
	initial int,
) (*Counter, error) {
	scm.mu.Lock()
	defer scm.mu.Unlock()
	
	key := scm.CounterKey(scope, sideIdx, charIdx, scriptName, counterName)
	
	// 检查是否已存在
	switch scope {
	case ScopeSkill:
		if scm.skillCounters[sideIdx] == nil {
			scm.skillCounters[sideIdx] = make(map[int]map[string]map[string]*Counter)
		}
		if scm.skillCounters[sideIdx][charIdx] == nil {
			scm.skillCounters[sideIdx][charIdx] = make(map[string]map[string]*Counter)
		}
		if scm.skillCounters[sideIdx][charIdx][scriptName] == nil {
			scm.skillCounters[sideIdx][charIdx][scriptName] = make(map[string]*Counter)
		}
		
		if counter, ok := scm.skillCounters[sideIdx][charIdx][scriptName][counterName]; ok {
			// 校验初始值
			if storedInitial, exists := scm.initialValues[key]; exists && storedInitial != initial {
				return nil, fmt.Errorf("counter %s already exists with different initial value %d (requested %d)", 
					counterName, storedInitial, initial)
			}
			return counter, nil
		}
		
		// 创建新计数器
		counter := &Counter{
			ID:    key,
			Value: initial,
			Max:   999,
		}
		scm.skillCounters[sideIdx][charIdx][scriptName][counterName] = counter
		scm.initialValues[key] = initial
		return counter, nil
		
	case ScopeCharacter:
		if scm.charCounters[sideIdx] == nil {
			scm.charCounters[sideIdx] = make(map[int]map[string]*Counter)
		}
		if scm.charCounters[sideIdx][charIdx] == nil {
			scm.charCounters[sideIdx][charIdx] = make(map[string]*Counter)
		}
		
		if counter, ok := scm.charCounters[sideIdx][charIdx][counterName]; ok {
			if storedInitial, exists := scm.initialValues[key]; exists && storedInitial != initial {
				return nil, fmt.Errorf("counter %s already exists with different initial value %d (requested %d)", 
					counterName, storedInitial, initial)
			}
			return counter, nil
		}
		
		counter := &Counter{
			ID:    key,
			Value: initial,
			Max:   999,
		}
		scm.charCounters[sideIdx][charIdx][counterName] = counter
		scm.initialValues[key] = initial
		return counter, nil
		
	case ScopeSide:
		if scm.sideCounters[sideIdx] == nil {
			scm.sideCounters[sideIdx] = make(map[string]*Counter)
		}
		
		if counter, ok := scm.sideCounters[sideIdx][counterName]; ok {
			if storedInitial, exists := scm.initialValues[key]; exists && storedInitial != initial {
				return nil, fmt.Errorf("counter %s already exists with different initial value %d (requested %d)", 
					counterName, storedInitial, initial)
			}
			return counter, nil
		}
		
		counter := &Counter{
			ID:    key,
			Value: initial,
			Max:   999,
		}
		scm.sideCounters[sideIdx][counterName] = counter
		scm.initialValues[key] = initial
		return counter, nil
		
	default:
		return nil, fmt.Errorf("unknown scope: %s", scope)
	}
}

// Get 获取已存在的计数器
func (scm *ScopedCounterManager) Get(
	scope CounterScope,
	sideIdx, charIdx int,
	scriptName string,
	counterName string,
) (*Counter, bool) {
	scm.mu.RLock()
	defer scm.mu.RUnlock()
	
	switch scope {
	case ScopeSkill:
		if scm.skillCounters[sideIdx] == nil || scm.skillCounters[sideIdx][charIdx] == nil ||
		   scm.skillCounters[sideIdx][charIdx][scriptName] == nil {
			return nil, false
		}
		counter, ok := scm.skillCounters[sideIdx][charIdx][scriptName][counterName]
		return counter, ok
		
	case ScopeCharacter:
		if scm.charCounters[sideIdx] == nil || scm.charCounters[sideIdx][charIdx] == nil {
			return nil, false
		}
		counter, ok := scm.charCounters[sideIdx][charIdx][counterName]
		return counter, ok
		
	case ScopeSide:
		if scm.sideCounters[sideIdx] == nil {
			return nil, false
		}
		counter, ok := scm.sideCounters[sideIdx][counterName]
		return counter, ok
		
	default:
		return nil, false
	}
}
