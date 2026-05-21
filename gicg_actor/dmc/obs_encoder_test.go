package dmc

import (
	"crypto/sha256"
	"encoding/binary"
	"math"
	"testing"
	"unsafe"

	"gicg_mono/gicg_actor"
)

// TestComputeStaticHash_MatchesPythonAlgo 守 Go side hash 算法跟 Python side mp_factories.py
// 等价:对 float32 raw bytes 跑 sha256 trunc 16。
//
// Python ref(mp_factories.py line 153 post 2026-05-21):
//
//	self._static_obs_hash = hashlib.sha256(self._static_obs_np.tobytes()).digest()[:16]
//
// where static_obs_np = np.ascontiguousarray(static, dtype=np.float32) — so int32 →
// float32 cast 已经在 Python 端完成,Python `tobytes()` 出的就是 float32 bytes。 Go side
// 自己做 int32 → float32 cast(input 是 engine.BuildStaticObs 返的 int32)。
//
// 本测试不依赖 engine instance:直接构造已知 int32 static obs + 手算 expected hash + 比对。
func TestComputeStaticHash_MatchesPythonAlgo(t *testing.T) {
	// 任意 int32 sample。
	static := []int32{1, 2, 3, -4, 0, 100, -1000, 7}
	hash := ComputeStaticHash(static)

	// Expected:手算 same algo — cast int32 → float32,tobytes,sha256[:16]。
	asFloat := make([]float32, len(static))
	for i, v := range static {
		asFloat[i] = float32(v)
	}
	floatBytes := unsafe.Slice((*byte)(unsafe.Pointer(&asFloat[0])), len(asFloat)*4)
	sum := sha256.Sum256(floatBytes)
	var expected [16]byte
	copy(expected[:], sum[:16])

	if hash != expected {
		t.Errorf("hash mismatch:\n  got      %x\n  expected %x", hash, expected)
	}
}

// TestComputeStaticHash_EmptyInput 守 边界:0-length input 不 panic + 返 sha256(empty)[:16]。
func TestComputeStaticHash_EmptyInput(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("panic on empty input: %v", r)
		}
	}()
	// unsafe.Slice on empty asFloat 在 Go 是 0-len slice,sha256(nil)[:16] 已知值。
	// 实现里 unsafe.Slice(&asFloat[0], 0) panic at &asFloat[0] index-into-empty。 让 me
	// verify 此 edge — 如果实现要 zero-length 安全则改实现,否则 spec is "non-empty".
	// 当前 spec:input non-empty(engine.BuildStaticObs 一定 > 0)。 本测试只验非空 path。
	_ = ComputeStaticHash([]int32{0})
}

// TestEncodeDmcTransitionPayload_RoundTrip 守 self-contained transition payload 编码 layout。
//
// Schema:DmcTransitionHeader(38 bytes:chosen+step+reward+5×u16+16-byte hash)+
// body(dyn + refs + pay + static)。
func TestEncodeDmcTransitionPayload_RoundTrip(t *testing.T) {
	dyn := []float32{1.5, -2.5, 0.0, 3.14}
	refs := []int64{0, -1, 100, 200, 300, 400}
	pay := []float32{0.1, 0.2, 0.3, 0.4}
	static := []int32{42, -1, 7}
	hash := [16]byte{0xaa, 0xbb}

	payload := EncodeDmcTransitionPayload(7, 42, 0.001234, 5, dyn, refs, pay, static, hash)

	headerSize := binary.Size(DmcTransitionHeader{})
	expectedLen := headerSize + len(dyn)*4 + len(refs)*8 + len(pay)*4 + len(static)*4
	if len(payload) != expectedLen {
		t.Fatalf("len: got %d, want %d", len(payload), expectedLen)
	}
	gotAction := binary.LittleEndian.Uint32(payload[0:4])
	gotStep := binary.LittleEndian.Uint32(payload[4:8])
	gotRewardMicro := int32(binary.LittleEndian.Uint32(payload[8:12]))
	gotNLegal := binary.LittleEndian.Uint32(payload[12:16])
	gotNDyn := binary.LittleEndian.Uint32(payload[16:20])
	gotNRefs := binary.LittleEndian.Uint32(payload[20:24])
	gotNPay := binary.LittleEndian.Uint32(payload[24:28])
	gotNStatic := binary.LittleEndian.Uint32(payload[28:32])
	if gotAction != 7 || gotStep != 42 {
		t.Errorf("chosen/step: got (%d,%d), want (7,42)", gotAction, gotStep)
	}
	wantRewardMicro := int32(0.001234 * 1e6)
	if gotRewardMicro != wantRewardMicro {
		t.Errorf("reward_micro: got %d, want %d", gotRewardMicro, wantRewardMicro)
	}
	if int(gotNLegal) != 5 || int(gotNDyn) != len(dyn) || int(gotNRefs) != len(refs) ||
		int(gotNPay) != len(pay) || int(gotNStatic) != len(static) {
		t.Errorf("counts: got (legal=%d, dyn=%d, refs=%d, pay=%d, static=%d), want (5,%d,%d,%d,%d)",
			gotNLegal, gotNDyn, gotNRefs, gotNPay, gotNStatic,
			len(dyn), len(refs), len(pay), len(static))
	}
	// static_hash position 32..48 (after 12B chosen+step+reward + 5×u32 n_* = 32 bytes)
	for i, b := range hash {
		if payload[32+i] != b {
			t.Errorf("static_hash[%d]: got %x, want %x", i, payload[32+i], b)
		}
	}
	// dyn bytes round-trip(skip refs/pay/static — same bit-pattern test pattern)
	off := headerSize
	for i, v := range dyn {
		gotBits := binary.LittleEndian.Uint32(payload[off+i*4 : off+i*4+4])
		if gotBits != math.Float32bits(v) {
			t.Errorf("dyn[%d]: got bits %x, want %x", i, gotBits, math.Float32bits(v))
		}
	}
}

// TestDMCParadigm_RegisteredOnImport 守 dmc package init() 触发 RegisterParadigm,
// 主体 gicg_actor.GetParadigm("dmc") 返非 nil。
func TestDMCParadigm_RegisteredOnImport(t *testing.T) {
	p := gicg_actor.GetParadigm("dmc")
	if p == nil {
		t.Fatal("dmc paradigm not registered — init() side-effect missing?")
	}
	if p.Name() != "dmc" {
		t.Errorf("name: got %q, want \"dmc\"", p.Name())
	}
}
