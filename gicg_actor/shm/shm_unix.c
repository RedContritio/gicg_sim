// shm_unix.c — Mac + Linux POSIX SHM ring implementation.
//
// Platform: Mac (_POSIX_SHARED_MEMORY_OBJECTS defined) + Linux.
// Windows path lives in shm_win.c — see whole-file _WIN32 guard below
// (cgo compiles every .c in this package directory, regardless of build tags
// on sibling .go files, so each .c must self-exclude on the wrong platform).
//
// Sync: C11 __atomic_xxx intrinsics (GCC/Clang compatible).
// The same atomics used in Go binding via cgo.
//
// Design: openspec/changes/i29-go-actor-pool/shminf_design.md §C, §F.

// Whole-file guard: on Windows we use shm_win.c instead. Without this guard a
// Windows cgo build would try to compile sys/mman.h + sched.h + shm_open and
// fail at the system-header layer.
#ifndef _WIN32

// Feature test macro — sched_yield() on macOS requires _DARWIN_C_SOURCE
// before <sched.h>; on Linux _POSIX_C_SOURCE ≥ 200112L is sufficient.
#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L

#include "shm_ring.h"

#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

// ─── Compile-time layout assertions ────────────────────────────────────────
// These catch struct size mismatches if padding changes across compilers.
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
static int64_t monotonic_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + (int64_t)(ts.tv_nsec / 1000000);
}

// ─── Lifecycle ─────────────────────────────────────────────────────────────

ShmHandle shm_create(const char* name, int64_t total_bytes, int* out_errno) {
    ShmHandle result = {NULL, 0};
    // Open (create) the shm object.
    int fd = shm_open(name, O_CREAT | O_RDWR | O_EXCL, 0600);
    if (fd < 0) {
        // O_EXCL fail: try without — caller may reuse an existing segment.
        fd = shm_open(name, O_CREAT | O_RDWR, 0600);
        if (fd < 0) {
            if (out_errno) *out_errno = errno;
            return result;
        }
    }
    if (ftruncate(fd, (off_t)total_bytes) != 0) {
        if (out_errno) *out_errno = errno;
        close(fd);
        return result;
    }
    void* ptr = mmap(NULL, (size_t)total_bytes,
                     PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd); // fd no longer needed after mmap
    if (ptr == MAP_FAILED) {
        if (out_errno) *out_errno = errno;
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
    int fd = shm_open(name, O_RDWR, 0);
    if (fd < 0) {
        if (out_errno) *out_errno = errno;
        return result;
    }
    void* ptr = mmap(NULL, (size_t)total_bytes,
                     PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (ptr == MAP_FAILED) {
        if (out_errno) *out_errno = errno;
        return result;
    }
    result.ptr = ptr;
    result.size = total_bytes;
    return result;
}

void shm_detach(ShmHandle h) {
    if (h.ptr && h.ptr != MAP_FAILED) {
        munmap(h.ptr, (size_t)h.size);
    }
}

void shm_unlink_name(const char* name) {
    shm_unlink(name);
}

// ─── Multi-producer req_ring: shm_ring_push ────────────────────────────────
//
// Lock-free N-producer 1-consumer ring using C11 atomics:
//   1. Atomic load count; if count >= capacity → ring full, return 0.
//   2. CAS tail from old to (old+1)%cap; retry on CAS fail (another producer raced).
//   3. Write payload into slot[old].
//   4. Atomic store slot->status = FULL.
//   5. Atomic increment count.
//
// ABA protection: count check prevents wrap-around from causing false-empty
// reads, and slot status is checked by consumer before marking head consumed.

int shm_ring_push(ShmHandle h, uint32_t client_id, uint32_t req_id,
                  const void* payload, uint32_t payload_len) {
    if (!h.ptr) return 0;
    ShmRingHeader* hdr = (ShmRingHeader*)h.ptr;
    int32_t cap = hdr->capacity;
    int32_t max_payload = hdr->slot_size - SHM_SLOT_HEADER_SIZE;
    if ((int32_t)payload_len > max_payload) return 0;

    // Spin until we acquire a slot via CAS on tail.
    for (;;) {
        int32_t cnt = __atomic_load_n(&hdr->count, __ATOMIC_ACQUIRE);
        if (cnt >= cap) {
            return 0; // full
        }
        int32_t old_tail = __atomic_load_n(&hdr->tail, __ATOMIC_RELAXED);
        int32_t new_tail = (old_tail + 1) % cap;
        // CAS tail: if another producer raced and changed tail, retry.
        if (__atomic_compare_exchange_n(&hdr->tail, &old_tail, new_tail,
                                        0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
            // We own slot[old_tail]. Write payload.
            char* slot = slot_ptr(h, old_tail);
            ShmSlotHeader* shdr = (ShmSlotHeader*)slot;
            // status must currently be EMPTY (producer cannot overwrite FULL).
            // In a correctly-used ring this always holds since we checked count.
            shdr->client_id = client_id;
            shdr->req_id = req_id;
            shdr->payload_len = payload_len;
            if (payload_len > 0) {
                memcpy(slot_payload(slot), payload, payload_len);
            }
            // Release store: make payload visible before setting FULL.
            __atomic_store_n(&shdr->status, SHM_SLOT_FULL, __ATOMIC_RELEASE);
            // Increment count so consumer sees one more item.
            __atomic_fetch_add(&hdr->count, 1, __ATOMIC_RELEASE);
            return 1;
        }
        // CAS failed — another producer got this slot; retry.
    }
}

// ─── Single-consumer req_ring: shm_ring_pop ───────────────────────────────
//
// Single-consumer pop:
//   1. Atomic load count; if 0 → empty, return 0.
//   2. Read head (single consumer owns head, no atomic needed for head itself).
//   3. Atomic load slot->status; if EMPTY → producer between CAS and store FULL,
//      return 0 (transient state; consumer will retry next call).
//   4. memcpy payload out.
//   5. Atomic store slot->status = EMPTY.
//   6. head = (head+1)%cap (non-atomic, single consumer).
//   7. Atomic decrement count.

int shm_ring_pop(ShmHandle h, uint32_t* out_client_id, uint32_t* out_req_id,
                 void* out_payload, uint32_t* out_payload_len, uint32_t max_payload) {
    if (!h.ptr) return 0;
    ShmRingHeader* hdr = (ShmRingHeader*)h.ptr;

    int32_t cnt = __atomic_load_n(&hdr->count, __ATOMIC_ACQUIRE);
    if (cnt <= 0) return 0;

    int32_t head = __atomic_load_n(&hdr->head, __ATOMIC_RELAXED);
    char* slot = slot_ptr(h, head);
    ShmSlotHeader* shdr = (ShmSlotHeader*)slot;

    // Producer may have incremented count but not yet stored FULL.
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

    // Mark slot EMPTY (release so payload reads happen before this store).
    __atomic_store_n(&shdr->status, SHM_SLOT_EMPTY, __ATOMIC_RELEASE);
    // Advance head (single consumer: relaxed store).
    int32_t cap = hdr->capacity;
    __atomic_store_n(&hdr->head, (head + 1) % cap, __ATOMIC_RELAXED);
    // Decrement count.
    __atomic_fetch_sub(&hdr->count, 1, __ATOMIC_RELEASE);
    return 1;
}

// ─── Single-slot resp_ring: shm_resp_write ─────────────────────────────────
//
// Producer side: spin until slot EMPTY, then write and mark FULL.
// Spin uses sched_yield() to avoid burning a core while blocked.
// timeout_ms=0 means spin forever (blocking).

int shm_resp_write(ShmHandle h, uint32_t req_id,
                   const void* payload, uint32_t len, int timeout_ms) {
    if (!h.ptr) return 0;
    ShmRingHeader* hdr = (ShmRingHeader*)h.ptr;
    int32_t max_payload = hdr->slot_size - SHM_SLOT_HEADER_SIZE;
    if ((int32_t)len > max_payload) return 0;

    // resp ring has capacity=1; slot 0 is always the single slot.
    char* slot = (char*)h.ptr + SHM_RING_HEADER_SIZE;
    ShmSlotHeader* shdr = (ShmSlotHeader*)slot;

    int64_t deadline = 0;
    if (timeout_ms > 0) {
        deadline = monotonic_ms() + timeout_ms;
    }

    // Spin-wait until slot is EMPTY.
    int spin = 0;
    for (;;) {
        uint8_t status = __atomic_load_n(&shdr->status, __ATOMIC_ACQUIRE);
        if (status == SHM_SLOT_EMPTY) break;
        spin++;
        if (spin < 64) {
            // Short spin: yield to other threads on same core.
            sched_yield();
        } else {
            // Longer wait: sleep 1 µs.
            struct timespec ts = {0, 1000};
            nanosleep(&ts, NULL);
        }
        if (timeout_ms > 0 && monotonic_ms() >= deadline) {
            return 0; // timeout
        }
    }

    // Write payload.
    shdr->req_id = req_id;
    shdr->payload_len = len;
    if (len > 0 && payload) {
        memcpy(slot_payload(slot), payload, len);
    }
    // Release store: make payload visible before FULL.
    __atomic_store_n(&shdr->status, SHM_SLOT_FULL, __ATOMIC_RELEASE);
    return 1;
}

// ─── Single-slot resp_ring: shm_resp_read ──────────────────────────────────
//
// Consumer side: spin until slot FULL, then read and mark EMPTY.

int shm_resp_read(ShmHandle h, uint32_t* out_req_id,
                  void* out_payload, uint32_t* out_len, uint32_t max_len, int timeout_ms) {
    if (!h.ptr) return 0;

    // resp ring has capacity=1; slot 0 is always the single slot.
    char* slot = (char*)h.ptr + SHM_RING_HEADER_SIZE;
    ShmSlotHeader* shdr = (ShmSlotHeader*)slot;

    int64_t deadline = 0;
    if (timeout_ms > 0) {
        deadline = monotonic_ms() + timeout_ms;
    }

    // Spin-wait until slot is FULL.
    int spin = 0;
    for (;;) {
        uint8_t status = __atomic_load_n(&shdr->status, __ATOMIC_ACQUIRE);
        if (status == SHM_SLOT_FULL) break;
        spin++;
        if (spin < 64) {
            sched_yield();
        } else {
            struct timespec ts = {0, 1000};
            nanosleep(&ts, NULL);
        }
        if (timeout_ms > 0 && monotonic_ms() >= deadline) {
            return 0; // timeout
        }
    }

    // Read payload.
    uint32_t plen = shdr->payload_len;
    if (out_req_id) *out_req_id = shdr->req_id;
    if (out_len)    *out_len    = plen;
    if (plen > 0 && out_payload) {
        uint32_t copy_len = plen < max_len ? plen : max_len;
        memcpy(out_payload, slot_payload(slot), copy_len);
    }

    // Mark EMPTY so producer can write next response.
    __atomic_store_n(&shdr->status, SHM_SLOT_EMPTY, __ATOMIC_RELEASE);
    return 1;
}

#endif // !_WIN32 — whole-file guard so cgo on Windows skips this TU.
