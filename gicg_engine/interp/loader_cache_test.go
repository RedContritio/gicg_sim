package interp

// 契约测试:DSL 缓存是进程内一次性 — 同一路径二次读取必须 hit cache,
// 即便文件内容在第一次读取后被修改。回归 2026-04-21 code review:
// "DSL cache 永不失效 (intentional),但没有测试覆盖" — 本补丁把
// intentional 行为凝固为断言,将来若无意引入 invalidation,测试会失败。
//
// 测试路径是临时文件,不污染生产 data/。

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDSLCache_StaleASTPersistsAcrossEdits(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "stale_test.lua")

	// 第一版内容 v1:定义常量 MARKER = 1
	v1 := `MARKER = 1`
	if err := os.WriteFile(path, []byte(v1), 0644); err != nil {
		t.Fatalf("write v1: %v", err)
	}

	// 第一次 load — 填充 cache
	pf1, err := loadParsedDSL(path)
	if err != nil {
		t.Fatalf("loadParsedDSL v1: %v", err)
	}
	if string(pf1.src) != v1 {
		t.Fatalf("v1 src mismatch: got %q", string(pf1.src))
	}

	// 原地覆盖成 v2
	v2 := `MARKER = 999`
	if err := os.WriteFile(path, []byte(v2), 0644); err != nil {
		t.Fatalf("write v2: %v", err)
	}

	// 第二次 load — 应返回 v1 的 parsed 形(cache hit)
	pf2, err := loadParsedDSL(path)
	if err != nil {
		t.Fatalf("loadParsedDSL v2: %v", err)
	}

	// 契约:cache 是 intentional,同一路径必须返回首次缓存的结果
	if pf2 != pf1 {
		t.Errorf("cache miss on second load — DSL cache regressed from "+
			"intentional-immutable to invalidating. pf1=%p pf2=%p", pf1, pf2)
	}
	if string(pf2.src) != v1 {
		t.Errorf("second load returned disk-current src (stale-aware), "+
			"breaking intentional-frozen contract. Expected cached v1, got %q",
			string(pf2.src))
	}
}

func TestDSLCache_ConcurrentFirstLoadRaces(t *testing.T) {
	// 并发首次加载同一路径不应 panic(double-check locking)。
	// 不同 path 则各自独立。用 goroutines + 同一 path。
	dir := t.TempDir()
	path := filepath.Join(dir, "concurrent_test.lua")
	if err := os.WriteFile(path, []byte(`X = 42`), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	N := 20
	done := make(chan *parsedDSLFile, N)
	errs := make(chan error, N)
	for i := 0; i < N; i++ {
		go func() {
			pf, err := loadParsedDSL(path)
			if err != nil {
				errs <- err
				return
			}
			done <- pf
		}()
	}

	var first *parsedDSLFile
	for i := 0; i < N; i++ {
		select {
		case pf := <-done:
			if first == nil {
				first = pf
			} else if pf != first {
				t.Errorf("concurrent load got different *parsedDSLFile: "+
					"first=%p got=%p — cache not winning-writer-consistent",
					first, pf)
			}
		case err := <-errs:
			t.Fatalf("concurrent load err: %v", err)
		}
	}
}
