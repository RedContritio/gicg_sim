package engine

// Observation label helpers — translate raw obs slot indices back to
// human-readable strings (counter name, hook description). Used by the
// checkpoint visualizer and replay tooling. itoa/opName are tiny
// allocation-free formatters kept here because this file already had
// them and they are used only by describeHook / BuildRawToActiveHookIdx.

func (g *Game) ActiveCounterSlotLabels() []string {
	total := 2*ObsMaxChars*ObsCharSlots + 2*ObsPlayerSlots + ObsGlobalSlots
	labels := make([]string, 0, total)

	counterName := func(id int) string {
		if g.CounterNames != nil {
			if n, ok := g.CounterNames[id]; ok {
				return n
			}
		}
		return "#" + itoa(id)
	}
	pad := func(n int) {
		for i := 0; i < n; i++ {
			labels = append(labels, "")
		}
	}

	charCounters, playerCounters, globalCounters := g.groupCounters(0)

	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < ObsMaxChars; ci++ {
			ids := charCounters[pi][ci]
			n := len(ids)
			if n > ObsCharSlots {
				n = ObsCharSlots
			}
			charLabel := ""
			if g.CharNames != nil {
				if nm, ok := g.CharNames[[2]int{pi, ci}]; ok {
					charLabel = ":" + nm
				}
			}
			prefix := "P" + itoa(pi) + ":c" + itoa(ci) + charLabel + ":"
			for i := 0; i < n; i++ {
				labels = append(labels, prefix+counterName(ids[i]))
			}
			pad(ObsCharSlots - n)
		}
	}

	for pi := 0; pi < 2; pi++ {
		ids := playerCounters[pi]
		n := len(ids)
		if n > ObsPlayerSlots {
			n = ObsPlayerSlots
		}
		prefix := "P" + itoa(pi) + ":"
		for i := 0; i < n; i++ {
			labels = append(labels, prefix+counterName(ids[i]))
		}
		pad(ObsPlayerSlots - n)
	}

	n := len(globalCounters)
	if n > ObsGlobalSlots {
		n = ObsGlobalSlots
	}
	for i := 0; i < n; i++ {
		labels = append(labels, "global:"+counterName(globalCounters[i]))
	}
	pad(ObsGlobalSlots - n)

	return labels
}

// BuildRawToActiveHookIdx returns a map from raw hook ID to the hook's
// position in the *active* (filtered) hook list, i.e. the index the
// training-side hook_emb_cached uses. Iteration order mirrors
// ActiveHookLabels and the Python encode_static filter: walk the permuted
// hook slots, skip any hook whose Tokens are empty, assign sequential
// indices to the rest. Hooks that are absent or empty do not appear.
func (g *Game) BuildRawToActiveHookIdx() map[int]int {
	allHooks := g.Hooks.AllHooks()
	m := make(map[int]int, len(allHooks))
	active := 0
	for hi := 0; hi < ObsMaxHooks; hi++ {
		src := hi
		if g.HookPerm != nil && hi < len(g.HookPerm) {
			src = g.HookPerm[hi]
		}
		if src >= len(allHooks) {
			continue
		}
		hook := allHooks[src]
		if len(hook.Tokens) == 0 {
			continue
		}
		m[hook.ID] = active
		active++
	}
	return m
}

// ActiveHookLabels returns a human-readable label for each non-empty hook
// in the exact order the training side sees them after filtering. Used by
// the checkpoint visualizer to translate an attention-hot hook index back
// into "what hook is this" (type + owner + counter context).
//
// Ordering must match BuildStaticObs's hook iteration: iterate the full
// permuted hook slot range, pick the ones with non-empty Tokens, in that
// order. The training side's encode_static() filters on the same criterion
// (hook_types_all.sum != 0) so indices align 1:1.
func (g *Game) ActiveHookLabels() []string {
	allHooks := g.Hooks.AllHooks()
	var labels []string
	for hi := 0; hi < ObsMaxHooks; hi++ {
		src := hi
		if g.HookPerm != nil && hi < len(g.HookPerm) {
			src = g.HookPerm[hi]
		}
		if src >= len(allHooks) {
			continue
		}
		hook := allHooks[src]
		if len(hook.Tokens) == 0 {
			continue
		}
		labels = append(labels, describeHook(g, hook))
	}
	return labels
}

func describeHook(g *Game, h *Hook) string {
	typeName := HookTypeName(h.Type)
	owner := ""
	if h.OwnerPlayer >= 0 {
		owner = "P" + itoa(h.OwnerPlayer)
		if h.OwnerChar >= 0 {
			name := ""
			if g.CharNames != nil {
				if n, ok := g.CharNames[[2]int{h.OwnerPlayer, h.OwnerChar}]; ok {
					name = ":" + n
				}
			}
			owner += ":c" + itoa(h.OwnerChar) + name
		}
	} else {
		owner = "sys"
	}
	tail := ""
	if h.Type == HookBeforeWrite || h.Type == HookAfterWrite {
		counterName := ""
		if g.CounterNames != nil {
			if n, ok := g.CounterNames[h.CounterID]; ok {
				counterName = n
			}
		}
		if counterName == "" {
			counterName = "#" + itoa(h.CounterID)
		}
		tail = "[" + counterName + "/" + opName(h.Op) + "]"
	}
	// Source = DSL file basename (e.g. "蒸发", "赤蝶_蝶火"). With this
	// every hook is uniquely identified, so the 9 on_reaction_damage[sys]
	// instances become 9 distinct labels (one per reactions/<name>.lua).
	src := ""
	if h.Source != "" {
		src = "/" + h.Source
	}
	return typeName + tail + "[" + owner + src + "]"
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := false
	if n < 0 {
		neg = true
		n = -n
	}
	var buf [12]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	s := string(buf[i:])
	if neg {
		return "-" + s
	}
	return s
}

func opName(op Op) string {
	switch op {
	case OpSet:
		return "set"
	case OpAdd:
		return "add"
	case OpSub:
		return "sub"
	}
	return "?"
}

// BuildStaticObs creates the static observation (once per episode).
// Layout: [CounterMeta: (min,max,sid)×slots][HookTokens: hooks×tokens×2]
