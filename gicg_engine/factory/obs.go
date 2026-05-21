package factory

import engine "gicg_mono/gicg_engine"

// ResolveObsConfig merges the JSON-provided ObsConfigJSON (with
// optional per-field overrides) onto the legacy-all-on default.
// Missing (nil pointer) fields preserve the default.
func ResolveObsConfig(j *ObsConfigJSON) engine.ObsConfig {
	out := engine.NewDefaultObsConfig()
	if j == nil {
		return out
	}
	if j.IncludeCharSkillRefs != nil {
		out.IncludeCharSkillRefs = *j.IncludeCharSkillRefs
	}
	if j.ShuffleCounters != nil {
		out.ShuffleCounters = *j.ShuffleCounters
	}
	if j.ShuffleHooks != nil {
		out.ShuffleHooks = *j.ShuffleHooks
	}
	if j.ShuffleCards != nil {
		out.ShuffleCards = *j.ShuffleCards
	}
	if j.ShuffleSkillSlots != nil {
		out.ShuffleSkillSlots = *j.ShuffleSkillSlots
	}
	return out
}
