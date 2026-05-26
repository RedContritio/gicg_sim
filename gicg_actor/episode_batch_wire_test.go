// episode_batch_wire_test.go — F1 EpisodeBatch wire encode/decode roundtrip tests。
package gicg_actor

import (
	"testing"
)

func TestEncodeDecodeEpisodeBatch_RoundTrip(t *testing.T) {
	txs := []*Transition{
		{ClientID: 1, EpisodeID: 5, Step: 0, Done: false, Payload: []byte{0xaa, 0xbb}},
		{ClientID: 1, EpisodeID: 5, Step: 1, Done: false, Payload: []byte{0xcc, 0xdd, 0xee}},
		{ClientID: 1, EpisodeID: 5, Step: 2, Done: true, Payload: []byte{}}, // terminal marker
	}

	encoded, err := EncodeEpisodeBatch(1, 5, txs)
	if err != nil {
		t.Fatalf("EncodeEpisodeBatch: %v", err)
	}
	// Skip outer length prefix (4 bytes) for Decode
	decoded, err := DecodeEpisodeBatch(encoded[4:])
	if err != nil {
		t.Fatalf("DecodeEpisodeBatch: %v", err)
	}
	if len(decoded) != 3 {
		t.Fatalf("got %d transitions, want 3", len(decoded))
	}
	// Verify client_id / episode_id preserved
	for i, tx := range decoded {
		if tx.ClientID != 1 {
			t.Errorf("tx[%d].ClientID = %d, want 1", i, tx.ClientID)
		}
		if tx.EpisodeID != 5 {
			t.Errorf("tx[%d].EpisodeID = %d, want 5", i, tx.EpisodeID)
		}
	}
	// Verify done bit
	if decoded[0].Done != false {
		t.Errorf("tx[0].Done = true, want false")
	}
	if decoded[1].Done != false {
		t.Errorf("tx[1].Done = true, want false")
	}
	if decoded[2].Done != true {
		t.Errorf("tx[2].Done = false, want true")
	}
	// Verify payload bytes
	if len(decoded[0].Payload) != 2 || decoded[0].Payload[0] != 0xaa {
		t.Errorf("tx[0].Payload mismatch: %v", decoded[0].Payload)
	}
	if len(decoded[1].Payload) != 3 || decoded[1].Payload[0] != 0xcc {
		t.Errorf("tx[1].Payload mismatch: %v", decoded[1].Payload)
	}
	if len(decoded[2].Payload) != 0 {
		t.Errorf("tx[2].Payload not empty: %v", decoded[2].Payload)
	}
}

func TestEncodeDecodeEpisodeBatch_SingleTrans(t *testing.T) {
	txs := []*Transition{
		{ClientID: 99, EpisodeID: 1, Done: true, Payload: []byte{0x01}},
	}
	encoded, err := EncodeEpisodeBatch(99, 1, txs)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	decoded, err := DecodeEpisodeBatch(encoded[4:])
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(decoded) != 1 {
		t.Fatalf("got %d, want 1", len(decoded))
	}
	if decoded[0].ClientID != 99 || decoded[0].EpisodeID != 1 || !decoded[0].Done {
		t.Errorf("unexpected: %+v", decoded[0])
	}
}

func TestEncodeEpisodeBatch_EmptyError(t *testing.T) {
	_, err := EncodeEpisodeBatch(1, 1, nil)
	if err == nil {
		t.Fatal("expected error for empty transitions")
	}
}

func TestDecodeEpisodeBatch_TooShort(t *testing.T) {
	_, err := DecodeEpisodeBatch([]byte{0x01, 0x02})
	if err == nil {
		t.Fatal("expected error for too-short payload")
	}
}

func TestDecodeEpisodeBatch_WrongKind(t *testing.T) {
	// Build a valid header but with Kind=0 (per-trans) instead of Kind=1
	txs := []*Transition{{ClientID: 1, EpisodeID: 1, Done: true, Payload: []byte{0x01}}}
	encoded, _ := EncodeEpisodeBatch(1, 1, txs)
	// Kind byte is at offset 4+14=18 in the full encoded (4 outer prefix + 14 header offset)
	// EpisodeBatchHeader: ver(2)+clientid(4)+episodeid(4)+ntrans(4)+kind(1) = 15, kind at offset 14
	payload := encoded[4:]
	payload[14] = 0 // flip kind to per-trans
	_, err := DecodeEpisodeBatch(payload)
	if err == nil {
		t.Fatal("expected error for wrong kind")
	}
}

func TestEpisodeBatchHeader_Size(t *testing.T) {
	// EpisodeBatchHeader = ver(2)+clientid(4)+episodeid(4)+ntrans(4)+kind(1)+reserved(1) = 16
	if EpisodeBatchHeaderSize != 16 {
		t.Errorf("EpisodeBatchHeaderSize = %d, want 16", EpisodeBatchHeaderSize)
	}
}
