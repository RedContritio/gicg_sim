// Package shm — Windows-specific cgo binding for the cross-language SHM ring.
//
// Mirrors shm.go (Mac/Linux) but with two Windows-specific differences:
//   - LDFLAGS:link kernel32 (CreateFileMapping / MapViewOfFile / Sleep /
//     CRITICAL_SECTION / InitOnceExecuteOnce all live there).
//   - Naming:Python multiprocessing.shared_memory.SharedMemory on Windows
//     passes the user-supplied name **as-is** to CreateFileMapping(name=…),
//     with no prefix added (the "wnsm_" prefix appears only in auto-generated
//     names returned by _make_filename() when SharedMemory(name=None)).
//     Therefore Go must NOT prepend the POSIX "/" — the bare name shared with
//     Python is the correct kernel-object name on Windows. NormaliseName is
//     a no-op on this platform.
//
// All other surface (Ring struct, Create / Attach / Close / Push / Pop /
// RespRead / RespWrite) matches shm.go byte-for-byte — caller Go code (transition
// SHM ring) imports gicg_mono/gicg_actor/shm and is unaware of the platform split.
// (历史 inference_shm_client.go 走过同 API,I29 R7.1 删。)
//
// Design: openspec/changes/i29-go-actor-pool/shminf_design.md §F.

//go:build windows

package shm

/*
#cgo CFLAGS: -O2 -D_WIN32_WINNT=0x0601
#cgo windows LDFLAGS: -lkernel32
#include "shm_ring.h"
#include <stdlib.h>
*/
import "C"
import (
	"errors"
	"fmt"
	"runtime"
	"time"
	"unsafe"
)

// RingTotalSize computes the total SHM block size for a ring with the given
// capacity and per-slot payload capacity. Identical formula to shm.go (the
// wire layout is platform-independent).
//
//	total = SHM_RING_HEADER_SIZE + capacity × (SHM_SLOT_HEADER_SIZE + slotPayload)
func RingTotalSize(capacity, slotPayload int) int {
	return C.SHM_RING_HEADER_SIZE + capacity*(C.SHM_SLOT_HEADER_SIZE+slotPayload)
}

// NormaliseName is a NO-OP on Windows. Unlike POSIX shm_open which requires a
// leading "/", Win32 CreateFileMapping accepts arbitrary names verbatim and
// Python's SharedMemory(name=...) on Windows passes the bare name through
// without modification (see CPython Modules/_multiprocessing/multiprocessing.c
// / Lib/multiprocessing/shared_memory.py — the "wnsm_" prefix is only used
// by _make_filename for auto-generated names, not user-supplied ones).
//
// Returning the input unchanged means callers on Mac/Linux can keep using
// NormaliseName uniformly without per-platform branches; the helper just
// does nothing here.
func NormaliseName(name string) string {
	return name
}

// Ring is a handle to a mmap'd SHM ring buffer (Windows: MapViewOfFile).
// Zero value is invalid; use Create or Attach.
type Ring struct {
	h        C.ShmHandle
	name     string
	owner    bool // owner Close also calls shm_unlink_name (NO-OP on Windows)
	capacity int
	slotSize int
}

// Create creates a new SHM section + maps it. Caller is the owner and must
// call Close() to unmap (Win kernel object is reference-counted by HANDLE — it
// disappears automatically when the last handle closes).
//
// name: bare Win32 named-section name (no leading "/"). Must match the name
// Python's SharedMemory(name=name, create=True, ...) is using on the other
// side.
// capacity: number of slots.
// slotPayload: per-slot payload capacity in bytes.
func Create(name string, capacity, slotPayload int) (*Ring, error) {
	if capacity <= 0 {
		return nil, errors.New("shm.Create: capacity must be > 0")
	}
	if slotPayload <= 0 {
		return nil, errors.New("shm.Create: slotPayload must be > 0")
	}
	name = NormaliseName(name)
	total := int64(RingTotalSize(capacity, slotPayload))
	cName := C.CString(name)
	defer C.free(unsafe.Pointer(cName))

	var cerrno C.int
	h := C.shm_create(cName, C.int64_t(total), &cerrno)
	if h.ptr == nil {
		return nil, fmt.Errorf("shm_create(%q, %d): GetLastError=%d", name, total, int(cerrno))
	}

	hdr := (*C.ShmRingHeader)(h.ptr)
	hdr.capacity = C.int32_t(capacity)
	hdr.slot_size = C.int32_t(C.SHM_SLOT_HEADER_SIZE + C.int(slotPayload))

	r := &Ring{
		h:        h,
		name:     name,
		owner:    true,
		capacity: capacity,
		slotSize: C.SHM_SLOT_HEADER_SIZE + slotPayload,
	}
	runtime.SetFinalizer(r, (*Ring).finalize)
	return r, nil
}

// Attach attaches to an existing SHM section created by another process
// (typically Python's SharedMemory(name=..., create=True) on the master side).
// The caller is not the owner; Close() unmaps but the section persists until
// the last open handle closes.
//
// total must match the size used by the creator (use RingTotalSize).
func Attach(name string, total int) (*Ring, error) {
	if total <= 0 {
		return nil, errors.New("shm.Attach: total must be > 0")
	}
	name = NormaliseName(name)
	cName := C.CString(name)
	defer C.free(unsafe.Pointer(cName))

	var cerrno C.int
	h := C.shm_attach(cName, C.int64_t(total), &cerrno)
	if h.ptr == nil {
		return nil, fmt.Errorf("shm_attach(%q, %d): GetLastError=%d", name, total, int(cerrno))
	}

	hdr := (*C.ShmRingHeader)(h.ptr)
	capv := int(hdr.capacity)
	slotSz := int(hdr.slot_size)
	if capv <= 0 || slotSz <= 0 {
		C.shm_detach(h)
		return nil, fmt.Errorf("shm_attach(%q): invalid ring header (capacity=%d slot_size=%d)",
			name, capv, slotSz)
	}

	r := &Ring{
		h:        h,
		name:     name,
		owner:    false,
		capacity: capv,
		slotSize: slotSz,
	}
	runtime.SetFinalizer(r, (*Ring).finalize)
	return r, nil
}

// Close unmaps the view and closes the underlying HANDLE. Owner status has no
// extra effect on Windows (no shm_unlink semantic — kernel object is GC'd by
// handle count). Idempotent.
func (r *Ring) Close() error {
	if r.h.ptr == nil {
		return nil
	}
	C.shm_detach(r.h)
	if r.owner {
		// NO-OP on Windows but keep symmetry with Mac/Linux so callers see
		// the same lifecycle shape (owner Close == "I'm done; release my
		// claim on the kernel object").
		cName := C.CString(r.name)
		C.shm_unlink_name(cName)
		C.free(unsafe.Pointer(cName))
	}
	r.h.ptr = nil
	runtime.SetFinalizer(r, nil)
	return nil
}

func (r *Ring) finalize() {
	_ = r.Close()
}

// Capacity returns the number of slots in the ring.
func (r *Ring) Capacity() int { return r.capacity }

// SlotPayloadMax returns the maximum payload bytes per slot.
func (r *Ring) SlotPayloadMax() int { return r.slotSize - C.SHM_SLOT_HEADER_SIZE }

// ─── Multi-producer req_ring ops ──────────────────────────────────────────

// Push pushes payload into the ring (multi-producer CAS). Returns an error if
// the ring is full or payload exceeds slot capacity.
func (r *Ring) Push(clientID, reqID uint32, payload []byte) error {
	if r.h.ptr == nil {
		return errors.New("shm.Ring.Push: ring is closed")
	}
	if len(payload) > r.SlotPayloadMax() {
		return fmt.Errorf("shm.Ring.Push: payload %d > slot max %d", len(payload), r.SlotPayloadMax())
	}
	var payPtr unsafe.Pointer
	if len(payload) > 0 {
		payPtr = unsafe.Pointer(&payload[0])
	}
	ok := C.shm_ring_push(r.h,
		C.uint32_t(clientID), C.uint32_t(reqID),
		payPtr, C.uint32_t(len(payload)))
	if ok == 0 {
		return errors.New("shm.Ring.Push: ring full")
	}
	return nil
}

// Pop pops the head slot (single-consumer).
func (r *Ring) Pop(outBuf []byte) (clientID, reqID uint32, n int, ok bool) {
	if r.h.ptr == nil {
		return 0, 0, 0, false
	}
	var cid, rid, plen C.uint32_t
	var payPtr unsafe.Pointer
	var bufCap C.uint32_t
	if len(outBuf) > 0 {
		payPtr = unsafe.Pointer(&outBuf[0])
		bufCap = C.uint32_t(len(outBuf))
	}
	rc := C.shm_ring_pop(r.h, &cid, &rid, payPtr, &plen, bufCap)
	if rc == 0 {
		return 0, 0, 0, false
	}
	return uint32(cid), uint32(rid), int(plen), true
}

// TryPop is a convenience wrapper: allocates an outBuf of SlotPayloadMax and
// calls Pop.
func (r *Ring) TryPop() (clientID, reqID uint32, payload []byte, ok bool) {
	buf := make([]byte, r.SlotPayloadMax())
	cid, rid, n, got := r.Pop(buf)
	if !got {
		return 0, 0, nil, false
	}
	return cid, rid, buf[:n], true
}

// ─── Single-slot resp_ring ops ─────────────────────────────────────────────

// RespWrite writes a response to a single-slot resp ring. timeout=0 spins forever.
func (r *Ring) RespWrite(reqID uint32, payload []byte, timeout time.Duration) error {
	if r.h.ptr == nil {
		return errors.New("shm.Ring.RespWrite: ring is closed")
	}
	if len(payload) > r.SlotPayloadMax() {
		return fmt.Errorf("shm.Ring.RespWrite: payload %d > slot max %d", len(payload), r.SlotPayloadMax())
	}
	var payPtr unsafe.Pointer
	if len(payload) > 0 {
		payPtr = unsafe.Pointer(&payload[0])
	}
	timeoutMs := C.int(0)
	if timeout > 0 {
		timeoutMs = C.int(timeout.Milliseconds())
	}
	rc := C.shm_resp_write(r.h, C.uint32_t(reqID), payPtr, C.uint32_t(len(payload)), timeoutMs)
	if rc == 0 {
		return errors.New("shm.Ring.RespWrite: timeout waiting for slot EMPTY")
	}
	return nil
}

// RespRead reads a response from a single-slot resp ring. timeout=0 spins forever.
func (r *Ring) RespRead(outBuf []byte, timeout time.Duration) (reqID uint32, n int, err error) {
	if r.h.ptr == nil {
		return 0, 0, errors.New("shm.Ring.RespRead: ring is closed")
	}
	var rid, plen C.uint32_t
	var payPtr unsafe.Pointer
	var bufCap C.uint32_t
	if len(outBuf) > 0 {
		payPtr = unsafe.Pointer(&outBuf[0])
		bufCap = C.uint32_t(len(outBuf))
	}
	timeoutMs := C.int(0)
	if timeout > 0 {
		timeoutMs = C.int(timeout.Milliseconds())
	}
	rc := C.shm_resp_read(r.h, &rid, payPtr, &plen, bufCap, timeoutMs)
	if rc == 0 {
		return 0, 0, errors.New("shm.Ring.RespRead: timeout waiting for slot FULL")
	}
	return uint32(rid), int(plen), nil
}
