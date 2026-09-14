package record

import (
	"encoding/json"
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestBuffTargetInputRoundTrip(t *testing.T) {
	for _, position := range []int{0, 7} {
		a := engine.Action{Kind: engine.ActionCard, PlayerIdx: 0, Index: 1,
			HasBuffTarget: true, TargetPlayer: 1, TargetChar: -1, TargetBuff: position}
		a.DicePayment[7] = 2
		want := engine.InputForAction(a)
		payload, err := json.Marshal(want)
		if err != nil {
			t.Fatal(err)
		}
		text := fmt.Sprintf("round 1:\n  actions:\n    - P0 出战角色 凯亚 使用卡牌 送你一程:\n        input: %s\n", payload)
		rec, err := Parse(text)
		if err != nil {
			t.Fatal(err)
		}
		if got := rec.Rounds[0].Actions[0].Input; got == nil || *got != want {
			t.Fatal("record lost precise summon selection/payment")
		}
	}
}

func TestSupportTargetInputRoundTrip(t *testing.T) {
	for _, slot := range []int{0, 3} {
		for _, player := range []int{0, 1} {
			a := engine.Action{Kind: engine.ActionCard, PlayerIdx: player, Index: 1,
				HasSupportTarget: true, TargetPlayer: player, TargetChar: -1, TargetSupport: slot}
			a.DicePayment[7] = 3
			want := engine.InputForAction(a)
			payload, err := json.Marshal(want)
			if err != nil {
				t.Fatal(err)
			}
			text := fmt.Sprintf("round 1:\n  actions:\n    - P%d 出战角色 凯亚 使用卡牌 派蒙:\n        input: %s\n", player, payload)
			rec, err := Parse(text)
			if err != nil {
				t.Fatal(err)
			}
			if got := rec.Rounds[0].Actions[0].Input; got == nil || *got != want {
				t.Fatal("record lost support replacement target/payment")
			}
		}
	}
}
