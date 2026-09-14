package interp

// F3 契约测试:topo loader 对依赖不可解析的文件 fail-loud。
//
// 历史:topoSortWithMeta 对 depends 无 provider 的文件做静默排除
// (excluded 标记 + 零告警),以逸待劳 因引用已删除的 "ap" counter
// 整文件被排除,死卡多 session 无人察觉。本文件凝固新契约:
//   1. 直接缺失依赖 → error,消息含文件路径 + 缺失符号名
//   2. 传递性破损(依赖的 provider 自身破损)→ 两个文件都列入 error
//   3. 集合内 / preExisting 可解析 → 正常拓扑序
//   4. 重复引用同一缺失符号只报一次
//   5. 循环依赖仍报 circular dependency(原契约不回退)
//
// 测试文件是临时目录合成 DSL,不污染生产 data/。

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeDSL 在 dir 下写一个合成 DSL 文件并返回路径。文件名需全测试
// 进程内唯一(dslCache 按路径缓存且永不失效,t.TempDir 保证唯一)。
func writeDSL(t *testing.T, dir, name, src string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(src), 0o644); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
	return p
}

func TestTopoFailLoud_MissingDep(t *testing.T) {
	dir := t.TempDir()
	bad := writeDSL(t, dir, "bad_card.lua", `local c = get_counter("不存在的计数器")`)

	_, err := topoSortWithMeta([]string{bad}, nil)
	if err == nil {
		t.Fatal("want error for unresolvable dep, got nil (silent exclusion regressed)")
	}
	msg := err.Error()
	if !strings.Contains(msg, bad) {
		t.Errorf("error %q does not name the broken file %q", msg, bad)
	}
	if !strings.Contains(msg, "counter:不存在的计数器") {
		t.Errorf("error %q does not name the missing dep counter:不存在的计数器", msg)
	}
}

func TestTopoFailLoud_TransitiveBrokenProvider(t *testing.T) {
	dir := t.TempDir()
	// A 声明 counter:甲 但自身依赖缺失符号;B 依赖 counter:甲。
	// 旧实现:A、B 连锁静默排除。新契约:两个文件都列入 error。
	fa := writeDSL(t, dir, "a_provider.lua",
		`local x = get_counter("缺失符号")
local 甲 = declare_counter("甲", Scope.PerPlayer, 0)`)
	fb := writeDSL(t, dir, "b_consumer.lua", `local 甲 = get_counter("甲")`)

	_, err := topoSortWithMeta([]string{fa, fb}, nil)
	if err == nil {
		t.Fatal("want error for transitively broken set, got nil")
	}
	msg := err.Error()
	if !strings.Contains(msg, fa) || !strings.Contains(msg, "counter:缺失符号") {
		t.Errorf("error %q does not report root breakage %s (counter:缺失符号)", msg, fa)
	}
	if !strings.Contains(msg, fb) || !strings.Contains(msg, "counter:甲") {
		t.Errorf("error %q does not report transitive breakage %s (counter:甲)", msg, fb)
	}
}

func TestTopoFailLoud_DuplicateDepReportedOnce(t *testing.T) {
	dir := t.TempDir()
	bad := writeDSL(t, dir, "dup_dep.lua",
		`local a = get_counter("重复缺失")
local b = get_counter("重复缺失")
local c = get_counter("重复缺失")`)

	_, err := topoSortWithMeta([]string{bad}, nil)
	if err == nil {
		t.Fatal("want error, got nil")
	}
	if n := strings.Count(err.Error(), "counter:重复缺失"); n != 1 {
		t.Errorf("missing dep reported %d times, want 1:\n%s", n, err)
	}
}

func TestTopo_ResolvesWithinSetAndPreExisting(t *testing.T) {
	dir := t.TempDir()
	fa := writeDSL(t, dir, "provider.lua", `local 乙 = declare_counter("乙", Scope.PerPlayer, 0)`)
	fb := writeDSL(t, dir, "consumer.lua",
		`local 乙 = get_counter("乙")
local sys = get_counter("系统计数器")`)

	// consumer 先列,依赖集合内 provider + preExisting 系统符号。
	sorted, err := topoSortWithMeta([]string{fb, fa}, []string{"counter:系统计数器"})
	if err != nil {
		t.Fatalf("resolvable set must load, got: %v", err)
	}
	if len(sorted) != 2 {
		t.Fatalf("sorted len = %d, want 2", len(sorted))
	}
	if sorted[0].path != fa || sorted[1].path != fb {
		t.Errorf("topo order = [%s, %s], want provider before consumer", sorted[0].path, sorted[1].path)
	}
}

func TestTopo_CycleStillDetected(t *testing.T) {
	dir := t.TempDir()
	fa := writeDSL(t, dir, "cycle_a.lua",
		`local 丁 = get_counter("丁")
local 丙 = declare_counter("丙", Scope.PerPlayer, 0)`)
	fb := writeDSL(t, dir, "cycle_b.lua",
		`local 丙 = get_counter("丙")
local 丁 = declare_counter("丁", Scope.PerPlayer, 0)`)

	_, err := topoSortWithMeta([]string{fa, fb}, nil)
	if err == nil {
		t.Fatal("want circular dependency error, got nil")
	}
	if !strings.Contains(err.Error(), "circular dependency") {
		t.Errorf("error %q is not the circular-dependency form", err)
	}
}

// LoadFilesWithDeps 是 topo 的公开入口(production: factory.NewGame),
// 错误必须原样传播而非被吞。
func TestLoadFilesWithDeps_PropagatesTopoError(t *testing.T) {
	dir := t.TempDir()
	bad := writeDSL(t, dir, "entry_bad.lua", `local c = get_counter("入口缺失")`)

	// 错误在 topoSortWithMeta 内、任何文件执行前抛出,nil-Game Runtime 足够。
	rt := NewRuntime(nil)
	err := rt.LoadFilesWithDeps([]string{bad})
	if err == nil {
		t.Fatal("want error from LoadFilesWithDeps, got nil")
	}
	if !strings.Contains(err.Error(), "counter:入口缺失") {
		t.Errorf("error %q lost the missing-dep detail", err)
	}
}
