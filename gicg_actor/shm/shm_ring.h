// shm_ring.h — cross-language SHM ring buffer C API (Mac / Linux / Windows).
//
// Design: openspec/changes/i29-go-actor-pool/shminf_design.md §F
//
// Wire layout (platform-identical so producers/consumers can be on different OS):
//   ShmRingHeader (64-byte cache-line aligned):
//     head:i32 | tail:i32 | count:i32 | capacity:i32 | slot_size:i32 | _pad[11 i32]
//   Slot array (capacity × slot_size bytes):
//     ShmSlotHeader (20-byte) | payload[slot_size - 20]
//   ShmSlotHeader:
//     status:u8 | _pad:7 | client_id:u32 | req_id:u32 | payload_len:u32
//
// Sync: atomic CAS on head/tail/count + atomic store/load on status. The C11
// __atomic_xxx intrinsics are supported by both clang/gcc (Mac/Linux) and
// MinGW gcc (Windows AMD64) with identical memory-order semantics, so the same
// algorithm runs on all three platforms.
//
// Per-platform backend:
//   Mac:     shm_open + mmap (no LDFLAGS needed, libSystem) — shm_unix.c
//   Linux:   shm_open + mmap (-lrt LDFLAGS in Go binding)   — shm_unix.c
//   Windows: CreateFileMapping + MapViewOfFile (-lkernel32) — shm_win.c
//
// Naming convention across platforms:
//   POSIX shm_open requires a leading "/" on the name. Win32 CreateFileMapping
//   does not (and Python multiprocessing.shared_memory.SharedMemory passes
//   user-supplied names verbatim on Win). The Go binding's NormaliseName
//   handles this per-platform — callers can pass either form.

#pragma once

#include <stdint.h>
#include <stddef.h>

// ─── Slot status constants ─────────────────────────────────────────────────
#define SHM_SLOT_EMPTY ((uint8_t)0)
#define SHM_SLOT_FULL  ((uint8_t)1)

// ─── Ring header (first 64 bytes of SHM block) ────────────────────────────
// Padded to a full 64-byte cache line so slots start on a cache-line boundary.
typedef struct {
    volatile int32_t head;      // consumer reads from head slot index
    volatile int32_t tail;      // producer writes to tail slot index
    volatile int32_t count;     // current number of full slots
    int32_t          capacity;  // ring capacity in slots (set at create, read-only after)
    int32_t          slot_size; // total slot size in bytes (header + payload area)
    int32_t          _pad[11];  // pad to 64 bytes (5 used × 4 = 20 bytes; 11 pad × 4 = 44; total 64)
} ShmRingHeader;

// ─── Slot header (prefix of each slot) ────────────────────────────────────
// Fixed 20 bytes: 1+7(pad)+4+4+4.
typedef struct {
    volatile uint8_t status;     // SHM_SLOT_EMPTY / SHM_SLOT_FULL
    uint8_t          _pad[7];    // align subsequent u32 fields to 8-byte boundary
    uint32_t         client_id;  // actor/client identifier for routing
    uint32_t         req_id;     // request sequence number (for resp routing)
    uint32_t         payload_len;// actual payload bytes written (≤ slot_size - 20)
} ShmSlotHeader;

#define SHM_RING_HEADER_SIZE   64   // sizeof(ShmRingHeader) must equal this
#define SHM_SLOT_HEADER_SIZE   20   // sizeof(ShmSlotHeader) must equal this

// ─── Handle ───────────────────────────────────────────────────────────────
// Opaque handle returned by shm_create/shm_attach. ptr points to the mmap'd
// region; size is the total mmap'd size in bytes.
typedef struct {
    void*   ptr;
    int64_t size;
} ShmHandle;

// ─── Lifecycle ────────────────────────────────────────────────────────────

// shm_create creates and maps a new shared-memory block.
// name:       POSIX shm name on Mac/Linux (e.g. "/gicg_req_ring", leading "/"
//             required for shm_open). Win32 named-section name on Windows
//             (no leading "/" required — Python SharedMemory(name=…) passes
//             user-supplied names verbatim to CreateFileMapping).
// total_bytes: total SHM block size in bytes (caller computes from ring layout).
// out_errno:  on failure receives errno (POSIX) or GetLastError() (Win).
// Returns {ptr, size} on success or {NULL, 0} on failure.
ShmHandle shm_create(const char* name, int64_t total_bytes, int* out_errno);

// shm_attach opens an existing SHM block by name.
// Must be called AFTER shm_create by the owner process.
// Returns {ptr, size} on success or {NULL, 0} on failure.
ShmHandle shm_attach(const char* name, int64_t total_bytes, int* out_errno);

// shm_detach unmaps the region.
// On POSIX: munmap; the shm object survives until shm_unlink_name is called.
// On Windows: UnmapViewOfFile + CloseHandle; Win has no shm_unlink semantic,
// the kernel object is reference-counted by HANDLE count and disappears when
// the last holder (this process or another) closes its handle.
void shm_detach(ShmHandle h);

// shm_unlink_name removes the SHM object from the namespace.
// On POSIX (owner only): shm_unlink(name). The object persists until unlinked
// or until reboot; call this on cleanup.
// On Windows: NO-OP. Windows kernel objects are not named-namespace entries
// — closing handles is sufficient. The function is provided for API symmetry
// so cross-platform Go binding code stays uniform.
void shm_unlink_name(const char* name);

// ─── Multi-producer req_ring ops ──────────────────────────────────────────

// shm_ring_push pushes a payload into the ring (multi-producer safe via CAS).
// h:           ring ShmHandle (mmap'd req_ring).
// client_id:   actor identifier written into slot header.
// req_id:      request sequence number written into slot header.
// payload:     pointer to payload bytes.
// payload_len: number of payload bytes (must be ≤ slot_size - SHM_SLOT_HEADER_SIZE).
// Returns 1 on success (slot acquired + payload written), 0 if ring is full.
int shm_ring_push(ShmHandle h, uint32_t client_id, uint32_t req_id,
                  const void* payload, uint32_t payload_len);

// shm_ring_pop pops the head slot (single-consumer).
// h:              ring ShmHandle.
// out_client_id:  filled with slot's client_id.
// out_req_id:     filled with slot's req_id.
// out_payload:    buffer to copy payload into.
// out_payload_len: filled with actual payload bytes copied.
// max_payload:    capacity of out_payload buffer.
// Returns 1 on success (slot consumed), 0 if ring is empty or head slot not yet FULL.
int shm_ring_pop(ShmHandle h, uint32_t* out_client_id, uint32_t* out_req_id,
                 void* out_payload, uint32_t* out_payload_len, uint32_t max_payload);

// ─── Single-slot resp_ring ops ─────────────────────────────────────────────

// shm_resp_write writes a response payload into a single-slot resp ring.
// Spins until the slot is EMPTY (consumer has read the previous response), then
// writes the payload and marks the slot FULL.
// h:           resp ring ShmHandle (capacity=1 ring).
// req_id:      echoed back in slot header (for consumer validation).
// payload:     response bytes.
// len:         number of response bytes.
// timeout_ms:  maximum ms to spin-wait for slot EMPTY; 0 = spin forever.
// Returns 1 on success, 0 on timeout.
int shm_resp_write(ShmHandle h, uint32_t req_id,
                   const void* payload, uint32_t len, int timeout_ms);

// shm_resp_read reads a response from a single-slot resp ring.
// Spins until the slot is FULL (producer has written), then reads and marks EMPTY.
// h:            resp ring ShmHandle.
// out_req_id:   filled with echoed req_id.
// out_payload:  buffer to copy response into.
// out_len:      filled with actual bytes copied.
// max_len:      capacity of out_payload.
// timeout_ms:   maximum ms to spin-wait for slot FULL; 0 = spin forever.
// Returns 1 on success, 0 on timeout.
int shm_resp_read(ShmHandle h, uint32_t* out_req_id,
                  void* out_payload, uint32_t* out_len, uint32_t max_len, int timeout_ms);
