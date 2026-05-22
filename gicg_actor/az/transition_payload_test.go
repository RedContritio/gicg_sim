// AZ transition payload encoder unit tests + bytes layout sanity check。

package az

import (
	"encoding/binary"
	"math"
	"testing"
)

func TestEncodeAzTransitionPayload_RoundTrip(t *testing.T) {
	dyn := []float32{1.5, -2.5, 0.0, 3.14}
	refs := []int64{0, 1, 2, 3, 4, 5}
	pay := []float32{0.1, 0.2}
	static := []int32{10, 20, 30}
	visits := []float32{0.5, 0.3, 0.15, 0.05}
	hash := [16]byte{0xaa, 0xbb}

	payload := EncodeAzTransitionPayload(
		2, 17, 1.0, 0.42, 4, dyn, refs, pay, static, visits, hash,
	)

	headerSize := binary.Size(AzTransitionHeader{})
	expectedLen := headerSize + len(dyn)*4 + len(refs)*8 + len(pay)*4 + len(static)*4 + len(visits)*4
	if len(payload) != expectedLen {
		t.Fatalf("len: got %d, want %d", len(payload), expectedLen)
	}

	// Verify header bytes layout(declarative struct binary.Size):
	// ChosenAction(4) + StepInEp(4) + RewardX1M(4) + RootValueX1M(4)
	// + 6 × uint32 N* fields (4 each) = 16 + 24 = 40
	// + StaticHash(16) = 56
	chosen := binary.LittleEndian.Uint32(payload[0:4])
	step := binary.LittleEndian.Uint32(payload[4:8])
	reward := int32(binary.LittleEndian.Uint32(payload[8:12]))
	rootVal := int32(binary.LittleEndian.Uint32(payload[12:16]))
	nLegal := binary.LittleEndian.Uint32(payload[16:20])
	nDyn := binary.LittleEndian.Uint32(payload[20:24])
	nRefs := binary.LittleEndian.Uint32(payload[24:28])
	nPay := binary.LittleEndian.Uint32(payload[28:32])
	nStatic := binary.LittleEndian.Uint32(payload[32:36])
	nVisits := binary.LittleEndian.Uint32(payload[36:40])

	if chosen != 2 {
		t.Errorf("chosen: got %d, want 2", chosen)
	}
	if step != 17 {
		t.Errorf("step: got %d, want 17", step)
	}
	if reward != int32(1.0*1e6) {
		t.Errorf("reward_micro: got %d, want %d", reward, int32(1.0*1e6))
	}
	if rootVal != int32(0.42*1e6) {
		t.Errorf("root_value_micro: got %d, want %d", rootVal, int32(0.42*1e6))
	}
	if nLegal != 4 || nDyn != uint32(len(dyn)) || nRefs != uint32(len(refs)) ||
		nPay != uint32(len(pay)) || nStatic != uint32(len(static)) || nVisits != uint32(len(visits)) {
		t.Errorf(
			"N* counts: legal=%d dyn=%d refs=%d pay=%d static=%d visits=%d (expected 4/4/6/2/3/4)",
			nLegal, nDyn, nRefs, nPay, nStatic, nVisits,
		)
	}
	// static_hash at offset 40..56
	for i, b := range hash {
		if payload[40+i] != b {
			t.Errorf("static_hash[%d]: got %x, want %x", i, payload[40+i], b)
		}
	}
	// dyn at offset 56(headerSize)
	dynOff := headerSize
	for i, v := range dyn {
		gotBits := binary.LittleEndian.Uint32(payload[dynOff+i*4 : dynOff+(i+1)*4])
		if gotBits != math.Float32bits(v) {
			t.Errorf("dyn[%d]: got bits %x, want %x", i, gotBits, math.Float32bits(v))
		}
	}
}

func TestEncodeAzTransitionPayload_EmptyArrays(t *testing.T) {
	payload := EncodeAzTransitionPayload(
		0, 0, 0.0, 0.0, 0,
		nil, nil, nil, nil, nil,
		[16]byte{},
	)
	headerSize := binary.Size(AzTransitionHeader{})
	if len(payload) != headerSize {
		t.Errorf("empty arrays: payload len=%d, want %d (header only)", len(payload), headerSize)
	}
}

func TestEncodeAzTransitionPayload_NegativeRootValue(t *testing.T) {
	payload := EncodeAzTransitionPayload(
		0, 0, 0.0, -0.5, 0,
		nil, nil, nil, nil, nil,
		[16]byte{},
	)
	gotRootVal := int32(binary.LittleEndian.Uint32(payload[12:16]))
	if gotRootVal != int32(-0.5*1e6) {
		t.Errorf("root_value_micro: got %d, want %d", gotRootVal, int32(-0.5*1e6))
	}
}
