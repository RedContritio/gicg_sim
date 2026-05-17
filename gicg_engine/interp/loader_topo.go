package interp

import (
	"fmt"
	"regexp"
)

// Dependency resolution for DSL file loading. Copied from lua/state.go,
// pure Go. The file loader (loader.go) consumes topoSortWithMeta output.

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

	n := len(files)
	inDeg := make([]int, n)
	edges := make([][]int, n)
	for i := range edges {
		edges[i] = nil
	}
	excluded := make([]bool, n)
	changed := true
	for changed {
		changed = false
		for i, fi := range files {
			if excluded[i] {
				continue
			}
			for _, sym := range fi.depends {
				pIdx, inProvider := provider[sym]
				if !inProvider {
					excluded[i] = true
					changed = true
					for _, ps := range fi.provides {
						if provider[ps] == i {
							delete(provider, ps)
						}
					}
					break
				}
				if pIdx >= 0 && excluded[pIdx] {
					excluded[i] = true
					changed = true
					for _, ps := range fi.provides {
						if provider[ps] == i {
							delete(provider, ps)
						}
					}
					break
				}
			}
		}
	}

	for i, fi := range files {
		if excluded[i] {
			continue
		}
		seen := map[int]bool{}
		for _, sym := range fi.depends {
			j, ok := provider[sym]
			if ok && j >= 0 && j != i && !seen[j] {
				seen[j] = true
				edges[j] = append(edges[j], i)
				inDeg[i]++
			}
		}
	}

	queue := make([]int, 0, n)
	for i := 0; i < n; i++ {
		if !excluded[i] && inDeg[i] == 0 {
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

	expectedCount := 0
	for i := 0; i < n; i++ {
		if !excluded[i] {
			expectedCount++
		}
	}
	if len(sorted) != expectedCount {
		var cycle []string
		for i := 0; i < n; i++ {
			if !excluded[i] && inDeg[i] > 0 {
				cycle = append(cycle, files[i].path)
			}
		}
		return nil, fmt.Errorf("circular dependency: %v", cycle)
	}

	return sorted, nil
}
