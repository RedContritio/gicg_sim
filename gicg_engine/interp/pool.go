package interp

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// PoolCharEntry holds the pre-walked file list for one char's pool entry.
// Computed once during ResolvePool and cached, so initGame /
// helpers_test don't re-ReadDir the char directory on every game
// construction. Skills is sorted (filepath.Walk visits in lexical order
// per dir entry) so the load sequence stays deterministic across
// processes. See ADR-0011's "脱耦磁盘" concern.
type PoolCharEntry struct {
	Dir     string   // absolute path to characters/<name>/
	Declare string   // <Dir>/<name>.lua — the declare_char file
	Skills  []string // <Dir>/<name>_*.lua — sorted absolute paths
}

// PoolResolution lists the DSL files a fully-folded pool exposes after
// applying its parent chain plus its own overrides + removes.
//
//   - Cards is keyed by declared card name (filename minus ".lua") and
//     points to the absolute file path that BuildDeck / collectDSLPaths
//     should load. Child-pool same-name overrides win.
//   - Chars is keyed by char name (= directory name); each entry holds
//     the pre-walked declare + skill paths so callers don't re-stat
//     the dir per game. Override is whole-directory: a child pool
//     that ships its own characters/<name>/ replaces the parent's
//     entry wholesale.
type PoolResolution struct {
	Cards map[string]string
	Chars map[string]*PoolCharEntry
}

// ResolvePoolUnion folds the union of multiple sibling pools, applied
// in list order so a later pool's same-name override wins. Used by
// initGame and tests when a single GicgEnv config selects more than
// one pool (e.g. v_legacy + test_basic for legacy replays that span
// the prod/test split). Empty input is rejected so callers don't
// silently get a no-op pool. Each ResolvePool call hits the
// per-pool cache, so repeated unions are O(1) after warmup.
func ResolvePoolUnion(dataDir string, poolIDs []string) (*PoolResolution, error) {
	if len(poolIDs) == 0 {
		return nil, fmt.Errorf("ResolvePoolUnion: poolIDs is empty")
	}
	out := &PoolResolution{
		Cards: map[string]string{},
		Chars: map[string]*PoolCharEntry{},
	}
	for _, pid := range poolIDs {
		res, err := ResolvePool(dataDir, pid)
		if err != nil {
			return nil, err
		}
		for k, v := range res.Cards {
			out.Cards[k] = v
		}
		for k, v := range res.Chars {
			out.Chars[k] = v
		}
	}
	return out, nil
}

// SplitCharFiles separates char-specific files (those located under
// one of the resolved char dirs) from shared files (cards). Match is
// by absolute-path prefix against each entry's Dir, so it works across
// pool layouts. Returns char_name → file list, plus the shared list.
func SplitCharFiles(chars map[string]*PoolCharEntry, all []string) (map[string][]string, []string) {
	charFiles := map[string][]string{}
	var shared []string
	prefixes := make(map[string]string, len(chars))
	for name, entry := range chars {
		prefixes[name] = entry.Dir + string(filepath.Separator)
	}
	for _, p := range all {
		matched := false
		for name, prefix := range prefixes {
			if strings.HasPrefix(p, prefix) {
				charFiles[name] = append(charFiles[name], p)
				matched = true
				break
			}
		}
		if !matched {
			shared = append(shared, p)
		}
	}
	return charFiles, shared
}

var (
	// poolCacheMu guards poolCache. ResolvePool first-callers fill the
	// cache; subsequent callers skip the filesystem walk entirely.
	// Process-global by design — same rationale as dslCache: training
	// runs hundreds of games per worker and we want the resolution to
	// survive the GameNew → GameFree cycle so deck construction never
	// touches disk after warmup. Cache is never invalidated during a
	// process lifetime; mid-run pool / manifest edits will not be
	// picked up (matches dslCache semantics — see loader.go).
	poolCacheMu sync.RWMutex
	poolCache   = map[string]*PoolResolution{}
)

// ResolvePool walks the parent chain rooted at poolID under
// dataDir/pools/, folds cards/chars from the root pool down to the
// requested pool, and applies each manifest's [cards].remove /
// [characters].remove. Returns the fully-resolved set ready for
// initGame to consume. Result is cached process-globally so repeated
// calls with the same (dataDir, poolID) are O(1) lookups.
//
// poolID must name a directory at data/pools/<poolID>/ containing a
// manifest.toml. Cycles are detected by tracking visited IDs and
// rejected with an error.
func ResolvePool(dataDir, poolID string) (*PoolResolution, error) {
	key := dataDir + "\x00" + poolID
	poolCacheMu.RLock()
	if cached, ok := poolCache[key]; ok {
		poolCacheMu.RUnlock()
		return cached, nil
	}
	poolCacheMu.RUnlock()

	chain, err := walkParentChain(dataDir, poolID)
	if err != nil {
		return nil, err
	}

	res := &PoolResolution{
		Cards: map[string]string{},
		Chars: map[string]*PoolCharEntry{},
	}
	// Fold root → leaf so child overrides win on duplicate names.
	for _, m := range chain {
		poolDir := filepath.Join(dataDir, "pools", m.ID)
		cards, err := collectPoolCards(filepath.Join(poolDir, "cards"))
		if err != nil {
			return nil, fmt.Errorf("pool %q: collect cards: %w", m.ID, err)
		}
		for name, path := range cards {
			res.Cards[name] = path
		}
		chars, err := collectPoolChars(filepath.Join(poolDir, "characters"))
		if err != nil {
			return nil, fmt.Errorf("pool %q: collect chars: %w", m.ID, err)
		}
		for name, entry := range chars {
			res.Chars[name] = entry
		}
		for _, n := range m.CardsRemove {
			delete(res.Cards, n)
		}
		for _, n := range m.CharsRemove {
			delete(res.Chars, n)
		}
	}

	poolCacheMu.Lock()
	if existing, ok := poolCache[key]; ok {
		poolCacheMu.Unlock()
		return existing, nil
	}
	poolCache[key] = res
	poolCacheMu.Unlock()
	return res, nil
}

// walkParentChain resolves poolID's manifest, then its parent's, and
// so on, returning the chain from root to leaf. Errors on cycles or
// missing manifests.
func walkParentChain(dataDir, poolID string) ([]*Manifest, error) {
	visited := map[string]bool{}
	var chain []*Manifest
	cur := poolID
	for cur != "" {
		if visited[cur] {
			return nil, fmt.Errorf("pool %q: parent chain has a cycle", poolID)
		}
		visited[cur] = true
		m, err := parseManifest(filepath.Join(dataDir, "pools", cur, "manifest.toml"))
		if err != nil {
			return nil, err
		}
		chain = append(chain, m)
		cur = m.Parent
	}
	// Reverse so chain[0] is the root and chain[len-1] is the leaf.
	for i, j := 0, len(chain)-1; i < j; i, j = i+1, j-1 {
		chain[i], chain[j] = chain[j], chain[i]
	}
	return chain, nil
}

// collectPoolCards walks a pool's cards/ tree and returns name →
// absolute path. Card name is the filename without ".lua".
// Subdirectories are traversed (e.g. cards/L3/铁剑.lua).
func collectPoolCards(cardsDir string) (map[string]string, error) {
	out := map[string]string{}
	if _, err := os.Stat(cardsDir); os.IsNotExist(err) {
		return out, nil // missing cards/ dir is fine — pool may only ship chars
	}
	err := filepath.Walk(cardsDir, func(p string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if info.IsDir() || !strings.HasSuffix(p, ".lua") {
			return nil
		}
		base := strings.TrimSuffix(filepath.Base(p), ".lua")
		abs, err := filepath.Abs(p)
		if err != nil {
			return err
		}
		out[base] = abs
		return nil
	})
	return out, err
}

// collectPoolChars lists a pool's characters/<name>/ directories and
// returns name → PoolCharEntry with declare + skill paths pre-walked. The
// declare file (<name>.lua) is required; chars without it are skipped
// — they couldn't be loaded by initGame anyway. Skills are sorted so
// load order stays deterministic.
func collectPoolChars(charsDir string) (map[string]*PoolCharEntry, error) {
	out := map[string]*PoolCharEntry{}
	if _, err := os.Stat(charsDir); os.IsNotExist(err) {
		return out, nil
	}
	dirs, err := os.ReadDir(charsDir)
	if err != nil {
		return nil, err
	}
	for _, d := range dirs {
		if !d.IsDir() {
			continue
		}
		name := d.Name()
		dirAbs, err := filepath.Abs(filepath.Join(charsDir, name))
		if err != nil {
			return nil, err
		}
		entries, err := os.ReadDir(dirAbs)
		if err != nil {
			return nil, fmt.Errorf("char %q: read dir: %w", name, err)
		}
		entry := &PoolCharEntry{Dir: dirAbs}
		declareName := name + ".lua"
		for _, e := range entries {
			if e.IsDir() || !strings.HasSuffix(e.Name(), ".lua") {
				continue
			}
			full := filepath.Join(dirAbs, e.Name())
			if e.Name() == declareName {
				entry.Declare = full
			} else {
				entry.Skills = append(entry.Skills, full)
			}
		}
		if entry.Declare == "" {
			// Char dir without a <name>.lua declare is not loadable —
			// skip silently rather than break ResolvePool for unrelated
			// pools that happen to share the parent.
			continue
		}
		sort.Strings(entry.Skills)
		out[name] = entry
	}
	return out, nil
}

// Manifest parsing lives in manifest.go.
