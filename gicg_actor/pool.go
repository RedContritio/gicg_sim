// Package gicg_actor — Go-native RL actor pool for GICG.
//
// 边界:本 package 含所有 RL-specific Go code(actor goroutine pool / paradigm adapter /
// IPC client / SHM ring writer)。 import "gicg_mono/gicg_engine" 单向依赖,engine package
// 不知道 actor 存在(RL-zero awareness)。
//
// 通过 ./capi build 出 libgicg_actor.dll/.dylib,Python master ctypes load 调 C API
// (gicg_actor_start_pool / gicg_actor_stop_pool 等)。 与现有 libgicg(gicg_engine/capi/)
// 独立 build,各自含一份 Go runtime ~10 MB 是保边界的代价(参 openspec/changes/
// i29-go-actor-pool/design.md D4)。
//
// Phase 0(本 commit):最小骨架 — 单 goroutine spawn/stop,SIGTERM no-op handler 防 cgo +
// Python multiprocessing 信号互锁(memory: feedback_go_cgo_signal_handler)。
package gicg_actor

import (
	"fmt"
	"os"
	"os/signal"
	"sync"
	"syscall"
)

// pool 是全局单例(Python master 同一时刻只起一组 actor pool)。 ctypes API 是
// stateless C 函数,实际 state 跑在本 package 全局变量里。 用 mu 保护并发 start/stop。
var (
	mu      sync.Mutex
	running bool
	stopCh  chan struct{}
	doneCh  chan struct{}
	nActors int
)

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

func init() {
	initSignalHandler()
}

// StartPool 起 n 个 actor goroutine(P0 占位:每 goroutine 仅打印 "ok" 即 sleep wait stop)。
// 返 0 = success,非 0 = 错误码。 重复 start(running=true 时再 start)返 1。
//
// P1 扩:接 paradigm adapter + episode loop + InfServer socket + SHM transition writer。
func StartPool(n int) int {
	mu.Lock()
	defer mu.Unlock()
	if running {
		return 1 // already running
	}
	if n <= 0 {
		return 2 // invalid n
	}
	stopCh = make(chan struct{})
	doneCh = make(chan struct{}, n)
	nActors = n
	for i := range n {
		go actorLoop(i, stopCh, doneCh)
	}
	running = true
	return 0
}

// StopPool 触发所有 actor goroutine 优雅退出 + 等齐 join。 返 0 = success,1 = not running。
//
// 跟 atexit hook 配合(Python GoActorBackend register atexit.register(self.stop))保证
// process exit 时 Go runtime cleanup。
func StopPool() int {
	mu.Lock()
	defer mu.Unlock()
	if !running {
		return 1
	}
	close(stopCh)
	// Wait all actors done.
	for range nActors {
		<-doneCh
	}
	running = false
	stopCh = nil
	doneCh = nil
	nActors = 0
	return 0
}

// actorLoop P0 占位:print "ok actor=N" 一次,select stop。 P1 替换为 episode 主循环。
func actorLoop(id int, stop <-chan struct{}, done chan<- struct{}) {
	defer func() { done <- struct{}{} }()
	fmt.Printf("[gicg_actor] ok actor=%d\n", id)
	<-stop
}

// Hello 是最简 ctypes 烟雾测:Python 调返 0 验证 ctypes load + Go runtime init OK。
func Hello() int {
	return 0
}
