package interp

import (
	"reflect"
	"testing"
)

func skillRefClosure(t *testing.T, src string, env *Env) *Closure {
	t.Helper()
	tokens, err := Tokenize([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	body, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	return &Closure{Params: []string{"ctx"}, Body: body, Env: env}
}

func TestHookSkillReferencesRespectTypesScopesAndAliases(t *testing.T) {
	rt := NewRuntime(nil)
	ref := &SkillRef{ID: 5, Name: "skill", CharName: "char"}
	rt.Skills.ByID[5] = ref
	env := NewEnv(nil)
	env.SetLocal("skill", ref)
	env.SetLocal("number", 5)
	env.SetLocal("lazy", &LazySkillRef{CharName: "char", SkillName: "skill"})
	for _, tc := range []struct {
		src  string
		want []int
	}{
		{`if ctx.skill_index ~= skill then return end`, []int{5}},
		{`local alias = skill
if ctx.skill_index ~= alias then return end`, []int{5}},
		{`local skill = 5
if ctx.skill_index ~= skill then return end`, []int{}},
		{`if ctx.skill_index ~= number then return end`, []int{}},
		{`local cb = function(skill) if ctx.skill_index ~= skill then return end end`, []int{}},
		{`if ctx.value > 0 then local skill = 5 end
if ctx.skill_index ~= skill then return end`, []int{5}},
		{`if ctx.skill_index ~= lazy then return end`, []int{5}},
	} {
		got := rt.hookSkillReferences(skillRefClosure(t, tc.src, env))
		if !reflect.DeepEqual(got, tc.want) {
			t.Fatalf("%s: got %v want %v", tc.src, got, tc.want)
		}
	}
	if got, _ := env.Get("skill"); got != ref {
		t.Fatal("metadata modified closure environment")
	}
}

func TestHookSkillReferencesFollowCapturedHelpers(t *testing.T) {
	rt := NewRuntime(nil)
	env := NewEnv(nil)
	env.SetLocal("skill", &SkillRef{ID: 7})
	helper := skillRefClosure(t, `if ctx.skill_index ~= skill then return end
helper(ctx)`, env)
	env.SetLocal("helper", helper)
	got := rt.hookSkillReferences(skillRefClosure(t, `helper(ctx)`, env))
	if !reflect.DeepEqual(got, []int{7}) {
		t.Fatalf("helper refs: %v", got)
	}
}
