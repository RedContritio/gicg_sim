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

/*
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	"gicg_mono/gicg_actor"
	// Side-effect imports: trigger per-paradigm registration via init()。
	// 加 paradigm 在此加一行 import,自动注册。 I29 收敛 scope:DMC ✓ AZ scaffold
	// PPO scaffold;CFR (frozen-research tier) + BC (dataset-driven 无 episode 生成)
	// 不纳入 Go port(D12 决策 2026-05-22)。
	_ "gicg_mono/gicg_actor/az"
	_ "gicg_mono/gicg_actor/dmc"
	_ "gicg_mono/gicg_actor/ppo"
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

// 起 N actor goroutine 跑指定 paradigm + 配 InfServer / TransSink socket addresses。
// Production 入口(P1.4 起):Python master 先 build 完 paradigm config JSON (DMC schema 见
// gicg_actor/dmc/paradigm.go:DMCConfig),然后调本 API 起 pool。
//
// 参数:
//
//	paradigm_name:registry lookup("dmc" / 后续 "az" "ppo" ...)
//	n_actors:goroutine 数
//	inf_addr:"host:port" InferenceServer 监听地址,空字符串则 skip(单测用)
//	trans_addr:"host:port" Python transition sink,空字符串则 skip(单测用)
//	paradigm_cfg_json:透传给 paradigm.Configure,paradigm 自反序列化
//	io_timeout_ms:socket I/O timeout,0 = 默认 30000
//
// 返码:见 gicg_actor/pool.go:StartPoolWithConfig 注释。
//
//export gicg_actor_start_pool_v2
func gicg_actor_start_pool_v2(
	paradigmName *C.char,
	nActors C.int,
	infAddr *C.char,
	transAddr *C.char,
	paradigmCfgJSON *C.char,
	ioTimeoutMs C.int,
) C.int {
	cfg := gicg_actor.Config{
		NActors:            int(nActors),
		ParadigmName:       C.GoString(paradigmName),
		InfServerAddr:      C.GoString(infAddr),
		TransSinkAddr:      C.GoString(transAddr),
		IOTimeoutMs:        int(ioTimeoutMs),
		ParadigmConfigJSON: C.GoString(paradigmCfgJSON),
	}
	return C.int(gicg_actor.StartPoolWithConfig(cfg))
}

// 优雅停 + join 所有 actor goroutine。 返 0 = success,1 = not running。
// Python GoActorBackend atexit hook 调本 API 兜 process exit。
//
//export gicg_actor_stop_pool
func gicg_actor_stop_pool() C.int {
	return C.int(gicg_actor.StopPool())
}

// 返回当前在跑的 actor goroutine 数。 pool 运行期间 < start 时的 n_actors 即说明有
// actor 静默 fatal 死亡(I29 T-RR.7 — actor 死亡可见性)。
//
//export gicg_actor_alive_count
func gicg_actor_alive_count() C.int {
	return C.int(gicg_actor.AliveCount())
}

// 以下 4 个 wire-layout introspection export 供 Python 测试做 Go↔Python wire 协议
// header 交叉校验 —— 任一端加字段忘同步另一端会被这些 size 不符 catch(I29 T-RR.8,
// 穷举审计 #D4:header struct 与 Python struct fmt 无运行时交叉校验)。
//
//export gicg_actor_wire_version
func gicg_actor_wire_version() C.int {
	return C.int(gicg_actor.WireVersion)
}

//export gicg_actor_transition_header_size
func gicg_actor_transition_header_size() C.int {
	return C.int(gicg_actor.TransitionHeaderSize)
}

//export gicg_actor_infer_request_header_size
func gicg_actor_infer_request_header_size() C.int {
	return C.int(gicg_actor.HeaderSize)
}

//export gicg_actor_infer_response_header_size
func gicg_actor_infer_response_header_size() C.int {
	return C.int(gicg_actor.ResponseHeaderSize)
}
