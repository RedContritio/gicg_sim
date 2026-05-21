package gicg_actor

import (
	"bytes"
	"math"
	"testing"
)

// TestEncodeDecodeInferRequest_RoundTrip 守 encode → decode 后 InferRequest 字段全相等
// (含 float32 bit-exact)。
func TestEncodeDecodeInferRequest_RoundTrip(t *testing.T) {
	orig := &InferRequest{
		StaticHash: [16]byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10},
		ClientID:   42,
		ReqID:      1337,
		DynObs:     []float32{1.5, -2.5, 0.0, 3.14159, math.MaxFloat32},
		Refs:       []int64{0, -1, 1 << 40, math.MaxInt64},
		Pay:        []float32{0.1, 0.2, 0.3, 0.4},
	}
	encoded, err := EncodeInferRequest(orig)
	if err != nil {
		t.Fatalf("encode failed: %v", err)
	}
	// outer length prefix:[4 byte len][payload]
	if len(encoded) < 4 {
		t.Fatalf("encoded too short: %d", len(encoded))
	}
	payload := encoded[4:]
	decoded, err := DecodeInferRequest(payload)
	if err != nil {
		t.Fatalf("decode failed: %v", err)
	}
	if decoded.StaticHash != orig.StaticHash {
		t.Errorf("StaticHash mismatch")
	}
	if decoded.ClientID != orig.ClientID {
		t.Errorf("ClientID: got %d, want %d", decoded.ClientID, orig.ClientID)
	}
	if decoded.ReqID != orig.ReqID {
		t.Errorf("ReqID: got %d, want %d", decoded.ReqID, orig.ReqID)
	}
	if len(decoded.DynObs) != len(orig.DynObs) {
		t.Errorf("DynObs len: got %d, want %d", len(decoded.DynObs), len(orig.DynObs))
	}
	for i := range orig.DynObs {
		if math.Float32bits(decoded.DynObs[i]) != math.Float32bits(orig.DynObs[i]) {
			t.Errorf("DynObs[%d]: got %g, want %g (bit-exact required)", i, decoded.DynObs[i], orig.DynObs[i])
		}
	}
	for i := range orig.Refs {
		if decoded.Refs[i] != orig.Refs[i] {
			t.Errorf("Refs[%d]: got %d, want %d", i, decoded.Refs[i], orig.Refs[i])
		}
	}
	for i := range orig.Pay {
		if math.Float32bits(decoded.Pay[i]) != math.Float32bits(orig.Pay[i]) {
			t.Errorf("Pay[%d]: got %g, want %g (bit-exact required)", i, decoded.Pay[i], orig.Pay[i])
		}
	}
}

// TestEncodeInferRequest_EmptyArrays 守 nil / empty 数组 encode 不 panic。
func TestEncodeInferRequest_EmptyArrays(t *testing.T) {
	req := &InferRequest{ClientID: 1, ReqID: 1}
	encoded, err := EncodeInferRequest(req)
	if err != nil {
		t.Fatalf("encode empty: %v", err)
	}
	expectedLen := 4 + HeaderSize // outer prefix + header, 0 byte payload data
	if len(encoded) != expectedLen {
		t.Errorf("empty encoded len: got %d, want %d", len(encoded), expectedLen)
	}
	decoded, err := DecodeInferRequest(encoded[4:])
	if err != nil {
		t.Fatalf("decode empty: %v", err)
	}
	if len(decoded.DynObs) != 0 || len(decoded.Refs) != 0 || len(decoded.Pay) != 0 {
		t.Errorf("expected all empty, got dyn=%d refs=%d pay=%d",
			len(decoded.DynObs), len(decoded.Refs), len(decoded.Pay))
	}
}

// TestDecodeInferRequest_WrongVersion 守 schema version mismatch fail loud。
func TestDecodeInferRequest_WrongVersion(t *testing.T) {
	// 构造 valid header 但 ver=999。
	payload := make([]byte, HeaderSize)
	// 用 binary.LittleEndian 写 ver=999
	payload[0] = 0xe7 // 999 = 0x3e7 LE → e7 03
	payload[1] = 0x03
	_, err := DecodeInferRequest(payload)
	if err == nil {
		t.Fatal("expected wire version mismatch error, got nil")
	}
	if !bytes.Contains([]byte(err.Error()), []byte("wire version")) {
		t.Errorf("error should mention wire version, got: %v", err)
	}
}

// TestEncodeDecodeInferResponse_OK 守 status=ok 路径 round-trip 含 float32 bit-exact。
func TestEncodeDecodeInferResponse_OK(t *testing.T) {
	orig := &InferResponse{
		Status: InferStatusOK,
		Logits: []float32{0.1, -0.2, 1e10, -1e10},
	}
	encoded, err := EncodeInferResponse(orig)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	decoded, err := DecodeInferResponse(encoded[4:])
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded.Status != InferStatusOK {
		t.Errorf("status: got %d, want %d", decoded.Status, InferStatusOK)
	}
	for i := range orig.Logits {
		if math.Float32bits(decoded.Logits[i]) != math.Float32bits(orig.Logits[i]) {
			t.Errorf("Logits[%d] bit mismatch", i)
		}
	}
}

// TestEncodeDecodeInferResponse_Err 守 status=err 路径 ErrMsg round-trip。
func TestEncodeDecodeInferResponse_Err(t *testing.T) {
	orig := &InferResponse{
		Status: InferStatusErr,
		ErrMsg: "test error: decode failure",
	}
	encoded, err := EncodeInferResponse(orig)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	decoded, err := DecodeInferResponse(encoded[4:])
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded.Status != InferStatusErr {
		t.Errorf("status: got %d, want %d", decoded.Status, InferStatusErr)
	}
	if decoded.ErrMsg != orig.ErrMsg {
		t.Errorf("ErrMsg: got %q, want %q", decoded.ErrMsg, orig.ErrMsg)
	}
}

// TestReadLengthPrefixed_FullMessage 守 reader 路径 ok。
func TestReadLengthPrefixed_FullMessage(t *testing.T) {
	req := &InferRequest{
		StaticHash: [16]byte{0xaa},
		ClientID:   1,
		ReqID:      2,
		DynObs:     []float32{1.0, 2.0, 3.0},
	}
	encoded, err := EncodeInferRequest(req)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	reader := bytes.NewReader(encoded)
	payload, err := ReadLengthPrefixed(reader)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	decoded, err := DecodeInferRequest(payload)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded.ClientID != 1 || decoded.ReqID != 2 {
		t.Errorf("decoded mismatch: %+v", decoded)
	}
}

// TestReadLengthPrefixed_OversizedRejected 守 malformed length fail loud。
func TestReadLengthPrefixed_OversizedRejected(t *testing.T) {
	// 构造一条 length-prefix 表示 super-large message。
	huge := []byte{0xFF, 0xFF, 0xFF, 0xFF} // 4 GB - 1
	reader := bytes.NewReader(huge)
	_, err := ReadLengthPrefixed(reader)
	if err == nil {
		t.Fatal("expected oversized rejection, got nil")
	}
}
