# SHMRing Inference Path Design (Path A)

Branch: `feature/i29-go-actor-shminf`  
Date: 2026-05-24  
Status: DESIGN ONLY — no production code yet.

## 背景与目标

**Root cause(win_bench_audit.md 确认)**:Go-actor 走 TCP socket per-request 推 inference,
Python InfServer 内 `forward_cb` 对每条 socket request 同步 `request_q.put` + 阻塞等
`response_qs[cid].get`。 最终 RTT 含:socket syscall + TCP framing + `request_q.put`
GIL + InfServer main loop `request_q.get` + GPU forward + `response_qs[cid].put` GIL +
`response_qs[cid].get` + socket write back。 实测 `inference_client.recv` mean=63 ms。

**Python mp 路径**:collector subprocess 里 `InferenceClient.infer()` 直接
`request_q.put` (OS-pipe shm-backed `mp.Queue`) + `response_q.get`。 无 socket syscall,
无 TCP framing。 管道 RTT <<1 ms。 实测 batching_efficiency=0.888,batch_avg=14.2。

**目标**:用 cross-language shared memory ring buffer 替代 TCP socket 推 inference
request / response,让 Go actor 以接近 Python mp.Queue 的 IPC 代价访问 InfServer。

预期收益:inference RTT 63 ms → <1 ms,batching_efficiency 从 ~5%(当前 Go path 未
instrument,历史 1.6)升到 8-14+,Go-actor fps 从 26 → 35-40+ (接近 Python mp 40)。

---

## A. Architecture

### 总体拓扑

```
┌─────────────────────────────────────────────────────────┐
│ Python master process                                    │
│                                                          │
│  InferenceServer (subprocess)                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │  shm_bridge thread                                 │  │
│  │    req_ring.try_pop() → request_q.put(...)         │  │
│  │    response_qs[cid].get() → resp_ring[cid].push()  │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌─server_loop (existing, unchanged) ────────────────┐   │
│  │  request_q.get() → batch → GPU forward            │   │
│  │  response_qs[cid].put(...)                        │   │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  libgicg_actor.dylib (Go runtime)                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │  N actor goroutines                                │  │
│  │    InferenceShmClient.Request(req)                 │  │
│  │      → req_ring.write_slot(cid, req_id, payload)  │  │
│  │      → resp_ring[cid].spin_wait(req_id)            │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Shared memory blocks (named, OS-managed):               │
│    gicg_req_ring  — N-slot req ring (Go→Py)              │
│    gicg_resp_{cid} — 1-slot resp ring per actor (Py→Go)  │
└─────────────────────────────────────────────────────────┘
```

### Req ring topology:1 shared ring,N-producer

選定方案:**1 個 shared req_ring,N actor goroutine 做 producer,1 Python InfServer
shm_bridge thread 做 consumer**。

理由:
- 1 ring → 1 named SHM block,生命週期管理單一(Python 端 create/unlink);Go 端
  attach by name,無需 per-actor setup
- InfServer 的 batching window 邏輯在 `server_loop` 已有 (`batch_timeout_ms`),
  bridge thread 只需快速 drain req_ring 推 request_q;batching 由 server_loop 搞定
- ring capacity 覆蓋所有 in-flight actor 請求:N=16 actors 同時送,ring≥32 slot 不溢出

反例(N per-actor req ring):
- Python bridge thread 需 poll N 個 ring,輪詢 cost O(N);ring 空 → busy-wait N 倍浪費
- 生命週期:Go 端需知道每個 actor 的 ring name → Config 傳 N 個名字 → 複雜
- InfServer batching 需感知 N 條 ring 才能攢 batch → 改動更大

### Resp ring topology:N per-actor resp rings

選定方案:**N 個 per-actor resp rings,Python InfServer 為 producer,Go actor goroutine
為 consumer**。

理由:
- Response 必須路由回發 request 的 actor(per req_id);共享 resp ring 需 Go 端 scan
  所有 slot 找自己的 req_id → O(N) per response → 慢且複雜
- Per-actor resp ring:每個 actor goroutine spin-wait 自己那個 ring,零衝突
- Single-slot 足夠:每個 actor 同時只有 1 個 in-flight inference(per-actor serial)。
  Single-slot ring = 最簡實現:producer 寫 FULL,consumer 讀走改 EMPTY

### Summary

| Ring | 數量 | Producer | Consumer | Capacity | 理由 |
|------|------|----------|----------|----------|------|
| req_ring | 1 shared | N Go actors | 1 Python bridge | ≥32 slots | 攢 batch 給 server_loop |
| resp_ring_i | N (per-actor) | Python bridge | actor i | 1 slot | 路由精確,zero-contention |

---

## B. Wire Layout

### Slot structure (fixed-size)

每個 slot 佈局:

```
[ status:u8 | _pad:u7 | client_id:u32 | req_id:u32 | payload_len:u32 | payload:bytes[SLOT_PAYLOAD_MAX] ]
```

`status` 值: `0=EMPTY, 1=FULL`。

固定頭部 = `1 + 7(pad) + 4 + 4 + 4 = 20 bytes`。

### Payload: req_ring slot

req_ring 的 payload = Go `EncodeInferRequest` 的 **inner payload**,即:

```
InferRequestHeader (binary-encoded, 36 bytes) ||
dyn_obs (f32 × NDyn) ||
refs   (i64 × NRefs) ||
pay    (f32 × NPay)  ||
static (i32 × NStatic)
```

注意:不含 outer `[u32 len_le]` prefix(SHM 不需要 framing,payload_len 已在 slot header)。

**大小估算**:
- InferRequestHeader = 36 bytes (binary.Size 實測)
- dyn_obs:後處理 NDyn ≈ 400~600 f32 × 4 = 1.6~2.4 KB
- refs:NLegal ≤ 30 × 3 = 90 i64 × 8 = 720 bytes
- pay:NLegal ≤ 30 × 8 colors = 240 f32 × 4 = 960 bytes
- static(首次):ObsMaxHooks × ObsIntsPerHook ≈ 900×64×5 = 288000 i32 × 4 = 1.1 MB
- static(後續):0 bytes (NStatic=0)

**關鍵**:static 首次 request 1.1 MB >>  slot 需覆蓋。若 SLOT_PAYLOAD_MAX = 1.5 MB,
N=32 slot req_ring total = 32 × (20 + 1.5 MB) ≈ 48 MB。

替代方案(建議):static 路徑走現有 TCP socket 首次 warm-up,後續走 SHM(NStatic=0)。
實測 Go perf trace `dmc.build_static_obs` n=2517 calls(vs 47835 inference calls)= ~5%
比率,只在每 episode 首次 request 才有。

兩種 SLOT_PAYLOAD_MAX 方案:

| 方案 | SLOT_PAYLOAD_MAX | Req ring total (N=32) | 限制 |
|------|-----------------|----------------------|------|
| A (推薦) | 16 KB | 512 KB | Static 走 TCP(首次),後續 NStatic=0;slot 16 KB 足夠非 static payload |
| B | 1.5 MB | 48 MB | 所有 payload 走 SHM;Win 48 MB shm 無壓力但記憶體大 |

**推薦方案 A**:Static 首次走現有 TCP socket forward_cb(低頻,~5% requests),
後續 NStatic=0 走 SHM。16 KB slot 足夠所有非 static inference payload。

### Payload: resp_ring_i slot

resp_ring_i 的 payload = InfServer 回傳的 logits bytes:

```
InferResponseHeader (binary-encoded, 9 bytes) ||
logits (f32 × NLogits)  ||
value  (f32 × NValue)   ← 0 (DMC) or 1 (AZ/PPO)
```

大小估算:NLogits ≤ max_actions=30,9 + 30×4 + 1×4 = 133 bytes。

**resp_ring_i single-slot**:capacity=1,SLOT_PAYLOAD_MAX = 256 bytes 足夠。
N=16 resp rings total = 16 × (20 + 256) = 4416 bytes ≈ 4.3 KB。極小。

### Ring header (control plane)

Ring 的 head/tail/count 放在 SHM block 首部:

```
[ head:i32 | tail:i32 | count:i32 | _pad:4 | slots[capacity] ]
```

Lock-free 方案見 §C sync primitives 討論。

---

## C. Cross-platform

### Mac / Linux:POSIX shm_open + mmap

```c
// create (Python side)
int fd = shm_open("/gicg_req_ring", O_CREAT|O_RDWR, 0600);
ftruncate(fd, total_bytes);
void* ptr = mmap(NULL, total_bytes, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);

// attach (Go side)
int fd = shm_open("/gicg_req_ring", O_RDWR, 0);
void* ptr = mmap(NULL, total_bytes, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
```

Python 端:用 `multiprocessing.shared_memory.SharedMemory(name=..., create=True, size=...)`
內部走 `shm_open`,API 已跨平台(Mac/Linux 均支援)。

Go 端:需 cgo shm_open + mmap(標準 POSIX,Go stdlib 無直接 wrapper)。

### Windows:CreateFileMapping + MapViewOfFile

Windows 無 POSIX `shm_open`。等價方案:

```c
// create
HANDLE h = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, size, L"gicg_req_ring");
void* ptr = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, size);

// attach
HANDLE h = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, L"gicg_req_ring");
void* ptr = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, size);
```

Python 端:`multiprocessing.shared_memory.SharedMemory` 在 Windows 內部走
`CreateFileMapping`(CPython `Modules/_multiprocessing/semaphore.c`),名稱加前綴
`"psm_"` → Win named shared memory。

**問題**:Python `SharedMemory` 在 Windows 用 `psm_<name>` 為 section name;
Go cgo 端必須也用同一前綴 attach。等價地:Python 把完整 section handle name 傳 Go。

替代:Go 端自己 `CreateFileMapping`,Python 端 `OpenFileMapping` 走同名 attach。
讓 Go 做 creator,Python 做 attacher —— 生命週期反過來(Go 先起,Python 後 attach)。

**建議:Python 做 creator,Go 做 attacher**,對齊現有 SHMRing 模式(Python master 
start 先建 shm,Go pool 後 attach)。Python 側 `SharedMemory` 在 Win 的完整 section 
name = `"Local\\psm_<name>"`;Go cgo 在 Win 側用 `OpenFileMappingW(L"Local\\psm_gicg_req_ring")`。

### Sync primitives:atomic head/tail + Python-side mp.Lock vs futex

三種選項比較:

| 方案 | Mac/Linux | Windows | 延遲 | 複雜度 |
|------|-----------|---------|------|--------|
| A: Python mp.Lock(serialize Go 端也用) | POSIX sem_t | Win Mutex | ~0.5-2 μs | 高:Go 需 cgo 調 Python mp primitive |
| B: atomic head/tail + spinlock + usleep backoff | asm atomics | asm atomics | <100 ns (no contention) | 中:cgo atomic intrinsics |
| C: atomic + semaphore signal/wait | sem_post/wait | ReleaseSemaphore/WaitForSingleObject | ~0.5-2 μs | 中:cgo sem + 跨平台 |

**推薦方案 B:lock-free atomic ring + spin-wait with yield**。

理由:
- req_ring 是多 producer single consumer。 可用 `sync/atomic` 做 CAS 搶 tail slot:
  producer 原子讀 count,若 count < capacity 則 CAS tail = (tail+1) % cap。
  只有 count 和 tail 需要原子,head 由單 consumer 更新無衝突。
- resp_ring_i 是 single producer single consumer(1-slot):producer 寫 slot 後 atomic
  store status=FULL;consumer spin-read status 直到 FULL 再讀走。
- Go 端的 spin-wait:用 `runtime.Gosched()` yield 替代 busy-loop,在 Go runtime 
  scheduler 層讓出 M 線程,不完全佔核。若 spin > N 次加 `time.Sleep(time.Microsecond)`
  backoff。
- 不依賴 Python mp.Lock 跨語言 marshal → 最小 cgo 面

**Go atomic in cgo**:用 `sync/atomic` 包(Go side)+ C 端用 `__atomic_xxx` intrinsics
(GCC/clang/MSVC 均支援)操作同一塊 shm 上的 int32 field。

---

## D. Python InfServer 改動(Incremental Bridge 方案)

**選定:shm_bridge thread 橋接 SHM → request_q**,保留 `server_loop` 全部邏輯不變。

### 概要

```
Python InferenceServer
│
├── _server_loop(existing, unchanged)
│     request_q.get() → batch → GPU forward → response_qs[cid].put()
│
└── _shm_bridge_loop(new thread, ~80 LOC)
      req_ring.try_pop() → request_q.put(('infer', cid, req_id, obs_bytes, b''))
      response_qs[cid].get() → resp_ring_cid.push(encoded_response)
```

### 詳細流程

**bridge thread request path**:
1. `req_ring.try_pop()` 取 SHM slot → 得 `(client_id, req_id, payload_bytes)`
2. `obs_bytes = payload_bytes`(已是 Go EncodeInferRequest inner payload format)
3. `request_q.put(('infer', client_id, req_id, obs_bytes, b''))` —— 與現有 socket
   `forward_cb` 推入格式完全相同,`server_loop` 看不到差別

**bridge thread response path**:
1. `kind, rid, resp_bytes = response_qs[client_id].get(timeout=0.5)`
2. 組裝 `InferResponseHeader + logits bytes` 寫入 `resp_ring_cid.push(resp_bytes)`
3. Go actor goroutine 在 resp_ring_cid spin-wait 讀走

### 改動文件

| 文件 | 改動 | LOC |
|------|------|-----|
| `training/core/actor/inference_server.py` | 加 `shm_clients: int` 參數;`__init__` 建 shm rings + bridge event;`start()` 前起 bridge thread;`stop()` 清理 rings | +60 |
| `training/core/actor/inference_server_shm_bridge.py` (new) | `_shm_bridge_loop` 函數 + `start_bridge_in_thread`;從 req_ring drain + 向 resp_rings 路由 | ~120 LOC |
| `training/core/actor/ipc/ring_shm.py` (new) | `SHMRingCrossLang`:固定槽位 SHM ring,用 Python `SharedMemory` + `ctypes.atomic` 或 polling;Go-readable layout(不用 pickle) | ~150 LOC |

### 為何不改 server_loop 主迴圈

改 server_loop 需要在 batching 窗口邏輯裡同時 poll `request_q` 和 N 個 resp_rings,
控制流複雜度上升、測試負擔大。 bridge thread 方案把 SHM ↔ mp.Queue 轉換抽離,
`server_loop` 視角只見 `request_q`,改動量和回歸風險遠低。

---

## E. Go-side 改動

### InferenceShmClient interface

新增 `InferenceShmClient` 與現有 `InferenceClient` 同 API:

```go
// inference_shm_client.go
type InferenceShmClient struct {
    reqRing    *ShmRing  // shared N-slot req ring (Go attaches by name)
    respRing   *ShmRing  // per-actor 1-slot resp ring
    clientID   uint32
    timeout    time.Duration
}

// Implement same call signature as InferenceClient.Request
func (c *InferenceShmClient) Request(req *InferRequest) (*InferResponse, error)
```

`Request` 實現:
1. `EncodeInferRequest` inner payload(去掉 outer `[u32 len]` prefix)
2. Spin-acquire slot in `reqRing` (CAS tail)
3. Copy payload + header (client_id, req_id, payload_len, status=FULL) into slot
4. Spin-wait `respRing.slot[0].status == FULL`
5. Copy out resp payload → `DecodeInferResponse`

**pool.go 改動**:
- 加 `ShmInfServerConfig` 欄位(ring names + capacity);為空時走現有 TCP 路徑
- `StartPoolWithConfig`:若 `ShmInfServerConfig` 非空,建 `InferenceShmClient` 而非
  `InferenceClient`;傳入 actor goroutine

**Adapter interface 不變**:paradigm 的 `Run(ctx, actorID, infCli, transWri)` 接受
`*InferenceClient` → 改 interface 到 `InferenceClientIface` 或直接讓
`InferenceShmClient` 嵌入同一個 wrapper 實現現有函數簽名。

選項:
- A:定義 `InferenceClientIface` interface,`InferenceClient` 和 `InferenceShmClient`
  各 implement → `Run` 接 interface → paradigm.go 不改一行
- B:在 pool.go 中用 `InferenceShmClient` 替換 `currentInfs[i]`,強轉 → 改 paradigm.Run 簽名

**推薦選項 A**:定義 interface,LOC +5,paradigm 代碼零改。

```go
// adapter.go 加
type InferenceRequester interface {
    Request(*InferRequest) (*InferResponse, error)
    Close() error
}

// Paradigm.Run 改為接 InferenceRequester
type Paradigm interface {
    Name() string
    Configure(jsonCfg string) error
    Run(ctx context.Context, actorID int, infCli InferenceRequester, transWri *TransitionWriter) error
}
```

---

## F. C cgo Bridge (跨平台 SHM 抽象)

### 文件佈局

```
gicg_actor/shm/
├── shm_ring.h         — C API 宣告(create/attach/read/write/signal/wait)
├── shm_unix.c         — Mac + Linux 實現(shm_open + mmap + __atomic)
├── shm_win.c          — Windows 實現(CreateFileMapping + MapViewOfFile + _InterlockedCompareExchange)
└── shm_go_binding.go  — cgo binding + Go ShmRing struct wrapper
```

### C API 宣告(shm_ring.h)

```c
// Slot status constants
#define SHM_SLOT_EMPTY 0
#define SHM_SLOT_FULL  1

// Control header (first bytes of SHM block)
typedef struct {
    volatile int32_t head;     // consumer reads from here
    volatile int32_t tail;     // producer writes here
    volatile int32_t count;    // current items
    int32_t          capacity; // ring capacity (set at create, read-only after)
    int32_t          slot_size;// total slot size in bytes
    int32_t          _pad[3];  // align to 32 bytes
} ShmRingHeader;

// Slot header (prefix of each slot)
typedef struct {
    volatile uint8_t status;   // SHM_SLOT_EMPTY / SHM_SLOT_FULL
    uint8_t          _pad[7];  // align to 8 bytes
    uint32_t         client_id;
    uint32_t         req_id;
    uint32_t         payload_len;
} ShmSlotHeader;

// Operations
typedef struct { void* ptr; int64_t size; } ShmHandle;

ShmHandle shm_create(const char* name, int64_t total_bytes); // returns ptr+size or {NULL,0}
ShmHandle shm_attach(const char* name, int64_t total_bytes);
void      shm_detach(ShmHandle h);
void      shm_unlink(const char* name);  // owner only

// Lock-free multi-producer push:CAS tail;returns 1 on success,0 if full
int shm_ring_push(ShmHandle h, uint32_t client_id, uint32_t req_id,
                  const void* payload, uint32_t payload_len);

// Single-consumer pop:returns 1 + fills out_* on success,0 if empty
int shm_ring_pop(ShmHandle h, uint32_t* out_cid, uint32_t* out_req_id,
                 void* out_payload, uint32_t* out_payload_len, uint32_t max_payload);

// Single-slot resp ring write (producer side):waits until slot EMPTY,writes,marks FULL
void shm_resp_write(ShmHandle h, uint32_t req_id, const void* payload, uint32_t len);

// Single-slot resp ring read (consumer side):spin-wait until FULL,reads,marks EMPTY
void shm_resp_read(ShmHandle h, uint32_t* out_req_id, void* out_payload,
                   uint32_t* out_len, uint32_t max_len);
```

### Mac/Linux 實現要點(shm_unix.c)

- `shm_create`:shm_open(O_CREAT|O_RDWR) + ftruncate + mmap(MAP_SHARED)
- `shm_attach`:shm_open(O_RDWR) + mmap(MAP_SHARED)
- Atomic ops:`__atomic_compare_exchange_n(&header->tail, &old, new, 0, __ATOMIC_SEQ_CST, __ATOMIC_RELAXED)`
- `shm_ring_push`:
  1. Atomic load `count`;if count >= capacity return 0
  2. CAS `tail = (tail+1)%cap`;retry on CAS fail(ABA 由 count check 保護)
  3. memcpy payload into slot
  4. Atomic store `slot->status = FULL`
  5. Atomic increment `count`
- `shm_ring_pop`(single consumer):
  1. Atomic load `count`;if 0 return 0
  2. Read `head = header->head`
  3. Atomic load `slot->status`;if EMPTY return 0(count non-zero但slot尚未FULL:producer 在 CAS tail 和 store FULL 之間,短暫不一致)
  4. memcpy slot payload to out
  5. Atomic store `slot->status = EMPTY`
  6. `header->head = (head+1)%cap` (single consumer,no atomic needed)
  7. Atomic decrement `count`

### Windows 實現要點(shm_win.c)

- `shm_create`:CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, size, name) + MapViewOfFile
- `shm_attach`:OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, name) + MapViewOfFile
- Atomic ops:`_InterlockedCompareExchange` (32-bit) 或 `InterlockedAdd`
- 其餘邏輯同 Unix

### Go binding(shm_go_binding.go)

```go
package shm

// #cgo LDFLAGS: -lrt  (Linux only — Mac 無需,Win 用 Kernel32)
// #include "shm_ring.h"
import "C"
import "unsafe"

type ShmRing struct {
    handle C.ShmHandle
    name   string
    owner  bool
}

func Create(name string, totalBytes int64) (*ShmRing, error) { ... }
func Attach(name string, totalBytes int64) (*ShmRing, error) { ... }
func (r *ShmRing) Push(clientID, reqID uint32, payload []byte) bool { ... }
func (r *ShmRing) Pop(outPayload []byte) (clientID, reqID, payloadLen uint32, ok bool) { ... }
func (r *ShmRing) RespWrite(reqID uint32, payload []byte) { ... }
func (r *ShmRing) RespReadSpin(outPayload []byte, timeout time.Duration) (reqID, payloadLen uint32, err error) { ... }
func (r *ShmRing) Close() { ... }
```

**cgo build tag**:
- Mac:無需 LDFLAGS(`shm_open` 在 libSystem)
- Linux:`#cgo linux LDFLAGS: -lrt`
- Windows:`#cgo windows LDFLAGS: -lkernel32`

---

## G. Risk + 測試策略

### 主要 risk

| Risk | 概率 | 嚴重性 | 緩解方案 |
|------|------|--------|---------|
| Windows `psm_` SHM name 前綴不匹配 | 中 | 高 | Python 端把完整名稱傳給 Go;單測 verify attach |
| Atomic ring ABA problem(count/status 不一致) | 中 | 中 | Pop 檢查 slot status FULL 而非僅 count;壓測 spike |
| Go spin-wait 佔核導致 scheduler stall | 低 | 中 | 加 `runtime.Gosched()` + μs backoff;perf trace 監控 |
| InfServer shm_bridge thread 和 server_loop request_q 競爭 | 低 | 低 | request_q 已設計為 MP-safe;bridge 只是又一個 producer |
| Static payload(1.1 MB)超 slot 上限 | 確定 | 中 | 方案 A:static 首次走 TCP;後續 NStatic=0 走 SHM |
| Python SharedMemory 在 Win 的 unlink 行為 | 中 | 低 | Win 無 shm_unlink;`SharedMemory.unlink()` no-op;Go 端 CloseHandle 即可 |

### 測試策略

#### T-SHM1:C ring 跨進程基本 push/pop

- Spike:單獨 C 程式 create ring → fork → child attach → parent push 5 int32 → child pop → verify
- 覆蓋:Mac + Win(CI 暫只 Mac)

#### T-SHM2:Go ↔ Python 跨語言 SHM spike

Phase 2 spike(100-200 LOC,見 §H):
- Go write 1 int32 into shared slot
- Python `SharedMemory.attach` read same 4 bytes
- Verify value matches

#### T-SHM3:InferenceShmClient round-trip

- Test:Mock Python server loop;Go `InferenceShmClient.Request` × 100;verify logits shape
- 平台:Mac only first

#### T-SHM4:Bridge thread vs TCP fallback

- InferenceServer 起 `shm_clients=N`;Go actor 用 shm path;verify batching_efficiency > socket path

#### T-SHM5:E2E perf compare

- Mac N=4:Python mp vs Go-actor-shm 各 50K frames
- Win N=16:同上
- 接受標準:Go-actor-shm fps ≥ Python mp fps

---

## H. LOC + 時間估算

### Phase 1 設計 + Spike(此文件輸出)

| 產出 | LOC |
|------|-----|
| `shminf_design.md`(此文件) | — |
| Phase 2 spike:Go writes int,Python reads | ~150 |

### Phase 2 實現

| 文件 | LOC(新增) | 備注 |
|------|----------|------|
| `gicg_actor/shm/shm_ring.h` | ~60 | C API 宣告 |
| `gicg_actor/shm/shm_unix.c` | ~120 | Mac + Linux SHM ops |
| `gicg_actor/shm/shm_win.c` | ~120 | Windows SHM ops |
| `gicg_actor/shm/shm_go_binding.go` | ~100 | cgo wrapper |
| `gicg_actor/inference_shm_client.go` | ~150 | InferenceShmClient impl |
| `gicg_actor/adapter.go` | +15 | InferenceRequester interface |
| `gicg_actor/pool.go` | +40 | ShmInfServerConfig + 分支 |
| `training/core/actor/ipc/ring_shm.py` | ~150 | Python SHMRingCrossLang |
| `training/core/actor/inference_server_shm_bridge.py` | ~120 | bridge thread loop |
| `training/core/actor/inference_server.py` | +60 | shm_clients param + bridge lifecycle |
| `training/paradigms/dmc/go_collector.py` | +20 | ShmInfServerConfig 傳入 |
| Tests | ~200 | T-SHM1..5 |
| **Total** | **~1155 LOC** | 不含 spike |

### 時間估算

依 LOC 估算(CLAUDE.md 工作習慣):
- C bridge + Go binding:~550 LOC = 估計最密集部分(跨平台語義驗證)
- Python bridge + ring_shm:~330 LOC = 算法直接,Python SharedMemory 熟悉
- Integration + tests:~200+200 LOC = 中等

總計:~1155 production LOC + 200 test LOC。 估 6-8 commit 單元。

---

## 阶段 2:最小 spike 方案(100-200 LOC,Mac only)

### 目標

驗證 Go writes int32 → Python reads same int32 via cross-language SHM,走完整路徑:
`shm_open + mmap`(Go cgo) + `SharedMemory(name=...)`(Python)。

### Spike 實現

**文件**:`gicg_actor/shm/spike/`(不進 production build)

```
gicg_actor/shm/spike/
├── shm_spike.h        (~20 LOC)  — create/attach/write/read/unlink
├── shm_spike_unix.c   (~50 LOC)  — shm_open + mmap + write int32
└── shm_spike_go.go    (~30 LOC)  — cgo binding,expose WriteInt32 / ReadInt32
```

```
tools/_bench/shm_spike_test.py (~60 LOC)
    - Go side:build spike .dylib,ctypes load,WriteInt32(name, value)
    - Python side:SharedMemory(name, create=False),ctypes.c_int32.from_buffer(shm.buf),read
    - Assert value matches
    - Run N=1000 iterations:verify zero read-back errors
```

**Spike 驗收**:
1. Mac:1000 回合 zero error
2. Python attach name = Go shm_open name(同名規則驗證)
3. Latency probe:Go WriteInt32 + Python read RTT < 1 μs mean

若 spike 通過 → 執行 §H Phase 2 實現。
若 spike 失敗(Win name mismatch 或 atomic 不一致)→ 改設計再 spike。

---

## 決策摘要

| 決策點 | 選擇 | 理由 |
|--------|------|------|
| Req ring topology | 1 shared N-producer ring | 攢 batch 給 InfServer;Go 端無需 N 個 name |
| Resp ring topology | N per-actor single-slot rings | 路由精確;零衝突 |
| Sync primitive | atomic CAS + spin-yield backoff | 最低延遲;無跨語言 lock 依賴 |
| Static payload | 首次 TCP warm-up,後續 NStatic=0 SHM | 16 KB slot 足夠;static 只佔 ~5% requests |
| Python InfServer 改動 | shm_bridge thread 橋接 SHM → request_q | 保留 server_loop 批處理邏輯;最低 LOC;最低回歸風險 |
| InferenceClient interface | 新增 InferenceRequester interface | paradigm.go 零改;A/B 路徑 cfg-driven 切換 |
| C bridge 抽象 | shm_ring.h + shm_unix.c + shm_win.c | 跨平台邏輯隔離;Go 側純 cgo binding |
| SLOT_PAYLOAD_MAX | 16 KB (方案 A) | 覆蓋所有非 static payload;ring 總大小 < 1 MB |

---

## 前置條件與 Spike 驗收門檻

**此 design 僅在以下前提下 proceed 到 Phase 2**:
1. Spike T-SHM2 驗證 Go ↔ Python 同名 SHM attach 成功(Mac 驗,Win 驗)
2. User 確認 LOC ~1155 + ~200 test 投入合理(vs F1 episode-granularity push 的 ~200 LOC)
3. 確認 `feature/i29-go-actor-shminf` branch 是目標分支

**若 Spike 失敗或 user 判 ROI 不足 → 退回 F1 episode-granularity push**,F1 已在
`win_bench_audit.md` 估 Win fps 35-38(接近 Python 40)、Mac fps 25-35,LOC ~200,
risk LOW-MED。
