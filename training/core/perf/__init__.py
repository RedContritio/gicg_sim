"""Opt-in performance tracing infrastructure.

Disabled by default. See
``trace.py`` for the public API + ``tools/perf/analyze.py`` for the
offline analyzer.
"""

from training.core.perf import trace

__all__ = ['trace']
