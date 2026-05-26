// Package shm — cgo binding for the cross-language SHM ring buffer.
//
// This file is the POSIX (Mac + Linux) backend. The Windows backend lives in
// shm_windows.go; both expose the identical Go API surface (Ring, Create,
// Attach, Push, Pop, RespRead, RespWrite, …) so callers (transition SHM ring etc.)
// are platform-agnostic. (历史 inference_shm_client.go 走过同 API,I29 R7.1 删。)
//
// Design: openspec/changes/i29-go-actor-pool/shminf_design.md §F
//
// Naming convention (POSIX):
//   - Python's multiprocessing.shared_memory names its blocks "psm_<random>"
//     and uses that bare name (no leading "/"). shm_open(2) requires a leading
//     "/" on Mac/Linux. Callers must pass the shm_open-compatible name (with
//     the leading "/"). Use NormaliseName() to prepend "/" if absent.
//   - For resp rings created purely by Go and attached by Python via the Go-
//     provided name, the caller can choose any convention. We use "/gicg_resp_N".
//   - On Windows the leading "/" is a no-op (see shm_windows.go).

//go:build !windows

package shm

/*
#cgo linux LDFLAGS: -lrt
#include "shm_ring.h"
#include <stdlib.h>
#include <errno.h>
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
// capacity and per-slot payload capacity.
//
//	total = SHM_RING_HEADER_SIZE + capacity × (SHM_SLOT_HEADER_SIZE + slotPayload)
func RingTotalSize(capacity, slotPayload int) int {
	return C.SHM_RING_HEADER_SIZE + capacity*(C.SHM_SLOT_HEADER_SIZE+slotPayload)
}

// NormaliseName ensures the name has a leading "/" as required by shm_open(2).
// Python SharedMemory prints names like "psm_abcd" without the slash.
func NormaliseName(name string) string {
	if len(name) == 0 || name[0] != '/' {
		return "/" + name
	}
	return name
}

// Ring is a handle to a mmap'd SHM ring buffer.
// Zero value is invalid; use Create or Attach.
type Ring struct {
	h        C.ShmHandle
	name     string // normalised POSIX name (with leading "/")
	owner    bool   // if true, Close() will also call shm_unlink_name
	capacity int
	slotSize int // total slot size = SHM_SLOT_HEADER_SIZE + payload area
}

// Create creates and mmap's a new SHM ring. The caller is the owner and must
// call Close() to munmap + unlink the block.
//
// name: shm_open-compatible name (leading "/" required; use NormaliseName).
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
		return nil, fmt.Errorf("shm_create(%q, %d): errno=%d", name, total, int(cerrno))
	}

	// Initialise ring header fields that are not zeroed by shm_create's memset
	// (capacity and slot_size must be set so push/pop work correctly).
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

// Attach attaches to an existing SHM ring created by another process.
// The caller is not the owner; Close() munmaps but does NOT unlink.
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
		return nil, fmt.Errorf("shm_attach(%q, %d): errno=%d", name, total, int(cerrno))
	}

	hdr := (*C.ShmRingHeader)(h.ptr)
	cap := int(hdr.capacity)
	slotSz := int(hdr.slot_size)
	if cap <= 0 || slotSz <= 0 {
		C.shm_detach(h)
		return nil, fmt.Errorf("shm_attach(%q): invalid ring header (capacity=%d slot_size=%d)",
			name, cap, slotSz)
	}

	r := &Ring{
		h:        h,
		name:     name,
		owner:    false,
		capacity: cap,
		slotSize: slotSz,
	}
	runtime.SetFinalizer(r, (*Ring).finalize)
	return r, nil
}

// Close detaches (munmaps) the ring. If the Ring was created with Create,
// also unlinks the shm object. Idempotent.
func (r *Ring) Close() error {
	if r.h.ptr == nil {
		return nil
	}
	C.shm_detach(r.h)
	if r.owner {
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
//
// The clientID and reqID are written into the slot header for routing.
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

// Pop pops the head slot (single-consumer). Returns (clientID, reqID, payload, true)
// on success, or (0, 0, nil, false) if the ring is empty or the head slot is not
// yet fully written.
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
// calls Pop. Returns (clientID, reqID, payload, true) or (0, 0, nil, false).
func (r *Ring) TryPop() (clientID, reqID uint32, payload []byte, ok bool) {
	buf := make([]byte, r.SlotPayloadMax())
	cid, rid, n, got := r.Pop(buf)
	if !got {
		return 0, 0, nil, false
	}
	return cid, rid, buf[:n], true
}

// ─── Single-slot resp_ring ops ─────────────────────────────────────────────

// RespWrite writes a response to a single-slot resp ring. Spins until the slot
// is EMPTY (previous response consumed by actor), then writes payload and marks
// FULL. timeout=0 means spin forever.
//
// Use for Python InfServer → Go actor response routing.
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

// RespRead reads a response from a single-slot resp ring. Spins until the slot
// is FULL, then reads and marks EMPTY. timeout=0 means spin forever.
//
// Use for Go actor waiting for Python InfServer response.
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
