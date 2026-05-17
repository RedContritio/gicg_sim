package interp

import (
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// writePoolFixture writes a manifest + optional cards/<name>.lua and
// characters/<name>/<name>.lua entries under root/pools/<id>/. Tests
// build small synthetic pool trees with this and then assert
// ResolvePool's fold / override / remove behavior on them, instead of
// depending on the live data/pools/ tree.
func writePoolFixture(t *testing.T, root, id, parent string, cards []string, chars []string, cardsRemove, charsRemove []string) {
	t.Helper()
	dir := filepath.Join(root, "pools", id)
	if err := os.MkdirAll(filepath.Join(dir, "cards"), 0o755); err != nil {
		t.Fatalf("mkdir cards: %v", err)
	}
	if err := os.MkdirAll(filepath.Join(dir, "characters"), 0o755); err != nil {
		t.Fatalf("mkdir chars: %v", err)
	}
	manifest := "[version]\nid = \"" + id + "\"\nparent = \"" + parent + "\"\n\n[cards]\nremove = ["
	for i, n := range cardsRemove {
		if i > 0 {
			manifest += ", "
		}
		manifest += "\"" + n + "\""
	}
	manifest += "]\n\n[characters]\nremove = ["
	for i, n := range charsRemove {
		if i > 0 {
			manifest += ", "
		}
		manifest += "\"" + n + "\""
	}
	manifest += "]\n"
	if err := os.WriteFile(filepath.Join(dir, "manifest.toml"), []byte(manifest), 0o644); err != nil {
		t.Fatalf("write manifest: %v", err)
	}
	for _, n := range cards {
		path := filepath.Join(dir, "cards", n+".lua")
		if err := os.WriteFile(path, []byte("-- "+id+":"+n), 0o644); err != nil {
			t.Fatalf("write card %s: %v", n, err)
		}
	}
	for _, n := range chars {
		charDir := filepath.Join(dir, "characters", n)
		if err := os.MkdirAll(charDir, 0o755); err != nil {
			t.Fatalf("mkdir char %s: %v", n, err)
		}
		if err := os.WriteFile(filepath.Join(charDir, n+".lua"), []byte("-- "+id+":"+n), 0o644); err != nil {
			t.Fatalf("write char declare %s: %v", n, err)
		}
	}
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func TestResolvePool_RootOnly(t *testing.T) {
	tmp := t.TempDir()
	writePoolFixture(t, tmp, "root", "", []string{"a", "b"}, []string{"x"}, nil, nil)

	res, err := ResolvePool(tmp, "root")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if got := sortedKeys(res.Cards); len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Errorf("cards = %v, want [a b]", got)
	}
	if got := sortedKeys(res.Chars); len(got) != 1 || got[0] != "x" {
		t.Errorf("chars = %v, want [x]", got)
	}
}

func TestResolvePool_ChildOverridesParentCard(t *testing.T) {
	// Both root and child declare card "shared"; child's path must win.
	tmp := t.TempDir()
	writePoolFixture(t, tmp, "base", "", []string{"shared", "only_in_base"}, nil, nil, nil)
	writePoolFixture(t, tmp, "child", "base", []string{"shared", "only_in_child"}, nil, nil, nil)

	res, err := ResolvePool(tmp, "child")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	wantPath := filepath.Join(tmp, "pools", "child", "cards", "shared.lua")
	if got := res.Cards["shared"]; got != wantPath {
		t.Errorf("shared resolved to %s, want %s (child should win)", got, wantPath)
	}
	if _, ok := res.Cards["only_in_base"]; !ok {
		t.Errorf("only_in_base missing — parent's non-overridden cards should fold through")
	}
	if _, ok := res.Cards["only_in_child"]; !ok {
		t.Errorf("only_in_child missing — child's new cards should be present")
	}
}

func TestResolvePool_RemoveCard(t *testing.T) {
	tmp := t.TempDir()
	writePoolFixture(t, tmp, "base", "", []string{"keep", "drop"}, nil, nil, nil)
	writePoolFixture(t, tmp, "child", "base", nil, nil, []string{"drop"}, nil)

	res, err := ResolvePool(tmp, "child")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if _, ok := res.Cards["drop"]; ok {
		t.Errorf("drop still present despite [cards].remove")
	}
	if _, ok := res.Cards["keep"]; !ok {
		t.Errorf("keep wrongly removed")
	}
}

func TestResolvePool_ChildOverridesParentCharDir(t *testing.T) {
	// Child shipping its own characters/<name>/ replaces the parent's
	// dir wholesale (whole-directory override, not file-level).
	tmp := t.TempDir()
	writePoolFixture(t, tmp, "base", "", nil, []string{"hero"}, nil, nil)
	writePoolFixture(t, tmp, "child", "base", nil, []string{"hero"}, nil, nil)

	res, err := ResolvePool(tmp, "child")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	wantDir := filepath.Join(tmp, "pools", "child", "characters", "hero")
	entry := res.Chars["hero"]
	if entry == nil || entry.Dir != wantDir {
		t.Errorf("hero entry dir = %v, want %s (child should win)", entry, wantDir)
	}
	wantDeclare := filepath.Join(wantDir, "hero.lua")
	if entry != nil && entry.Declare != wantDeclare {
		t.Errorf("hero declare = %s, want %s", entry.Declare, wantDeclare)
	}
}

func TestResolvePool_RemoveChar(t *testing.T) {
	tmp := t.TempDir()
	writePoolFixture(t, tmp, "base", "", nil, []string{"keep_hero", "drop_hero"}, nil, nil)
	writePoolFixture(t, tmp, "child", "base", nil, nil, nil, []string{"drop_hero"})

	res, err := ResolvePool(tmp, "child")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if _, ok := res.Chars["drop_hero"]; ok {
		t.Errorf("drop_hero still present despite [characters].remove")
	}
	if _, ok := res.Chars["keep_hero"]; !ok {
		t.Errorf("keep_hero wrongly removed")
	}
}

func TestResolvePool_CycleRejected(t *testing.T) {
	// a → b → a forms a cycle; resolver must reject.
	tmp := t.TempDir()
	writePoolFixture(t, tmp, "a", "b", nil, nil, nil, nil)
	writePoolFixture(t, tmp, "b", "a", nil, nil, nil, nil)

	if _, err := ResolvePool(tmp, "a"); err == nil {
		t.Errorf("expected cycle error, got nil")
	}
}

func TestResolvePool_MissingManifest(t *testing.T) {
	tmp := t.TempDir()
	if _, err := ResolvePool(tmp, "nonexistent"); err == nil {
		t.Errorf("expected error for nonexistent pool, got nil")
	}
}

func TestResolvePool_ChainOfThree(t *testing.T) {
	// root → mid → leaf. Each layer adds one card; leaf's [cards].remove
	// drops one of mid's. Verifies ordering is root → leaf so child
	// removes win against grandparent's adds.
	tmp := t.TempDir()
	writePoolFixture(t, tmp, "root", "", []string{"r1"}, nil, nil, nil)
	writePoolFixture(t, tmp, "mid", "root", []string{"m1", "m2"}, nil, nil, nil)
	writePoolFixture(t, tmp, "leaf", "mid", []string{"l1"}, nil, []string{"m2"}, nil)

	res, err := ResolvePool(tmp, "leaf")
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	for _, n := range []string{"r1", "m1", "l1"} {
		if _, ok := res.Cards[n]; !ok {
			t.Errorf("%s missing from chain fold", n)
		}
	}
	if _, ok := res.Cards["m2"]; ok {
		t.Errorf("m2 should have been removed by leaf manifest")
	}
}
