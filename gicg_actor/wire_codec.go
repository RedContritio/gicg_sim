// wire_codec.go — raw bytes ↔ typed slice 互转 helper。
//
// 从 wire_format.go 拆出(单文件行数上限)。 writer 侧长度取自 slice 自身;reader
// 侧长度来自 header 声明的 NDyn/NRefs/NPay/NStatic,且 DecodeInferRequest 会先校验
// payload 总长,所以这里的 off/n 不做边界重检。
//
// unsafe.Slice 只用来做 zero-copy view,不持有指针,pinned 语义与直接取址相同。
package gicg_actor

import (
	"bytes"
	"unsafe"
)

func writeF32(buf *bytes.Buffer, xs []float32) {
	if len(xs) == 0 {
		return
	}
	buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&xs[0])), len(xs)*4))
}

func writeI64(buf *bytes.Buffer, xs []int64) {
	if len(xs) == 0 {
		return
	}
	buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&xs[0])), len(xs)*8))
}

func writeI32(buf *bytes.Buffer, xs []int32) {
	if len(xs) == 0 {
		return
	}
	buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&xs[0])), len(xs)*4))
}

func readF32(payload []byte, off, n int) ([]float32, int) {
	if n == 0 {
		return nil, off
	}
	out := make([]float32, n)
	copy(unsafe.Slice((*byte)(unsafe.Pointer(&out[0])), n*4), payload[off:off+n*4])
	return out, off + n*4
}

func readI64(payload []byte, off, n int) ([]int64, int) {
	if n == 0 {
		return nil, off
	}
	out := make([]int64, n)
	copy(unsafe.Slice((*byte)(unsafe.Pointer(&out[0])), n*8), payload[off:off+n*8])
	return out, off + n*8
}

func readI32(payload []byte, off, n int) ([]int32, int) {
	if n == 0 {
		return nil, off
	}
	out := make([]int32, n)
	copy(unsafe.Slice((*byte)(unsafe.Pointer(&out[0])), n*4), payload[off:off+n*4])
	return out, off + n*4
}

func f32Bytes(xs []float32) []byte {
	if len(xs) == 0 {
		return nil
	}
	out := make([]byte, len(xs)*4)
	copy(out, unsafe.Slice((*byte)(unsafe.Pointer(&xs[0])), len(xs)*4))
	return out
}
