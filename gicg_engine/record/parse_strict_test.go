package record

import (
	"encoding/json"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestParseRejectsCorruptDecisionInputs(t *testing.T) {
	input := engine.InputForAction(engine.Action{Kind: engine.ActionSkill})
	b, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	prefix := "round 1:\n  actions:\n    - P0 出战角色 甲 使用技能 乙:\n        input: "
	for _, bad := range []string{
		strings.Replace(string(b), `[0,0,0,0,0,0,0,0]`, `[0]`, 1),
		strings.Replace(string(b), `[0,0,0,0,0,0,0,0]`, `[0,0,0,0,0,0,0,0,0]`, 1),
		strings.Replace(string(b), `[0,0,0,0,0,0,0,0]`, `[-1,0,0,0,0,0,0,0]`, 1),
		strings.Replace(string(b), `"forced":false`, `"forced":null`, 1),
		strings.Replace(string(b), `"forced":false`, `"forced":true`, 1),
		strings.Replace(string(b), `"hand_index":-1`, `"hand_index":0`, 1),
		strings.Replace(string(b), `"has_target":false`, `"has_target":true`, 1),
		strings.Replace(string(b), `"forced":false`, `"forced":false,"forced":true`, 1),
		strings.Replace(string(b), `"forced":false`, `"froced":false`, 1),
		"null", "{}", string(b) + " {}",
	} {
		if _, err := Parse(prefix + bad); err == nil {
			t.Errorf("accepted bad input %s", bad)
		}
	}
	if _, err := Parse(prefix + string(b)); err != nil {
		t.Fatal(err)
	}
}

func TestParseRejectsUnknownAndDuplicateStructure(t *testing.T) {
	for _, src := range []string{
		"round 2:\n", "round 1:\nround 1:\n", "round 1:\nround 3:\n",
		"round 1:\n  actionz:\n    - P0 结束回合:\n",
		"round 1:\n  actions:\n    - P0 未知动作:\n",
		"round 1:\n  actions:\n    - P9 结束回合:\n",
		"round 1:\n胜者: P0\n胜者: P1\n", "胜者: P9\n", "roundz 1:\n",
		"round 1:\n  actions:\n  actions:\n",
		"round 1:\n  state:\n  state:\n",
		"round 1:\n  state:\n    active_chars: [0, null]\n",
		"round 1:\n  state:\n    先手: P0\n    先手: P1\n",
	} {
		if _, err := Parse(src); err == nil {
			t.Errorf("accepted corrupted structure %q", src)
		}
	}
}

func TestParseRejectsMalformedStateLiterals(t *testing.T) {
	for _, field := range []string{
		"手牌: 苹果,香蕉", "手牌: [苹果,,香蕉]", "手牌: [苹果,]",
		"行动点: typo", "手牌: []\n      手牌: []",
		"角色:\n        甲: { 生命: typo }",
		"角色:\n        甲: { 生命: 1, 生命: 2 }",
		"角色:\n        甲: { 生命: 1, 状态: { 生命: 2 } }",
		"角色:\n        甲: { 生命: 1, 状态: { 护盾: nope } }",
		"角色:\n        甲: { 生命: 1, 状态: { 护盾: 2 ] }",
		"角色:\n        甲: { 生命: 1 }\n        甲: { 生命: 2 }",
	} {
		src := "round 1:\n  state:\n    P0:\n      " + field + "\n"
		if _, err := Parse(src); err == nil {
			t.Errorf("accepted broken state %q", field)
		}
	}
}
