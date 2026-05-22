// AZ paradigm Configure 单测 + 注册验证。 完整 Run loop test 走 P2.2 ship 后端到端。

package az

import (
	"encoding/json"
	"strings"
	"testing"

	"gicg_mono/gicg_actor"
)

func TestAZParadigm_RegisteredOnImport(t *testing.T) {
	p := gicg_actor.GetParadigm("az")
	if p == nil {
		t.Fatal("az paradigm not registered — init() side-effect missing?")
	}
	if p.Name() != "az" {
		t.Errorf("name: got %q, want \"az\"", p.Name())
	}
}

func TestAZConfigure_Valid(t *testing.T) {
	cfg := AZConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec:        json.RawMessage(`{"pools":["v_legacy"],"seed":1,"players":[{"chars":[{"name":"赤蝶"}]},{"chars":[{"name":"墨客"}]}]}`),
			MaxActions:      30,
			MaxEpisodeSteps: 360,
			BaseSeed:        42,
		},
		NRollouts:        100,
		ParallelRollouts: 4,
		CPuct:            1.5,
		DirichletAlpha:   0.3,
		DirichletWeight:  0.25,
		TemperatureMoves: 30,
		TemperatureValue: 1.0,
	}
	bs, _ := json.Marshal(cfg)
	p := &AZParadigm{}
	if err := p.Configure(string(bs)); err != nil {
		t.Fatalf("Configure: %v", err)
	}
	if p.cfg.NRollouts != 100 || p.cfg.CPuct != 1.5 {
		t.Errorf("cfg mismatch: NRollouts=%d CPuct=%f", p.cfg.NRollouts, p.cfg.CPuct)
	}
}

func TestAZConfigure_Errors(t *testing.T) {
	cases := []struct {
		name    string
		cfg     AZConfig
		wantSub string
	}{
		{
			name:    "missing game_spec",
			cfg:     AZConfig{BaseActorConfig: gicg_actor.BaseActorConfig{MaxActions: 10, MaxEpisodeSteps: 100}, NRollouts: 10, CPuct: 1.0},
			wantSub: "game_spec missing",
		},
		{
			name:    "bad n_rollouts",
			cfg:     AZConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}, CPuct: 1.0},
			wantSub: "n_rollouts=0",
		},
		{
			name:    "bad c_puct",
			cfg:     AZConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}, NRollouts: 10, CPuct: 0},
			wantSub: "c_puct",
		},
		{
			name:    "bad max_actions",
			cfg:     AZConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 0, MaxEpisodeSteps: 100}, NRollouts: 10, CPuct: 1.0},
			wantSub: "max_actions=0",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := &AZParadigm{}
			bs, _ := json.Marshal(tc.cfg)
			err := p.Configure(string(bs))
			if err == nil {
				t.Fatalf("want error containing %q, got nil", tc.wantSub)
			}
			if !strings.Contains(err.Error(), tc.wantSub) {
				t.Errorf("err=%v, want substring %q", err, tc.wantSub)
			}
		})
	}
}

func TestAZConfigure_DefaultsApplied(t *testing.T) {
	cfg := AZConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec:        json.RawMessage(`{}`),
			MaxActions:      10,
			MaxEpisodeSteps: 100,
		},
		NRollouts: 10,
		CPuct:     1.0,
		// ParallelRollouts / TemperatureValue omitted — should default
	}
	bs, _ := json.Marshal(cfg)
	p := &AZParadigm{}
	if err := p.Configure(string(bs)); err != nil {
		t.Fatalf("Configure: %v", err)
	}
	if p.cfg.ParallelRollouts != 1 {
		t.Errorf("default ParallelRollouts = %d, want 1", p.cfg.ParallelRollouts)
	}
	if p.cfg.TemperatureValue != 1.0 {
		t.Errorf("default TemperatureValue = %f, want 1.0", p.cfg.TemperatureValue)
	}
}
