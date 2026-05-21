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
	"crypto/sha256"
	"encoding/binary"
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
		charIdx := int64(-1)
		switch a.Kind {
		case engine.ActionSkill:
			pi := a.PlayerIdx
			ci := g.Players[pi].ActiveChar
			if rawID, ok := g.CanonicalSkillHooks[[3]int{pi, ci, a.Index}]; ok {
				if ai, ok2 := rawToActive[rawID]; ok2 {
					hookIdx = int64(ai)
				}
			}
		case engine.ActionCard:
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

// EncodeMinimalTransitionPayload — minimal transition payload schema for Phase 1:
//
//	[u32 chosen_action_idx][u32 step_in_episode][i32 reward_x1m] | dyn_obs raw bytes
//
// Python collector 端 reconstruct DmcTransition by:
//   - 从 static_obs_hash lookup static fields cache
//   - dyn_obs raw bytes → np.frombuffer view
//   - reward = reward_x1m / 1e6
//   - 跟 Python `_capture_obs_np` 同 layout 拼装完整 obs_dict
//
// Phase 1 简化:每条 transition 只发 dyn_obs(不重发 refs/pay,Python 端从 hash cache 取
// 上次 inference 用的 refs/pay)。 但本 schema 跟 Python 端配合需 P1.4 端到端验证 — 这里
// 先 ship encoding 函数 + Go 单测,P1.4 时 Python 端 decode 对接。
func EncodeMinimalTransitionPayload(dynObs []float32, chosenAction uint32, step uint32, reward float32) []byte {
	out := make([]byte, 4+4+4+len(dynObs)*4)
	binary.LittleEndian.PutUint32(out[0:4], chosenAction)
	binary.LittleEndian.PutUint32(out[4:8], step)
	rewardMicroI32 := int32(reward * 1e6)
	binary.LittleEndian.PutUint32(out[8:12], uint32(rewardMicroI32))
	if len(dynObs) > 0 {
		copy(out[12:], unsafe.Slice((*byte)(unsafe.Pointer(&dynObs[0])), len(dynObs)*4))
	}
	return out
}
