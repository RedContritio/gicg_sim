// transition_writer.go — TCP localhost socket writer,Go actor → Python trainer collector。
//
// 协议(design D7 修正):同 inference 一份 raw bytes + length prefix wire format。 socket
// fire-and-forget(actor 不等 Python 端 ack),失败时 fail loud + log,actor 决定是否重连。
//
// concurrent safety:多 goroutine 共享同一 writer → Push 上 mutex 序列化(TCP write 顺序保证)。

package gicg_actor

import (
	"fmt"
	"net"
	"sync"
	"time"
)

// TransitionWriter 单 TCP 连接 fire-and-forget transition push。 N actor goroutine 共享。
type TransitionWriter struct {
	addr    string
	timeout time.Duration
	mu      sync.Mutex
	conn    net.Conn
}

func NewTransitionWriter(addr string, timeout time.Duration) *TransitionWriter {
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &TransitionWriter{addr: addr, timeout: timeout}
}

func (w *TransitionWriter) Connect() error {
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
	w.conn = conn
	return nil
}

func (w *TransitionWriter) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.conn == nil {
		return nil
	}
	err := w.conn.Close()
	w.conn = nil
	return err
}

// Push fire-and-forget 写一条 transition。 失败时 conn 标 nil(下次 Push lazy 重连)。
// thread-safe(mutex 序列化 TCP write,保证 frame 完整性)。
func (w *TransitionWriter) Push(t *Transition) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.conn == nil {
		d := net.Dialer{Timeout: w.timeout}
		conn, err := d.Dial("tcp", w.addr)
		if err != nil {
			return fmt.Errorf("lazy dial %s: %w", w.addr, err)
		}
		w.conn = conn
	}
	if err := w.conn.SetWriteDeadline(time.Now().Add(w.timeout)); err != nil {
		return fmt.Errorf("set write deadline: %w", err)
	}
	encoded, err := EncodeTransition(t)
	if err != nil {
		return fmt.Errorf("encode transition: %w", err)
	}
	if _, err := w.conn.Write(encoded); err != nil {
		w.conn = nil
		return fmt.Errorf("write transition: %w", err)
	}
	return nil
}
