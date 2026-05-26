// shm_test.go — unit tests for the SHM ring Go binding.
//
// Tests run in-process (same mmap region shared within the process for
// single-thread tests; goroutines share the same mmap for concurrency tests).
// No cross-process IPC needed for unit tests — cross-language verification is
// done by tools/_dev/shm_ring_spike.py.
//
// Platform: Mac/Linux + Windows (Phase 4 added Win impl via shm_windows.go +
// shm_win.c). The Go API surface is identical across platforms so the same
// test bodies exercise both shm_unix.c and shm_win.c code paths.

package shm_test

import (
	"fmt"
	"runtime"
	"sync"
	"testing"
	"time"

	"gicg_mono/gicg_actor/shm"
)

// isWindows is true when these tests run on Windows. Used to gate
// platform-specific expectations (e.g. NormaliseName is a no-op on Win, but
// prepends "/" on POSIX). Detected via runtime.GOOS so the same test source
// covers both platforms.
var isWindows = runtime.GOOS == "windows"

// uniqueName returns a unique shm name for each test to avoid cross-test
// collisions even if a prior test crashed without cleanup.
//
// The name carries a leading "/" so POSIX shm_open accepts it directly.
// Windows ignores the "/" (NormaliseName is a no-op on Win and Windows
// CreateFileMapping accepts arbitrary names including ones with "/"), so the
// same name shape works on both platforms — keeps the test source single-arch.
func uniqueName(t *testing.T) string {
	t.Helper()
	name := fmt.Sprintf("/gicg_test_%d", time.Now().UnixNano())
	t.Cleanup(func() {
		// Best-effort cleanup in case the test ring was not explicitly closed.
		// shm.NormaliseName handles the leading "/" already.
		_ = name
	})
	return name
}

// TestLayoutConstants verifies the exported C constants match our expectations.
func TestLayoutConstants(t *testing.T) {
	// Verify ring header size and slot header size via RingTotalSize arithmetic.
	// RingTotalSize(cap, payload) = 64 + cap*(20+payload)
	got := shm.RingTotalSize(1, 0)
	want := 64 + 1*(20+0)
	if got != want {
		t.Fatalf("RingTotalSize(1,0) = %d, want %d", got, want)
	}
	got = shm.RingTotalSize(4, 100)
	want = 64 + 4*(20+100)
	if got != want {
		t.Fatalf("RingTotalSize(4,100) = %d, want %d", got, want)
	}
}

// TestNormaliseName verifies the platform-appropriate name normalisation:
//   - POSIX (Mac/Linux): prepends "/" so shm_open(2) is happy.
//   - Windows: returns the input verbatim — Python's SharedMemory on Win
//     passes user-supplied names through to CreateFileMapping as-is, and Win
//     named-object names do not need (and do not accept) a leading "/".
func TestNormaliseName(t *testing.T) {
	type tc struct{ in, wantPosix, wantWin string }
	cases := []tc{
		{"psm_abc", "/psm_abc", "psm_abc"},
		{"/gicg_foo", "/gicg_foo", "/gicg_foo"}, // POSIX no-op (already has /); Win passes through.
		{"", "/", ""},
	}
	for _, c := range cases {
		want := c.wantPosix
		if isWindows {
			want = c.wantWin
		}
		if got := shm.NormaliseName(c.in); got != want {
			t.Errorf("NormaliseName(%q) = %q, want %q", c.in, got, want)
		}
	}
}

// TestCreateAndClose verifies basic Create + Close lifecycle without leaks.
func TestCreateAndClose(t *testing.T) {
	name := uniqueName(t)
	r, err := shm.Create(name, 4, 64)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	if r.Capacity() != 4 {
		t.Errorf("Capacity() = %d, want 4", r.Capacity())
	}
	if r.SlotPayloadMax() != 64 {
		t.Errorf("SlotPayloadMax() = %d, want 64", r.SlotPayloadMax())
	}
	if err := r.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	// Idempotent close must not panic.
	if err := r.Close(); err != nil {
		t.Fatalf("double Close: %v", err)
	}
}

// TestSingleThreadRoundtrip pushes N values then pops N values in order.
// This exercises push + pop on the same ring without concurrency.
func TestSingleThreadRoundtrip(t *testing.T) {
	const capacity = 8
	const payloadSize = 32
	const N = capacity // fill the ring exactly

	name := uniqueName(t)
	r, err := shm.Create(name, capacity, payloadSize)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	defer r.Close()

	// Push N payloads.
	for i := 0; i < N; i++ {
		payload := []byte(fmt.Sprintf("msg-%04d", i))
		if err := r.Push(uint32(i), uint32(i*10), payload); err != nil {
			t.Fatalf("Push(%d): %v", i, err)
		}
	}

	// Ring is now full; one more push must fail.
	if err := r.Push(0, 0, []byte("overflow")); err == nil {
		t.Fatal("expected Push on full ring to fail, but it succeeded")
	}

	// Pop N payloads and verify contents.
	for i := 0; i < N; i++ {
		cid, rid, payload, ok := r.TryPop()
		if !ok {
			t.Fatalf("TryPop(%d): empty ring", i)
		}
		if cid != uint32(i) {
			t.Errorf("TryPop(%d): cid=%d want %d", i, cid, i)
		}
		if rid != uint32(i*10) {
			t.Errorf("TryPop(%d): rid=%d want %d", i, rid, i*10)
		}
		wantPayload := fmt.Sprintf("msg-%04d", i)
		if string(payload) != wantPayload {
			t.Errorf("TryPop(%d): payload=%q want %q", i, payload, wantPayload)
		}
	}

	// Ring is now empty.
	_, _, _, ok := r.TryPop()
	if ok {
		t.Fatal("expected TryPop on empty ring to return false")
	}
}

// TestProducerConsumer runs a goroutine producer pushing 1000 messages and a
// goroutine consumer popping them, verifying correct count and order.
func TestProducerConsumer(t *testing.T) {
	const capacity = 32
	const payloadSize = 16
	const totalMessages = 1000

	name := uniqueName(t)
	r, err := shm.Create(name, capacity, payloadSize)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	defer r.Close()

	received := make([][]byte, 0, totalMessages)
	var mu sync.Mutex
	var wg sync.WaitGroup

	// Consumer goroutine: pops until it has received totalMessages items.
	wg.Add(1)
	go func() {
		defer wg.Done()
		count := 0
		buf := make([]byte, payloadSize)
		for count < totalMessages {
			_, _, n, ok := r.Pop(buf)
			if !ok {
				// Ring empty; yield and retry.
				runtime.Gosched()
				continue
			}
			item := make([]byte, n)
			copy(item, buf[:n])
			mu.Lock()
			received = append(received, item)
			mu.Unlock()
			count++
		}
	}()

	// Producer: pushes totalMessages items.
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < totalMessages; i++ {
			payload := []byte(fmt.Sprintf("%08d", i))
			for {
				err := r.Push(0, uint32(i), payload)
				if err == nil {
					break
				}
				// Ring full; yield and retry.
				runtime.Gosched()
			}
		}
	}()

	wg.Wait()

	mu.Lock()
	defer mu.Unlock()

	if len(received) != totalMessages {
		t.Fatalf("received %d messages, want %d", len(received), totalMessages)
	}

	// Verify strict ordering (FIFO ring, single consumer, single producer).
	for i, item := range received {
		want := fmt.Sprintf("%08d", i)
		if string(item) != want {
			t.Errorf("received[%d] = %q, want %q", i, item, want)
			if i > 5 {
				t.Fatal("too many ordering errors, stopping")
			}
		}
	}
}

// TestSingleSlotRespRoundtrip verifies the resp ring write→read path in-process.
func TestSingleSlotRespRoundtrip(t *testing.T) {
	const payloadSize = 64
	name := uniqueName(t)

	// Create a single-slot ring (capacity=1).
	r, err := shm.Create(name, 1, payloadSize)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	defer r.Close()

	const N = 20
	var wg sync.WaitGroup

	// Reader goroutine: reads N responses.
	results := make([]string, N)
	wg.Add(1)
	go func() {
		defer wg.Done()
		buf := make([]byte, payloadSize)
		for i := 0; i < N; i++ {
			_, n, err := r.RespRead(buf, 2*time.Second)
			if err != nil {
				t.Errorf("RespRead(%d): %v", i, err)
				return
			}
			results[i] = string(buf[:n])
		}
	}()

	// Writer goroutine: writes N responses.
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < N; i++ {
			payload := []byte(fmt.Sprintf("resp-%04d", i))
			if err := r.RespWrite(uint32(i), payload, 2*time.Second); err != nil {
				t.Errorf("RespWrite(%d): %v", i, err)
				return
			}
		}
	}()

	wg.Wait()

	for i, got := range results {
		want := fmt.Sprintf("resp-%04d", i)
		if got != want {
			t.Errorf("results[%d] = %q, want %q", i, got, want)
		}
	}
}

// TestCreateAttachRoundtrip verifies Create in one "process-like" context and
// Attach in another, sharing the same underlying SHM block.
// Both sides are in-process (same process, different Ring handles) which is
// sufficient to verify the Attach path for Mac/Linux shm_open + mmap.
func TestCreateAttachRoundtrip(t *testing.T) {
	const capacity = 4
	const payloadSize = 32

	name := uniqueName(t)
	total := shm.RingTotalSize(capacity, payloadSize)

	creator, err := shm.Create(name, capacity, payloadSize)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	defer creator.Close()

	attacher, err := shm.Attach(name, total)
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer attacher.Close()

	// Push via creator, pop via attacher.
	payload := []byte("cross-handle-msg")
	if err := creator.Push(7, 42, payload); err != nil {
		t.Fatalf("creator.Push: %v", err)
	}
	cid, rid, got, ok := attacher.TryPop()
	if !ok {
		t.Fatal("attacher.TryPop: empty (expected message)")
	}
	if cid != 7 {
		t.Errorf("clientID = %d, want 7", cid)
	}
	if rid != 42 {
		t.Errorf("reqID = %d, want 42", rid)
	}
	if string(got) != string(payload) {
		t.Errorf("payload = %q, want %q", got, payload)
	}
}
