// Package main — c-shared export 入口,build 出 libgicg_actor.dll/.dylib。
//
// Python ctypes load 走本 package //export 的 C API。 实际 state + logic 在
// gicg_mono/gicg_actor(本 main package import 它,把 C-callable wrapper 暴露出去)。
//
// Build(Mac):
//
//	go build -buildmode=c-shared -o gicg_env/libgicg_actor.dylib ./gicg_actor/capi
//
// Build(Win,PowerShell):
//
//	$env:CGO_ENABLED = "1"
//	$env:CC = "C:\Strawberry\c\bin\gcc.exe"
//	$env:PATH = "C:\Strawberry\c\bin;" + $env:PATH
//	go build -buildmode=c-shared -o gicg_env\libgicg_actor.dll .\gicg_actor\capi
//
// 跟现有 libgicg(gicg_engine/capi/)独立 build — 各自含 Go runtime ~10 MB 是保边界的代价
// (参 openspec/changes/i29-go-actor-pool/design.md D4)。
package main

// #include <stdint.h>
import "C"

import (
	"gicg_mono/gicg_actor"
)

// main 必需(go build -buildmode=c-shared 要求 main package),但 c-shared 模式下不执行。
// 实际 export 通过 //export 注释 + 包 init 完成。
func main() {}

// Python ctypes 烟雾测:返 0 即 ctypes load OK + Go runtime init OK。
//
//export gicg_actor_hello
func gicg_actor_hello() C.int {
	return C.int(gicg_actor.Hello())
}

// 起 n 个 actor goroutine。 返 0 = success,1 = already running,2 = invalid n。
// 重复 start(未先 stop)返 1。
//
//export gicg_actor_start_pool
func gicg_actor_start_pool(n C.int) C.int {
	return C.int(gicg_actor.StartPool(int(n)))
}

// 优雅停 + join 所有 actor goroutine。 返 0 = success,1 = not running。
// Python GoActorBackend atexit hook 调本 API 兜 process exit。
//
//export gicg_actor_stop_pool
func gicg_actor_stop_pool() C.int {
	return C.int(gicg_actor.StopPool())
}
