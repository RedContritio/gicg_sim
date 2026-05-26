// shm_bench_test.go — micro-benchmarks for SHM ring push/pop hot path。
//
// I29 P0.5 transport bench 测 Go subprocess vs Python mp subprocess pure SHMRing push:
// Go @ 12 KB payload ~700K push/s vs Python ~720K push/s (Go 97.3%)。 此处 same-process
// 同 goroutine push+pop pure-Go 测,排除:
//   - subprocess fork/exec startup
//   - cross-process kernel SHM page fault
//   - Python ctypes overhead
//   - Master pop loop (busy spin)
//
// 数据用来定位 4% gap 是 Go runtime overhead 还是 SHM C lib upper limit。
//
// 跑法: go test -bench=. -benchmem -benchtime=10s ./gicg_actor/shm/

//go:build !windows

package shm

import (
	"runtime"
	"testing"
)

// BenchmarkRingPushPop_12KB — 主 metric。 single goroutine push+immediately-pop loop,
// payload size 12 KB (与 P0.5 一致),measure 纯 SHM ops upper bound on Mac M-series。
func BenchmarkRingPushPop_12KB(b *testing.B) {
	benchPushPop(b, 12*1024)
}

func BenchmarkRingPushPop_4KB(b *testing.B) {
	benchPushPop(b, 4*1024)
}

func BenchmarkRingPushPop_64B(b *testing.B) {
	benchPushPop(b, 64)
}

// BenchmarkRingPushPop_8B — minimum non-zero payload (Create 不允许 payload=0)。
// 标识 Mac M-series 单核 lock-free MPSC 上限 (atomic ops + minimal memcpy)。
func BenchmarkRingPushPop_8B(b *testing.B) {
	benchPushPop(b, 8)
}

func benchPushPop(b *testing.B, payloadSize int) {
	ring, err := Create("/bench_pushpop", 16, payloadSize)
	if err != nil {
		b.Fatalf("Create: %v", err)
	}
	defer ring.Close()

	payload := make([]byte, payloadSize)
	for i := range payload {
		payload[i] = 'X'
	}
	outBuf := make([]byte, payloadSize)

	// Pin to OS thread — same condition as P0.5 actor goroutine。
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	b.SetBytes(int64(payloadSize))
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if err := ring.Push(0, uint32(i), payload); err != nil {
			b.Fatalf("Push iter %d: %v", i, err)
		}
		_, _, _, ok := ring.Pop(outBuf)
		if !ok {
			b.Fatalf("Pop iter %d: not ok", i)
		}
	}
}
