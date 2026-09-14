package record

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestConfigRoundTripAndRejectInvalid(t *testing.T) {
	g := &engine.Game{BaseSeed: -9223372036854775807, MaxRounds: 12, FixDice: []int{0, 1, 2, 0, 0, 0, 0, 5}}
	var b strings.Builder
	writeConfig(&b, g)
	rec, err := Parse(b.String() + "胜者: 平局\n")
	if err != nil {
		t.Fatal(err)
	}
	if rec.Config.BaseSeed != g.BaseSeed || rec.Config.MaxRounds != 12 || rec.Config.FixDice[7] != 5 || rec.Winner != 2 {
		t.Fatalf("lost config or draw winner: %+v", rec)
	}
	for _, src := range []string{
		`config: {"random_protocol":"legacy"}`,
		`config: {"random_protocol":"pcg-v1","fix_dice":[1]}`,
		`config: {"random_protocol":"pcg-v1","max_rounds":-1}`,
		`config: {"random_protocol":"pcg-v1","typo":1}`,
		b.String() + b.String(),
	} {
		if _, err := Parse(src); err == nil {
			t.Errorf("accepted invalid config %s", src)
		}
	}
}

func TestActionInputSelectsExactPaymentAndTarget(t *testing.T) {
	// Test serialization independently of the legal-action generator.
	src := `round 1:
  actions:
    - P0 调和卡牌 苹果:
        input: {"payment":[0,0,0,0,0,0,0,0],"hand_index":2,"forced":false,"has_target":false,"target_player":0,"target_char":0,"tune_source_color":4}
    - P1 出战角色 甲 使用卡牌 药 → P1 乙:
        input: {"payment":[0,0,1,0,0,0,0,2],"hand_index":3,"forced":false,"has_target":true,"target_player":1,"target_char":1,"tune_source_color":0}
`
	r, err := Parse(src)
	if err != nil {
		t.Fatal(err)
	}
	a := r.Rounds[0].Actions
	if len(a) != 2 || a[0].Kind != ActTune || a[0].Input.HandIndex != 2 || a[0].Input.TuneSourceColor != 4 {
		t.Fatalf("lost tune choice: %+v", a)
	}
	if a[1].Input.DicePayment[7] != 2 || !a[1].Input.HasTarget || a[1].Input.TargetChar != 1 {
		t.Fatalf("lost payment or target: %+v", a[1])
	}
}
