// shm_win.c — Windows SHM ring implementation.
//
// Platform: Windows (cgo build under MinGW GCC).
// Counterpart to shm_unix.c — same wire format / same struct layout / same atomic
// semantics, but using Win32 Named Shared Memory (CreateFileMapping + MapViewOfFile)
// instead of POSIX shm_open + mmap.
//
// Atomics: MinGW GCC fully supports C11 __atomic_xxx intrinsics on Windows AMD64,
// so we reuse the same atomic operations as the POSIX impl (acquire / release /
// CAS) — no need for MSVC _Interlocked wrappers.
//
// Naming compatibility with Python multiprocessing.shared_memory.SharedMemory:
//   CPython (≥ 3.8) on Windows internally calls CreateFileMapping(name=<bare>)
//   with the user-supplied name **as-is** (no prefix added). The "wnsm_" prefix
//   appears only in auto-generated names returned by _make_filename() for
//   SharedMemory(name=None). When the Python caller passes an explicit name like
//   "gicg_req_ring", that exact string becomes the kernel object name. Therefore
//   the Go cgo side must also use the bare name (no leading "/") for
//   CreateFileMappingA on Windows. The Mac/Linux POSIX requirement of "/<name>"
//   for shm_open does NOT apply here.
//
// Design: openspec/changes/i29-go-actor-pool/shminf_design.md §C, §F.

// Whole-file guard: on Mac/Linux we use shm_unix.c. cgo compiles every .c in
// this package directory regardless of which .go build tags are active, so the
// only reliable way to exclude this TU from a POSIX build is to gate on _WIN32
// at the C preprocessor level. (shm_unix.c has the mirror `#ifndef _WIN32`.)
#ifdef _WIN32

// Target Windows 7+ (for INIT_ONCE / modern Win APIs); Vista is sufficient for
// CreateFileMapping / MapViewOfFile but newer baseline is more standard.
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif

#include "shm_ring.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

// ─── Compile-time layout assertions ────────────────────────────────────────
// Catch struct size mismatches across compilers (MSVC vs MinGW vs Clang) so
// the cross-process layout stays byte-identical with the Unix impl.
_Static_assert(sizeof(ShmRingHeader) == SHM_RING_HEADER_SIZE,
               "ShmRingHeader must be 64 bytes");
_Static_assert(sizeof(ShmSlotHeader) == SHM_SLOT_HEADER_SIZE,
               "ShmSlotHeader must be 20 bytes");

// ─── Internal helpers ───────────────────────────────────────────────────────

// slot_ptr returns a pointer to the start of slot[idx] within the ring.
// idx is taken modulo capacity so callers can pass raw monotonic indices.
static inline char* slot_ptr(ShmHandle h, int32_t idx) {
    ShmRingHeader* hdr = (ShmRingHeader*)h.ptr;
    int32_t cap = hdr->capacity;
    int32_t slot_size = hdr->slot_size;
    int32_t wrapped = ((idx % cap) + cap) % cap;
    return (char*)h.ptr + SHM_RING_HEADER_SIZE + (size_t)wrapped * (size_t)slot_size;
}

// slot_payload returns pointer to the payload area within a slot.
static inline char* slot_payload(char* slot) {
    return slot + SHM_SLOT_HEADER_SIZE;
}

// monotonic_ms returns monotonic milliseconds (for timeouts).
// GetTickCount64 is monotonic across the system, ms resolution, no wrap on 64-bit.
static int64_t monotonic_ms(void) {
    return (int64_t)GetTickCount64();
}

// yield_cpu hands control to another runnable thread on the same processor.
// SwitchToThread() returns immediately if no other thread is ready (similar to
// sched_yield()). For longer waits we fall back to Sleep(0) which yields to any
// equal-priority thread on any processor.
static inline void yield_cpu(void) {
    SwitchToThread();
}

// short_sleep_us sleeps for approximately 1 µs. Windows scheduler quantum is
// ~15.6 ms so true µs sleep is impossible without timeBeginPeriod (which has
// global side effects). Sleep(0) yields the time slice but burns no scheduler
// time. We accept the coarser granularity — the spin loop already calls yield
// first for short waits.
static inline void short_sleep_us(void) {
    Sleep(0);
}

// ─── Lifecycle ─────────────────────────────────────────────────────────────
//
// SHM block lifecycle on Windows:
//   - shm_create: CreateFileMappingA(INVALID_HANDLE_VALUE, …, name) creates a
//     backed-by-paging-file kernel object. We then MapViewOfFile to get a
//     virtual-memory pointer.
//   - shm_attach: OpenFileMappingA(FILE_MAP_ALL_ACCESS, …, name) opens the
//     existing kernel object created by shm_create or by Python's SharedMemory.
//     MapViewOfFile then gives us the same shared memory region.
//   - shm_detach: UnmapViewOfFile releases the virtual address mapping (but the
//     kernel object survives as long as any handle is open).
//   - shm_unlink_name: NO-OP on Windows. Windows kernel objects are reference-
//     counted by open HANDLE count, not by name. The object disappears
//     automatically when all handles close — there is no shm_unlink equivalent.
//     We close the handle in shm_detach (handle stored alongside the pointer).
//
// Handle storage trick: ShmHandle is {void* ptr; int64_t size}. We need to keep
// the Win HANDLE alive so the mapping does not get torn down before
// UnmapViewOfFile. We allocate a small bookkeeping struct, store the HANDLE in
// it, and stash a pointer to that struct via a side table keyed by ptr. Simpler
// alternative: stash the HANDLE in a per-allocation header just before the
// mapped region — but we can not modify shm_ring.h's ShmHandle struct without
// breaking ABI with shm_unix.c.
//
// Chosen approach: maintain a small linear array of (ptr → handle) pairs
// protected by a CRITICAL_SECTION. Linear scan is O(N) but N is the number of
// live SHM rings per process (typically ≤ 32) so this is fine. Avoids dynamic
// allocation per slot lookup.

#define MAX_LIVE_HANDLES 64

typedef struct {
    void*  ptr;
    HANDLE h;
} HandleEntry;

static HandleEntry      g_handles[MAX_LIVE_HANDLES];
static CRITICAL_SECTION g_handles_lock;
static INIT_ONCE        g_init_once = INIT_ONCE_STATIC_INIT;

static BOOL CALLBACK init_handles_table(PINIT_ONCE once, PVOID param, PVOID* ctx) {
    (void)once; (void)param; (void)ctx;
    InitializeCriticalSection(&g_handles_lock);
    memset(g_handles, 0, sizeof(g_handles));
    return TRUE;
}

static void ensure_handles_init(void) {
    InitOnceExecuteOnce(&g_init_once, init_handles_table, NULL, NULL);
}

// Store (ptr, h). Returns 1 on success, 0 if table is full.
static int handles_store(void* ptr, HANDLE h) {
    ensure_handles_init();
    EnterCriticalSection(&g_handles_lock);
    int ok = 0;
    for (int i = 0; i < MAX_LIVE_HANDLES; i++) {
        if (g_handles[i].ptr == NULL) {
            g_handles[i].ptr = ptr;
            g_handles[i].h   = h;
            ok = 1;
            break;
        }
    }
    LeaveCriticalSection(&g_handles_lock);
    return ok;
}

// Find and remove entry for ptr. Returns the HANDLE (NULL if not found).
static HANDLE handles_take(void* ptr) {
    ensure_handles_init();
    HANDLE found = NULL;
    EnterCriticalSection(&g_handles_lock);
    for (int i = 0; i < MAX_LIVE_HANDLES; i++) {
        if (g_handles[i].ptr == ptr) {
            found = g_handles[i].h;
            g_handles[i].ptr = NULL;
            g_handles[i].h   = NULL;
            break;
        }
    }
    LeaveCriticalSection(&g_handles_lock);
    return found;
}

ShmHandle shm_create(const char* name, int64_t total_bytes, int* out_errno) {
    ShmHandle result = {NULL, 0};
    // Create (or open if already exists — matches POSIX shm_open O_CREAT semantic).
    // dwMaximumSizeHigh / Low split the 64-bit size into two DWORDs.
    DWORD size_hi = (DWORD)((uint64_t)total_bytes >> 32);
    DWORD size_lo = (DWORD)((uint64_t)total_bytes & 0xFFFFFFFFu);
    HANDLE h = CreateFileMappingA(
        INVALID_HANDLE_VALUE,    // backed by system paging file
        NULL,                    // default security
        PAGE_READWRITE,
        size_hi,
        size_lo,
        name);
    if (h == NULL) {
        if (out_errno) *out_errno = (int)GetLastError();
        return result;
    }
    // Note: if the mapping already existed, GetLastError() returns
    // ERROR_ALREADY_EXISTS but the handle is still valid (same as POSIX
    // shm_open without O_EXCL). We accept that — caller may legitimately reuse.

    void* ptr = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, (SIZE_T)total_bytes);
    if (ptr == NULL) {
        if (out_errno) *out_errno = (int)GetLastError();
        CloseHandle(h);
        return result;
    }
    if (!handles_store(ptr, h)) {
        // Bookkeeping table full — fail loud rather than leak the HANDLE.
        if (out_errno) *out_errno = (int)ERROR_TOO_MANY_OPEN_FILES;
        UnmapViewOfFile(ptr);
        CloseHandle(h);
        return result;
    }
    // Zero-initialise so head/tail/count/status all start at 0.
    memset(ptr, 0, (size_t)total_bytes);
    result.ptr = ptr;
    result.size = total_bytes;
    return result;
}

ShmHandle shm_attach(const char* name, int64_t total_bytes, int* out_errno) {
    ShmHandle result = {NULL, 0};
    HANDLE h = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, name);
    if (h == NULL) {
        if (out_errno) *out_errno = (int)GetLastError();
        return result;
    }
    void* ptr = MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, (SIZE_T)total_bytes);
    if (ptr == NULL) {
        if (out_errno) *out_errno = (int)GetLastError();
        CloseHandle(h);
        return result;
    }
    if (!handles_store(ptr, h)) {
        if (out_errno) *out_errno = (int)ERROR_TOO_MANY_OPEN_FILES;
        UnmapViewOfFile(ptr);
        CloseHandle(h);
        return result;
    }
    result.ptr = ptr;
    result.size = total_bytes;
    return result;
}

void shm_detach(ShmHandle h) {
    if (!h.ptr) return;
    HANDLE win_h = handles_take(h.ptr);
    UnmapViewOfFile(h.ptr);
    if (win_h) {
        CloseHandle(win_h);
    }
    // NOTE: Closing the last HANDLE to the section deletes the kernel object.
    // If both Python (via SharedMemory) and Go hold handles, the section
    // survives until both close. This matches Python's SharedMemory.close()
    // semantics and POSIX's mmap+close behaviour (object persists until unlink).
}

void shm_unlink_name(const char* name) {
    (void)name;
    // NO-OP on Windows. Kernel objects are reference-counted by HANDLE; there
    // is no namespace unlink. The object disappears when the last handle
    // closes (via shm_detach above). This is intentional — provides the same
    // function signature as shm_unix.c so Go binding stays platform-agnostic.
}

// ─── Multi-producer req_ring: shm_ring_push ────────────────────────────────
//
// Algorithm identical to shm_unix.c (see that file for full design notes).
// C11 __atomic intrinsics are supported by MinGW GCC on Windows AMD64 with
// the same memory-order semantics as on Linux/Mac.
//
// 2026-05-27 fix: count-CAS-first replaces the racy "load count → CAS tail
// → count++" pattern that caused Win N=19 production deadlock. See
// shm_unix.c for the full root-cause writeup.

int shm_ring_push(ShmHandle h, uint32_t client_id, uint32_t req_id,
                  const void* payload, uint32_t payload_len) {
    if (!h.ptr) return 0;
    ShmRingHeader* hdr = (ShmRingHeader*)h.ptr;
    int32_t cap = hdr->capacity;
    int32_t max_payload = hdr->slot_size - SHM_SLOT_HEADER_SIZE;
    if ((int32_t)payload_len > max_payload) return 0;

    // Step 1: Atomically reserve a count slot via CAS.
    int32_t cnt;
    do {
        cnt = __atomic_load_n(&hdr->count, __ATOMIC_ACQUIRE);
        if (cnt >= cap) return 0; // full
    } while (!__atomic_compare_exchange_n(&hdr->count, &cnt, cnt + 1,
                                          0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED));

    // Step 2: Claim a unique tail position via CAS-tail.
    int32_t old_tail, new_tail;
    do {
        old_tail = __atomic_load_n(&hdr->tail, __ATOMIC_RELAXED);
        new_tail = (old_tail + 1) % cap;
    } while (!__atomic_compare_exchange_n(&hdr->tail, &old_tail, new_tail,
                                          0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED));

    // Step 3-4: Write payload, then mark FULL with RELEASE.
    char* slot = slot_ptr(h, old_tail);
    ShmSlotHeader* shdr = (ShmSlotHeader*)slot;
    shdr->client_id = client_id;
    shdr->req_id = req_id;
    shdr->payload_len = payload_len;
    if (payload_len > 0) {
        memcpy(slot_payload(slot), payload, payload_len);
    }
    __atomic_store_n(&shdr->status, SHM_SLOT_FULL, __ATOMIC_RELEASE);
    return 1;
}

// ─── Single-consumer req_ring: shm_ring_pop ───────────────────────────────

int shm_ring_pop(ShmHandle h, uint32_t* out_client_id, uint32_t* out_req_id,
                 void* out_payload, uint32_t* out_payload_len, uint32_t max_payload) {
    if (!h.ptr) return 0;
    ShmRingHeader* hdr = (ShmRingHeader*)h.ptr;

    int32_t cnt = __atomic_load_n(&hdr->count, __ATOMIC_ACQUIRE);
    if (cnt <= 0) return 0;

    int32_t head = __atomic_load_n(&hdr->head, __ATOMIC_RELAXED);
    char* slot = slot_ptr(h, head);
    ShmSlotHeader* shdr = (ShmSlotHeader*)slot;

    uint8_t status = __atomic_load_n(&shdr->status, __ATOMIC_ACQUIRE);
    if (status != SHM_SLOT_FULL) {
        return 0; // transient: producer between CAS and status store
    }

    uint32_t plen = shdr->payload_len;
    if (out_payload_len) *out_payload_len = plen;
    if (out_client_id)  *out_client_id  = shdr->client_id;
    if (out_req_id)     *out_req_id     = shdr->req_id;
    if (plen > 0 && out_payload) {
        uint32_t copy_len = plen < max_payload ? plen : max_payload;
        memcpy(out_payload, slot_payload(slot), copy_len);
    }

    __atomic_store_n(&shdr->status, SHM_SLOT_EMPTY, __ATOMIC_RELEASE);
    int32_t cap = hdr->capacity;
    __atomic_store_n(&hdr->head, (head + 1) % cap, __ATOMIC_RELAXED);
    __atomic_fetch_sub(&hdr->count, 1, __ATOMIC_RELEASE);
    return 1;
}

// ─── Single-slot resp_ring: shm_resp_write ─────────────────────────────────

int shm_resp_write(ShmHandle h, uint32_t req_id,
                   const void* payload, uint32_t len, int timeout_ms) {
    if (!h.ptr) return 0;
    ShmRingHeader* hdr = (ShmRingHeader*)h.ptr;
    int32_t max_payload = hdr->slot_size - SHM_SLOT_HEADER_SIZE;
    if ((int32_t)len > max_payload) return 0;

    char* slot = (char*)h.ptr + SHM_RING_HEADER_SIZE;
    ShmSlotHeader* shdr = (ShmSlotHeader*)slot;

    int64_t deadline = 0;
    if (timeout_ms > 0) {
        deadline = monotonic_ms() + timeout_ms;
    }

    int spin = 0;
    for (;;) {
        uint8_t status = __atomic_load_n(&shdr->status, __ATOMIC_ACQUIRE);
        if (status == SHM_SLOT_EMPTY) break;
        spin++;
        if (spin < 64) {
            yield_cpu();
        } else {
            short_sleep_us();
        }
        if (timeout_ms > 0 && monotonic_ms() >= deadline) {
            return 0; // timeout
        }
    }

    shdr->req_id = req_id;
    shdr->payload_len = len;
    if (len > 0 && payload) {
        memcpy(slot_payload(slot), payload, len);
    }
    __atomic_store_n(&shdr->status, SHM_SLOT_FULL, __ATOMIC_RELEASE);
    return 1;
}

// ─── Single-slot resp_ring: shm_resp_read ──────────────────────────────────

int shm_resp_read(ShmHandle h, uint32_t* out_req_id,
                  void* out_payload, uint32_t* out_len, uint32_t max_len, int timeout_ms) {
    if (!h.ptr) return 0;

    char* slot = (char*)h.ptr + SHM_RING_HEADER_SIZE;
    ShmSlotHeader* shdr = (ShmSlotHeader*)slot;

    int64_t deadline = 0;
    if (timeout_ms > 0) {
        deadline = monotonic_ms() + timeout_ms;
    }

    int spin = 0;
    for (;;) {
        uint8_t status = __atomic_load_n(&shdr->status, __ATOMIC_ACQUIRE);
        if (status == SHM_SLOT_FULL) break;
        spin++;
        if (spin < 64) {
            yield_cpu();
        } else {
            short_sleep_us();
        }
        if (timeout_ms > 0 && monotonic_ms() >= deadline) {
            return 0; // timeout
        }
    }

    uint32_t plen = shdr->payload_len;
    if (out_req_id) *out_req_id = shdr->req_id;
    if (out_len)    *out_len    = plen;
    if (plen > 0 && out_payload) {
        uint32_t copy_len = plen < max_len ? plen : max_len;
        memcpy(out_payload, slot_payload(slot), copy_len);
    }

    __atomic_store_n(&shdr->status, SHM_SLOT_EMPTY, __ATOMIC_RELEASE);
    return 1;
}

#endif // _WIN32 — whole-file guard mirroring shm_unix.c's `#ifndef _WIN32`.
