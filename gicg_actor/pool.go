// Package gicg_actor — Go-native RL actor pool for GICG.
//
// 边界:本 package 含所有 RL-specific Go code(actor goroutine pool / paradigm adapter /
// IPC client / transition writer)。 import "gicg_mono/gicg_engine" 单向依赖,engine
// package 不知道 actor 存在(RL-zero awareness)。
//
// I29 redesign (2026-05-25):cmd/gicg_actor standalone executable 走 Run(ctx, cfg, sinks),
// 不依赖 package 全局 singleton。 P3 ship 已退役 capi/ c-shared ABI (StartPool /
// StartPoolWithConfig / StopPool / AliveCount / Hello + singleton mu/running/cancel/wg
// 全局 state),master Python 不再 ctypes load libgicg_actor — DMCGoSubprocessCollector
// 经 subprocess.Popen 起本 binary,Run() 是唯一入口。
package gicg_actor

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"sync/atomic"
	"syscall"
)

// Config 是 pool 启动配置。 cmd/gicg_actor parseConfig 反序列化 stdin JSON 组装。
type Config struct {
	NActors       int    // 起 N 个 actor goroutine
	ParadigmName  string // adapter registry lookup key
	InfServerAddr string // "host:port" — Go socket connect Python InfServer (TCP path)
	TransSinkAddr string // "host:port" — Go socket connect Python trainer transition sink (TCP path)
	IOTimeoutMs   int    // 默认 30000 ms
	// ParadigmConfigJSON 透传给 paradigm.Configure(). paradigm 自反序列化 — 主体不知 schema.
	// DMC schema 见 gicg_actor/dmc/paradigm.go:DMCConfig。
	ParadigmConfigJSON string

	// BaseActorID — 起 N actor goroutine 时,各 goroutine 的 actorID 偏移基址。
	// I29 R7.2 (2026-05-25):master Python 把 N independent Go subprocess 起来 mimic Python mp 的
	// N+2 OS process 拓扑,每 subprocess NActors=1 + BaseActorID=i ∈ [0, N) — 保
	// clientID = baseActorID + i = i 在跨 subprocess 唯一(否则 N subprocess 都 actorID=0,
	// 共享 SHM ring 上 (cid, ep_id) key 撞,DMC assembler 把 N actor 的 episode 混一起)。
	// 默认 0(单 subprocess 路径 / R7.2 之前的行为)。
	BaseActorID int
}

// aliveActors — 当前在跑的 actor goroutine 数(atomic)。 runInternal 进 spawn 时置 NActors,
// 每个 actorLoop 退出(fatal 或 ctx-cancel)即 -1。 测试可读 (内部 sanity invariant —
// 健康运行 == NActors;< NActors 说明有 actor 静默 fatal 死亡)。 cmd/gicg_actor 外部不 expose
// (master 经 SHMRing trans 缺失 自然 surface alive 异常)。
var aliveActors int32

func init() {
	initSignalHandler()
}

// initSignalHandler 在 package init 时装 SIGTERM no-op handler。
//
// 背景(memory: feedback_go_cgo_signal_handler):c-shared Go lib 加载进 Python 时,Python
// 装的 no-op SIGTERM handler 让 Go runtime 不 override → proc.terminate() 双方都不响应 → mp
// test hang。 Go init goroutine signal.Notify → os.Exit(0) 必装,让 Go runtime 接管
// SIGTERM 时优雅退出而非 hang。
//
// I29 redesign 后 master 不再 cgo load lib (cgo path 退役),此 handler 仍生效在
// cmd/gicg_actor standalone binary 中 — cmd/gicg_actor/main.go 自己也装一份 (defense in
// depth,显式 cancel ctx + 让 paradigm.Run 走 graceful path)。
func initSignalHandler() {
	c := make(chan os.Signal, 1)
	signal.Notify(c, syscall.SIGTERM)
	go func() {
		<-c
		os.Exit(0)
	}()
}

// Run — I29 redesign (2026-05-25) standalone executable 入口。 不依赖 package singleton。
//
// sinks 长度必须 == cfg.NActors (per-actor sink) 或 == 1 (所有 actor 共享同一 sink,SHM ring
// MPSC mode)。 infReqs 必须 == cfg.NActors (per-actor inference client)。
//
// 行为:registry lookup ParadigmName + paradigm.Configure + N actor goroutine 跑 paradigm.Run。
//
// 阻塞直到所有 actor goroutine 完成 (ctx cancel 或 paradigm.Run 返回)。
// 返 err = paradigm 配置错 / unknown paradigm;actor goroutine 内 err 仅 log 不上抛
// (单 actor fatal 不杀整 pool,与 pre-redesign capi 行为一致)。
func Run(ctx context.Context, cfg Config, infReqs []InferenceRequester, sinks []TransitionSink) error {
	if cfg.NActors <= 0 {
		return fmt.Errorf("Run: NActors must be > 0, got %d", cfg.NActors)
	}
	if cfg.ParadigmName == "" {
		return fmt.Errorf("Run: ParadigmName must be set (placeholder PoC path 已退役)")
	}
	if len(sinks) != cfg.NActors && len(sinks) != 1 {
		return fmt.Errorf("Run: sinks len %d, want NActors=%d or 1 (shared)", len(sinks), cfg.NActors)
	}
	if len(infReqs) != cfg.NActors {
		return fmt.Errorf("Run: infReqs len %d, want NActors=%d", len(infReqs), cfg.NActors)
	}
	return runInternal(ctx, cfg, infReqs, sinks)
}

// runInternal — Run 共用内核 (无 validation)。 caller 已 validate cfg + 已 alloc sinks/infReqs。
func runInternal(ctx context.Context, cfg Config, infReqs []InferenceRequester, sinks []TransitionSink) error {
	paradigm := GetParadigm(cfg.ParadigmName)
	if paradigm == nil {
		return fmt.Errorf("runInternal: unknown paradigm %q", cfg.ParadigmName)
	}
	if cfg.ParadigmConfigJSON != "" {
		if err := paradigm.Configure(cfg.ParadigmConfigJSON); err != nil {
			return fmt.Errorf("runInternal: paradigm configure: %w", err)
		}
	}

	// 1 sink + N actor → broadcast (SHM ring MPSC)。 否则 per-actor index。
	sinkFor := func(id int) TransitionSink {
		if len(sinks) == 1 {
			return sinks[0]
		}
		return sinks[id]
	}

	var runWg sync.WaitGroup
	atomic.StoreInt32(&aliveActors, int32(cfg.NActors))
	for i := range cfg.NActors {
		runWg.Add(1)
		// actorID = BaseActorID + i — I29 R7.2 让 N independent subprocess 起后
		// 跨 subprocess 的 clientID 唯一(避免 SHM ring (cid, ep_id) key 撞)。
		// infReqs / sinkFor 仍按 process 内 local index i — InferenceClient + SHM ring
		// 是 per-subprocess 资源,而 DMC paradigm 经 actorID 把 clientID 写到 wire payload。
		actorID := cfg.BaseActorID + i
		go func(localIdx, externalID int) {
			defer runWg.Done()
			defer atomic.AddInt32(&aliveActors, -1)
			runActor(ctx, externalID, paradigm, infReqs[localIdx], sinkFor(localIdx))
		}(i, actorID)
	}
	runWg.Wait()
	return nil
}

// runActor — 单 actor goroutine 主体,直接 paradigm.Run + err log。
func runActor(ctx context.Context, id int, paradigm Paradigm, infCli InferenceRequester, sink TransitionSink) {
	err := paradigm.Run(ctx, id, infCli, sink)
	if err != nil && ctx.Err() == nil {
		fmt.Fprintf(os.Stderr, "[gicg_actor] actor=%d paradigm=%s fatal: %v\n",
			id, paradigm.Name(), err)
	}
}
