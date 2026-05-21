// wire_format.go — raw bytes + length prefix IPC 协议 encode/decode。
//
// 跟 Python InfServer socket listener 对接(P1.3 ship)。 协议设计依据
// openspec/changes/i29-go-actor-pool/design.md D5(IPC research 验证 <1μs RTT,唯一
// 5μs 预算下 viable;protobuf/Cap'n/Arrow/FB/msgpack 各有阻碍)。
//
// 设计原则:
//   - 全 little-endian(Win x86 + Linux x64 + Mac arm64 都默认 LE,跨平台一致)
//   - 长度前缀用 uint32(4 byte)— 单 message 上限 4 GB,实际 payload ~4 KB
//   - numpy ndarray 用 contiguous raw bytes 写,Python np.frombuffer view zero-copy
//   - schema 版本号 2 byte(头位),Python/Go 都校验,mismatch fail loud
//
// Wire format(inference request):
//
//	[u16 ver][16 byte static_hash][u32 client_id][u32 req_id]
//	[u16 n_dyn_f32][u16 n_refs_i64][u16 n_pay_f32]
//	| dyn_obs (n_dyn_f32 × 4 bytes) | refs (n_refs_i64 × 8 bytes) | pay (n_pay_f32 × 4 bytes)
//
// Wire format(inference response):
//
//	[u8 status (0=ok, 1=err)][u16 n_logits_f32]
//	| logits (n_logits_f32 × 4 bytes)  // status=0 case
//	| err_msg (variable bytes, no null terminator) // status=1 case
//
// Outer frame:每条 message 用 [u32 len_le][payload bytes],reader 先读 4 byte len 再
// 读 len byte payload。 防 TCP coalescing 切分。

package gicg_actor

import (
	"encoding/binary"
	"fmt"
	"io"
	"unsafe"
)

const (
	WireVersion        uint16 = 1
	StaticHashSize     int    = 16
	MaxMessageBytes    uint32 = 16 * 1024 * 1024 // 16 MB hard cap — defense against malformed length
	InferStatusOK      uint8  = 0
	InferStatusErr     uint8  = 1
	HeaderSize         int    = 2 + 16 + 4 + 4 + 2 + 2 + 2 // = 32 byte fixed header
	ResponseHeaderSize int    = 1 + 2                      // = 3 byte fixed
)

// InferRequest 是单个 inference 请求 — actor goroutine 产出,通过 socket 发到 Python InfServer。
//
// DynObs / Refs / Pay 是 paradigm-specific numpy schema 的 raw bytes;主体不知 schema 内容,
// 透传给 InfServer 端 decoder。
type InferRequest struct {
	StaticHash [StaticHashSize]byte // 16-byte blake2b digest of static obs
	ClientID   uint32               // actor goroutine id
	ReqID      uint32               // monotone per-client request id
	DynObs     []float32            // dynamic observation (paradigm-specific layout)
	Refs       []int64              // padded action refs (paradigm-specific)
	Pay        []float32            // padded action payments (paradigm-specific)
}

// InferResponse 是 server 端返的 logits(或错误信息)。
type InferResponse struct {
	Status uint8 // 0 = ok, 1 = err
	Logits []float32
	ErrMsg string // status=1 时填,status=0 时空
}

// EncodeInferRequest 把 InferRequest 序列化成 raw bytes(含 outer length prefix)。
//
// 返 [u32 len_le][payload bytes]:reader 先读 4 byte len 决定 recv_into buf size,然后读
// len byte payload。 防 TCP 切分。
//
// 不分配中间 slice — 直接 binary.LittleEndian.Put* 到目标 buf,numpy contiguous slice 用
// unsafe.Slice cast 直接 memcpy(zero-copy concept)。
func EncodeInferRequest(req *InferRequest) ([]byte, error) {
	if len(req.DynObs) > 0xFFFF {
		return nil, fmt.Errorf("encode: dyn_obs len %d > u16 max", len(req.DynObs))
	}
	if len(req.Refs) > 0xFFFF {
		return nil, fmt.Errorf("encode: refs len %d > u16 max", len(req.Refs))
	}
	if len(req.Pay) > 0xFFFF {
		return nil, fmt.Errorf("encode: pay len %d > u16 max", len(req.Pay))
	}
	dynBytes := len(req.DynObs) * 4
	refsBytes := len(req.Refs) * 8
	payBytes := len(req.Pay) * 4
	payloadLen := HeaderSize + dynBytes + refsBytes + payBytes
	out := make([]byte, 4+payloadLen)
	binary.LittleEndian.PutUint32(out[0:4], uint32(payloadLen))
	// Header 32 byte fixed
	off := 4
	binary.LittleEndian.PutUint16(out[off:off+2], WireVersion)
	off += 2
	copy(out[off:off+16], req.StaticHash[:])
	off += 16
	binary.LittleEndian.PutUint32(out[off:off+4], req.ClientID)
	off += 4
	binary.LittleEndian.PutUint32(out[off:off+4], req.ReqID)
	off += 4
	binary.LittleEndian.PutUint16(out[off:off+2], uint16(len(req.DynObs)))
	off += 2
	binary.LittleEndian.PutUint16(out[off:off+2], uint16(len(req.Refs)))
	off += 2
	binary.LittleEndian.PutUint16(out[off:off+2], uint16(len(req.Pay)))
	off += 2
	// numpy contiguous bytes — unsafe.Slice 转 byte view (zero-copy concept)
	if dynBytes > 0 {
		copy(out[off:off+dynBytes], unsafe.Slice((*byte)(unsafe.Pointer(&req.DynObs[0])), dynBytes))
		off += dynBytes
	}
	if refsBytes > 0 {
		copy(out[off:off+refsBytes], unsafe.Slice((*byte)(unsafe.Pointer(&req.Refs[0])), refsBytes))
		off += refsBytes
	}
	if payBytes > 0 {
		copy(out[off:off+payBytes], unsafe.Slice((*byte)(unsafe.Pointer(&req.Pay[0])), payBytes))
		off += payBytes
	}
	return out, nil
}

// ReadLengthPrefixed 读 [u32 len_le][payload bytes] 一条 message。 用 io.ReadFull 防 TCP
// 切分。 len 超 MaxMessageBytes 直接 fail loud(防 malformed length DoS server)。
func ReadLengthPrefixed(r io.Reader) ([]byte, error) {
	var lenBuf [4]byte
	if _, err := io.ReadFull(r, lenBuf[:]); err != nil {
		return nil, fmt.Errorf("read length prefix: %w", err)
	}
	n := binary.LittleEndian.Uint32(lenBuf[:])
	if n > MaxMessageBytes {
		return nil, fmt.Errorf("message len %d exceeds cap %d", n, MaxMessageBytes)
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(r, buf); err != nil {
		return nil, fmt.Errorf("read payload %d byte: %w", n, err)
	}
	return buf, nil
}

// DecodeInferRequest 反序列化(test 用 + Python 端口模板)。 server side 实际跑 Python(详
// design D5),Go 这边只 producer。 测试需要 decoder 验 round-trip 正确性。
func DecodeInferRequest(payload []byte) (*InferRequest, error) {
	if len(payload) < HeaderSize {
		return nil, fmt.Errorf("payload %d byte < header %d", len(payload), HeaderSize)
	}
	off := 0
	ver := binary.LittleEndian.Uint16(payload[off : off+2])
	off += 2
	if ver != WireVersion {
		return nil, fmt.Errorf("wire version mismatch: got %d, want %d", ver, WireVersion)
	}
	req := &InferRequest{}
	copy(req.StaticHash[:], payload[off:off+16])
	off += 16
	req.ClientID = binary.LittleEndian.Uint32(payload[off : off+4])
	off += 4
	req.ReqID = binary.LittleEndian.Uint32(payload[off : off+4])
	off += 4
	nDyn := int(binary.LittleEndian.Uint16(payload[off : off+2]))
	off += 2
	nRefs := int(binary.LittleEndian.Uint16(payload[off : off+2]))
	off += 2
	nPay := int(binary.LittleEndian.Uint16(payload[off : off+2]))
	off += 2
	expectedLen := HeaderSize + nDyn*4 + nRefs*8 + nPay*4
	if len(payload) != expectedLen {
		return nil, fmt.Errorf("payload len %d != expected %d (n_dyn=%d n_refs=%d n_pay=%d)",
			len(payload), expectedLen, nDyn, nRefs, nPay)
	}
	if nDyn > 0 {
		req.DynObs = make([]float32, nDyn)
		copy(unsafe.Slice((*byte)(unsafe.Pointer(&req.DynObs[0])), nDyn*4), payload[off:off+nDyn*4])
		off += nDyn * 4
	}
	if nRefs > 0 {
		req.Refs = make([]int64, nRefs)
		copy(unsafe.Slice((*byte)(unsafe.Pointer(&req.Refs[0])), nRefs*8), payload[off:off+nRefs*8])
		off += nRefs * 8
	}
	if nPay > 0 {
		req.Pay = make([]float32, nPay)
		copy(unsafe.Slice((*byte)(unsafe.Pointer(&req.Pay[0])), nPay*4), payload[off:off+nPay*4])
	}
	return req, nil
}

// EncodeInferResponse / DecodeInferResponse — server 不在 Go 端,但测试 round-trip 需要本
// 端能 encode/decode 模拟 server 端行为。
func EncodeInferResponse(resp *InferResponse) ([]byte, error) {
	if resp.Status == InferStatusOK {
		if len(resp.Logits) > 0xFFFF {
			return nil, fmt.Errorf("encode: logits len %d > u16 max", len(resp.Logits))
		}
		logitsBytes := len(resp.Logits) * 4
		payloadLen := ResponseHeaderSize + logitsBytes
		out := make([]byte, 4+payloadLen)
		binary.LittleEndian.PutUint32(out[0:4], uint32(payloadLen))
		out[4] = InferStatusOK
		binary.LittleEndian.PutUint16(out[5:7], uint16(len(resp.Logits)))
		if logitsBytes > 0 {
			copy(out[7:7+logitsBytes], unsafe.Slice((*byte)(unsafe.Pointer(&resp.Logits[0])), logitsBytes))
		}
		return out, nil
	}
	// err 路径
	errBytes := []byte(resp.ErrMsg)
	payloadLen := ResponseHeaderSize + len(errBytes)
	out := make([]byte, 4+payloadLen)
	binary.LittleEndian.PutUint32(out[0:4], uint32(payloadLen))
	out[4] = InferStatusErr
	binary.LittleEndian.PutUint16(out[5:7], uint16(len(errBytes)))
	copy(out[7:7+len(errBytes)], errBytes)
	return out, nil
}

func DecodeInferResponse(payload []byte) (*InferResponse, error) {
	if len(payload) < ResponseHeaderSize {
		return nil, fmt.Errorf("response payload %d byte < header %d", len(payload), ResponseHeaderSize)
	}
	resp := &InferResponse{Status: payload[0]}
	n := int(binary.LittleEndian.Uint16(payload[1:3]))
	switch resp.Status {
	case InferStatusOK:
		expectedLen := ResponseHeaderSize + n*4
		if len(payload) != expectedLen {
			return nil, fmt.Errorf("ok response len %d != expected %d (n_logits=%d)",
				len(payload), expectedLen, n)
		}
		if n > 0 {
			resp.Logits = make([]float32, n)
			copy(unsafe.Slice((*byte)(unsafe.Pointer(&resp.Logits[0])), n*4), payload[3:3+n*4])
		}
	case InferStatusErr:
		expectedLen := ResponseHeaderSize + n
		if len(payload) != expectedLen {
			return nil, fmt.Errorf("err response len %d != expected %d (n_msg=%d)",
				len(payload), expectedLen, n)
		}
		resp.ErrMsg = string(payload[3 : 3+n])
	default:
		return nil, fmt.Errorf("unknown response status %d", resp.Status)
	}
	return resp, nil
}
