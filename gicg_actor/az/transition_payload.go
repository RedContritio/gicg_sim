// transition_payload.go — AZ paradigm transition payload encoder。
//
// 跟 DMC payload 结构同 but 加 visits distribution + root_value(MCTS-specific
// 训练 target)。
//
// Wire format(declarative struct + 变长 array tail):
//
//	header = binary-encoded AzTransitionHeader{ChosenAction, StepInEp, RewardX1M,
//	                                            RootValueX1M, NLegal, NDyn, NRefs,
//	                                            NPay, NStatic, NVisits, StaticHash}
//	body   = dyn (f32×N) || refs (i64×N) || pay (f32×N) || static (i32×N) ||
//	         visits (f32×NVisits)
//
// NVisits 通常 = NLegal(MCTS 给每个 legal action 算 visits)— 但 schema 不强制相等,
// Python 端 decode 后 reshape 用 NVisits 实际值。
//
// 设计 vs DMC:
// - DMC 训练 target = (action_idx, G)
// - AZ 训练 target = (visits_dist, G, root_value)— 多两个 float field
// - visits 是 raw int counts in Python,这里 normalize 成 prob f32 for wire-compact
//   (Python collector 解码后 backfill total_visits 可重建 counts if needed)

package az

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"unsafe"
)

// AzTransitionHeader — declarative schema(binary.Read/Write 处理 offset)。 加字段在 struct
// 加一行,encode/decode 自动 follow。 跟 Python AZ_PAYLOAD_FMT 同步。
type AzTransitionHeader struct {
	ChosenAction uint32
	StepInEp     uint32
	RewardX1M    int32 // reward × 1e6 fixed-point(同 DMC,terminal-only ±1)
	RootValueX1M int32 // MCTS root value × 1e6(bootstrap target)
	NLegal       uint32
	NDyn         uint32
	NRefs        uint32
	NPay         uint32
	NStatic      uint32
	NVisits      uint32
	StaticHash   [16]byte
}

// EncodeAzTransitionPayload 序列化 self-contained AZ transition。 同 DMC 模式 — first
// transition per episode 携带 static_obs,后续 NStatic=0。
//
// visits 是 normalized prob distribution(sum to 1)over legal actions(typically NLegal
// entries,但 schema 不强制)。 Python collector decode 后用 root_value + visits 作训练
// target。
func EncodeAzTransitionPayload(
	chosenAction uint32,
	step uint32,
	reward float32,
	rootValue float32,
	nLegal int,
	dynObs []float32,
	refs []int64,
	pay []float32,
	static []int32,
	visits []float32,
	staticHash [16]byte,
) []byte {
	header := AzTransitionHeader{
		ChosenAction: chosenAction,
		StepInEp:     step,
		RewardX1M:    int32(reward * 1e6),
		RootValueX1M: int32(rootValue * 1e6),
		NLegal:       uint32(nLegal),
		NDyn:         uint32(len(dynObs)),
		NRefs:        uint32(len(refs)),
		NPay:         uint32(len(pay)),
		NStatic:      uint32(len(static)),
		NVisits:      uint32(len(visits)),
		StaticHash:   staticHash,
	}
	headerSize := binary.Size(header)
	body := headerSize + len(dynObs)*4 + len(refs)*8 + len(pay)*4 + len(static)*4 + len(visits)*4
	var buf bytes.Buffer
	buf.Grow(body)
	if err := binary.Write(&buf, binary.LittleEndian, &header); err != nil {
		panic(fmt.Sprintf("EncodeAzTransitionPayload header write: %v", err))
	}
	if len(dynObs) > 0 {
		buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&dynObs[0])), len(dynObs)*4))
	}
	if len(refs) > 0 {
		buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&refs[0])), len(refs)*8))
	}
	if len(pay) > 0 {
		buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&pay[0])), len(pay)*4))
	}
	if len(static) > 0 {
		buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&static[0])), len(static)*4))
	}
	if len(visits) > 0 {
		buf.Write(unsafe.Slice((*byte)(unsafe.Pointer(&visits[0])), len(visits)*4))
	}
	return buf.Bytes()
}
