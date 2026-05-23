package gicg_actor

import (
	"encoding/binary"
	"sync"
	"testing"
)

// resetPerf 重置 aggregator + 显式 enable/disable,用于测试。 production 代码不应调。
func resetPerfTest(enable bool) {
	perfAgg.mu.Lock()
	defer perfAgg.mu.Unlock()
	perfAgg.curStages = make(map[string]*perfBucket)
	perfAgg.curEventN = 0
	perfAgg.lastFlushNs = 0
	perfAgg.ring = perfAgg.ring[:0]
	perfEnabled.Store(enable)
}

func TestPerfTraceDisabledZeroAlloc(t *testing.T) {
	resetPerfTest(false)
	// AllocsPerRun 跑 N 次 hot path,返平均 heap alloc。 disabled 必须 == 0。
	got := testing.AllocsPerRun(1000, func() {
		h := Span("test.disabled")
		h.End()
	})
	if got != 0 {
		t.Fatalf("Span/End disabled path must be zero-alloc, got %v allocs/op", got)
	}
	if PerfTraceEnabled() {
		t.Fatal("PerfTraceEnabled must be false after resetPerfTest(false)")
	}
}

func TestPerfTraceEnabledAggregation(t *testing.T) {
	resetPerfTest(true)
	defer resetPerfTest(false)
	var wg sync.WaitGroup
	const nGoroutines = 8
	const nPerG = 50
	for i := 0; i < nGoroutines; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < nPerG; j++ {
				h := Span("test.concurrent")
				h.End()
			}
		}()
	}
	wg.Wait()
	// Flush + decode → 应能 aggregate 全 nGoroutines*nPerG = 400 events 在 'test.concurrent'。
	buf := make([]byte, 1<<16)
	n := PerfTraceFlush(buf)
	if n <= 0 {
		t.Fatalf("PerfTraceFlush returned %d", n)
	}
	totalN := uint32(0)
	off := 0
	nWindows := binary.LittleEndian.Uint32(buf[off:])
	off += 4
	for w := uint32(0); w < nWindows; w++ {
		off += 8 // ts
		nStages := binary.LittleEndian.Uint32(buf[off:])
		off += 4
		for s := uint32(0); s < nStages; s++ {
			nameLen := int(binary.LittleEndian.Uint16(buf[off:]))
			off += 2
			name := string(buf[off : off+nameLen])
			off += nameLen
			n := binary.LittleEndian.Uint32(buf[off:])
			off += 4
			off += 16 // sum_ns + max_ns
			if name == "test.concurrent" {
				totalN += n
			}
		}
	}
	if totalN != nGoroutines*nPerG {
		t.Fatalf("expected %d events, got %d", nGoroutines*nPerG, totalN)
	}
}

func TestPerfTraceRingFIFOEvict(t *testing.T) {
	resetPerfTest(true)
	defer resetPerfTest(false)
	// 直接调 flushLocked perfRingCap+5 次,看 ring 维持 cap 且 FIFO drop oldest。
	perfAgg.mu.Lock()
	for i := 0; i < perfRingCap+5; i++ {
		// 注入一个 stage 让 flush 真发生
		perfAgg.curStages["s"] = &perfBucket{n: 1}
		perfAgg.flushLocked(int64(i+1) * 1_000_000)
	}
	got := len(perfAgg.ring)
	perfAgg.mu.Unlock()
	if got != perfRingCap {
		t.Fatalf("ring should cap at %d after FIFO evict, got %d", perfRingCap, got)
	}
}

func TestPerfTraceFlushDisabledReturnsZero(t *testing.T) {
	resetPerfTest(false)
	buf := make([]byte, 1024)
	if n := PerfTraceFlush(buf); n != 0 {
		t.Fatalf("disabled flush should return 0, got %d", n)
	}
}
