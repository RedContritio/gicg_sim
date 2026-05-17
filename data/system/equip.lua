-- equipped stores the *CardRef of the weapon currently equipped on a
-- char slot, or nil when unequipped. Historically this was a raw int
-- counter and weapon cards compared against their card ref (pointer)
-- which never matched — tests passed by accident because equipped
-- checks never triggered. Under RefKind.Card the comparison is pointer
-- identity and actually works.
local equipped = declare_counter("equipped", Scope.PerChar, nil, { ref_kind = RefKind.Card })
