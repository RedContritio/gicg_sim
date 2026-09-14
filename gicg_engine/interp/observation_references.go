package interp

// ObservationReferenceKinds describes typed storage without exposing runtime
// values or mutable registry objects through the observation boundary.
func (rt *Runtime) ObservationReferenceKinds() map[int]int {
	result := map[int]int{}
	for _, entry := range rt.Counters.Entries {
		if entry.RefKind == RefKindNone {
			continue
		}
		for _, id := range entry.CounterIDs {
			if id >= 0 {
				result[id] = entry.RefKind
			}
		}
	}
	return result
}
