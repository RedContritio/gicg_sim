package engine

import (
	"encoding/json"
	"fmt"
	"math/rand"
)

// MarshalJSON preserves the next random draw, including for deck streams.
func (r *Random) MarshalJSON() ([]byte, error) {
	state, err := r.source.pcg.MarshalBinary()
	if err != nil {
		return nil, err
	}
	return json.Marshal(state)
}

func (r *Random) UnmarshalJSON(data []byte) error {
	var state []byte
	if err := json.Unmarshal(data, &state); err != nil {
		return err
	}
	if len(state) == 0 {
		return fmt.Errorf("empty random state")
	}
	candidate := NewRandom(0)
	if err := candidate.source.pcg.UnmarshalBinary(state); err != nil {
		return err
	}
	// Rebind the legacy rand wrapper to this object's source, not candidate's.
	r.source = candidate.source
	r.rand = rand.New(&r.source)
	return nil
}
