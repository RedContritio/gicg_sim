// wire_format.go — raw bytes + length prefix IPC 协议 encode/decode。
//
// 跟 Python InfServer socket listener 对接(P1.3 ship)。 协议设计依据
// openspec/changes/i29-go-actor-pool/design.md D5(IPC research 验证 <1μs RTT)。
//
// 设计原则:
//   - 全 little-endian(Win x86 + Linux x64 + Mac arm64 都默认 LE,跨平台一致)
//   - 长度前缀用 uint32(4 byte)— 单 message 上限 16 MB 实际 hard cap
//   - numpy ndarray 用 contiguous raw bytes 写,Python np.frombuffer view zero-copy
//   - schema 版本号 2 byte(头位),Python/Go 都校验,mismatch fail loud
//
// **Declarative schema**:fixed header 走单一 binary-encoded struct(InferRequestHeader /
// InferResponseHeader),encoding/binary.Read+Write 处理 offset。 加字段在 struct 加一行即可,
// encode/decode 自动 follow,无需手动维护 byte 偏移量。 变长 array 部分按 _ArraySpecs 列表
// 顺序 emit/parse,加 array 同样改 1 行。 Python 端 inference_server_socket_wire.py 用
// struct format string + calcsize 实现等价 declarative 模式。
//
// Wire format(inference request,v2):
//
//	header = binary-encoded InferRequestHeader{Ver, StaticHash, ClientID, ReqID,
//	                                            NDyn, NRefs, NPay, NStatic}
//	payload = header || dyn_obs (f32 ×N) || refs (i64 ×N) || pay (f32 ×N) || static (i32 ×N)
//	outer   = [u32 len_le] || payload
//
// NStatic = 0 表示 "本 request 不带 static_obs"(server 走 hash cache);> 0 时
// 携带 raw int32 数组,server 端 cache by hash + decode 后保留 decoded result。
// v2 vs v1 改:加 NStatic + tail static blob。 v1 不保留兼容。
//
// Wire format(inference response):
//
//	header = InferResponseHeader{Status, N}
//	body   = logits (n × 4) when status=OK | err_msg bytes when status=Err

package gicg_actor

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"unsafe"
)

// ─── Schema 常量 ─────────────────────────────────────────────────────────
const (
	WireVersion     uint16 = 2
	StaticHashSize  int    = 16
	MaxMessageBytes uint32 = 16 * 1024 * 1024
	InferStatusOK   uint8  = 0
	InferStatusErr  uint8  = 1
)

// InferRequestHeader 是 wire 上的固定头(无 array body)。 binary.Read/Write
// 处理 offset — 加字段在此 struct 加一行,encode/decode 自动 follow。
// 注意 Go struct field order = wire byte order,改顺序破坏协议。
type InferRequestHeader struct {
	Ver        uint16
	StaticHash [16]byte
	ClientID   uint32
	ReqID      uint32
	NDyn       uint16
	NRefs      uint16
	NPay       uint16
	NStatic    uint16
}

// HeaderSize is derived from the struct layout (no manual byte counting)。
var HeaderSize = binary.Size(InferRequestHeader{})

// InferResponseHeader 同样固定头。 加字段在此加一行。
type InferResponseHeader struct {
	Status uint8
	N      uint16
}

// ResponseHeaderSize 派生自 struct,no hardcoded byte count。
var ResponseHeaderSize = binary.Size(InferResponseHeader{})

// InferRequest 是单个 inference 请求 — actor goroutine 产出,通过 socket 发到 Python InfServer。
type InferRequest struct {
	StaticHash [StaticHashSize]byte
	ClientID   uint32
	ReqID      uint32
	DynObs     []float32 // dynamic obs (paradigm-specific layout)
	Refs       []int64   // padded action refs
	Pay        []float32 // padded action payments
	// Static 可空 — len 0 表示 "本 request 不带,InfServer 走 cache by StaticHash"。
	Static []int32
}

// InferResponse 是 server 端返的 logits / 错误信息。
type InferResponse struct {
	Status uint8
	Logits []float32
	ErrMsg string
}

// EncodeInferRequest 把 InferRequest 序列化成 raw bytes(含 outer length prefix)。
// 走 binary.Write 写 fixed header(无 byte counting)+ raw bytes append 写 array bodies。
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
	if len(req.Static) > 0xFFFF {
		return nil, fmt.Errorf("encode: static len %d > u16 max", len(req.Static))
	}
	header := InferRequestHeader{
		Ver:        WireVersion,
		StaticHash: req.StaticHash,
		ClientID:   req.ClientID,
		ReqID:      req.ReqID,
		NDyn:       uint16(len(req.DynObs)),
		NRefs:      uint16(len(req.Refs)),
		NPay:       uint16(len(req.Pay)),
		NStatic:    uint16(len(req.Static)),
	}

	var buf bytes.Buffer
	// 4-byte outer length placeholder(回填)
	buf.Grow(4 + HeaderSize)
	_ = binary.Write(&buf, binary.LittleEndian, uint32(0))
	if err := binary.Write(&buf, binary.LittleEndian, &header); err != nil {
		return nil, fmt.Errorf("encode header: %w", err)
	}
	// 变长 array bodies — 顺序固定(改顺序破坏协议)
	writeF32(&buf, req.DynObs)
	writeI64(&buf, req.Refs)
	writeF32(&buf, req.Pay)
	writeI32(&buf, req.Static)

	out := buf.Bytes()
	// 回填 outer length = total - 4(prefix 自身不算 in payload len)
	binary.LittleEndian.PutUint32(out[0:4], uint32(len(out)-4))
	return out, nil
}

// DecodeInferRequest 反序列化(test 用 + Python 端口模板)。
func DecodeInferRequest(payload []byte) (*InferRequest, error) {
	if len(payload) < HeaderSize {
		return nil, fmt.Errorf("payload %d byte < header %d", len(payload), HeaderSize)
	}
	var header InferRequestHeader
	if err := binary.Read(bytes.NewReader(payload[:HeaderSize]), binary.LittleEndian, &header); err != nil {
		return nil, fmt.Errorf("decode header: %w", err)
	}
	if header.Ver != WireVersion {
		return nil, fmt.Errorf("wire version mismatch: got %d, want %d", header.Ver, WireVersion)
	}
	expected := HeaderSize +
		int(header.NDyn)*4 +
		int(header.NRefs)*8 +
		int(header.NPay)*4 +
		int(header.NStatic)*4
	if len(payload) != expected {
		return nil, fmt.Errorf("payload len %d != expected %d (n_dyn=%d n_refs=%d n_pay=%d n_static=%d)",
			len(payload), expected, header.NDyn, header.NRefs, header.NPay, header.NStatic)
	}
	off := HeaderSize
	req := &InferRequest{
		StaticHash: header.StaticHash,
		ClientID:   header.ClientID,
		ReqID:      header.ReqID,
	}
	req.DynObs, off = readF32(payload, off, int(header.NDyn))
	req.Refs, off = readI64(payload, off, int(header.NRefs))
	req.Pay, off = readF32(payload, off, int(header.NPay))
	req.Static, _ = readI32(payload, off, int(header.NStatic))
	return req, nil
}

// EncodeInferResponse / DecodeInferResponse — server 不在 Go 端,但测试 round-trip 需要本
// 端能 encode/decode 模拟 server 端行为。
func EncodeInferResponse(resp *InferResponse) ([]byte, error) {
	var header InferResponseHeader
	var body []byte
	switch resp.Status {
	case InferStatusOK:
		if len(resp.Logits) > 0xFFFF {
			return nil, fmt.Errorf("encode: logits len %d > u16 max", len(resp.Logits))
		}
		header = InferResponseHeader{Status: InferStatusOK, N: uint16(len(resp.Logits))}
		body = f32Bytes(resp.Logits)
	case InferStatusErr:
		errBytes := []byte(resp.ErrMsg)
		if len(errBytes) > 0xFFFF {
			return nil, fmt.Errorf("encode: err_msg len %d > u16 max", len(errBytes))
		}
		header = InferResponseHeader{Status: InferStatusErr, N: uint16(len(errBytes))}
		body = errBytes
	default:
		return nil, fmt.Errorf("encode: unknown status %d", resp.Status)
	}

	var buf bytes.Buffer
	buf.Grow(4 + ResponseHeaderSize + len(body))
	_ = binary.Write(&buf, binary.LittleEndian, uint32(0))
	_ = binary.Write(&buf, binary.LittleEndian, &header)
	buf.Write(body)
	out := buf.Bytes()
	binary.LittleEndian.PutUint32(out[0:4], uint32(len(out)-4))
	return out, nil
}

func DecodeInferResponse(payload []byte) (*InferResponse, error) {
	if len(payload) < ResponseHeaderSize {
		return nil, fmt.Errorf("response payload %d byte < header %d", len(payload), ResponseHeaderSize)
	}
	var header InferResponseHeader
	if err := binary.Read(bytes.NewReader(payload[:ResponseHeaderSize]), binary.LittleEndian, &header); err != nil {
		return nil, fmt.Errorf("decode response header: %w", err)
	}
	resp := &InferResponse{Status: header.Status}
	switch header.Status {
	case InferStatusOK:
		expected := ResponseHeaderSize + int(header.N)*4
		if len(payload) != expected {
			return nil, fmt.Errorf("ok response len %d != expected %d (n_logits=%d)", len(payload), expected, header.N)
		}
		resp.Logits, _ = readF32(payload, ResponseHeaderSize, int(header.N))
	case InferStatusErr:
		expected := ResponseHeaderSize + int(header.N)
		if len(payload) != expected {
			return nil, fmt.Errorf("err response len %d != expected %d (n_msg=%d)", len(payload), expected, header.N)
		}
		resp.ErrMsg = string(payload[ResponseHeaderSize : ResponseHeaderSize+int(header.N)])
	default:
		return nil, fmt.Errorf("unknown response status %d", header.Status)
	}
	return resp, nil
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

// ─── 内部 byte 拼装 helper — 单 source 处理 raw bytes ↔ typed slice 互转 ───

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
