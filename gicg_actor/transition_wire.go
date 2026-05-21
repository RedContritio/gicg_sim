// transition_wire.go — transition push 协议 encode/decode。
//
// Goes over second localhost socket (Go actor → Python trainer collector),独立于 D5
// inference socket。 Design D7 修正(commit 44e4cf3 起):原默认 "reuse SHMRing 协议"
// 不可行(Python SHMRing 用 mp.Lock/mp.Value 跨语言不可靠),改 socket。 defer 真 SHM
// 优化到 perf 数据驱动。
//
// Wire format(paradigm-agnostic envelope + opaque paradigm-specific payload):
//
//	[u16 ver][u32 client_id][u32 episode_id][u32 step][u8 done][u8 _reserved]
//	[u32 n_payload_bytes] | payload_bytes (paradigm-specific opaque blob)
//
// Outer frame 同 inference: [u32 len_le][payload bytes]。
//
// Paradigm 自己 encode 内层 payload(DMC: obs_dict + action_ref + reward + value 等;
// AZ: tree_visits + value;PPO: log_prob + advantage 等)。 主体只透传 raw bytes,Python
// 端 collector 调 paradigm-specific decoder 还原 Transition object。
//
// Done bit:1 表示 episode 末 transition(Python 端据此 finalize episode)。 reserved
// 留作未来扩展 flag(prio replay weight 等)。

package gicg_actor

import (
	"encoding/binary"
	"fmt"
)

const (
	TransitionHeaderSize int = 2 + 4 + 4 + 4 + 1 + 1 + 4 // = 20 byte fixed
)

// Transition 是单 transition 的 wire 表示。 Payload 是 paradigm 内部 schema 的 opaque
// bytes(主体不知 layout)。
type Transition struct {
	ClientID  uint32
	EpisodeID uint32
	Step      uint32
	Done      bool
	Payload   []byte
}

// EncodeTransition 序列化(含 outer length prefix)。
func EncodeTransition(t *Transition) ([]byte, error) {
	if uint64(len(t.Payload)) > uint64(MaxMessageBytes) {
		return nil, fmt.Errorf("encode transition: payload %d byte > %d cap",
			len(t.Payload), MaxMessageBytes)
	}
	payloadLen := TransitionHeaderSize + len(t.Payload)
	out := make([]byte, 4+payloadLen)
	binary.LittleEndian.PutUint32(out[0:4], uint32(payloadLen))
	off := 4
	binary.LittleEndian.PutUint16(out[off:off+2], WireVersion)
	off += 2
	binary.LittleEndian.PutUint32(out[off:off+4], t.ClientID)
	off += 4
	binary.LittleEndian.PutUint32(out[off:off+4], t.EpisodeID)
	off += 4
	binary.LittleEndian.PutUint32(out[off:off+4], t.Step)
	off += 4
	if t.Done {
		out[off] = 1
	} else {
		out[off] = 0
	}
	off += 1
	out[off] = 0 // reserved
	off += 1
	binary.LittleEndian.PutUint32(out[off:off+4], uint32(len(t.Payload)))
	off += 4
	if len(t.Payload) > 0 {
		copy(out[off:off+len(t.Payload)], t.Payload)
	}
	return out, nil
}

// DecodeTransition 反序列化(test 用 + Python 端协议模板)。
func DecodeTransition(payload []byte) (*Transition, error) {
	if len(payload) < TransitionHeaderSize {
		return nil, fmt.Errorf("transition payload %d < header %d", len(payload), TransitionHeaderSize)
	}
	off := 0
	ver := binary.LittleEndian.Uint16(payload[off : off+2])
	off += 2
	if ver != WireVersion {
		return nil, fmt.Errorf("transition wire version mismatch: got %d, want %d", ver, WireVersion)
	}
	t := &Transition{}
	t.ClientID = binary.LittleEndian.Uint32(payload[off : off+4])
	off += 4
	t.EpisodeID = binary.LittleEndian.Uint32(payload[off : off+4])
	off += 4
	t.Step = binary.LittleEndian.Uint32(payload[off : off+4])
	off += 4
	t.Done = payload[off] != 0
	off += 1
	off += 1 // reserved
	n := int(binary.LittleEndian.Uint32(payload[off : off+4]))
	off += 4
	expectedLen := TransitionHeaderSize + n
	if len(payload) != expectedLen {
		return nil, fmt.Errorf("transition payload len %d != expected %d (n=%d)",
			len(payload), expectedLen, n)
	}
	if n > 0 {
		t.Payload = make([]byte, n)
		copy(t.Payload, payload[off:off+n])
	}
	return t, nil
}
