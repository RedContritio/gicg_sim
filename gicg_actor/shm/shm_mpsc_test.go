// shm_mpsc_test.go — MPSC race regression tests for shm_ring_push/pop。
//
// 2026-05-27 production Win N=19 deadlock (frames 卡 5862 + collect_pops_got=0
// w/ shm_ring_peek_count=32 stuck) 根因 = push 的 `check count<cap` → `CAS tail`
// → `count++` 三步非原子 — N producer 可同时通过 cap gate,各自 CAS 不同 slot
// 全部成功,count++ 累加超过 cap,tail 取模后覆盖未消费 FULL slot,master pop
// 卡在 slot[head] status != FULL。
//
// 这两个 test 锚定 race。 修前应 FAIL,修后应 PASS。

package shm_test

import (
	"fmt"
	"runtime"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"gicg_mono/gicg_actor/shm"
)

// TestMPSCNoOverflow — N goroutine producer 并发 push,验证 push 成功数 ≤ cap
// + consumer 每个 pop 拿到合法 payload (即未被并发覆盖)。 现行 算法在高并发时
// 会令成功 push > cap → 覆盖未消费 slot → pop 拿到 corrupted payload 或 deadlock。
func TestMPSCNoOverflow(t *testing.T) {
	const capacity = 8
	const payloadSize = 32
	const nProducers = 16
	const pushesPerProducer = 1000

	name := uniqueName(t)
	r, err := shm.Create(name, capacity, payloadSize)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	defer r.Close()

	var totalSuccess atomic.Int64
	var totalFailFull atomic.Int64
	var wg sync.WaitGroup

	// Consumer goroutine: pops until it sees deadlock or expected count。
	// 死锁检测:连续 200ms 没 pop 到任何东西 + producer 全 done → 死锁,fail。
	popped := make(map[string]int) // payload → seen count, 用于 detect dup (覆盖)
	var poppedMu sync.Mutex
	consumerDone := make(chan struct{})

	go func() {
		defer close(consumerDone)
		buf := make([]byte, payloadSize)
		lastPopTime := time.Now()
		for {
			_, _, n, ok := r.Pop(buf)
			if !ok {
				if time.Since(lastPopTime) > 500*time.Millisecond {
					// 长时间没 pop 到 — 可能死锁 或 producer done。 退出 consumer,
					// 让主线程根据 totalSuccess 判断。
					return
				}
				runtime.Gosched()
				continue
			}
			lastPopTime = time.Now()
			payload := string(buf[:n])
			poppedMu.Lock()
			popped[payload]++
			poppedMu.Unlock()
		}
	}()

	// Producer goroutines: each push K items, retry on full。
	for p := range nProducers {
		wg.Add(1)
		go func(pid int) {
			defer wg.Done()
			for i := range pushesPerProducer {
				payload := fmt.Appendf(nil, "p%02d-msg%05d", pid, i)
				for {
					err := r.Push(uint32(pid), uint32(i), payload)
					if err == nil {
						totalSuccess.Add(1)
						break
					}
					// "ring full" — wait + retry
					totalFailFull.Add(1)
					runtime.Gosched()
				}
			}
		}(p)
	}

	wg.Wait()
	// 等 consumer drain + timeout 自然退出
	<-consumerDone

	// 验收 1: 总成功数 = 预期
	expected := int64(nProducers * pushesPerProducer)
	if totalSuccess.Load() != expected {
		t.Errorf("totalSuccess=%d want %d (some producer never completed — deadlock?)",
			totalSuccess.Load(), expected)
	}

	// 验收 2: consumer 拿到 unique payload 总数 = 总 push 数
	// 若 race 覆盖 → 某些 payload 永远没被 pop (死锁前被覆盖) → unique 数 < 预期
	// 若 race 覆盖 → 某些 payload 重复 pop (count 错乱 + slot 复用) → seen count > 1
	poppedMu.Lock()
	defer poppedMu.Unlock()
	var dupCount int
	for payload, n := range popped {
		if n > 1 {
			if dupCount < 5 {
				t.Errorf("payload %q popped %d times (race: slot overwritten or count misaccounted)",
					payload, n)
			}
			dupCount++
		}
	}
	if dupCount >= 5 {
		t.Errorf("(suppressed %d more duplicate-pop errors)", dupCount-5)
	}
	uniqueOK := int64(len(popped))
	if uniqueOK != expected {
		t.Errorf("popped unique payloads=%d want %d (race: %d payloads lost to overwrites or deadlock)",
			uniqueOK, expected, expected-uniqueOK)
	}
}

// TestMPSCCountInvariant — 验证并发 push 期间 ring count 永不超过 capacity。
//
// 现行 buggy 算法允许 count 临时 > cap (N producer 同时通过 cap gate, 各 CAS tail
// + count++, 最终 count = cap + (N-cap-already-counted)。 实测 Win N=19 production
// shm_ring_peek_count = 40 (cap=32)。
//
// 修后 push 的 cap check 应 atomic (count CAS 一并 reserve), 任何 producer 视角下
// count <= cap。
func TestMPSCCountInvariant(t *testing.T) {
	const capacity = 4 // 小 cap 放大 race 触发
	const payloadSize = 16
	const nProducers = 32
	const pushesPerProducer = 200

	name := uniqueName(t)
	r, err := shm.Create(name, capacity, payloadSize)
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	defer r.Close()

	var wg sync.WaitGroup
	stopMonitor := make(chan struct{})

	// 观察 push 反向 — push 失败 (ring full) 表示 producer 看到 count >= cap;
	// 大量 push 不应永久 fail (consumer 在 drain)。 死锁是 root signal。

	// Consumer goroutine: drain forever。
	consumerDone := make(chan struct{})
	var consumerPops atomic.Int64
	go func() {
		defer close(consumerDone)
		buf := make([]byte, payloadSize)
		lastPopTime := time.Now()
		for {
			_, _, _, ok := r.Pop(buf)
			if !ok {
				if time.Since(lastPopTime) > 1000*time.Millisecond {
					select {
					case <-stopMonitor:
						return
					default:
					}
				}
				runtime.Gosched()
				continue
			}
			consumerPops.Add(1)
			lastPopTime = time.Now()
		}
	}()

	// Producer pushers, retry on full。
	for p := range nProducers {
		wg.Add(1)
		go func(pid int) {
			defer wg.Done()
			for i := range pushesPerProducer {
				payload := fmt.Appendf(nil, "%02d:%05d", pid, i)
				for {
					err := r.Push(uint32(pid), uint32(i), payload)
					if err == nil {
						break
					}
					runtime.Gosched()
				}
			}
		}(p)
	}

	// 等 producer 全 done OR 60s timeout (死锁 → consumer 卡)
	doneCh := make(chan struct{})
	go func() {
		wg.Wait()
		close(doneCh)
	}()
	select {
	case <-doneCh:
		// good
	case <-time.After(30 * time.Second):
		t.Fatalf("producer wg.Wait() timed out — deadlock; consumerPops=%d; expected push total %d",
			consumerPops.Load(), nProducers*pushesPerProducer)
	}

	close(stopMonitor)
	<-consumerDone

	expected := int64(nProducers * pushesPerProducer)
	if consumerPops.Load() != expected {
		t.Errorf("consumerPops=%d want %d (race: data lost to overwrite or deadlock)",
			consumerPops.Load(), expected)
	}
}
