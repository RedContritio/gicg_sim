// transition_writer.go — TCP localhost socket sink,Go actor → Python trainer collector。
//
// 协议:paradigm 端 encode 完整 wire frame (outer length prefix + TransitionHeader/EpisodeBatchHeader +
// paradigm payload),sink 仅做 conn.Write 透传。 fire-and-forget — actor 不等 Python ack。
//
// concurrent safety:多 goroutine 共享同一 writer → Push 上 mutex 序列化 (TCP write 顺序保证)。
// I29 T-B1 起 production 路径每 actor 一条 *TransitionWriterTCP,mutex contention ≈ 0;mutex 仍保
// (Close/Push race + 重连串行)。

package gicg_actor

import (
	"fmt"
	"net"
	"sync"
	"time"
)

// TransitionWriterTCP — TransitionSink TCP 实现。
//
// 旧 *TransitionWriter (含 Push(*Transition) / PushBatch(cid, eid, []*Transition) 双方法) 已 retire;
// encode 责任移到 paradigm 端,sink 单一签名 Push(cid, seq, payload)。 见 transition_sink.go。
type TransitionWriterTCP struct {
	addr           string
	timeout        time.Duration
	mu             sync.Mutex
	conn           net.Conn
	noDelayApplied bool // set after SetNoDelay(true); unexported, used by tests
}

// 编译期断言 TransitionWriterTCP 实现 TransitionSink。
var _ TransitionSink = (*TransitionWriterTCP)(nil)

func NewTransitionWriterTCP(addr string, timeout time.Duration) *TransitionWriterTCP {
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &TransitionWriterTCP{addr: addr, timeout: timeout}
}

// setupConn casts net.Conn to *net.TCPConn, enables TCP_NODELAY, and assigns w.conn.
// Caller must hold w.mu. On any failure the conn is closed and an error is returned.
func (w *TransitionWriterTCP) setupConn(conn net.Conn) error {
	tc, ok := conn.(*net.TCPConn)
	if !ok {
		conn.Close()
		return fmt.Errorf("expected *net.TCPConn, got %T", conn)
	}
	if err := tc.SetNoDelay(true); err != nil {
		tc.Close()
		return fmt.Errorf("set no delay: %w", err)
	}
	w.conn = tc
	w.noDelayApplied = true
	return nil
}

func (w *TransitionWriterTCP) Connect() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.conn != nil {
		return nil
	}
	d := net.Dialer{Timeout: w.timeout}
	conn, err := d.Dial("tcp", w.addr)
	if err != nil {
		return fmt.Errorf("transition dial %s: %w", w.addr, err)
	}
	return w.setupConn(conn)
}

func (w *TransitionWriterTCP) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.conn == nil {
		return nil
	}
	err := w.conn.Close()
	w.conn = nil
	return err
}

// Push 写一条 framed payload 到 socket (fire-and-forget)。 失败时 conn 标 nil (下次 lazy 重连)。
// thread-safe — mutex 序列化 TCP write 保 frame 完整性。 clientID / seq 仅用于 caller 端语义,本
// TCP impl 不读 (payload 内含 wire header,Python listener 解码 header 拿 clientID / seq)。
func (w *TransitionWriterTCP) Push(clientID, seq uint32, payload []byte) error {
	_ = clientID
	_ = seq
	mwSpan := Span("transition_writer.mutex_wait")
	w.mu.Lock()
	mwSpan.End() // 只覆盖 lock-acquire 时间
	defer w.mu.Unlock()
	if w.conn == nil {
		d := net.Dialer{Timeout: w.timeout}
		conn, err := d.Dial("tcp", w.addr)
		if err != nil {
			return fmt.Errorf("lazy dial %s: %w", w.addr, err)
		}
		if err := w.setupConn(conn); err != nil {
			return fmt.Errorf("lazy reconnect setup: %w", err)
		}
	}
	swSpan := Span("transition_writer.socket_write")
	if err := w.conn.SetWriteDeadline(time.Now().Add(w.timeout)); err != nil {
		swSpan.End()
		return fmt.Errorf("set write deadline: %w", err)
	}
	if _, err := w.conn.Write(payload); err != nil {
		swSpan.End()
		w.conn = nil
		return fmt.Errorf("write payload: %w", err)
	}
	swSpan.End()
	return nil
}
