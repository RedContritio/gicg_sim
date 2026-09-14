// Package dmc — DMC paradigm adapter for Go actor pool。
//
// Mirror Python 端 _decoder.py / _episode.py 的 obs encoder layout:
//   - dyn_obs:gicg_engine.BuildDynamicObs(perspective) []int32 → []float32 view
//   - refs_padded:GetLegalActions + canonical hook/card 解码 → (max_actions, 3) int64
//   - pay_padded:GetLegalActionPayments → (max_actions, DiceColorCount=8) float32
//   - static_hash:blake2b-128 of BuildStaticObs() bytes
//
// 走 Go-native engine 调用(no cgo overhead),输出按 wire_format.go schema 喂
// InferenceClient.Request。 数值等价目标:**bit-exact vs Python `_capture_obs_np`
// 输出**(P1.2 verify gate),通过 byte-level np.array_equal cross-lang test 守(待 P1.2b
// + P1.4 Python wiring ship 后跑)。

package dmc

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"unsafe"

	"gicg_mono/gicg_actor"
	engine "gicg_mono/gicg_engine"
)

// 跟 Python 端 obs_constants.py 同。 这里 mirror 一份是为了 Go side 单测不 import engine 时也能用。
// Go side 是单一 source of truth,但 Python side OBS_* 常量也必须一致(P1 verify gate
// cross-lang bit-exact 守 numpy raw bytes 比对)。
const (
	OBSMetaSize           = engine.ObsMetaSize               // 3
	OBSMaxCardTypes       = engine.ObsMaxCardTypes           // 80
	OBSHandBuckets        = 4                                // engine internal magic
	OBSEnemySizes         = 2                                // hardcode same as Python OBS_ENEMY_SIZES
	OBSMaxChars           = engine.ObsMaxChars               // 6
	OBSRecentDamageEvents = engine.ObsRecentDamageEvents     // 8
	OBSRecentDamageFields = engine.ObsRecentDamageFieldCount // 11
	OBSPrepareSkillSlots  = engine.ObsPrepareSkillSlots      // 4
	OBSModifierLogKMod    = engine.ObsModifierLogKMod        // 4
	OBSModifierLogFields  = engine.ObsModifierLogFieldCount  // 5

	DiceColorCount = engine.DiceColorCount // 8

	// Action kind enum,must match training/core/obs_constants.py。
	ActionSkill   = 0
	ActionCard    = 1
	ActionSwitch  = 2
	ActionEndTurn = 3
)

// ComputeStaticHash 对 engine.BuildStaticObs() 输出做 sha256-trunc16 摘要。
//
// 跟 Python 端 _DMCObsDictRemoteProvider.observe_env 同算法:`hashlib.sha256(
// np.ascontiguousarray(static, dtype=np.float32).tobytes()).digest()[:16]`。
// 用 sha256[:16] 而非 blake2b,因为 Go stdlib 自带 crypto/sha256 而 blake2b 在
// golang.org/x/crypto 需 external dep;collision-safe 2^64 birthday bound
// 在 production scenario 多样性上充足(详 mp_factories.py 注释)。
//
// 注意 dtype:Python 端把 int32 static_obs 转 float32 再 hash;Go side 也得 cast 一份才能
// bit-exact 一致。 这是个 cross-lang fragility 点(同一 int32 转 float32 在两边 IEEE 754
// 应该 deterministic,但 hash digest 不容差错)。
func ComputeStaticHash(staticObs []int32) [16]byte {
	// Cast int32 → float32(bit-pattern 不同,Python tobytes 转 float32 而不是 int32)
	asFloat := make([]float32, len(staticObs))
	for i, v := range staticObs {
		asFloat[i] = float32(v)
	}
	floatBytes := unsafe.Slice((*byte)(unsafe.Pointer(&asFloat[0])), len(asFloat)*4)
	sum := sha256.Sum256(floatBytes)
	var out [16]byte
	copy(out[:], sum[:16])
	return out
}

// BuildInferRequest 从 engine.Game 当前 state 组装 InferRequest payload。 由 episode 主
// loop 在 actor goroutine 每 turn 调用。
//
// staticHash 由 caller 缓存(每 episode 算一次 ComputeStaticHash,跨 turn 不变),传入
// 节省 hash overhead。 client_id / req_id 由 caller 填。
//
// 注意:dyn_obs Python 是 float32(Python `_get_obs` astype),Go side engine.BuildDynamicObs
// 返 []int32,本函数转 float32 byte-equivalent。
//
// refs_padded layout (max_actions × 3):每行 (kind, hookIdx, charIdx)。 default fill:
// (ACTION_END_TURN, -1, -1) — pad 行表示 "结束回合"。 mirror Python pad_action_refs。
//
// pay_padded layout (max_actions × DiceColorCount=8) float32:每行是 DicePayment by color。
// default fill 0.0 — pad 行无 dice 消耗。
func BuildInferRequest(g *engine.Game, staticHash [16]byte, clientID, reqID uint32, maxActions int) *gicg_actor.InferRequest {
	// dyn_obs:从 acting player 视角(Python side 等价:env._get_obs() returns
	// dyn_obs for env.acting_player perspective)。
	perspective := g.ActingPlayer()
	dynInt32 := g.BuildDynamicObs(perspective)
	dynF32 := make([]float32, len(dynInt32))
	for i, v := range dynInt32 {
		dynF32[i] = float32(v)
	}

	// Action enumeration + canonical hook/card resolution。
	actions := g.GetLegalActions()
	rawToActive := g.BuildRawToActiveHookIdx()
	refs := make([]int64, maxActions*3)
	pay := make([]float32, maxActions*DiceColorCount)

	// Default pad rows:(ACTION_END_TURN, -1, -1) for refs;0 for pay。
	for i := range maxActions {
		refs[i*3+0] = ActionEndTurn
		refs[i*3+1] = -1
		refs[i*3+2] = -1
		// pay default 0(already by make)
	}

	n := len(actions)
	if n > maxActions {
		n = maxActions
	}
	for i := range n {
		a := actions[i]
		kind := int64(a.Kind)
		hookIdx := int64(-1)
		charIdx := int64(engine.ActionCharRef(a))
		switch a.Kind {
		case engine.ActionReroll:
			hookIdx = int64(a.Index) // quantity, not a hook for this action kind
		case engine.ActionSkill:
			pi := a.PlayerIdx
			ci := g.Players[pi].ActiveChar
			if rawID, ok := g.CanonicalSkillHooks[[3]int{pi, ci, a.Index}]; ok {
				if ai, ok2 := rawToActive[rawID]; ok2 {
					hookIdx = int64(ai)
				}
			}
		case engine.ActionCard, engine.ActionTune:
			pi := a.PlayerIdx
			ref := -1
			if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
				ref = g.Players[pi].Hand[a.Index].Ref
			}
			if ref >= 0 {
				if rawID, ok := g.CanonicalCardHooks[ref]; ok {
					if ai, ok2 := rawToActive[rawID]; ok2 {
						hookIdx = int64(ai)
					}
				}
			}
		case engine.ActionSwitch:
			charIdx = int64(a.Index)
		}
		refs[i*3+0] = kind
		refs[i*3+1] = hookIdx
		refs[i*3+2] = charIdx
		for c := range DiceColorCount {
			pay[i*DiceColorCount+c] = float32(a.DicePayment[c])
		}
	}

	return &gicg_actor.InferRequest{
		StaticHash: staticHash,
		ClientID:   clientID,
		ReqID:      reqID,
		DynObs:     dynF32,
		Refs:       refs,
		Pay:        pay,
	}
}

// DmcPayloadVer — DMC paradigm-specific payload schema 版本号。 每次改
// DmcTransitionHeader struct 顺序 / 字段类型 / 增删字段都必须 bump 此值。
// 与 outer WireVersion (gicg_actor.WireVersion) 独立 — outer 是 envelope 版本,
// 本字段是 paradigm payload 版本。 Python 端 transition_sink_wire.DMC_PAYLOAD_VER
// 须 lock-step。 mismatch decode 时 fail-loud。
const DmcPayloadVer uint8 = 1

// DmcTransitionHeader — DMC paradigm transition payload 固定头(declarative schema)。
//
// binary.Write/Read 处理 byte offset,加字段在 struct 加一行即可,encode/decode 自动
// follow。 同样 Python 端 transition_sink_wire 用 struct format string 同步。
//
// 注意 Go struct field order = wire byte order,改顺序破坏协议。 改顺序 / 类型 /
// 增删字段时必须 bump DmcPayloadVer (本文件) + Python DMC_PAYLOAD_VER (lock-step)。
//
// PayloadVer 在 header 首字节 — decoder 读 1 byte 即可识别 schema 漂移,无需依赖
// 后续字段 length 推断(audit 2026-05-28:expected_len 校验只能 catch 部分 drift,
// 改字段类型/顺序保持 total size 不变时 silent corruption)。
//
// NDyn/NRefs/NPay/NStatic 走 u32(同 InferRequestHeader)— static_obs 实测可达 ~293K
// int32(ObsMaxHooks × ObsIntsPerHook 主导,DSL 复杂场景),u16 65535 silent overflow
// 已被实测发现(2026-05-22 perf smoke decode error 调查)。
type DmcTransitionHeader struct {
	PayloadVer   uint8 // 必须始终 == DmcPayloadVer
	ChosenAction uint32
	StepInEp     uint32
	RewardX1M    int32 // reward × 1e6 fixed-point (避 cross-lang nan-bits drift)
	NLegal       uint32
	NDyn         uint32
	NRefs        uint32
	NPay         uint32
	NStatic      uint32 // 0 表示本 transition 不带 static_obs(Python 走 cache by StaticHash)
	StaticHash   [16]byte
}

// EncodeDmcTransitionPayload — self-contained transition payload(每条 transition 包含
// 所有 Python 重建 DmcTransition 所需 — dyn_obs + refs + pay + n_legal + chosen + reward
// + static_hash;static_obs raw 仅在 episode 第一条 transition 携带,后续 NStatic=0
// 让 Python 走 hash cache)。
//
// Schema:
//
//	header = binary-encoded DmcTransitionHeader{ChosenAction, StepInEp, RewardX1M, NLegal,
//	                                            NDyn, NRefs, NPay, NStatic, StaticHash}
//	body   = dyn_obs (f32 ×N) || refs (i64 ×N) || pay (f32 ×N) || static (i32 ×N)
func EncodeDmcTransitionPayload(
	chosenAction uint32,
	step uint32,
	reward float32,
	nLegal int,
	dynObs []float32,
	refs []int64,
	pay []float32,
	static []int32,
	staticHash [16]byte,
) []byte {
	header := DmcTransitionHeader{
		PayloadVer:   DmcPayloadVer,
		ChosenAction: chosenAction,
		StepInEp:     step,
		RewardX1M:    int32(reward * 1e6),
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
	// declarative:binary.Write 处理 struct field-by-field 写,加字段在 struct 上加一行
	// 自动 follow,无需手动 byte offset arithmetic。
	if err := binary.Write(&buf, binary.LittleEndian, &header); err != nil {
		// 不应发生 — struct 全 fixed-size。 panic 以暴露 schema 漂移。
		panic(fmt.Sprintf("EncodeDmcTransitionPayload header write: %v", err))
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
