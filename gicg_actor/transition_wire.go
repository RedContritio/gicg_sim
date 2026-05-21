// transition_wire.go — transition push 协议 encode/decode。
//
// Goes over second localhost socket (Go actor → Python trainer collector),独立于 D5
// inference socket。 Design D7 修正(commit 44e4cf3 起):原默认 "reuse SHMRing 协议"
// 不可行(Python SHMRing 用 mp.Lock/mp.Value 跨语言不可靠),改 socket。 defer 真 SHM
// 优化到 perf 数据驱动。
//
// **Declarative schema** — fixed header 走 binary-encoded TransitionHeader struct,
// binary.Read/Write 处理 offset。 加字段在 struct 加一行即可,encode/decode 自动 follow,
// 无需手动维护 byte 偏移量。 同样 Python 端 transition_sink_wire.py 用 struct format
// string + calcsize 实现等价 declarative 模式。
//
// Wire format(paradigm-agnostic envelope + opaque paradigm-specific payload):
//
//	header  = binary-encoded TransitionHeader{Ver, ClientID, EpisodeID, Step,
//	                                            Done, Reserved, NPayload}
//	payload = header || payload_bytes  (paradigm-specific opaque blob)
//	outer   = [u32 len_le] || payload
//
// Paradigm 自己 encode 内层 payload(DMC: obs_dict + action_ref + reward + value 等;
// AZ: tree_visits + value;PPO: log_prob + advantage 等)。 主体只透传 raw bytes,Python
// 端 collector 调 paradigm-specific decoder 还原 Transition object。
//
// Done bit:1 表示 episode 末 transition(Python 端据此 finalize episode)。 reserved
// 留作未来扩展 flag(prio replay weight 等)。

package gicg_actor

import (
	"bytes"
	"encoding/binary"
	"fmt"
)

// TransitionHeader 是 wire 上的固定头(envelope,不含 paradigm payload)。 binary.Read/Write
// 处理 offset。 加字段在此 struct 加一行,encode/decode 自动 follow。
// 注意 Go struct field order = wire byte order,改顺序破坏协议。
type TransitionHeader struct {
	Ver       uint16
	ClientID  uint32
	EpisodeID uint32
	Step      uint32
	Done      uint8 // 0 / 1
	Reserved  uint8 // 未来扩展 flag (prio weight 等)
	NPayload  uint32
}

// TransitionHeaderSize 派生自 struct(no manual byte counting)。
var TransitionHeaderSize = binary.Size(TransitionHeader{})

// Transition 是单 transition 的 wire 表示。 Payload 是 paradigm 内部 schema 的 opaque
// bytes(主体不知 layout)。
type Transition struct {
	ClientID  uint32
	EpisodeID uint32
	Step      uint32
	Done      bool
	Payload   []byte
}

// EncodeTransition 序列化(含 outer length prefix)。 走 binary.Write 写 fixed header
// (no byte counting)+ append raw payload。
func EncodeTransition(t *Transition) ([]byte, error) {
	if uint64(len(t.Payload)) > uint64(MaxMessageBytes) {
		return nil, fmt.Errorf("encode transition: payload %d byte > %d cap",
			len(t.Payload), MaxMessageBytes)
	}
	header := TransitionHeader{
		Ver:       WireVersion,
		ClientID:  t.ClientID,
		EpisodeID: t.EpisodeID,
		Step:      t.Step,
		Done:      boolToU8(t.Done),
		Reserved:  0,
		NPayload:  uint32(len(t.Payload)),
	}
	var buf bytes.Buffer
	buf.Grow(4 + TransitionHeaderSize + len(t.Payload))
	_ = binary.Write(&buf, binary.LittleEndian, uint32(0)) // outer length placeholder
	if err := binary.Write(&buf, binary.LittleEndian, &header); err != nil {
		return nil, fmt.Errorf("encode transition header: %w", err)
	}
	if len(t.Payload) > 0 {
		buf.Write(t.Payload)
	}
	out := buf.Bytes()
	binary.LittleEndian.PutUint32(out[0:4], uint32(len(out)-4))
	return out, nil
}

// DecodeTransition 反序列化(test 用 + Python 端协议模板)。
func DecodeTransition(payload []byte) (*Transition, error) {
	if len(payload) < TransitionHeaderSize {
		return nil, fmt.Errorf("transition payload %d < header %d", len(payload), TransitionHeaderSize)
	}
	var header TransitionHeader
	if err := binary.Read(bytes.NewReader(payload[:TransitionHeaderSize]), binary.LittleEndian, &header); err != nil {
		return nil, fmt.Errorf("decode transition header: %w", err)
	}
	if header.Ver != WireVersion {
		return nil, fmt.Errorf("transition wire version mismatch: got %d, want %d", header.Ver, WireVersion)
	}
	expected := TransitionHeaderSize + int(header.NPayload)
	if len(payload) != expected {
		return nil, fmt.Errorf("transition payload len %d != expected %d (n=%d)",
			len(payload), expected, header.NPayload)
	}
	t := &Transition{
		ClientID:  header.ClientID,
		EpisodeID: header.EpisodeID,
		Step:      header.Step,
		Done:      header.Done != 0,
	}
	if header.NPayload > 0 {
		t.Payload = make([]byte, header.NPayload)
		copy(t.Payload, payload[TransitionHeaderSize:])
	}
	return t, nil
}

func boolToU8(b bool) uint8 {
	if b {
		return 1
	}
	return 0
}
