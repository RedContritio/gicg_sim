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

// GoRuntimeMemStats — Go runtime.MemStats 关键字段透传给 Python (via ctypes)。
// 字段顺序 / 类型必须与 Python side training/core/actor/go_runtime_stats.py
// GoRuntimeMemStats Structure 同构,任一端加字段必须同步更新另一端。
// 字段语义参 https://pkg.go.dev/runtime#MemStats。
typedef struct {
    uint64_t heap_alloc;       // bytes of allocated heap objects (live)
    uint64_t heap_sys;         // bytes of heap memory obtained from OS
    uint64_t heap_inuse;       // bytes in in-use spans
    uint64_t heap_idle;        // bytes in idle (unused) spans
    uint64_t heap_released;    // bytes physical memory returned to OS
    uint64_t sys;              // total bytes of memory obtained from OS
    uint64_t mallocs;          // cumulative count of heap objects allocated
    uint64_t frees;            // cumulative count of heap objects freed
    uint64_t num_gc;           // number of completed GC cycles
    uint64_t pause_total_ns;   // cumulative ns in GC stop-the-world pauses
} GoRuntimeMemStats;
*/
import "C"

import (
	"runtime"
	"unsafe"

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

// Go runtime heap stats 透传给 Python — mem leak 定位用(嫌疑:Go runtime heap
// 长跑增长但 Python tracemalloc 不显)。 调 runtime.ReadMemStats(整 stop-the-world,
// 高频调用有开销;mem_probe 默认 30s 采样一次,可接受)。
//
// 字段:见 C 头 GoRuntimeMemStats 注释 / runtime.MemStats godoc。
// 返:0 = OK, 1 = nil out pointer。
//
// Go-side perf trace flush — drain ring buffer (binary little-endian schema 见
// gicg_actor/perf_trace.go:PerfTraceFlush 注释)。 disabled (default 起,未由
// gicg_actor_set_perf_trace_enabled 启) 返 0。 buf 不够大返 -needed_bytes,
// caller realloc 再调 (但 ring 已 drain → 数据丢;用合理 buf >= 1 MB 实测安全)。
//
//export gicg_actor_perf_trace_flush
func gicg_actor_perf_trace_flush(outBuf *C.char, bufLen C.uint32_t) C.int {
	if outBuf == nil || bufLen == 0 {
		return C.int(0)
	}
	goBuf := unsafe.Slice((*byte)(unsafe.Pointer(outBuf)), int(bufLen))
	return C.int(gicg_actor.PerfTraceFlush(goBuf))
}

//export gicg_actor_perf_trace_enabled
func gicg_actor_perf_trace_enabled() C.int {
	if gicg_actor.PerfTraceEnabled() {
		return C.int(1)
	}
	return C.int(0)
}

// gicg_actor_set_perf_trace_enabled — cfg-driven enable (post 2026-05-23 旧
// GICG_GO_PERF_TRACE env var 砍后唯一启用路径)。 Python dispatch 读
// cfg.debug.go_perf_trace 后通过此 capi 同步给 Go atomic.Bool。 lib load 后 /
// 起 pool 前调即可 (无 init-time gate)。 enabled != 0 → enable,== 0 → disable。
// 返 0 (无校验失败路径)。
//
//export gicg_actor_set_perf_trace_enabled
func gicg_actor_set_perf_trace_enabled(enabled C.int) C.int {
	gicg_actor.SetPerfTraceEnabled(enabled != 0)
	return C.int(0)
}

//export gicg_actor_runtime_memstats
func gicg_actor_runtime_memstats(out *C.GoRuntimeMemStats) C.int {
	if out == nil || unsafe.Pointer(out) == nil {
		return C.int(1)
	}
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	out.heap_alloc = C.uint64_t(m.HeapAlloc)
	out.heap_sys = C.uint64_t(m.HeapSys)
	out.heap_inuse = C.uint64_t(m.HeapInuse)
	out.heap_idle = C.uint64_t(m.HeapIdle)
	out.heap_released = C.uint64_t(m.HeapReleased)
	out.sys = C.uint64_t(m.Sys)
	out.mallocs = C.uint64_t(m.Mallocs)
	out.frees = C.uint64_t(m.Frees)
	out.num_gc = C.uint64_t(m.NumGC)
	out.pause_total_ns = C.uint64_t(m.PauseTotalNs)
	return C.int(0)
}
