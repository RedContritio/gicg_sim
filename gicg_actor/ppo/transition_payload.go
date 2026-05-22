// transition_payload.go — PPO paradigm transition payload encoder。
//
// 跟 DMC payload 结构同 but 加 log_prob(actor sampling time per-action log-likelihood)+
// value(network V(s) at pre-step state,GAE bootstrap target)。
//
// Wire format(declarative struct + 变长 array tail):
//
//	header = binary-encoded PpoTransitionHeader{ChosenAction, StepInEp, RewardX1M,
//	                                             LogProbX1M, ValueX1M, NLegal, NDyn,
//	                                             NRefs, NPay, NStatic, StaticHash}
//	body   = dyn (f32×N) || refs (i64×N) || pay (f32×N) || static (i32×N)
//
// vs DMC:加 LogProbX1M + ValueX1M 两 i32 fixed-point f32(×1e6 scale 防 cross-lang
// nan-bits drift,同 reward 路径)。

package ppo

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"unsafe"
)

// PpoTransitionHeader — declarative schema(binary.Read/Write 处理 offset)。 加字段在 struct
// 加一行,encode/decode 自动 follow。 跟 Python PPO_PAYLOAD_FMT 同步。
type PpoTransitionHeader struct {
	ChosenAction uint32
	StepInEp     uint32
	RewardX1M    int32 // reward × 1e6 fixed-point
	LogProbX1M   int32 // log_prob × 1e6 (chosen action 的 log π(a|s))
	ValueX1M     int32 // network V(s) × 1e6 (GAE bootstrap target)
	NLegal       uint32
	NDyn         uint32
	NRefs        uint32
	NPay         uint32
	NStatic      uint32
	StaticHash   [16]byte
}

// EncodePpoTransitionPayload 序列化 self-contained PPO transition。 同 DMC/AZ 模式 —
// first transition per episode 携带 static_obs,后续 NStatic=0。
func EncodePpoTransitionPayload(
	chosenAction uint32,
	step uint32,
	reward float32,
	logProb float32,
	value float32,
	nLegal int,
	dynObs []float32,
	refs []int64,
	pay []float32,
	static []int32,
	staticHash [16]byte,
) []byte {
	header := PpoTransitionHeader{
		ChosenAction: chosenAction,
		StepInEp:     step,
		RewardX1M:    int32(reward * 1e6),
		LogProbX1M:   int32(logProb * 1e6),
		ValueX1M:     int32(value * 1e6),
		NLegal:       uint32(nLegal),
		NDyn:         uint32(len(dynObs)),
		NRefs:        uint32(len(refs)),
		NPay:         uint32(len(pay)),
		NStatic:      uint32(len(static)),
		StaticHash:   staticHash,
	}
	headerSize := binary.Size(header)
	body := headerSize + len(dynObs)*4 + len(refs)*8 + len(pay)*4 + len(static)*4
	var buf bytes.Buffer
	buf.Grow(body)
	if err := binary.Write(&buf, binary.LittleEndian, &header); err != nil {
		panic(fmt.Sprintf("EncodePpoTransitionPayload header write: %v", err))
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
	return buf.Bytes()
}
