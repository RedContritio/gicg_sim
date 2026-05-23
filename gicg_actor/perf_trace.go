// perf_trace.go — Go-side span-timing aggregator,mirror Python training/core/perf/trace.py。
//
// 用途:audit Win N=16 production stage 3.5 的 Go-actor 端 wall 拆分(minimax /
// DeepCopy / inference RPC / Push / etc),定位 Python mp-actor 37 fps vs Go-actor
// 25 fps 的真瓶颈。
//
// API(zero-overhead when disabled):
//
//	defer trace.Span("dmc.episode").End()      // RAII timing block
//	defer trace.Span("game.deepcopy").End()    // 计数 + 累计 ns
//
// disabled (env var GICG_GO_PERF_TRACE 未设 1) 时:Span 返 zero SpanHandle,End
// 内单一 atomic.Load → 0 heap alloc(testing.AllocsPerRun=0 verify)。
//
// enabled 时:每 End 取锁累计 {n, sum_ns, max_ns} 到当前 bucket,达到 flushWindowN
// 或 flushIntervalS 时 snapshot 入 ring buffer(cap=ringCap FIFO)。 capi 端
// gicg_actor_perf_trace_flush drain 整 ring → Python ctypes 解码 emit metrics.jsonl。
//
// 名称规则(per session memory pattern):"<scope>.<phase>" — dmc.* / game.* /
// inference_client.* / transition_writer.*。 Python aggregator 不解析,仅 group by
// name 做 sum/max。

package gicg_actor

import (
	"encoding/binary"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

// 控制参数。 enabled 在 init 时 sample env var,后续 atomic-load 避免 hot path env 调用。
var (
	perfEnabled       atomic.Bool
	perfFlushWindowN  = 1000
	perfFlushInterval = 1 * time.Second
	perfRingCap       = 64
)

// PerfTraceEnabled 测试 / 外部代码 read-only 查询(对应 Python is_enabled())。
func PerfTraceEnabled() bool { return perfEnabled.Load() }

// SpanHandle 是 Span() 返回的 stack value。 zero value (startNs==0) 表示 disabled / no-op。
// 字段全 value (no pointer / slice) → defer trace.Span(...).End() 在 escape analysis
// 下走 stack,zero alloc。
type SpanHandle struct {
	name    string
	startNs int64 // 0 == sentinel "disabled / noop"
}

// Span 启 timing block。 disabled 时返 zero SpanHandle (single atomic.Load,no alloc)。
func Span(name string) SpanHandle {
	if !perfEnabled.Load() {
		return SpanHandle{}
	}
	return SpanHandle{name: name, startNs: time.Now().UnixNano()}
}

// End 收 timing。 disabled / zero handle 时 no-op (single branch)。
func (h SpanHandle) End() {
	if h.startNs == 0 {
		return
	}
	dt := time.Now().UnixNano() - h.startNs
	perfAgg.record(h.name, dt)
}

// perfWindow 是一次 flush snapshot。 stages map → {n, sum_ns, max_ns}。 序列化协议见
// perf_trace_capi.go (binary little-endian)。
type perfWindow struct {
	tsUnixMs uint64
	stages   map[string]*perfBucket
}

type perfBucket struct {
	n      uint32
	sumNs  uint64
	maxNs  uint64
}

type perfAggregator struct {
	mu          sync.Mutex
	curStages   map[string]*perfBucket
	curEventN   int
	lastFlushNs int64
	ring        []perfWindow // FIFO,cap = perfRingCap
}

var perfAgg = &perfAggregator{
	curStages: make(map[string]*perfBucket),
	ring:      make([]perfWindow, 0, 64),
}

func (a *perfAggregator) record(name string, dtNs int64) {
	if dtNs < 0 {
		dtNs = 0 // clock skew 防御 (NTP 跳变)
	}
	a.mu.Lock()
	b := a.curStages[name]
	if b == nil {
		b = &perfBucket{}
		a.curStages[name] = b
	}
	b.n++
	b.sumNs += uint64(dtNs)
	if uint64(dtNs) > b.maxNs {
		b.maxNs = uint64(dtNs)
	}
	a.curEventN++
	nowNs := time.Now().UnixNano()
	if a.curEventN >= perfFlushWindowN || nowNs-a.lastFlushNs >= perfFlushInterval.Nanoseconds() {
		a.flushLocked(nowNs)
	}
	a.mu.Unlock()
}

// flushLocked 把当前 buckets snapshot 入 ring + reset。 caller 必须持 a.mu。
func (a *perfAggregator) flushLocked(nowNs int64) {
	if len(a.curStages) == 0 {
		a.lastFlushNs = nowNs
		return
	}
	w := perfWindow{
		tsUnixMs: uint64(nowNs / 1_000_000),
		stages:   a.curStages,
	}
	if len(a.ring) >= perfRingCap {
		// FIFO evict oldest
		copy(a.ring, a.ring[1:])
		a.ring = a.ring[:len(a.ring)-1]
	}
	a.ring = append(a.ring, w)
	a.curStages = make(map[string]*perfBucket)
	a.curEventN = 0
	a.lastFlushNs = nowNs
}

// PerfTraceFlush drain ring buffer + force-flush 当前 partial bucket → 序列化到 out。
// out 不够大返 -needed (caller 重 alloc 调)。 disabled 时返 0。
//
// Wire format (binary little-endian):
//
//	u32 n_windows
//	per window:
//	  u64 ts_unix_ms
//	  u32 n_stages
//	  per stage:
//	    u16 name_len, name_bytes (utf-8), u32 n, u64 sum_ns, u64 max_ns
func PerfTraceFlush(out []byte) int {
	if !perfEnabled.Load() {
		return 0
	}
	perfAgg.mu.Lock()
	// Force-flush partial bucket so caller sees current second's data。
	perfAgg.flushLocked(time.Now().UnixNano())
	windows := perfAgg.ring
	perfAgg.ring = make([]perfWindow, 0, perfRingCap)
	perfAgg.mu.Unlock()

	// Pre-compute needed bytes (header u32 + per-window header + per-stage payload)。
	needed := 4
	for _, w := range windows {
		needed += 8 + 4 // ts_unix_ms + n_stages
		for name := range w.stages {
			needed += 2 + len(name) + 4 + 8 + 8
		}
	}
	if needed > len(out) {
		// 不修改 ring (已 drain),但本次返 -needed,caller realloc 再调时 ring 已空 →
		// 数据丢失。 trade-off:caller 用合理 buf size (>=1 MB 实测)就不会触发。
		return -needed
	}
	off := 0
	binary.LittleEndian.PutUint32(out[off:], uint32(len(windows)))
	off += 4
	for _, w := range windows {
		binary.LittleEndian.PutUint64(out[off:], w.tsUnixMs)
		off += 8
		binary.LittleEndian.PutUint32(out[off:], uint32(len(w.stages)))
		off += 4
		for name, b := range w.stages {
			binary.LittleEndian.PutUint16(out[off:], uint16(len(name)))
			off += 2
			copy(out[off:], name)
			off += len(name)
			binary.LittleEndian.PutUint32(out[off:], b.n)
			off += 4
			binary.LittleEndian.PutUint64(out[off:], b.sumNs)
			off += 8
			binary.LittleEndian.PutUint64(out[off:], b.maxNs)
			off += 8
		}
	}
	return off
}

// init reads env var once at package load。 set GICG_GO_PERF_TRACE=1 *before* Python
// ctypes.CDLL(libgicg_actor) — Go runtime 起在 lib load 时,env 之后改无效。
func init() {
	if os.Getenv("GICG_GO_PERF_TRACE") == "1" {
		perfEnabled.Store(true)
	}
}
