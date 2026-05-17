package tests

// 契约矩阵测试:filterTalentCardsForSlotUniqueness 的四种 slot-count 情形。
//
// 旧测试只覆盖 k=1(TestTalent_*)和 k=2(TestMirrorMatch_Talent_*),
// 缺 k=0(双方都没 X,应 drop)和 k=1 非对称侧(只 P1 有 X)。
// 此测试矩阵把 4 种组合都打一遍,用 cards 加载名单断言。

import (
	"strings"
	"testing"

	"gicg_mono/gicg_engine/interp"
)

// hasSuffix reports whether any path in filtered ends with name (最末
// 路径元素匹配)。
func hasSuffix(filtered []string, name string) bool {
	for _, p := range filtered {
		if strings.HasSuffix(p, name) {
			return true
		}
	}
	return false
}

// runFilter 构造 shared DSL 路径并跑 filter。复用 helpers_setup_test.go
// 里已经定义的 collectDSLPaths / splitDSLPaths / filterTalentCards...
func runFilter(team0, team1 []string) []string {
	teams := [2][]string{team0, team1}
	pool, all := collectDSLPaths(teams)
	_, shared := interp.SplitCharFiles(pool.Chars, all)
	return filterTalentCardsForSlotUniqueness(shared, teams)
}

// K=0: 双方都没有 X → X 的 talent 必须被 drop。
func TestFilterTalent_MatrixK0_DropsOrphanTalent(t *testing.T) {
	filtered := runFilter([]string{"赤蝶"}, []string{"墨客"})

	// 应保留:赤蝶 & 墨客 的 talent
	mustKeep := []string{"蝶鳞.lua", "守正.lua"}
	// 应 drop:其他 char 的 talent
	mustDrop := []string{"刺刺猫爪.lua", "发现静电.lua", "星愿.lua"}

	for _, name := range mustKeep {
		if !hasSuffix(filtered, name) {
			t.Errorf("k0 case: %s should be kept (team has required char), got dropped", name)
		}
	}
	for _, name := range mustDrop {
		if hasSuffix(filtered, name) {
			t.Errorf("k0 case: %s should be dropped (neither team has required char), got kept", name)
		}
	}
}

// K=1 P0 side: owner 在 P0 team,keep。
func TestFilterTalent_MatrixK1_P0Side(t *testing.T) {
	filtered := runFilter([]string{"赤蝶"}, []string{"墨客"})
	if !hasSuffix(filtered, "蝶鳞.lua") {
		t.Errorf("蝶鳞 should be kept when P0=赤蝶")
	}
}

// K=1 P1 side: owner 只在 P1 team,keep(对称测试,确保 filter 不偏袒
// 某一侧)。
func TestFilterTalent_MatrixK1_P1Side(t *testing.T) {
	filtered := runFilter([]string{"墨客"}, []string{"赤蝶"})
	if !hasSuffix(filtered, "蝶鳞.lua") {
		t.Errorf("蝶鳞 should be kept when P1=赤蝶 (filter must be symmetric)")
	}
	if !hasSuffix(filtered, "守正.lua") {
		t.Errorf("守正 should be kept when P0=墨客")
	}
}

// K=2 mirror: 双方都有 char,keep。
func TestFilterTalent_MatrixK2_BothSides(t *testing.T) {
	filtered := runFilter([]string{"赤蝶"}, []string{"赤蝶"})
	if !hasSuffix(filtered, "蝶鳞.lua") {
		t.Errorf("蝶鳞 should be kept in mirror k=2")
	}
}
