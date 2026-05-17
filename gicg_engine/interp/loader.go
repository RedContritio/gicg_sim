package interp

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// LoadFilesWithDeps loads DSL files in dependency order with sandboxed
// environments. Files that depend on a specific char are loaded under that
// char's slot context — but only when there's exactly one slot bound to
// that name. Mirror matches must instead use LoadCharFilesPerBinding so
// each binding gets its own slot-specific load (each closure captures the
// per-slot CharProxy).
func (rt *Runtime) LoadFilesWithDeps(paths []string, preExisting ...string) error {
	sortedFiles, err := topoSortWithMeta(paths, preExisting)
	if err != nil {
		return err
	}
	for _, sf := range sortedFiles {
		// Always reset before each file so a previous iteration's charDep-
		// derived slot can't leak into this one (previously the `else`
		// branch only fired for files without charDep — mirror-match files
		// whose charDep didn't resolve uniquely kept stale slot context).
		rt.CurrentOwnerPlayer = -1
		rt.CurrentOwnerChar = -1
		if sf.charDep != "" {
			pi, ci := rt.findUniqueSlotByName(sf.charDep)
			if pi >= 0 {
				rt.CurrentOwnerPlayer = pi
				rt.CurrentOwnerChar = ci
			}
		}
		if err := rt.ExecFileSandboxed(sf.path); err != nil {
			return fmt.Errorf("load %s: %w", sf.path, err)
		}
	}
	rt.CurrentOwnerPlayer = -1
	rt.CurrentOwnerChar = -1
	return nil
}

// findUniqueSlotByName returns the (player, char) slot for a given char name
// if exactly one slot has that name. Returns (-1, -1) otherwise — used by the
// global topo loader to skip auto-setting owner context in mirror matches,
// where there is no single canonical owner.
func (rt *Runtime) findUniqueSlotByName(name string) (int, int) {
	pi, ci := -1, -1
	count := 0
	for p := 0; p < 2; p++ {
		for c := 0; c < MaxChars; c++ {
			slot := rt.Chars.BySlot[p][c]
			if slot != nil && slot.Name == name {
				pi, ci = p, c
				count++
			}
		}
	}
	if count != 1 {
		return -1, -1
	}
	return pi, ci
}

// LoadCharFilesPerBinding loads a list of char-specific DSL files under a
// fixed owner context (the binding's slot), bypassing the global topo
// loader's auto-set logic. Topo deps are computed within the file subset.
// Caller passes the slot's (playerIdx, charIdx) explicitly so per-binding
// loads attribute closures and slot Skills to the correct player.
func (rt *Runtime) LoadCharFilesPerBinding(paths []string, playerIdx, charIdx int, preExisting ...string) error {
	sortedFiles, err := topoSortWithMeta(paths, preExisting)
	if err != nil {
		return err
	}
	prevP, prevC := rt.CurrentOwnerPlayer, rt.CurrentOwnerChar
	rt.CurrentOwnerPlayer = playerIdx
	rt.CurrentOwnerChar = charIdx
	defer func() {
		rt.CurrentOwnerPlayer = prevP
		rt.CurrentOwnerChar = prevC
	}()
	for _, sf := range sortedFiles {
		if err := rt.ExecFileSandboxed(sf.path); err != nil {
			return fmt.Errorf("load %s: %w", sf.path, err)
		}
	}
	return nil
}

// parsedDSLFile is the cached in-memory form of a DSL file. The
// fields it holds are all effectively immutable after caching:
//
//   - src     — the raw file bytes as read at cache-fill time
//   - chunk   — AST; ExecChunk walks it without mutation
//   - bodies  — token-pair slice per hook; readers take subslices
//     but never append or mutate entries
//
// Sharing one parsedDSLFile across runtimes / goroutines is safe
// for concurrent reads. topoSortWithMeta uses .src to scan for
// declare_* / get_* dependencies without re-reading from disk,
// which keeps the full DSL load pipeline (parse + topo) on a
// single atomic snapshot of the file tree.
type parsedDSLFile struct {
	src    []byte
	chunk  *Chunk
	bodies [][]engine.TokenPair
}

var (
	// dslCache maps absolute-or-as-passed DSL paths to their
	// cached parsed form. First read for a given path reads +
	// tokenizes + parses the file and inserts; subsequent lookups
	// skip all three steps and also reuse the raw src for topo
	// scanning.
	//
	// Intentionally process-global: most training setups launch
	// many Runtimes (one per env clone, one per worker) over the
	// same data/ tree, and we want the parsed AST to survive
	// Runtime lifecycles so later games don't re-parse. Cache is
	// never invalidated during a process lifetime — mid-run DSL
	// edits will NOT be picked up (by design: this avoids the
	// "edit an active buff file mid-training and watch a worker
	// crash on partially-written content" failure mode seen on
	// 2026-04-19 during the #152 fix).
	dslCacheMu sync.RWMutex
	dslCache   = map[string]*parsedDSLFile{}
)

// loadParsedDSL returns the cached parsed form for path, parsing
// from disk on first access. Safe for concurrent calls.
func loadParsedDSL(path string) (*parsedDSLFile, error) {
	dslCacheMu.RLock()
	if pf, ok := dslCache[path]; ok {
		dslCacheMu.RUnlock()
		return pf, nil
	}
	dslCacheMu.RUnlock()

	src, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	bodies := engine.ExtractHookBodies(string(src))
	tokens, err := Tokenize(src)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	chunk, err := Parse(tokens)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}

	pf := &parsedDSLFile{src: src, chunk: chunk, bodies: bodies}
	dslCacheMu.Lock()
	// Double-check: another goroutine may have inserted between our
	// RUnlock and this Lock. First-writer-wins semantics either way.
	if existing, ok := dslCache[path]; ok {
		dslCacheMu.Unlock()
		return existing, nil
	}
	dslCache[path] = pf
	dslCacheMu.Unlock()
	return pf, nil
}

// PreloadDSLFiles warms the DSL parse cache for a batch of paths.
// Intended to be called once at process startup (e.g. by the
// training launcher before any GameNew) so the first game creation
// and subsequent clones don't race each other on the parser and
// don't observe partially-written files from a concurrent editor.
// Idempotent: calling with paths already cached is a no-op per path.
func PreloadDSLFiles(paths []string) error {
	for _, p := range paths {
		if _, err := loadParsedDSL(p); err != nil {
			return err
		}
	}
	return nil
}

// ExecFileSandboxed parses (or fetches cached AST) and executes a
// DSL file in a sandboxed env. See dslCache for the caching policy.
func (rt *Runtime) ExecFileSandboxed(path string) error {
	pf, err := loadParsedDSL(path)
	if err != nil {
		return err
	}

	// Hook bodies are consumed by registerHook calls during chunk
	// execution. The backing slice belongs to the cache entry and
	// is never mutated — assignment advances rt.PendingTokens by
	// reslicing only, so concurrent runtimes can all share it.
	rt.PendingTokens = pf.bodies

	// Track which file is being executed so registerHook can stamp the
	// resulting Hook entries with their source + per-file index. Reset
	// the per-file hook counter so each file load starts at #0.
	prevSource := rt.CurrentSourceFile
	prevIdx := rt.CurrentSourceHookIdx
	prevTalent := rt.CurrentFileTalentOwner
	prevCharOwner := rt.CurrentFileCharOwner
	rt.CurrentSourceFile = strings.TrimSuffix(filepath.Base(path), ".lua")
	rt.CurrentSourceHookIdx = 0
	rt.CurrentFileTalentOwner = ""
	rt.CurrentFileCharOwner = ""

	// Execute in sandboxed env (child of global, writes stay local)
	env := NewEnv(rt.Interp.Global)
	err = rt.Interp.ExecChunk(rt, pf.chunk, env)

	rt.PendingTokens = nil
	rt.CurrentSourceFile = prevSource
	rt.CurrentSourceHookIdx = prevIdx
	rt.CurrentFileTalentOwner = prevTalent
	rt.CurrentFileCharOwner = prevCharOwner
	return err
}

// PendingTokens for hook token emission (observation layer).
// Set before file execution, consumed by hook registration.
var _ = 0 // placeholder — PendingTokens is stored on Runtime

// Dependency resolution (sortedFile + topoSortWithMeta) lives in
// loader_topo.go.
