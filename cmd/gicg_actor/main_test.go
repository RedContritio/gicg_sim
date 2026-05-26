package main

import (
	"bytes"
	"encoding/json"
	"testing"
)

// TestParseConfig_Minimal — happy-path Config JSON decode + roundtrip,验证 snake_case
// JSON 字段名与 Go struct tag 对齐 (Python 侧 go_subprocess.py 用 snake_case dict 透传)。
func TestParseConfig_Minimal(t *testing.T) {
	in := bytes.NewBufferString(`{"n_actors": 1, "trans_shm_name": "test_ring", "trans_shm_capacity": 16, "trans_shm_slot_size": 1024, "paradigm_name": "dmc", "inf_server_addr": "127.0.0.1:0"}`)
	cfg, err := parseConfig(in)
	if err != nil {
		t.Fatalf("parseConfig: %v", err)
	}
	if cfg.NActors != 1 {
		t.Fatalf("NActors=%d, want 1", cfg.NActors)
	}
	if cfg.TransShmName != "test_ring" {
		t.Fatalf("TransShmName=%q, want test_ring", cfg.TransShmName)
	}
	if cfg.TransShmCapacity != 16 {
		t.Fatalf("TransShmCapacity=%d, want 16", cfg.TransShmCapacity)
	}
	if cfg.TransShmSlotSize != 1024 {
		t.Fatalf("TransShmSlotSize=%d, want 1024", cfg.TransShmSlotSize)
	}
	if cfg.ParadigmName != "dmc" {
		t.Fatalf("ParadigmName=%q, want dmc", cfg.ParadigmName)
	}
	// roundtrip JSON encode — 验证 marshal 出来字段名仍是 snake_case
	b, _ := json.Marshal(cfg)
	if !bytes.Contains(b, []byte(`"trans_shm_name":"test_ring"`)) {
		t.Fatalf("encode missing snake_case field: %s", b)
	}
}

// TestParseConfig_RejectsInvalidNActors — fail-loud on n_actors <= 0。
func TestParseConfig_RejectsInvalidNActors(t *testing.T) {
	in := bytes.NewBufferString(`{"n_actors": 0, "trans_shm_name": "x"}`)
	_, err := parseConfig(in)
	if err == nil {
		t.Fatalf("parseConfig accepted n_actors=0")
	}
}

// TestParseConfig_RequiresTransShmName — fail-loud on empty trans_shm_name。
func TestParseConfig_RequiresTransShmName(t *testing.T) {
	in := bytes.NewBufferString(`{"n_actors": 1}`)
	_, err := parseConfig(in)
	if err == nil {
		t.Fatalf("parseConfig accepted empty trans_shm_name")
	}
}

// TestParseConfig_GoMaxProcs — I29 R6.1 cfg knob roundtrip + default-zero
// semantics (<= 0 时不调 runtime.GOMAXPROCS,让 Go 自管 NumCPU)。
func TestParseConfig_GoMaxProcs(t *testing.T) {
	// explicit value
	in := bytes.NewBufferString(`{"n_actors": 1, "trans_shm_name": "x", "trans_shm_capacity": 16, "trans_shm_slot_size": 1024, "paradigm_name": "dmc", "inf_server_addr": "127.0.0.1:0", "go_gomaxprocs": 4}`)
	cfg, err := parseConfig(in)
	if err != nil {
		t.Fatalf("parseConfig: %v", err)
	}
	if cfg.GoMaxProcs != 4 {
		t.Fatalf("GoMaxProcs=%d, want 4", cfg.GoMaxProcs)
	}
	// default (missing) -> 0 (= Go runtime NumCPU semantic per main: skip 调 runtime.GOMAXPROCS)
	in2 := bytes.NewBufferString(`{"n_actors": 1, "trans_shm_name": "x", "trans_shm_capacity": 16, "trans_shm_slot_size": 1024, "paradigm_name": "dmc", "inf_server_addr": "127.0.0.1:0"}`)
	cfg2, err := parseConfig(in2)
	if err != nil {
		t.Fatalf("parseConfig: %v", err)
	}
	if cfg2.GoMaxProcs != 0 {
		t.Fatalf("default GoMaxProcs=%d, want 0", cfg2.GoMaxProcs)
	}
}
