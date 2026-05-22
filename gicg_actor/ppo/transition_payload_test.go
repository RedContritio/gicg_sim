// PPO transition payload encoder unit tests + bytes layout sanity check。

package ppo

import (
	"encoding/binary"
	"math"
	"testing"
)

func TestEncodePpoTransitionPayload_RoundTrip(t *testing.T) {
	dyn := []float32{1.5, -2.5, 3.0}
	refs := []int64{0, 1, 2, 3, 4, 5}
	pay := []float32{0.1, 0.2}
	static := []int32{10, 20}
	hash := [16]byte{0xaa, 0xbb}

	payload := EncodePpoTransitionPayload(
		3, 25, 0.5, -1.23, 0.66, 4, dyn, refs, pay, static, hash,
	)
	headerSize := binary.Size(PpoTransitionHeader{})
	expectedLen := headerSize + len(dyn)*4 + len(refs)*8 + len(pay)*4 + len(static)*4
	if len(payload) != expectedLen {
		t.Fatalf("len: got %d, want %d", len(payload), expectedLen)
	}
	// Header layout (declarative struct):
	// ChosenAction(4) + StepInEp(4) + RewardX1M(4) + LogProbX1M(4) + ValueX1M(4)
	// + 5 × uint32 N* (4 each) = 20 + 20 = 40
	// + StaticHash(16) = 56 byte total
	if headerSize != 56 {
		t.Errorf("header size = %d, want 56", headerSize)
	}
	chosen := binary.LittleEndian.Uint32(payload[0:4])
	step := binary.LittleEndian.Uint32(payload[4:8])
	reward := int32(binary.LittleEndian.Uint32(payload[8:12]))
	logProb := int32(binary.LittleEndian.Uint32(payload[12:16]))
	value := int32(binary.LittleEndian.Uint32(payload[16:20]))
	nLegal := binary.LittleEndian.Uint32(payload[20:24])
	nDyn := binary.LittleEndian.Uint32(payload[24:28])
	nRefs := binary.LittleEndian.Uint32(payload[28:32])
	nPay := binary.LittleEndian.Uint32(payload[32:36])
	nStatic := binary.LittleEndian.Uint32(payload[36:40])
	if chosen != 3 || step != 25 {
		t.Errorf("chosen/step: (%d,%d), want (3,25)", chosen, step)
	}
	if reward != int32(0.5*1e6) || logProb != int32(-1.23*1e6) || value != int32(0.66*1e6) {
		t.Errorf(
			"fixed-point: reward=%d logProb=%d value=%d want (%d,%d,%d)",
			reward, logProb, value, int32(0.5*1e6), int32(-1.23*1e6), int32(0.66*1e6),
		)
	}
	if nLegal != 4 || nDyn != uint32(len(dyn)) || nRefs != uint32(len(refs)) ||
		nPay != uint32(len(pay)) || nStatic != uint32(len(static)) {
		t.Errorf("N* counts mismatch: %d %d %d %d %d", nLegal, nDyn, nRefs, nPay, nStatic)
	}
	for i, b := range hash {
		if payload[40+i] != b {
			t.Errorf("static_hash[%d]: got %x, want %x", i, payload[40+i], b)
		}
	}
	dynOff := headerSize
	for i, v := range dyn {
		gotBits := binary.LittleEndian.Uint32(payload[dynOff+i*4 : dynOff+(i+1)*4])
		if gotBits != math.Float32bits(v) {
			t.Errorf("dyn[%d]: got bits %x, want %x", i, gotBits, math.Float32bits(v))
		}
	}
}

func TestEncodePpoTransitionPayload_EmptyArrays(t *testing.T) {
	payload := EncodePpoTransitionPayload(
		0, 0, 0.0, 0.0, 0.0, 0,
		nil, nil, nil, nil,
		[16]byte{},
	)
	headerSize := binary.Size(PpoTransitionHeader{})
	if len(payload) != headerSize {
		t.Errorf("empty: payload len=%d, want %d (header only)", len(payload), headerSize)
	}
}

func TestEncodePpoTransitionPayload_NegativeLogProbValue(t *testing.T) {
	// log_prob 通常 < 0(uniform 30 actions → log(1/30) ≈ -3.4),value 可负
	payload := EncodePpoTransitionPayload(
		0, 0, 0.0, -3.4, -0.5, 0,
		nil, nil, nil, nil,
		[16]byte{},
	)
	logProb := int32(binary.LittleEndian.Uint32(payload[12:16]))
	value := int32(binary.LittleEndian.Uint32(payload[16:20]))
	if logProb != int32(-3.4*1e6) {
		t.Errorf("log_prob_micro: got %d, want %d", logProb, int32(-3.4*1e6))
	}
	if value != int32(-0.5*1e6) {
		t.Errorf("value_micro: got %d, want %d", value, int32(-0.5*1e6))
	}
}
