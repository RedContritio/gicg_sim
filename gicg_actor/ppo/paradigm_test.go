// PPO paradigm Configure unit tests + 注册 verify。

package ppo

import (
	"encoding/json"
	"strings"
	"testing"

	"gicg_mono/gicg_actor"
)

func TestPPOParadigm_RegisteredOnImport(t *testing.T) {
	p := gicg_actor.GetParadigm("ppo")
	if p == nil {
		t.Fatal("ppo paradigm not registered — init() side-effect missing?")
	}
	if p.Name() != "ppo" {
		t.Errorf("name: got %q, want \"ppo\"", p.Name())
	}
}

func TestPPOConfigure_Valid(t *testing.T) {
	cfg := PPOConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec:        json.RawMessage(`{"pools":["v_legacy"],"seed":1,"players":[{"chars":[{"name":"赤蝶"}]},{"chars":[{"name":"墨客"}]}]}`),
			MaxActions:      30,
			MaxEpisodeSteps: 360,
			BaseSeed:        42,
		},
		RolloutOpponent:  "F1-D2",
		Gamma:            0.99,
		GAELambda:        0.95,
		Temperature:      1.0,
		MyPlayerStrategy: "alternate",
	}
	bs, _ := json.Marshal(cfg)
	p := &PPOParadigm{}
	if err := p.Configure(string(bs)); err != nil {
		t.Fatalf("Configure: %v", err)
	}
	if p.cfg.RolloutOpponent != "F1-D2" || p.cfg.Gamma != 0.99 {
		t.Errorf("cfg mismatch: RolloutOpponent=%q Gamma=%f", p.cfg.RolloutOpponent, p.cfg.Gamma)
	}
}

func TestPPOConfigure_Errors(t *testing.T) {
	cases := []struct {
		name    string
		cfg     PPOConfig
		wantSub string
	}{
		{
			name:    "missing game_spec",
			cfg:     PPOConfig{BaseActorConfig: gicg_actor.BaseActorConfig{MaxActions: 10, MaxEpisodeSteps: 100}, RolloutOpponent: "self", Gamma: 0.99, GAELambda: 0.95},
			wantSub: "game_spec missing",
		},
		{
			name:    "missing rollout_opponent",
			cfg:     PPOConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}, Gamma: 0.99, GAELambda: 0.95},
			wantSub: "rollout_opponent missing",
		},
		{
			name:    "bad gamma",
			cfg:     PPOConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}, RolloutOpponent: "self", Gamma: 1.5, GAELambda: 0.95},
			wantSub: "gamma=1.5",
		},
		{
			name:    "bad gae_lambda",
			cfg:     PPOConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}, RolloutOpponent: "self", Gamma: 0.99, GAELambda: 0},
			wantSub: "gae_lambda=0",
		},
		{
			name:    "negative temperature",
			cfg:     PPOConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}, RolloutOpponent: "self", Gamma: 0.99, GAELambda: 0.95, Temperature: -0.1},
			wantSub: "temperature",
		},
		{
			name:    "unknown my_player_strategy",
			cfg:     PPOConfig{BaseActorConfig: gicg_actor.BaseActorConfig{GameSpec: json.RawMessage(`{}`), MaxActions: 10, MaxEpisodeSteps: 100}, RolloutOpponent: "self", Gamma: 0.99, GAELambda: 0.95, MyPlayerStrategy: "bogus"},
			wantSub: "unknown my_player_strategy",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := &PPOParadigm{}
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

func TestPPOConfigure_DefaultsApplied(t *testing.T) {
	cfg := PPOConfig{
		BaseActorConfig: gicg_actor.BaseActorConfig{
			GameSpec:        json.RawMessage(`{}`),
			MaxActions:      10,
			MaxEpisodeSteps: 100,
		},
		RolloutOpponent: "random",
		Gamma:           0.99,
		GAELambda:       0.95,
		// MyPlayerStrategy omitted — should default to "alternate"
	}
	bs, _ := json.Marshal(cfg)
	p := &PPOParadigm{}
	if err := p.Configure(string(bs)); err != nil {
		t.Fatalf("Configure: %v", err)
	}
	if p.cfg.MyPlayerStrategy != "alternate" {
		t.Errorf("default MyPlayerStrategy = %q, want alternate", p.cfg.MyPlayerStrategy)
	}
}
