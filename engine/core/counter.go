// core/counter.go
package core

import "fmt"

// Counter 计数器
type Counter struct {
	ID      string
	Value   int
	Default int
	Max     int
	
	// 所属
	Side *Side
}

// CounterManager 计数器管理器
type CounterManager struct {
	Counters map[string]*Counter
	side     *Side
}

// NewCounterManager 创建计数器管理器
func NewCounterManager(side *Side) *CounterManager {
	return &CounterManager{
		Counters: make(map[string]*Counter),
		side:     side,
	}
}

// Create 创建计数器
func (cm *CounterManager) Create(id string, defaultVal, max int) *Counter {
	counter := &Counter{
		ID:      id,
		Value:   defaultVal,
		Default: defaultVal,
		Max:     max,
		Side:    cm.side,
	}
	cm.Counters[id] = counter
	return counter
}

// Get 获取计数器
func (cm *CounterManager) Get(id string) (*Counter, error) {
	if c, ok := cm.Counters[id]; ok {
		return c, nil
	}
	return nil, fmt.Errorf("counter %s not found", id)
}

// GetValue 获取计数器值（便捷方法，返回0如果不存在）
func (cm *CounterManager) GetValue(id string) int {
	if c, ok := cm.Counters[id]; ok {
		return c.Value
	}
	return 0
}

// MustGet 获取计数器（不存在则panic）
func (cm *CounterManager) MustGet(id string) *Counter {
	c, err := cm.Get(id)
	if err != nil {
		panic(err)
	}
	return c
}

// Set 设置值
func (c *Counter) Set(value int) {
	if c.Max > 0 && value > c.Max {
		value = c.Max
	}
	if value < 0 {
		value = 0
	}
	c.Value = value
}

// Get 获取值
func (c *Counter) Get() int {
	return c.Value
}

// Inc 增加
func (c *Counter) Inc(delta int) {
	c.Set(c.Value + delta)
}

// Dec 减少
func (c *Counter) Dec(delta int) {
	c.Set(c.Value - delta)
}

// Clear 清零
func (c *Counter) Clear() {
	c.Set(0)
}

// Reset 重置为默认值
func (c *Counter) Reset() {
	c.Value = c.Default
}

// CounterManager.ResetAll 重置所有
func (cm *CounterManager) ResetAll() {
	for _, c := range cm.Counters {
		c.Reset()
	}
}
