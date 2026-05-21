package gicg_actor

import (
	"bytes"
	"testing"
)

func TestEncodeDecodeTransition_RoundTrip(t *testing.T) {
	orig := &Transition{
		ClientID:  7,
		EpisodeID: 100,
		Step:      42,
		Done:      true,
		Payload:   []byte{0x01, 0x02, 0x03, 0xff, 0xfe, 0xfd},
	}
	encoded, err := EncodeTransition(orig)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	decoded, err := DecodeTransition(encoded[4:])
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded.ClientID != orig.ClientID {
		t.Errorf("ClientID: got %d, want %d", decoded.ClientID, orig.ClientID)
	}
	if decoded.EpisodeID != orig.EpisodeID {
		t.Errorf("EpisodeID: got %d, want %d", decoded.EpisodeID, orig.EpisodeID)
	}
	if decoded.Step != orig.Step {
		t.Errorf("Step: got %d, want %d", decoded.Step, orig.Step)
	}
	if decoded.Done != orig.Done {
		t.Errorf("Done: got %v, want %v", decoded.Done, orig.Done)
	}
	if !bytes.Equal(decoded.Payload, orig.Payload) {
		t.Errorf("Payload mismatch")
	}
}

func TestEncodeTransition_EmptyPayload(t *testing.T) {
	orig := &Transition{ClientID: 1, EpisodeID: 1, Step: 0, Done: false}
	encoded, err := EncodeTransition(orig)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	expectedLen := 4 + TransitionHeaderSize
	if len(encoded) != expectedLen {
		t.Errorf("empty: got %d byte, want %d", len(encoded), expectedLen)
	}
	decoded, err := DecodeTransition(encoded[4:])
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(decoded.Payload) != 0 {
		t.Errorf("expected empty payload, got %d byte", len(decoded.Payload))
	}
}

func TestDecodeTransition_WrongVersion(t *testing.T) {
	payload := make([]byte, TransitionHeaderSize)
	payload[0] = 0xff
	payload[1] = 0x00 // ver = 255 != 1
	_, err := DecodeTransition(payload)
	if err == nil {
		t.Fatal("expected version mismatch error")
	}
}

func TestReadTransitionFromReader(t *testing.T) {
	orig := &Transition{ClientID: 3, EpisodeID: 99, Step: 7, Done: true, Payload: []byte("hello")}
	encoded, _ := EncodeTransition(orig)
	r := bytes.NewReader(encoded)
	payload, err := ReadLengthPrefixed(r)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	decoded, err := DecodeTransition(payload)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded.ClientID != 3 || decoded.Step != 7 {
		t.Errorf("unexpected: %+v", decoded)
	}
}
