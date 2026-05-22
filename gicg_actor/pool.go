// Package gicg_actor — Go-native RL actor pool for GICG.
//
// 边界:本 package 含所有 RL-specific Go code(actor goroutine pool / paradigm adapter /
// IPC client / transition writer)。 import "gicg_mono/gicg_engine" 单向依赖,engine
// package 不知道 actor 存在(RL-zero awareness)。
//
// 通过 ./capi build 出 libgicg_actor.dll/.dylib,Python master ctypes load 调 C API
// (gicg_actor_start_pool / gicg_actor_stop_pool 等)。 与现有 libgicg(gicg_engine/capi/)
// 独立 build。 详 openspec/changes/i29-go-actor-pool/design.md D4。
package gicg_actor

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// Config 是 pool 启动配置。 ctypes API 传字符串/int,Go side 组装成 Config。
type Config struct {
	NActors       int    // 起 N 个 actor goroutine
	ParadigmName  string // adapter registry lookup key
	InfServerAddr string // "host:port" — Go socket connect Python InfServer
	TransSinkAddr string // "host:port" — Go socket connect Python trainer transition sink
	IOTimeoutMs   int    // 默认 30000 ms
	// ParadigmConfigJSON 透传给 paradigm.Configure(). paradigm 自反序列化 — 主体不知 schema.
	// DMC schema 见 gicg_actor/dmc/paradigm.go:DMCConfig。
	ParadigmConfigJSON string
}

// pool 是全局单例。 Python master 同一时刻只起一组 actor pool;ctypes API 是 stateless
// 函数,实际 state 跑在本 package 全局变量里。 mu 保护并发 start/stop。
var (
	mu         sync.Mutex
	running    bool
	cancel     context.CancelFunc
	wg         sync.WaitGroup
	currentCfg Config
	currentInf *InferenceClient
	currentTW  *TransitionWriter
	// aliveActors — 当前在跑的 actor goroutine 数(atomic)。 StartPool 置 NActors,
	// 每个 actorLoop 退出(fatal 或 ctx-cancel)即 -1。 Python 经 C API 读之 —— actor
	// 静默 fatal 死亡(穷举审计 #E2)从此可见(I29 T-RR.7)。
	aliveActors int32
)

func init() {
	initSignalHandler()
}

// initSignalHandler 在 package init 时装 SIGTERM no-op handler。
//
// 背景(memory: feedback_go_cgo_signal_handler):c-shared Go lib 加载进 Python 时,Python
// 装的 no-op SIGTERM handler 让 Go runtime 不 override → proc.terminate() 双方都不响应 → mp
// test hang。 Go init goroutine signal.Notify → os.Exit(0) 必装,让 Go runtime 接管
// SIGTERM 时优雅退出而非 hang。
func initSignalHandler() {
	c := make(chan os.Signal, 1)
	signal.Notify(c, syscall.SIGTERM)
	go func() {
		<-c
		os.Exit(0)
	}()
}

// StartPool 起 N actor goroutine。 P0 占位仍保留(hello-world test 用):若 ParadigmName
// 为空,跑 placeholder(单 goroutine print "ok" 即等 stop)。 P1.1b 起,真 paradigm 调
// paradigm.Run(ctx, ...)。
//
// 返 0 = success,非 0 = 错误码:
//
//	1 = already running
//	2 = invalid n_actors
//	3 = unknown paradigm name
//	4 = inference client connect failed
//	5 = transition writer connect failed
//	6 = paradigm.Configure failed (bad JSON / unknown field)
func StartPool(n int) int {
	return StartPoolWithConfig(Config{NActors: n})
}

// transitionWriteTimeout — transition push 的 socket write deadline。 远长于 inference
// 的 IOTimeoutMs:transition 是 fire-and-forget,backpressure 下 write 阻塞是正常的
// (Python 端有界 queue 满 → listener 停 drain socket → TCP 回压),不该触发 deadline
// 把 actor 当 fatal 杀掉。 此值只兜底「consumer 真死」—— driver 健康时每个 collect
// 周期(秒级)就 drain queue,绝不逼近 5 min(I29 T-RR.3 #12)。
const transitionWriteTimeout = 5 * time.Minute

// StartPoolWithConfig — production 入口(ctypes API 调本函数)。
func StartPoolWithConfig(cfg Config) int {
	mu.Lock()
	defer mu.Unlock()
	if running {
		return 1
	}
	if cfg.NActors <= 0 {
		return 2
	}
	timeout := time.Duration(cfg.IOTimeoutMs) * time.Millisecond
	ctx, cancelFn := context.WithCancel(context.Background())

	// Paradigm == "" — P0 占位路径(hello-world test 用)。 P1.1b 起 production 必传 ParadigmName。
	var paradigm Paradigm
	if cfg.ParadigmName != "" {
		paradigm = GetParadigm(cfg.ParadigmName)
		if paradigm == nil {
			cancelFn()
			return 3
		}
		if err := paradigm.Configure(cfg.ParadigmConfigJSON); err != nil {
			fmt.Fprintf(os.Stderr, "[gicg_actor] paradigm configure failed: %v\n", err)
			cancelFn()
			return 6
		}
		// Connect InfServer + TransSink upfront — fail-loud if address bad,actor
		// goroutine 起跑后才发现 socket 不通会有 N 个 partial-init 状态。
		if cfg.InfServerAddr != "" {
			currentInf = NewInferenceClient(cfg.InfServerAddr, timeout)
			if err := currentInf.Connect(); err != nil {
				fmt.Fprintf(os.Stderr, "[gicg_actor] inf connect failed: %v\n", err)
				cancelFn()
				currentInf = nil
				return 4
			}
		}
		if cfg.TransSinkAddr != "" {
			// transitionWriteTimeout(5 min)而非 inference 的 timeout(IOTimeoutMs):
			// backpressure 下 transition write 阻塞是正常的,不该触发 deadline 杀 actor。
			currentTW = NewTransitionWriter(cfg.TransSinkAddr, transitionWriteTimeout)
			if err := currentTW.Connect(); err != nil {
				fmt.Fprintf(os.Stderr, "[gicg_actor] trans connect failed: %v\n", err)
				cancelFn()
				if currentInf != nil {
					_ = currentInf.Close()
					currentInf = nil
				}
				currentTW = nil
				return 5
			}
		}
	}

	cancel = cancelFn
	currentCfg = cfg
	atomic.StoreInt32(&aliveActors, int32(cfg.NActors))
	for i := range cfg.NActors {
		wg.Add(1)
		go actorLoop(ctx, i, paradigm)
	}
	running = true
	return 0
}

// StopPool 触发所有 actor goroutine 优雅退出 + 等齐 join。 返 0 = success,1 = not running。
func StopPool() int {
	mu.Lock()
	defer mu.Unlock()
	if !running {
		return 1
	}
	if cancel != nil {
		cancel()
	}
	wg.Wait()
	if currentInf != nil {
		_ = currentInf.Close()
		currentInf = nil
	}
	if currentTW != nil {
		_ = currentTW.Close()
		currentTW = nil
	}
	running = false
	cancel = nil
	currentCfg = Config{}
	return 0
}

func actorLoop(ctx context.Context, id int, paradigm Paradigm) {
	defer wg.Done()
	// LIFO defer:本行(注册在 wg.Done 之后)先于 wg.Done 执行 —— StopPool 的
	// wg.Wait() 返回时 aliveActors 必已归 0。
	defer atomic.AddInt32(&aliveActors, -1)
	if paradigm == nil {
		// P0 placeholder — hello-world 路径(无 paradigm config)。
		fmt.Printf("[gicg_actor] ok actor=%d\n", id)
		<-ctx.Done()
		return
	}
	// P1.1b production path — paradigm own 完整 episode lifecycle。
	err := paradigm.Run(ctx, id, currentInf, currentTW)
	if err != nil && ctx.Err() == nil {
		fmt.Fprintf(os.Stderr, "[gicg_actor] actor=%d paradigm=%s fatal: %v\n",
			id, paradigm.Name(), err)
	}
}

// Hello 是最简 ctypes 烟雾测:Python 调返 0 验证 ctypes load + Go runtime init OK。
func Hello() int {
	return 0
}

// AliveCount 返回当前在跑的 actor goroutine 数。 StartPool 后 == NActors;某 actor 因
// fatal error 退出则减(clean exit 只在 StopPool ctx-cancel 时发生)。 故 pool 运行期间
// AliveCount < NActors 即说明有 actor 静默 fatal 死亡 —— Python 侧据此可见(I29 T-RR.7,
// 穷举审计 #E2:actor 死亡静默 → 吞吐看似慢实为 actor 减少)。
func AliveCount() int {
	return int(atomic.LoadInt32(&aliveActors))
}
