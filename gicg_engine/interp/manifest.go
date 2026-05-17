package interp

import (
	"fmt"
	"os"
	"sort"
	"strings"
)

// Manifest is the in-memory form of a pools/<id>/manifest.toml. Parsed
// by parseManifest using a minimal line-based scanner — see ADR-0011
// for the schema. Only the fields actually consumed by the loader are
// populated; unknown sections/keys are silently ignored so future
// schema extensions stay backward-compatible with older binaries.
type Manifest struct {
	ID          string
	Parent      string // empty string = root pool (no parent)
	Desc        string
	CardsRemove []string // card names removed from the parent's set
	CharsRemove []string // char names removed from the parent's set
}

// parseManifest reads a pools/<id>/manifest.toml and extracts the
// fields ResolvePool needs. This is a deliberately minimal parser
// (only line-level [section] / key = "value" / key = ["a", "b"]
// forms) so the engine doesn't grow a TOML dependency. Comments
// (lines starting with #) and blank lines are skipped. Unknown
// sections/keys are silently ignored.
func parseManifest(path string) (*Manifest, error) {
	src, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("manifest %s: %w", path, err)
	}
	m := &Manifest{}
	section := ""
	for _, raw := range strings.Split(string(src), "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			section = line[1 : len(line)-1]
			continue
		}
		eq := strings.Index(line, "=")
		if eq < 0 {
			continue
		}
		key := strings.TrimSpace(line[:eq])
		val := strings.TrimSpace(line[eq+1:])
		if hashIdx := indexUnquoted(val, '#'); hashIdx >= 0 {
			val = strings.TrimSpace(val[:hashIdx])
		}
		switch section + "." + key {
		case "version.id":
			m.ID = trimQuotes(val)
		case "version.parent":
			m.Parent = trimQuotes(val)
		case "version.desc":
			m.Desc = trimQuotes(val)
		case "cards.remove":
			m.CardsRemove = parseStringList(val)
		case "characters.remove":
			m.CharsRemove = parseStringList(val)
		}
	}
	if m.ID == "" {
		return nil, fmt.Errorf("manifest %s: missing [version].id", path)
	}
	return m, nil
}

// trimQuotes strips matching surrounding double quotes. Inputs without
// matching quotes are returned unchanged so malformed manifests
// surface their raw text in downstream error messages.
func trimQuotes(val string) string {
	if len(val) >= 2 && val[0] == '"' && val[len(val)-1] == '"' {
		return val[1 : len(val)-1]
	}
	return val
}

// parseStringList parses a single-line TOML string array of the form
// `["a", "b"]` or `[]`. Trailing commas are tolerated; embedded
// brackets, multiline arrays, and escape sequences are not — manifests
// in this repo are author-controlled and deliberately stay simple.
func parseStringList(val string) []string {
	val = strings.TrimSpace(val)
	if !strings.HasPrefix(val, "[") || !strings.HasSuffix(val, "]") {
		return nil
	}
	inner := strings.TrimSpace(val[1 : len(val)-1])
	if inner == "" {
		return nil
	}
	var out []string
	for _, tok := range strings.Split(inner, ",") {
		tok = strings.TrimSpace(tok)
		if tok == "" {
			continue
		}
		out = append(out, trimQuotes(tok))
	}
	sort.Strings(out)
	return out
}

// indexUnquoted returns the index of the first occurrence of ch
// outside of any double-quoted span, or -1 if none. Used by
// parseManifest to strip trailing inline comments without mangling
// strings that happen to contain '#'.
func indexUnquoted(s string, ch byte) int {
	inQuote := false
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c == '"' {
			inQuote = !inQuote
		} else if c == ch && !inQuote {
			return i
		}
	}
	return -1
}
