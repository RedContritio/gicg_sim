// inference_client.go — TCP localhost socket 客户端,Go actor → Python InfServer。
//
// 协议(design D5):raw bytes + length prefix,详 wire_format.go。 client 维持一条 keep-alive
// TCP 连接,Request 同步 send-then-recv(InfServer 端 batched 处理,单 actor 视角是 blocking RPC)。
//
// Concurrent safety:多个 goroutine 共享同一 InferenceClient → Request 上 mutex 序列化。
// alternative 是 per-goroutine 一条 connection(N actor 起 N TCP conn),per-conn 不上锁,
// throughput 更高但 conn 资源消耗。 当前选 single-conn + mutex(scale 到 N=32 实测前不优化)。

package gicg_actor

import (
	"errors"
	"fmt"
	"net"
	"sync"
	"time"
)

// InferenceClient 单一 TCP 连接,N actor goroutine 共享。 Request 上锁序列化。
type InferenceClient struct {
	addr    string
	timeout time.Duration
	mu      sync.Mutex
	conn    net.Conn
}

// NewInferenceClient 创建 client,不立即 connect(lazy)。 addr 格式 "host:port"。
func NewInferenceClient(addr string, timeout time.Duration) *InferenceClient {
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &InferenceClient{addr: addr, timeout: timeout}
}

// Connect 显式 dial(可选 — Request 会 lazy 连)。 重连用:close current + dial new。
func (c *InferenceClient) Connect() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn != nil {
		return nil
	}
	d := net.Dialer{Timeout: c.timeout}
	conn, err := d.Dial("tcp", c.addr)
	if err != nil {
		return fmt.Errorf("dial %s: %w", c.addr, err)
	}
	c.conn = conn
	return nil
}

// Close 关 TCP 连接。 idempotent。
func (c *InferenceClient) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn == nil {
		return nil
	}
	err := c.conn.Close()
	c.conn = nil
	return err
}

// Request 同步发送 InferRequest 并等 response。 conn 失效时 fail loud,caller 决定重连。
//
// thread-safe:多 goroutine 调本方法 内部 mutex 序列化。 单 InfServer 处理一次只能 ack
// 一个 client send(不然 response 跟 request 对不上),所以这个 mutex 是正确的(虽然
// 限制了 client-side concurrency)。
func (c *InferenceClient) Request(req *InferRequest) (*InferResponse, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn == nil {
		d := net.Dialer{Timeout: c.timeout}
		conn, err := d.Dial("tcp", c.addr)
		if err != nil {
			return nil, fmt.Errorf("lazy dial %s: %w", c.addr, err)
		}
		c.conn = conn
	}
	if err := c.conn.SetDeadline(time.Now().Add(c.timeout)); err != nil {
		return nil, fmt.Errorf("set deadline: %w", err)
	}
	encSpan := Span("inference_client.encode")
	encoded, err := EncodeInferRequest(req)
	encSpan.End()
	if err != nil {
		return nil, fmt.Errorf("encode: %w", err)
	}
	sendSpan := Span("inference_client.send")
	if _, err := c.conn.Write(encoded); err != nil {
		sendSpan.End()
		c.conn = nil // mark broken — caller may retry via fresh Request
		return nil, fmt.Errorf("write request: %w", err)
	}
	sendSpan.End()
	recvSpan := Span("inference_client.recv")
	payload, err := ReadLengthPrefixed(c.conn)
	recvSpan.End()
	if err != nil {
		c.conn = nil
		return nil, fmt.Errorf("read response: %w", err)
	}
	decSpan := Span("inference_client.decode")
	resp, err := DecodeInferResponse(payload)
	decSpan.End()
	if err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	if resp.Status == InferStatusErr {
		return resp, errors.New("inference server: " + resp.ErrMsg)
	}
	return resp, nil
}
