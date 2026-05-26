// adapter.go — Paradigm interface + registry。
//
// 主体 paradigm-agnostic 干净:pool 只 spawn N goroutine 调 paradigm.Run,paradigm 自己 own
// 完整 episode lifecycle(NewEpisode + state machine + actor/opp turn 切换 + transition push)。
// 这跟 design.md D3 一致:"主体 paradigm-agnostic + per-paradigm adapter"。
//
// 注册方式:gicg_actor/dmc/init() 在 import 时调 RegisterParadigm("dmc", &DMCParadigm{}),
// cmd/gicg_actor/main.go import dmc package 触发 init,gicg_actor.Run 通过 GetParadigm
// 名字 lookup 拿到 instance。 az/ppo/cfr/bc 同模式 P2 ship。 I29 redesign P3 (2026-05-25)
// 前 gicg_actor/capi/main.go (cgo c-shared export) 是注册触发入口,redesign 后 cgo 路径
// 退役,改 cmd/gicg_actor standalone subprocess 入口。

package gicg_actor

import (
	"context"
	"fmt"
	"sync"
)

// Paradigm 是一个 RL 算法 paradigm 的 actor-side 实现。 主体只调 Name() + Run()。
//
// Run 是 actor goroutine 主循环 — 跑一组 episode(直到 ctx cancel)。 paradigm 自己:
//   - 创建 engine instance(via `import "<module>/gicg_engine"`,native call)
//   - 走 actor turn(encode obs + 调 InferenceClient.Request + decode action + engine.Step)
//   - 走 opp turn(paradigm 自己的 opp baseline,DMC F1-D*,AZ MCTS 等)
//   - paradigm 自己 encode wire frame → 调 sink.Push(clientID, seq, encoded_bytes)
//   - 跨 episode reuse engine pool(P1.1b 简化:每 episode new 一个;P3 优化)
//
// Run 返 err 表示 fatal — actor goroutine 退出,主体 log + 不重启(P1.1b 简化)。
// ctx.Done() 表示 stop_pool 信号,paradigm 必须及时退出(检查频率 ≥ 每 episode)。
//
// Configure 在 pool spawn actor 之前调一次,传 paradigm-specific JSON cfg。 paradigm 自
// 反序列化(scenario spec / opp 参数 / max_actions 等)。 Configure 失败 → StartPool 返
// error code,actor 不 spawn。 主体 paradigm-agnostic,不知 cfg schema。
type Paradigm interface {
	Name() string
	Configure(jsonCfg string) error
	// Run 接 InferenceRequester (interface) + TransitionSink (interface) — 两 transport
	// 抽象,paradigm impl 不区分 underlying TCP / SHM。 TCP path 起 *TransitionWriterTCP,
	// SHM path 起 *TransitionWriterShm,两者均实现 TransitionSink。 paradigm 端 encode
	// 完整 wire frame 后调 sink.Push(clientID, seq, payload),透传无解析。
	Run(ctx context.Context, actorID int, infCli InferenceRequester, sink TransitionSink) error
}

// paradigmRegistry — 全局单例,paradigm package init() 注册。 名字 conflict raise(防 silent
// override)。
var (
	registryMu sync.RWMutex
	registry   = map[string]Paradigm{}
)

// RegisterParadigm 注册一个 paradigm。 paradigm package init() 调:
//
//	func init() { gicg_actor.RegisterParadigm("dmc", &DMCParadigm{}) }
//
// 重复注册 same name panic(防 silent override)— init 期 panic 让 build 时立即失败。
func RegisterParadigm(name string, p Paradigm) {
	if name == "" {
		panic("RegisterParadigm: empty name")
	}
	if p == nil {
		panic("RegisterParadigm: nil paradigm")
	}
	registryMu.Lock()
	defer registryMu.Unlock()
	if _, exists := registry[name]; exists {
		panic(fmt.Sprintf("RegisterParadigm: duplicate name %q", name))
	}
	registry[name] = p
}

// GetParadigm — name lookup,返 nil 表示 unknown(caller fail loud)。
func GetParadigm(name string) Paradigm {
	registryMu.RLock()
	defer registryMu.RUnlock()
	return registry[name]
}

// RegisteredParadigms 返当前 registry 中所有 paradigm 名(用于 ctypes API 列出可用 paradigm)。
func RegisteredParadigms() []string {
	registryMu.RLock()
	defer registryMu.RUnlock()
	names := make([]string, 0, len(registry))
	for k := range registry {
		names = append(names, k)
	}
	return names
}
