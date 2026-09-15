package ir

// Generic map-sorting helpers shared by the DSL audit tool
// (see audit_test.go). Kept in a separate file so neither file exceeds
// the line limit; nothing here is specific to the audit.

import "sort"

type kv[V any] struct {
	k string
	v V
}

func sortedByValueDesc(m map[string]int) []kv[int] {
	out := make([]kv[int], 0, len(m))
	for k, v := range m {
		out = append(out, kv[int]{k, v})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].v != out[j].v {
			return out[i].v > out[j].v
		}
		return out[i].k < out[j].k
	})
	return out
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func sortedIntKeys(m map[int]int) []int {
	out := make([]int, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Ints(out)
	return out
}
