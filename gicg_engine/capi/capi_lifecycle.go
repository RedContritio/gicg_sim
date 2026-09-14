// Lifecycle: cooperative shutdown signal handler for c-shared library.
//
// When libgicg is loaded into a Python process (via ctypes) and Python
// later spawns a child actor that imports cgo-bound engine code, the Go
// runtime initializes inside the child. Python's default SIGTERM
// handler is effectively a no-op for a thread blocked inside cgo. As
// a result `multiprocessing.Process.terminate()` (which sends SIGTERM
// on POSIX) does not kill the actor, leaving the parent stuck on
// `proc.join`.
//
// This init registers a Go-side handler that catches SIGTERM/SIGINT
// and calls os.Exit(0). os.Exit terminates immediately without running
// deferred functions, independently of the Python thread
// state because the signal handler runs on its own goroutine + OS
// thread.
//
// Windows: SIGINT works the same way; SIGTERM does not exist there
// but `multiprocessing.Process.terminate()` on Windows uses
// TerminateProcess which is uncatchable, so cooperative shutdown is
// unnecessary on that platform.

package main

import (
	"os"
	"os/signal"
	"syscall"
)

func init() {
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		<-sigChan
		os.Exit(0)
	}()
}
