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
//	                                            Done, Kind, NPayload}
//	payload = header || payload_bytes  (paradigm-specific opaque blob)
//	outer   = [u32 len_le] || payload
//
// Paradigm 自己 encode 内层 payload(DMC: obs_dict + action_ref + reward + value 等;
// AZ: tree_visits + value;PPO: log_prob + advantage 等)。 主体只透传 raw bytes,Python
// 端 collector 调 paradigm-specific decoder 还原 Transition object。
//
// Done bit:1 表示 episode 末 transition(Python 端据此 finalize episode)。
//
// Kind byte 区分 frame 类型:
//   - KindPerTrans (0):原有 per-transition frame(per-step push 路径)
//   - KindEpisodeBatch (1):episode 整 batch frame(F1 优化路径)
//     Python 端 listener 据 kind dispatch decode 路径。 两种 frame 同 socket 可并存。
//
// EpisodeBatch frame wire format(Kind=1):
//
//	outer   = [u32 len_le] || batch_header || batch_body
//	batch_header = binary-encoded EpisodeBatchHeader{Ver, ClientID, EpisodeID, NTrans, Kind=1, Reserved}
//	batch_body   = for each trans: [u32 payload_len] || payload_bytes
//
// per-trans frame (Kind=0) 与原 TransitionHeader 完全兼容。

package gicg_actor

import (
	"bytes"
	"encoding/binary"
	"fmt"
)

// Kind byte 值 — 区分 per-transition frame 和 episode batch frame。
const (
	KindPerTrans     uint8 = 0 // 原 per-transition frame
	KindEpisodeBatch uint8 = 1 // F1 episode batch frame
)

// TransitionHeader 是 wire 上的固定头(envelope,不含 paradigm payload)。 binary.Read/Write
// 处理 offset。 加字段在此 struct 加一行,encode/decode 自动 follow。
// 注意 Go struct field order = wire byte order,改顺序破坏协议。
//
// Kind 字段在 Done 之前(offset 14),让 listener 可在 offset 14 统一 peek Kind。
// EpisodeBatchHeader 的 Kind 也在 offset 14,两种 frame 同 offset 可靠 dispatch。
// Done 移到 offset 15(原 Reserved 位)。 Kind=0=KindPerTrans,1=KindEpisodeBatch。
type TransitionHeader struct {
	Ver       uint16
	ClientID  uint32
	EpisodeID uint32
	Step      uint32
	Kind      uint8 // KindPerTrans=0 / KindEpisodeBatch=1 — at offset 14, matches EpisodeBatchHeader.Kind
	Done      uint8 // 0 / 1 — at offset 15
	NPayload  uint32
}

// EpisodeBatchHeader — episode batch frame 的固定头(outer length prefix 后紧跟)。
// 与 TransitionHeader 同 wire version,但 Kind=1。 binary.Read/Write 处理 offset。
// 注意 Go struct field order = wire byte order,改顺序破坏协议。
//
// NTrans 是本 batch 内含的 transition 数量(含 terminal marker)。
// 每个 trans 以 [u32 payload_len] || payload_bytes 格式跟在 EpisodeBatchHeader 后。
type EpisodeBatchHeader struct {
	Ver       uint16
	ClientID  uint32
	EpisodeID uint32
	NTrans    uint32 // transition count in batch
	Kind      uint8  // KindEpisodeBatch = 1
	Reserved  uint8
}

// TransitionHeaderSize 派生自 struct(no manual byte counting)。
var TransitionHeaderSize = binary.Size(TransitionHeader{})

// EpisodeBatchHeaderSize 派生自 struct(no manual byte counting)。
var EpisodeBatchHeaderSize = binary.Size(EpisodeBatchHeader{})

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
		Kind:      KindPerTrans,
		Done:      boolToU8(t.Done),
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

// EncodeEpisodeBatch 序列化整 episode 的 transition slice 为单一 wire frame(含 outer length prefix)。
//
// Format:
//
//	outer = [u32 len_le] || EpisodeBatchHeader || for each tx: [u32 payload_len] || payload
//
// 单次 conn.Write 推整 episode,Python 端 listener 看 Kind=1 dispatch decode_episode_batch。
// transitions slice 含 terminal marker(Done=true),Python 端 ingest_episode 统一处理。
// 失败:任一 payload 超 MaxMessageBytes 或 len(txs)==0。
func EncodeEpisodeBatch(clientID, episodeID uint32, txs []*Transition) ([]byte, error) {
	if len(txs) == 0 {
		return nil, fmt.Errorf("encode episode batch: empty transitions")
	}
	header := EpisodeBatchHeader{
		Ver:       WireVersion,
		ClientID:  clientID,
		EpisodeID: episodeID,
		NTrans:    uint32(len(txs)),
		Kind:      KindEpisodeBatch,
		Reserved:  0,
	}
	// 预计算 body 大小,一次性 Grow 防多次 alloc。
	bodySize := EpisodeBatchHeaderSize
	for _, tx := range txs {
		if uint64(len(tx.Payload)) > uint64(MaxMessageBytes) {
			return nil, fmt.Errorf("encode episode batch: tx payload %d byte > %d cap", len(tx.Payload), MaxMessageBytes)
		}
		bodySize += 4 + 1 + 1 + len(tx.Payload) // [u32 payload_len] + done byte + reserved byte + payload
	}

	var buf bytes.Buffer
	buf.Grow(4 + bodySize)
	// outer length placeholder(回填)
	_ = binary.Write(&buf, binary.LittleEndian, uint32(0))
	if err := binary.Write(&buf, binary.LittleEndian, &header); err != nil {
		return nil, fmt.Errorf("encode episode batch header: %w", err)
	}
	for _, tx := range txs {
		// per-trans: [u32 payload_len] || [u8 done] || [u8 reserved] || payload
		_ = binary.Write(&buf, binary.LittleEndian, uint32(len(tx.Payload)))
		_ = binary.Write(&buf, binary.LittleEndian, boolToU8(tx.Done))
		_ = binary.Write(&buf, binary.LittleEndian, uint8(0)) // reserved
		buf.Write(tx.Payload)
	}
	out := buf.Bytes()
	binary.LittleEndian.PutUint32(out[0:4], uint32(len(out)-4))
	return out, nil
}

// DecodeEpisodeBatch 反序列化 episode batch frame payload(不含 outer length prefix)。
// 返回解码出的 Transition slice,携带 ClientID/EpisodeID 但 Step 信息由 payload 内 DMC header 承载。
func DecodeEpisodeBatch(payload []byte) ([]*Transition, error) {
	if len(payload) < EpisodeBatchHeaderSize {
		return nil, fmt.Errorf("episode batch payload %d < header %d", len(payload), EpisodeBatchHeaderSize)
	}
	var header EpisodeBatchHeader
	if err := binary.Read(bytes.NewReader(payload[:EpisodeBatchHeaderSize]), binary.LittleEndian, &header); err != nil {
		return nil, fmt.Errorf("decode episode batch header: %w", err)
	}
	if header.Ver != WireVersion {
		return nil, fmt.Errorf("episode batch wire version mismatch: got %d, want %d", header.Ver, WireVersion)
	}
	if header.Kind != KindEpisodeBatch {
		return nil, fmt.Errorf("episode batch kind mismatch: got %d, want %d", header.Kind, KindEpisodeBatch)
	}
	off := EpisodeBatchHeaderSize
	txs := make([]*Transition, 0, header.NTrans)
	for i := uint32(0); i < header.NTrans; i++ {
		if off+6 > len(payload) { // 4(len) + 1(done) + 1(reserved)
			return nil, fmt.Errorf("episode batch truncated at trans %d", i)
		}
		payLen := int(binary.LittleEndian.Uint32(payload[off : off+4]))
		done := payload[off+4] != 0
		off += 6 // skip len(4) + done(1) + reserved(1)
		if off+payLen > len(payload) {
			return nil, fmt.Errorf("episode batch trans %d payload %d overruns frame", i, payLen)
		}
		var txPayload []byte
		if payLen > 0 {
			txPayload = make([]byte, payLen)
			copy(txPayload, payload[off:off+payLen])
		}
		off += payLen
		txs = append(txs, &Transition{
			ClientID:  header.ClientID,
			EpisodeID: header.EpisodeID,
			Step:      0, // Step not encoded at batch level — DMC payload header carries step_in_episode
			Done:      done,
			Payload:   txPayload,
		})
	}
	return txs, nil
}

func boolToU8(b bool) uint8 {
	if b {
		return 1
	}
	return 0
}
