package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Counter-family builtins: declare_counter, get_counter, get_counter_group,
// on_before_write / on_after_write, register_on_tag_write, plus the
// shared registerWriteHooksForProxy / registerHook / refreshSelfEntryRef
// helpers that sit inside the same Runtime closure surface.

func (rt *Runtime) builtinDeclareCounter(args []Value) (Value, error) {
	name, _ := args[0].(string)
	scope, _ := ToInt(args[1])
	initVal, hasInitVal := ToInt(args[2])

	cmin, cmax := 0, 255
	tag := 0
	refKind := RefKindNone
	display := ""
	if len(args) > 3 && args[3] != nil {
		opts, _ := args[3].(*Table)
		if opts != nil {
			if v, ok := opts.Fields["min"]; ok {
				cmin, _ = ToInt(v)
			}
			if v, ok := opts.Fields["max"]; ok {
				cmax, _ = ToInt(v)
			}
			if v, ok := opts.Fields["tag"]; ok {
				tag, _ = ToInt(v)
			}
			if v, ok := opts.Fields["display"]; ok {
				display, _ = v.(string)
			}
			if v, ok := opts.Fields["ref_kind"]; ok {
				refKind, _ = ToInt(v)
			}
		}
	}

	// Ref-tagged counters store an ID internally; -1 is the "no ref"
	// sentinel. Adjust init value + bounds automatically so DSL can
	// simply pass `nil` (or omit init) for the empty case, and bounds
	// default to [-1, 65535] which covers all plausible skill/card IDs.
	if refKind != RefKindNone {
		if !hasInitVal {
			initVal = -1
		}
		if cmin == 0 {
			cmin = -1
		}
		if cmax == 255 {
			cmax = 65535
		}
	}

	key := rt.CounterKey(name, scope)
	existing := rt.Counters.Entries[key]
	if existing != nil {
		if existing.Min != cmin || existing.Max != cmax || existing.InitValue != initVal || existing.Scope != scope || existing.RefKind != refKind {
			return nil, fmt.Errorf("declare_counter conflict for %q: params differ", name)
		}
		// For non-Self scopes, re-declare is fully idempotent.
		if scope != ScopeSelf && scope != ScopeActiveStatus {
			return existing.Ref, nil
		}
		// Self/ActiveStatus: fall through to per-slot extension path below.
	}

	g := rt.Game

	displayName := display
	if displayName == "" {
		displayName = name
	}
	registerCounterName := func(id int) {
		if rt.Game.CounterNames == nil {
			rt.Game.CounterNames = make(map[int]string)
		}
		rt.Game.CounterNames[id] = displayName
	}

	if scope == ScopeSelf || scope == ScopeActiveStatus {
		entry := existing
		if entry == nil {
			slotIDs := make([]int, 2*MaxChars)
			for i := range slotIDs {
				slotIDs[i] = -1
			}
			entry = &CounterEntry{
				CounterIDs:  nil,
				Scope:       scope,
				Min:         cmin,
				Max:         cmax,
				InitValue:   initVal,
				Tag:         tag,
				Display:     display,
				OwnerPlayer: -1,
				OwnerChar:   -1,
				RefKind:     refKind,
				SlotIDs:     slotIDs,
			}
			// Entry-level Ref is a SelfSlotProxy with empty OwnerName —
			// used only for AllCounterIDs iteration (write-hook batch
			// registration, tag-group iteration). Not DSL-accessible.
			var slotArr [2 * MaxChars]int
			copy(slotArr[:], entry.SlotIDs)
			entry.Ref = &SelfSlotProxy{SlotIDs: slotArr, OwnerName: "", RefKind: refKind}
			rt.Counters.Entries[key] = entry
			if tag > 0 {
				rt.Counters.TagGroups[tag] = append(rt.Counters.TagGroups[tag], entry)
			}
		}

		if rt.CurrentOwnerPlayer >= 0 {
			slotIdx := rt.CurrentOwnerPlayer*MaxChars + rt.CurrentOwnerChar
			if entry.SlotIDs[slotIdx] < 0 {
				id := g.CreateCounter(initVal, cmin, cmax)
				g.RegisterCounterChar(id, rt.CurrentOwnerPlayer, rt.CurrentOwnerChar)
				entry.SlotIDs[slotIdx] = id
				entry.CounterIDs = append(entry.CounterIDs, id)
				registerCounterName(id)
				rt.refreshSelfEntryRef(entry)
			}
			return &CounterProxy{ID: entry.SlotIDs[slotIdx], RefKind: refKind}, nil
		}

		if rt.CurrentFileTalentOwner != "" {
			ownerName := rt.CurrentFileTalentOwner
			for p := 0; p < 2; p++ {
				for c := 0; c < MaxChars; c++ {
					slot := rt.Chars.BySlot[p][c]
					if slot == nil || slot.Name != ownerName {
						continue
					}
					slotIdx := p*MaxChars + c
					if entry.SlotIDs[slotIdx] >= 0 {
						continue
					}
					id := g.CreateCounter(initVal, cmin, cmax)
					g.RegisterCounterChar(id, p, c)
					entry.SlotIDs[slotIdx] = id
					entry.CounterIDs = append(entry.CounterIDs, id)
					registerCounterName(id)
				}
			}
			rt.refreshSelfEntryRef(entry)
			var slotArr [2 * MaxChars]int
			copy(slotArr[:], entry.SlotIDs)
			return &SelfSlotProxy{SlotIDs: slotArr, OwnerName: ownerName, RefKind: refKind}, nil
		}

		return nil, fmt.Errorf("declare_counter %q: Scope.Self/ActiveStatus requires per-binding char or talent (requires_char) context", name)
	}

	var ref Value
	var counterIDs []int

	switch scope {
	case ScopePerPlayer:
		var ids [2]int
		for p := 0; p < 2; p++ {
			ids[p] = g.CreateCounter(initVal, cmin, cmax)
			g.RegisterCounterChar(ids[p], p, -1)
		}
		proxy := &PerPlayerProxy{IDs: ids, RefKind: refKind}
		ref = proxy
		counterIDs = ids[:]

	case ScopePerChar:
		var ids [2 * MaxChars]int
		for i := 0; i < 2*MaxChars; i++ {
			ids[i] = g.CreateCounter(initVal, cmin, cmax)
			p := 0
			if i >= MaxChars {
				p = 1
			}
			c := i % MaxChars
			g.RegisterCounterChar(ids[i], p, c)
		}
		proxy := &PerCharProxy{IDs: ids, RefKind: refKind}
		ref = proxy
		counterIDs = ids[:]

	default: // Global
		id := g.CreateCounter(initVal, cmin, cmax)
		proxy := &CounterProxy{ID: id, RefKind: refKind}
		ref = proxy
		counterIDs = []int{id}
	}

	entry := &CounterEntry{
		Ref:         ref,
		CounterIDs:  counterIDs,
		Scope:       scope,
		Min:         cmin,
		Max:         cmax,
		InitValue:   initVal,
		Tag:         tag,
		Display:     display,
		OwnerPlayer: rt.CurrentOwnerPlayer,
		OwnerChar:   rt.CurrentOwnerChar,
		RefKind:     refKind,
	}
	rt.Counters.Entries[key] = entry

	for _, cid := range counterIDs {
		registerCounterName(cid)
	}

	if tag > 0 {
		rt.Counters.TagGroups[tag] = append(rt.Counters.TagGroups[tag], entry)
	}

	return ref, nil
}

// refreshSelfEntryRef rebuilds the entry-level summary SelfSlotProxy so
// write-hook / tag-group iterators see the latest SlotIDs snapshot. The
// summary proxy has OwnerName="" — it's never returned to DSL, only
// used by AllCounterIDs callers.
func (rt *Runtime) refreshSelfEntryRef(entry *CounterEntry) {
	var slotArr [2 * MaxChars]int
	copy(slotArr[:], entry.SlotIDs)
	entry.Ref = &SelfSlotProxy{SlotIDs: slotArr, OwnerName: "", RefKind: entry.RefKind}
}

func (rt *Runtime) builtinGetCounter(args []Value) (Value, error) {
	name, _ := args[0].(string)
	scope, _ := ToInt(args[1])
	key := rt.CounterKey(name, scope)
	existing, ok := rt.Counters.Entries[key]
	if !ok {
		return nil, fmt.Errorf("unresolved_dependency:%s", name)
	}

	// Self/ActiveStatus: construct a proxy tailored to the calling
	// context. Per-binding char files get a slot-pinned CounterProxy
	// (static ID — closures capture the right counter). Shared-load
	// talent cards get a SelfSlotProxy (dynamic slot resolution via
	// ctx at hook-fire time).
	if existing.Scope == ScopeSelf || existing.Scope == ScopeActiveStatus {
		if rt.CurrentOwnerPlayer >= 0 {
			slotIdx := rt.CurrentOwnerPlayer*MaxChars + rt.CurrentOwnerChar
			id := existing.SlotIDs[slotIdx]
			if id < 0 {
				return nil, fmt.Errorf(
					"get_counter(Scope.Self/ActiveStatus) %q: caller slot (p=%d c=%d) has no allocated counter — declare order / char dep broken?",
					name, rt.CurrentOwnerPlayer, rt.CurrentOwnerChar)
			}
			return &CounterProxy{ID: id, RefKind: existing.RefKind}, nil
		}
		if rt.CurrentFileTalentOwner != "" {
			var slotArr [2 * MaxChars]int
			copy(slotArr[:], existing.SlotIDs)
			return &SelfSlotProxy{SlotIDs: slotArr, OwnerName: rt.CurrentFileTalentOwner, RefKind: existing.RefKind}, nil
		}
		return nil, fmt.Errorf(
			"get_counter(Scope.Self/ActiveStatus) %q: requires per-binding char or talent (requires_char) context",
			name)
	}

	// Optional bind argument for PerPlayer
	if len(args) > 2 && args[2] != nil {
		if pp, ok := existing.Ref.(*PerPlayerProxy); ok {
			bind, _ := ToInt(args[2])
			return &PerPlayerView{Inner: pp, Bind: bind}, nil
		}
	}
	return existing.Ref, nil
}

func (rt *Runtime) builtinGetCounterGroup(args []Value) (Value, error) {
	tag, _ := ToInt(args[0])
	entries := rt.Counters.TagGroups[tag]
	return &CounterGroupProxy{Entries: entries}, nil
}

func (rt *Runtime) builtinRegisterOnTagWrite(args []Value) (Value, error) {
	tag, _ := ToInt(args[0])
	hookType, _ := args[1].(string)
	opVal, _ := ToInt(args[2])
	fn, _ := args[3].(*Closure)
	op := engine.Op(opVal)

	entries := rt.Counters.TagGroups[tag]
	for _, e := range entries {
		ref := e.Ref
		rt.registerWriteHooksForProxy(ref, hookType, op, fn, ref)
	}
	return nil, nil
}

// Write-hook helpers + registerHook live in builtins_counter_hooks.go.
