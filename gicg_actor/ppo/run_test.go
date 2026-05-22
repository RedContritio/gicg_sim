// PPO Run loop helpers unit tests — sampleActionTemperature + buildOppMover。

package ppo

import (
	"math"
	"math/rand"
	"strings"
	"testing"
)

func TestSampleActionTemperature_Argmax(t *testing.T) {
	logits := []float32{0.1, 0.9, 0.5, 0.0}
	rng := rand.New(rand.NewSource(1))
	idx, logProb := sampleActionTemperature(logits, 4, 0.0, rng)
	if idx != 1 {
		t.Errorf("T=0 argmax idx = %d, want 1", idx)
	}
	if logProb != 0.0 {
		t.Errorf("T=0 log_prob = %f, want 0(deterministic)", logProb)
	}
}

func TestSampleActionTemperature_MaskInvalid(t *testing.T) {
	// padded logits 后段更大但 nLegal=3 → 不参选
	logits := []float32{0.1, 0.9, 0.5, 100.0, 100.0}
	rng := rand.New(rand.NewSource(1))
	idx, _ := sampleActionTemperature(logits, 3, 0.0, rng)
	if idx != 1 {
		t.Errorf("masked argmax: got idx=%d, want 1", idx)
	}
}

func TestSampleActionTemperature_Softmax(t *testing.T) {
	logits := []float32{1.0, 2.0, 3.0}
	rng := rand.New(rand.NewSource(42))
	hits := make([]int, 3)
	const N = 5000
	for i := 0; i < N; i++ {
		idx, _ := sampleActionTemperature(logits, 3, 1.0, rng)
		hits[idx]++
	}
	// Expected softmax probs:exp(1)/(e+e²+e³),exp(2)/...,exp(3)/...
	// ≈ 0.090, 0.245, 0.665。 ±5% tolerance over N=5000。
	probs := []float32{0.090, 0.245, 0.665}
	for i, want := range probs {
		got := float32(hits[i]) / N
		if math.Abs(float64(got-want)) > 0.03 {
			t.Errorf("softmax idx=%d freq=%.3f, want ≈%.3f", i, got, want)
		}
	}
}

func TestSampleActionTemperature_LogProbConsistent(t *testing.T) {
	logits := []float32{1.0, 2.0, 3.0}
	rng := rand.New(rand.NewSource(0))
	idx, logProb := sampleActionTemperature(logits, 3, 1.0, rng)
	// 验:log_prob = log(softmax(logits)[idx])
	maxL := float32(math.Inf(-1))
	for _, v := range logits {
		if v > maxL {
			maxL = v
		}
	}
	expSum := float32(0)
	for _, v := range logits {
		expSum += float32(math.Exp(float64(v - maxL)))
	}
	expectedProb := float32(math.Exp(float64(logits[idx]-maxL))) / expSum
	expectedLogProb := float32(math.Log(float64(expectedProb)))
	if math.Abs(float64(logProb-expectedLogProb)) > 1e-5 {
		t.Errorf("log_prob: got %f, want %f(idx=%d)", logProb, expectedLogProb, idx)
	}
}

func TestSampleActionTemperature_EmptyLegal(t *testing.T) {
	rng := rand.New(rand.NewSource(0))
	idx, _ := sampleActionTemperature([]float32{1.0}, 0, 1.0, rng)
	if idx != -1 {
		t.Errorf("nLegal=0: got %d, want -1", idx)
	}
}

func TestBuildOppMover_Random(t *testing.T) {
	mover, err := buildOppMover("random", 1)
	if err != nil {
		t.Fatalf("buildOppMover(random): %v", err)
	}
	if mover == nil {
		t.Fatal("mover nil")
	}
}

func TestBuildOppMover_F1D2(t *testing.T) {
	mover, err := buildOppMover("F1-D2", 1)
	if err != nil {
		t.Fatalf("buildOppMover(F1-D2): %v", err)
	}
	if mover == nil {
		t.Fatal("mover nil")
	}
}

func TestBuildOppMover_Errors(t *testing.T) {
	cases := []struct {
		spec    string
		wantSub string
	}{
		{"", "empty"},
		{"self", "not supported"},
		{"bogus", "unknown rollout_opponent"},
		{"F1-Dxx", "bad depth"},
		{"F99-D2", "unknown features"},
		{"F1-D5", "depth must be 1..4"},
	}
	for _, tc := range cases {
		t.Run(tc.spec, func(t *testing.T) {
			_, err := buildOppMover(tc.spec, 1)
			if err == nil {
				t.Fatalf("want error containing %q, got nil", tc.wantSub)
			}
			if !strings.Contains(err.Error(), tc.wantSub) {
				t.Errorf("err=%v, want %q", err, tc.wantSub)
			}
		})
	}
}
