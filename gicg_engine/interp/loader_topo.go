package interp

import (
	"fmt"
	"regexp"
	"strings"
)

// Dependency resolution for DSL file loading. Copied from lua/state.go,
// pure Go. The file loader (loader.go) consumes topoSortWithMeta output.
// 依赖扫描 regex 跑在原始 src 上(comment-blind):注释中的
// get_counter("X") 字面文本同样计入依赖。

type sortedFile struct {
	path    string
	charDep string
}

func topoSortWithMeta(paths []string, preExisting []string) ([]sortedFile, error) {
	type fileInfo struct {
		path     string
		provides []string
		depends  []string
		charDep  string
	}

	declareRe := regexp.MustCompile(`declare_counter\(\s*"([^"]+)"`)
	declareCharRe := regexp.MustCompile(`declare_char\(\s*"([^"]+)"`)
	declareSkillRe := regexp.MustCompile(`declare_skill\([^,]+,\s*"([^"]+)"`)
	declareCardRe := regexp.MustCompile(`declare_card\(\s*"([^"]+)"`)
	getRe := regexp.MustCompile(`get_counter\(\s*"([^"]+)"`)
	getCharRe := regexp.MustCompile(`get_char\(\s*"([^"]+)"`)
	getSkillRe := regexp.MustCompile(`get_skill\([^,]+,\s*"([^"]+)"`)
	getCardRe := regexp.MustCompile(`get_card\(\s*"([^"]+)"`)

	files := make([]fileInfo, len(paths))
	for i, p := range paths {
		// Use cached bytes when available so the topo scan sees the
		// same snapshot the parser will later execute (and so we
		// don't re-read every file on every GameNew).
		pf, err := loadParsedDSL(p)
		if err != nil {
			return nil, fmt.Errorf("read %s: %w", p, err)
		}
		src := string(pf.src)
		fi := fileInfo{path: p}
		for _, m := range declareRe.FindAllStringSubmatch(src, -1) {
			fi.provides = append(fi.provides, "counter:"+m[1])
		}
		for _, m := range declareCharRe.FindAllStringSubmatch(src, -1) {
			fi.provides = append(fi.provides, "char:"+m[1])
		}
		for _, m := range declareSkillRe.FindAllStringSubmatch(src, -1) {
			fi.provides = append(fi.provides, "skill:"+m[1])
		}
		for _, m := range declareCardRe.FindAllStringSubmatch(src, -1) {
			fi.provides = append(fi.provides, "card:"+m[1])
		}
		for _, m := range getRe.FindAllStringSubmatch(src, -1) {
			fi.depends = append(fi.depends, "counter:"+m[1])
		}
		for _, m := range getCharRe.FindAllStringSubmatch(src, -1) {
			fi.depends = append(fi.depends, "char:"+m[1])
			if fi.charDep == "" {
				fi.charDep = m[1]
			}
		}
		for _, m := range getSkillRe.FindAllStringSubmatch(src, -1) {
			fi.depends = append(fi.depends, "skill:"+m[1])
		}
		for _, m := range getCardRe.FindAllStringSubmatch(src, -1) {
			fi.depends = append(fi.depends, "card:"+m[1])
		}
		files[i] = fi
	}

	provider := map[string]int{}
	for _, sym := range preExisting {
		provider[sym] = -1
	}
	for i, fi := range files {
		for _, sym := range fi.provides {
			provider[sym] = i
		}
	}

	// Fail-loud dependency check (F3). Files with unresolvable deps were
	// previously excluded from the load with zero warning, so broken DSL
	// vanished from games silently — the 以逸待劳 dead-card incident: its
	// "ap" counter dep outlived the AP-system removal and the card never
	// loaded again, unnoticed across sessions. A file whose deps cannot
	// resolve — directly, or because a provider file is itself broken —
	// is now a load error naming each file and dep. Declarative
	// optionality lives upstream of the topo (the requires_char
	// pre-filter in factory.FilterTalentCardsForSlotUniqueness), never
	// here: every file handed to the topo MUST load.
	n := len(files)
	broken := make([]bool, n)
	reasons := make([][]string, n)
	changed := true
	for changed {
		changed = false
		for i, fi := range files {
			if broken[i] {
				continue
			}
			seenSym := map[string]bool{}
			for _, sym := range fi.depends {
				if seenSym[sym] {
					continue
				}
				seenSym[sym] = true
				pIdx, inProvider := provider[sym]
				if !inProvider {
					reasons[i] = append(reasons[i], "missing "+sym)
				} else if pIdx >= 0 && broken[pIdx] {
					reasons[i] = append(reasons[i], sym+" comes from broken file "+files[pIdx].path)
				} else {
					continue
				}
				broken[i] = true
				changed = true
			}
		}
	}
	var failed []string
	for i := range files {
		if broken[i] {
			failed = append(failed, files[i].path+": "+strings.Join(reasons[i], "; "))
		}
	}
	if len(failed) > 0 {
		return nil, fmt.Errorf(
			"DSL load: %d file(s) have unresolvable dependencies:\n  %s\ndeclare the missing symbol, fix the reference, or remove the file from the pool",
			len(failed), strings.Join(failed, "\n  "))
	}

	inDeg := make([]int, n)
	edges := make([][]int, n)
	for i, fi := range files {
		seen := map[int]bool{}
		for _, sym := range fi.depends {
			j := provider[sym]
			if j >= 0 && j != i && !seen[j] {
				seen[j] = true
				edges[j] = append(edges[j], i)
				inDeg[i]++
			}
		}
	}

	queue := make([]int, 0, n)
	for i := 0; i < n; i++ {
		if inDeg[i] == 0 {
			queue = append(queue, i)
		}
	}

	sorted := make([]sortedFile, 0, n)
	for head := 0; head < len(queue); head++ {
		idx := queue[head]
		sorted = append(sorted, sortedFile{path: files[idx].path, charDep: files[idx].charDep})
		for _, dep := range edges[idx] {
			inDeg[dep]--
			if inDeg[dep] == 0 {
				queue = append(queue, dep)
			}
		}
	}

	if len(sorted) != n {
		var cycle []string
		for i := 0; i < n; i++ {
			if inDeg[i] > 0 {
				cycle = append(cycle, files[i].path)
			}
		}
		return nil, fmt.Errorf("circular dependency: %v", cycle)
	}

	return sorted, nil
}
