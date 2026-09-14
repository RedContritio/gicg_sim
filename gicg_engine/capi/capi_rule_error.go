package main

/*
#include <stdlib.h>
*/
import "C"

import (
	engine "gicg_mono/gicg_engine"
	"unsafe"
)

// Only expected DSL execution failures are caught. Programming panics still
// propagate; converting arbitrary panics into success would hide engine bugs.
func recoverRuleError(id C.int) {
	if v := recover(); v != nil {
		recordRuleError(id, v)
	}
}

func recoverRuleErrorInt(id C.int, result *C.int) {
	if v := recover(); v != nil {
		recordRuleError(id, v)
		*result = -1
	}
}

func recordRuleError(id C.int, v any) {
	failure, ok := v.(*engine.RuleError)
	if !ok {
		panic(v)
	}
	if h := getHandle(int(id)); h != nil {
		h.Game.Failure = failure
	}
}

// GameGetRuleError returns required message bytes, excluding NUL. With a buffer
// it writes a NUL-terminated, possibly shortened diagnostic. Zero means healthy.
//
//export GameGetRuleError
func GameGetRuleError(id C.int, out *C.char, capacity C.int) C.int {
	h := getHandle(int(id))
	if h == nil || h.Game.Failure == nil {
		return 0
	}
	message := h.Game.Failure.Error()
	if out != nil && capacity > 0 {
		buf := unsafe.Slice((*byte)(unsafe.Pointer(out)), int(capacity))
		n := copy(buf[:len(buf)-1], message)
		buf[n] = 0
	}
	return C.int(len(message))
}
