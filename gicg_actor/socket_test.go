package gicg_actor

import (
	"context"
	"io"
	"math"
	"net"
	"sync"
	"testing"
	"time"
)

// startMockInfServer 起一个 echo-style mock InfServer:read InferRequest → decode →
// echo client_id/req_id back + 填随机 logits。 用于 InferenceClient 端单测,验证 socket
// round-trip + encoding。
func startMockInfServer(t *testing.T) (addr string, stop func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr = listener.Addr().String()
	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			default:
			}
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go handleMockInferConn(conn)
		}
	}()
	stop = func() {
		cancel()
		_ = listener.Close()
		wg.Wait()
	}
	return addr, stop
}

func handleMockInferConn(conn net.Conn) {
	defer conn.Close()
	for {
		payload, err := ReadLengthPrefixed(conn)
		if err != nil {
			if err != io.EOF {
				// silently drop — connection might be closed in tests
			}
			return
		}
		req, err := DecodeInferRequest(payload)
		if err != nil {
			return
		}
		// Echo:logits = [client_id, req_id, n_dyn, n_refs, n_pay](作为 float32 hack 验证)。
		resp := &InferResponse{
			Status: InferStatusOK,
			Logits: []float32{
				float32(req.ClientID),
				float32(req.ReqID),
				float32(len(req.DynObs)),
				float32(len(req.Refs)),
				float32(len(req.Pay)),
			},
		}
		encoded, err := EncodeInferResponse(resp)
		if err != nil {
			return
		}
		_, _ = conn.Write(encoded)
	}
}

func TestInferenceClient_RequestRoundTrip(t *testing.T) {
	addr, stop := startMockInfServer(t)
	defer stop()

	c := NewInferenceClient(addr, 2*time.Second)
	defer c.Close()

	req := &InferRequest{
		StaticHash: [16]byte{0xab, 0xcd},
		ClientID:   7,
		ReqID:      99,
		DynObs:     []float32{1.0, 2.0, 3.0},
		Refs:       []int64{10, 20},
		Pay:        []float32{0.5},
	}
	resp, err := c.Request(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if resp.Status != InferStatusOK {
		t.Errorf("status: got %d, want OK", resp.Status)
	}
	want := []float32{7, 99, 3, 2, 1}
	if len(resp.Logits) != len(want) {
		t.Fatalf("logits len: got %d, want %d", len(resp.Logits), len(want))
	}
	for i := range want {
		if math.Float32bits(resp.Logits[i]) != math.Float32bits(want[i]) {
			t.Errorf("logits[%d]: got %g, want %g", i, resp.Logits[i], want[i])
		}
	}
}

func TestInferenceClient_MultipleRequests(t *testing.T) {
	addr, stop := startMockInfServer(t)
	defer stop()

	c := NewInferenceClient(addr, 2*time.Second)
	defer c.Close()

	for i := range 5 {
		req := &InferRequest{ClientID: uint32(i), ReqID: uint32(i * 10), DynObs: []float32{float32(i)}}
		resp, err := c.Request(req)
		if err != nil {
			t.Fatalf("iter %d: %v", i, err)
		}
		if int(resp.Logits[0]) != i || int(resp.Logits[1]) != i*10 {
			t.Errorf("iter %d: echo mismatch: %+v", i, resp.Logits)
		}
	}
}

// startMockTransSink 起 mock transition sink — 接收并 decode 每条 transition,记录到 channel。
func startMockTransSink(t *testing.T) (addr string, recv <-chan *Transition, stop func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr = listener.Addr().String()
	ch := make(chan *Transition, 64)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			conn, err := listener.Accept()
			if err != nil {
				close(ch)
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				for {
					payload, err := ReadLengthPrefixed(c)
					if err != nil {
						return
					}
					t, err := DecodeTransition(payload)
					if err != nil {
						return
					}
					ch <- t
				}
			}(conn)
		}
	}()
	stop = func() {
		_ = listener.Close()
		wg.Wait()
	}
	return addr, ch, stop
}

func TestTransitionWriter_PushRoundTrip(t *testing.T) {
	addr, recv, stop := startMockTransSink(t)
	defer stop()

	w := NewTransitionWriterTCP(addr, 2*time.Second)
	defer w.Close()

	// I29 redesign:encode 在 paradigm 端,sink 仅 conn.Write framed bytes 透传。
	orig := &Transition{ClientID: 5, EpisodeID: 100, Step: 7, Done: true, Payload: []byte("hello world")}
	framed, err := EncodeTransition(orig)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	if err := w.Push(orig.ClientID, orig.Step, framed); err != nil {
		t.Fatalf("push: %v", err)
	}

	select {
	case got := <-recv:
		if got.ClientID != 5 || got.Step != 7 || !got.Done {
			t.Errorf("decoded mismatch: %+v", got)
		}
		if string(got.Payload) != "hello world" {
			t.Errorf("payload: got %q", string(got.Payload))
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timeout waiting for transition")
	}
}

func TestTransitionWriter_MultiplePush(t *testing.T) {
	addr, recv, stop := startMockTransSink(t)
	defer stop()

	w := NewTransitionWriterTCP(addr, 2*time.Second)
	defer w.Close()

	for i := range 20 {
		t1 := &Transition{ClientID: uint32(i), Step: uint32(i)}
		framed, err := EncodeTransition(t1)
		if err != nil {
			t.Fatalf("iter %d encode: %v", i, err)
		}
		if err := w.Push(t1.ClientID, t1.Step, framed); err != nil {
			t.Fatalf("iter %d push: %v", i, err)
		}
	}
	// 等到 receive 20 个或 timeout
	count := 0
	timeout := time.After(2 * time.Second)
loop:
	for count < 20 {
		select {
		case got := <-recv:
			if int(got.ClientID) != count {
				t.Errorf("iter %d: client_id got %d", count, got.ClientID)
			}
			count++
		case <-timeout:
			break loop
		}
	}
	if count != 20 {
		t.Fatalf("got %d/20 transitions", count)
	}
}
