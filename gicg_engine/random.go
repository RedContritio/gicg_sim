package engine

import (
	"math/rand"
	randv2 "math/rand/v2"
)

// RandomProtocol identifies the seed-to-event stream. Seed-only replays from
// the legacy math/rand source are not compatible with this protocol.
const RandomProtocol = "pcg-v1"

// Random owns all generator state. Unlike *rand.Rand, it can be copied without
// drawing from the original stream. Do not share an instance between games.
// Only methods without hidden buffering are exposed (not rand.Rand.Read).
type Random struct {
	source pcgSource
	rand   *rand.Rand
}

type pcgSource struct{ pcg randv2.PCG }

func (s *pcgSource) Seed(seed int64) {
	s.pcg = *randv2.NewPCG(uint64(seed), uint64(seed)^0x9e3779b97f4a7c15)
}
func (s *pcgSource) Uint64() uint64 { return s.pcg.Uint64() }
func (s *pcgSource) Int63() int64   { return int64(s.Uint64() >> 1) }

func NewRandom(seed int64) *Random {
	r := &Random{}
	r.source.Seed(seed)
	r.rand = rand.New(&r.source)
	return r
}

func (r *Random) Seed(seed int64)                    { r.rand.Seed(seed) }
func (r *Random) Int63() int64                       { return r.rand.Int63() }
func (r *Random) Uint64() uint64                     { return r.rand.Uint64() }
func (r *Random) Intn(n int) int                     { return r.rand.Intn(n) }
func (r *Random) Perm(n int) []int                   { return r.rand.Perm(n) }
func (r *Random) Shuffle(n int, swap func(int, int)) { r.rand.Shuffle(n, swap) }

func copyRandom(dst, src *Random) *Random {
	if src == nil {
		return nil
	}
	if dst == nil {
		dst = NewRandom(0)
	}
	dst.source = src.source
	return dst
}

// Clone preserves the next draw and never advances the source.
func (r *Random) Clone() *Random { return copyRandom(nil, r) }

// SetSimulationSeed explicitly replaces future chance events in a speculative
// game. Call on a private clone after restore, never on the live game. Current
// hands/dice stay unchanged; BaseSeed also controls future round-start rolls.
func (g *Game) SetSimulationSeed(seed int64) {
	g.BaseSeed = seed
	g.Rng = NewRandom(seed)
	for pi := range g.DeckRngs {
		g.DeckSeeds[pi] = seed ^ int64(pi+1)*0x517cc1b727220a95
		g.DeckRngs[pi] = NewRandom(g.DeckSeeds[pi])
	}
}
